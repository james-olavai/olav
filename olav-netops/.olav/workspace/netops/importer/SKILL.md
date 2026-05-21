---
name: importer
agent_type: api  # skip TodoListMiddleware — tool-execution flow, not plan-and-iterate
# Format classification (rancid vs. canonical bundle vs. loose vendor dump
# vs. show-tech) is a fuzzy task where reasoning helps; nothink mis-routes
# in repeated trials.  Keep thinking ON for this sub-agent.
thinking_mode: enabled
description: "Offline snapshot ingest — drops a bundle / rancid backup / vendor dump in and lands it in raw_output_store + structured views."
metadata:
  version: 0.1.0
  type: agent
  agent_type: api
  category: network-data-ingest
  intent: offline_snapshot_ingestion
tools:
  # deepagents native — format discovery + Tier 3 LLM-fallback inspection
  - ls
  - read_file
  - glob
  - grep
  # Python first-party — validation, discovery cascade, final landing
  - ingest_snapshot
  - validate_bundle
  - discover_platform_for_host
dynamic_context:
  - path: ./references/bundle_schema.guide.yaml
  - path: ./references/vendor_dump_heuristics.guide.yaml
  - path: ./references/rancid_format.guide.yaml
  - path: ./references/platform_signatures.guide.yaml
system: $ref:./prompts/system.md
---

## Overview

The **Ingest agent** takes pre-collected raw network output that someone
else gathered — air-gapped jump host, rancid nightly backup, vendor
support `show tech-support`, hand-built bundle — and lands it in
OLAV's main DB using the same downstream path as live SSH collection.

Users drop a file or directory into `~/.olav/inbox/` (or anywhere) and
invoke this agent. The agent uses deepagents-native file primitives
(`ls`, `read_file`, `glob`, `grep`) to identify the format, then calls
`validate_bundle` for a pre-flight sanity check and `ingest_snapshot`
for the actual landing.

See [dev_docs/80](../../../../dev_docs/80.%20PORTABLE_SNAPSHOT_INGEST.md)
for the full design.

## Two-tool model

| Tool | When to use | Returns |
|---|---|---|
| `validate_bundle(path)` | Always run first — cheap, no DB writes | `{ok, errors, warnings, hosts_seen, commands_seen}` |
| `ingest_snapshot(path, collection_source)` | Only after `validate_bundle.ok == True` | `{bundle_id, snapshot_id, hosts, commands, parser_fills}` |

## Format detection workflow

1. `ls <path>` — what's inside?
2. If you see `manifest.yaml` at the root → **canonical bundle** (the
   easy case). Run `validate_bundle` then `ingest_snapshot`.
3. If you see `<group>/configs/<host>` files with `!`-banner separators →
   **rancid** layout. (Phase 4 — currently `ingest_snapshot` does NOT
   accept rancid; bail out and tell the user.)
4. If you see loose `<host>.txt` files containing concatenated CLI
   output → **vendor dump** layout. Same as rancid — bail out for now.
5. If you see vendor archives (`*.tar`, `*.tgz` with `show-tech*`
   contents) → **tech-support bundle**. Defer to Phase 6.

When **ambiguous**, surface to the user before acting — do not guess.

## Safety / chain-of-custody

- Bundles carry a SHA256 hash in `manifest.yaml`. `validate_bundle`
  recomputes and refuses on mismatch — tampering or transit corruption
  fails closed.
- `ingest_snapshot` writes one row to `netops.bundle_ingests` per
  invocation: collector identity, sha256, timestamps, ingesting user.
  This is the audit chain — query later via `SELECT * FROM
  netops.bundle_ingests ORDER BY ingested_at DESC`.
- All raw output is re-scrubbed through `olav.core.redaction.scrub`
  (netconan) regardless of the manifest's `pre_scrubbed` flag —
  defense-in-depth.
