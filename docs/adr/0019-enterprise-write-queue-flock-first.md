# ADR-0019: Enterprise write-queue form — flock first, Postgres as fallback

**Status**: Proposed
**Date**: 2026-07-26

## Context

ADR-0018 decided that team-scale write serialization ("queuing") is an
Enterprise-tier concern, injected at the shared `open_write_connection()` seam,
while OSS keeps retries. It deferred the *form* of that queuing to a follow-up.
This ADR is that follow-up. Full comparison in dev_docs/111 §7.

Three candidate forms were weighed:

- **flock gate** — before writing, take `fcntl.flock(LOCK_EX)` on a per-db
  lockfile (kernel-queued, blocking), then `duckdb.connect(...)` and write.
  Cross-process by construction (subprocesses/CLI/cron all honor it), no daemon,
  no IPC protocol, no change to the `skill_runner` subprocess model. Kernel
  releases the lock automatically if a writer crashes.
- **daemon write-broker** — the daemon holds the sole write connection; all
  writers post write requests over IPC and the daemon serializes them.
- **server-side backend** — replace `main.duckdb` with Postgres / MotherDuck /
  DuckDB-over-HTTP; the DB's own MVCC handles concurrency, no app-level queue.

The decisive premise (dev_docs/111 §7.1): **OLAV's write load is not OLTP.** It
is a burst-per-agent-session pattern (presales emits one HLD/LLD; netops stores
one snapshot/topology) — low-frequency, bursty, batched. The team pain is
occasional bursts colliding on the lock, not sustained high throughput. So a
"globally serialized single-file writer" is far from its ceiling for realistic
teams, which lowers the real need for a high-concurrency backend.

Two OLAV-specific constraints also weigh heavily:

- **Data sovereignty** — OLAV is positioned for local models with data staying
  in-domain (network configs are sensitive). A cloud SaaS backend (MotherDuck)
  is likely a dealbreaker for many enterprise customers.
- **DuckDB analytical value** — much of OLAV's read path (batfish/topology/
  snapshot diff) leans on DuckDB's columnar store and local snapshot files;
  swapping to Postgres forfeits that.

## Decision

We will adopt the Enterprise write-queue in **phases**, not a single choice.

1. **Enterprise v1 = flock gate.** Implement queuing as an `fcntl.flock(LOCK_EX)`
   blocking gate per db_path, injected at the `open_write_connection()` seam and
   shipped in `olav.enterprise.*`. This upgrades "lock-failure + retry" to
   "cross-process real queuing, zero write failures" with the smallest change,
   no resident process, and full retention of DuckDB's advantages and data
   sovereignty. The gate MUST carry an acquisition timeout (`LOCK_NB` + polling
   or `alarm`) so a stalled lock-holder cannot deadlock the queue; a crashed
   holder is auto-released by the kernel.

2. **v2 = Postgres backend, on demand only.** Escalate to a server-side backend
   ONLY when a customer's measured team scale / write frequency exceeds the
   flock single-file serialization ceiling, or when "reads blocked by the write
   lock" becomes a real pain point. When we do, prefer **self-hosted Postgres**
   (data sovereignty); **MotherDuck only if the customer explicitly accepts
   data leaving their domain.** Because the seam abstracts write acquisition,
   v1→v2 is a seam-implementation swap, not a rewrite — choosing flock for v1
   does not foreclose v2.

3. **We reject the daemon write-broker as the default.** It has the largest
   build cost (a self-built SQL-over-IPC gateway carrying arbitrary write
   transactions), only mid-tier ceiling, a single point of failure (daemon down
   = whole team's writes down), and it weakens the deliberate `skill_runner`
   subprocess sandbox (`skill_runner.py:14-23`). Its one distinctive value — a
   single choke point for audit/rate-limit/tenant-quota/backpressure — is mostly
   achievable inside the seam helper without a resident broker. Revisit only if
   a governance requirement genuinely cannot be met at the seam.

## Consequences

### Positive

- v1 ships fast and small: a seam-local flock gate, no new resident component,
  no IPC protocol, no subprocess-model change.
- Crash safety is a property of the kernel (auto-release), not of app code we
  must write and test.
- DuckDB advantages and in-domain data sovereignty are preserved in v1.
- The phased path is honest about DuckDB's ceiling without paying the backend-
  migration cost before a customer actually needs it.

### Negative / Costs

- flock does not solve read-blocked-by-write (DuckDB's own read/write exclusion
  is unchanged); that limitation is the explicit v1→v2 trigger, not a surprise.
- flock semantics on old NFS are unreliable; deployment environments must be
  verified (see follow-up). Local FS / single-host containers are fine.
- Deferring the backend means a future, larger migration for the largest teams —
  a cost postponed, not eliminated.
- A blocking gate turns "fail-fast + retry" into "block + timeout"; the timeout
  must be tuned so a pathological long write transaction doesn't stall the team.

### Follow-ups

- **Governance/verification**: confirm flock reliability on each supported
  enterprise deployment filesystem (NFSv4, container overlay) before v1 GA.
- **Seam design**: the flock gate must live behind the same
  `open_write_connection()` seam ADR-0018 mandates; a boundary test asserts the
  gate code is in `olav.enterprise.*` and absent from OSS wheels.
- **Open**: the OSS↔Enterprise injection mechanism (entry-point discovery vs
  guarded optional import) — dev_docs/111 §7bis.4.
- **Related**: ADR-0018 (tiered model), ADR-0002 (repo boundary), dev_docs/111.
