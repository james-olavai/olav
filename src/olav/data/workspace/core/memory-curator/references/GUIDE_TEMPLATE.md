# Guide YAML template

Canonical shape of a `*.guide.yaml` file (the on-disk artefact
that `prime_guides_from_dir` reads + the `usage_guide` memory row).

```yaml
schema_version: 1
intent: <snake_case_unique_identifier>
agent: <core | ops | services | audit | ...>
keywords:
  - <english_term_1>
  - <english_term_2>
  - <chinese_term_1>
  - <chinese_term_2>
body: |
  <clean prose, preserving technical content verbatim>

  Multiple paragraphs OK.  Tables, code blocks, bulleted lists
  are all fine.  The whole `body` becomes one LanceDB memory row,
  embedded as `intent + keywords + body`.

related:                       # optional
  - intent: <related_intent>
    note: "why these are linked"
```

## Required fields

| Field    | Type        | Notes |
|---|---|---|
| `schema_version` | int   | Always `1` for the current platform |
| `intent`         | str   | snake_case; becomes part of the deterministic `memory_id = guide_<agent>_<intent>` |
| `agent`          | str   | controls which agent's `<workspace>/<agent>/guides/` the file lands in |
| `keywords`       | list[str] | at minimum 4-6, ideally bilingual (en + zh) |
| `body`           | str (block scalar) | the actual rule / wisdom |

## Optional fields

| Field     | Type | Notes |
|---|---|---|
| `related` | list[dict] | links to other intents — surfaces in `pattern_extractor` output |

## Memory categories the curator can write

| Category | When | Storage |
|---|---|---|
| `usage_guide` | Short NL rule, or summary of a long doc | `<agent>/guides/<intent>.guide.yaml` + LanceDB row |
| `document`    | Long-doc body chunks (~500 tok each) | LanceDB rows only — no YAML on disk |
| `topology`    | Mermaid / DOT / SVG topology source | LanceDB row, `metadata.media_type` set |

## Naming conventions

* `intent` should read like a sentence fragment naming the
  knowledge: `netbox_device_sync_team_acme`,
  `bgp_idle_check_l1_first`, `ospf_area_mismatch_diagnostic`.
* `keywords` should mix the user's natural query terms with
  technical synonyms: if the rule is about BGP `Idle` state,
  include `bgp`, `idle`, `不通`, `邻居 down`.
* `body` should be self-contained.  Don't reference "the
  conversation we just had" — future readers won't have it.

## Examples in the wild

* `core/guides/troubleshoot_layered_l1_to_l4.guide.yaml`
* `core/guides/take_snapshot_when_db_stale.guide.yaml`
* `ops/guides/output_export_rules.guide.yaml`
* `services/guides/netbox_device_sync_team_acme.guide.yaml`
  (created by memory-curator in the demo flow)

## File location

Standard: `<workspace>/<agent>/guides/<intent>.guide.yaml`

In a typical OLAV deployment:

```
.olav/workspace/
├── core/guides/        ← agent="core" guides
├── ops/guides/         ← agent="ops" guides
├── services/guides/    ← agent="services" guides
└── audit/guides/       ← agent="audit" guides
```

`prime_guides_from_dir` recursively globs `**/guides/*.guide.yaml`,
so any sub-tree depth works — but stick to the convention.
