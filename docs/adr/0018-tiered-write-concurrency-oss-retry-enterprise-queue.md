# ADR-0018: Tiered DuckDB write-concurrency — OSS retries, Enterprise queues

**Status**: Proposed
**Date**: 2026-07-26

## Context

OLAV writes to DuckDB with an *optimistic* concurrency model: short-lived
`duckdb.connect(path, read_only=False)` connections, DuckDB's own file-level
write lock as the cross-process serializer, and retry-with-backoff to survive
lock contention. DuckDB's write lock **does not queue** — the loser gets an
immediate `IOException: ... Could not set lock on file` at `connect()` time
(`skill_runner.py:30-43`). Two independent retry paths exist:
`audit_recorder.py:250` (in-process `threading.Lock` + backoff) and
`skill_runner.py:336` (full-jitter retry around `execute_skill_script`
subprocesses).

The real contention is **cross-process**: one AIMessage dispatches several
`execute_skill_script` tool_calls concurrently, each a subprocess racing to open
the same `main.duckdb` (presales and netops share `MAIN_DB_PATH`). A naive
"asyncio.Queue write worker inside the daemon" does **not** fix this — writes
happen in subprocesses, not the daemon event loop, and the daemon is opt-in
(`daemon.py`), so making writes depend on it would turn an optional component
into a hard startup dependency (dev_docs/111 §1.1).

The severity of contention is set by **deployment shape**, not by the code:

- **Personal use (OSS positioning)**: one user, one session. Contention is an
  occasional short-window subprocess burst. Full-jitter retry already closes
  5+-way collisions reliably (`skill_runner.py:75-87`); presales live e2e is
  N=3 green. Retry is the *right* engineering point here.
- **Team use (Enterprise positioning)**: many users/sessions continuously
  contending the same DB. Retry tail-latency and failure rate degrade
  non-linearly with concurrency; teams need real queued serialization.

A full inventory (dev_docs/111 §5) found ~40 write sites across 3 "acquire a
write connection" patterns, no reusable central helper, and `get_database()`
explicitly warned as unfit for writes (`database.py:70-79`).

## Decision

We will treat write-concurrency as a **tiered** concern, not one-size-fits-all.

1. **OSS (`olav` / `olav-netops`) keeps retries.** No write broker, no flock
   gate, no central worker ships in the OSS wheels. Short-connection +
   file-lock + full-jitter retry stays. It is validated for the personal-use
   concurrency profile; adding a queue there is over-engineering that violates
   the opt-in daemon design.

2. **Enterprise (`olav-ent`) owns queuing + web.** Team-scale write
   serialization (daemon write-broker and/or flock gate and/or a server-side DB
   backend) and the collaborative web front-end ship as `olav.enterprise.*`
   modules, distributed with olav-ent. The concrete queuing *form* (self-built
   SQL-over-IPC broker vs flock gate vs Postgres/MotherDuck backend) is
   deferred to a follow-up ADR — dev_docs/111 §4/§7 records the tensions.

3. **A single write seam is the shared prerequisite for both tiers.** We will
   converge the ~40 scattered write sites onto one platform-core
   `open_write_connection(db_path, *, read_only=False, conn=None)` in
   `src/olav`. Its OSS implementation is lock+retry (extracted from
   `audit_recorder._run_with_retry`, which then reuses the shared helper). The
   Enterprise queue is injected **at the same seam**, so "personal = retry /
   team = queue" are two implementations of one seam, not two parallel write
   paths. The seam must support: connection injection (reuse-or-create without
   closing an injected conn), a long-held-transaction variant, a `read_only`
   flag, and must exclude `:memory:` sandboxes and the `get_database()`
   singleton.

Acceptance criteria for the convergence work: batch 1 (helper + the two
factories `api_registry._open` / `registry_sync._open_main_db` + all presales
`with`-form sites) must pass a presales N=3 e2e showing lock contention gone
before batches 2–3 proceed (dev_docs/111 §6).

## Consequences

### Positive

- Right-sized effort per tier: personal users pay zero complexity; teams get
  predictable, zero-failure writes.
- One seam localizes the OSS↔Enterprise difference to a single injection point
  instead of touching every write site twice.
- Convergence removes the two-independent-lock-systems hazard (audit_recorder
  vs skill_runner) by unifying them behind one helper.
- Enterprise boundary stays clean: queuing lives in `olav.enterprise.*`, auto-
  stripped from public mirrors and absent from OSS wheels (ADR-0002,
  `feedback_presales_enterprise_boundary`).

### Negative / Costs

- Convergence touches ~40 sites; batch 3 (held long transactions, injected
  conns, nested writes, netops three-mirror sync) is genuinely fiddly.
- Committing to DuckDB for the OSS tier caps that tier's concurrency; the
  enterprise tier may still need a backend swap (DuckDB single-writer is not a
  team database) — a cost deferred, not avoided.
- A pluggable seam adds one indirection layer to every write.

### Follow-ups

- **Follow-up ADR**: choose the enterprise queuing form (broker vs flock vs
  server-side backend) — dev_docs/111 §7 open questions 1–5.
- **Governance**: a boundary test asserting no `olav.enterprise.*` import from
  OSS write paths; a test pinning that OSS wheels contain no queue/broker code.
- **Related**: ADR-0002 (repo boundary — enterprise as guarded/entry-point
  coupling), dev_docs/111 (full design + write-site inventory).
- **Open**: flock reliability on NFS/overlay FS; read/write separation for
  team read paths blocked by the write lock.
