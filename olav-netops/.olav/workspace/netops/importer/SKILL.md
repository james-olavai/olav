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
  - execute_skill_script
scripts:
  - name: survey_bundle
    description: "One-shot format detection + host/platform survey. Always call first. Returns format, hosts, platforms, platform_sample_lines (Tier 3 fallback), collector info, and prescriptive notes field."
    file: survey_bundle.py
  - name: validate_bundle
    description: "Pre-flight sanity check — sha256 + manifest schema. No DB writes. Call after survey_bundle confirms ingest_supported=True."
    file: validate_bundle.py
  - name: ingest_snapshot
    description: "Land a canonical bundle into raw_output_store + structured views. Call after validate_bundle."
    file: ingest_snapshot.py
  - name: discover_platform_for_host
    description: "Tier 1+2 TextFSM cascade platform detection for one host dir. Only needed for hosts in needs_platform_detection. If confidence=unknown, classify from platform_sample_lines in survey_bundle result — no read_file needed."
    file: discover_platform.py
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
invoke this agent. The agent calls `survey_bundle` first to identify the
format and host inventory, then follows the prescribed workflow in the
`notes` field of the result.

See [dev_docs/80](../../../../dev_docs/80.%20PORTABLE_SNAPSHOT_INGEST.md)
for the full design.

## Script pipeline

| Script | When to use | Returns |
|---|---|---|
| `survey_bundle(path)` | **Always first** — format detection + host survey | `{format, ingest_supported, hosts, platforms, needs_platform_detection, platform_sample_lines, collector, notes}` |
| `discover_platform_for_host(host_dir)` | Only for hosts in `needs_platform_detection` | `{platform, confidence, sample_file}` |
| `validate_bundle(path)` | After `ingest_supported=True` confirmed | `{ok, errors, warnings, hosts_seen, commands_seen}` |
| `ingest_snapshot(path, …)` | After `validate_bundle.ok == True` | `{bundle_id, snapshot_id, hosts, commands, parser_fills}` |

## Format detection workflow

1. `survey_bundle(path)` — returns `format` + `notes` prescribing the next step.
2. If `ingest_supported=False` → tell the user the format is not yet
   supported and what format it was detected as.
3. If `ingest_supported=True` → proceed to step 3.
4. For hosts in `needs_platform_detection`: call
   `discover_platform_for_host(host_dir)`.  If `confidence="unknown"`,
   read `platform_sample_lines[hostname]` from the survey result and
   classify visually — no `read_file` needed.
5. `validate_bundle(path)` → check `ok`.
6. `ingest_snapshot(path, collection_source=…, host_platforms=…)`.

When **ambiguous**, surface `survey_bundle.notes` to the user — do not guess.

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
