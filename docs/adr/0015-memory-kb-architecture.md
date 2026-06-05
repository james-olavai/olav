# ADR-0015: Memory Architecture — reflection / expert_knowledge split + olav_kb/ global KB

**Status**: Accepted
**Date**: 2026-06-05

## Context

OLAV has a single LanceDB `memory` table with categories `fact`, `decision`,
`preference`, `audit`, `expert_knowledge`, and `usage_guide`.  Two problems
have accumulated:

1. **Trust conflation.** `expert_knowledge` is written both by agents
   automatically (via `OperationalEventCapturePlugin` / `trace_learner`) and by
   users explicitly (via `memory-curator` HITL or `olav kb import-guides`).
   These have very different reliability profiles — agent-observed knowledge is
   unverified and time-bound; user-curated knowledge is intentional and durable.
   Mixing them in one category means AutoRecall cannot weight them differently.

2. **Knowledge fragmentation.** Curated knowledge (`*.guide.yaml`, `.expert.yaml`)
   is scattered across every agent's `references/` directory.  There is no
   single place where an operator can browse, contribute to, or version-control
   the platform's domain knowledge.  `prime_guides_from_dir` scans the entire
   workspace and silently loads agent-local context into the global LanceDB,
   polluting global recall with agent-specific material.

The current `expert_kb.py` (476 lines) and `guide_kb.py` (442 lines) implement
two nearly-identical YAML-file → LanceDB pipelines for `.expert.yaml` and
`*.guide.yaml` respectively.  Both formats are OLAV-specific YAML schemas that
operators must learn before contributing knowledge.

## Decision

### D1 — Two memory categories with distinct write paths and priorities

| Category | Written by | Trust | TTL | AutoRecall weight |
|---|---|---|---|---|
| `reflection` | Agent conversation (auto-capture) | Unverified / ephemeral | 30 days (configurable) | High (recent, specific) |
| `expert_knowledge` | `olav kb import-kb` (user-initiated) | Curated / durable | None | Low (foundation baseline) |

We will **remove `usage_guide`, `fact`, `decision`, `preference`** as distinct
write-path categories.  Existing rows are migrated or deleted per D4.

`audit` category is retained unchanged (written by audit tooling, not by this
pipeline).

`reflection` is the **new name** for all agent-derived memory writes.
`expert_knowledge` is **redefined** as user-curated-only; agent code may no
longer write to it.

### D2 — `olav_kb/` at repository root

We will create `olav_kb/` at the repository root as the single authoritative
source for platform knowledge.  Any file format is accepted:

```
olav_kb/
  network/       # BGP/OSPF/topology rules, vendor quirks
  platform/      # OLAV operational rules
  integrations/  # NetBox, Grafana, InfluxDB API guides
  audit/         # Audit Profile authoring conventions
```

Files are loaded by `olav kb import-kb` using **LangChain's `DirectoryLoader`**
with format-specific sub-loaders (already available in `langchain_community`
0.4.1 without new dependencies):

```
TextLoader / UnstructuredMarkdownLoader / PyPDFLoader /
Docx2txtLoader / UnstructuredHTMLLoader / CSVLoader
```

Chunks are produced by `RecursiveCharacterTextSplitter` (default 500 tokens,
100-token overlap) and written to LanceDB as:

```
category = "expert_knowledge"
origin   = "import"
scope    = "global"
```

We reject dual-track (YAML-structured vs raw document): all content goes
through the same LangChain loader pipeline.  Operators who want precise intent
tags or scoping can use `memory-curator` HITL instead.

### D3 — `expires_at` field in LanceDB schema

We will add `expires_at pa.timestamp("us")` (nullable) to the `memory` table
schema.  `reflection` writes always populate this field:

```python
expires_at = datetime.utcnow() + timedelta(days=reflection_ttl_days)
```

`reflection_ttl_days` defaults to 30.  It may be overridden per-skill in
`SKILL.md` frontmatter:

```yaml
memory:
  reflection_ttl_days: 7   # short-lived operational notes
```

AutoRecall filters `WHERE expires_at IS NULL OR expires_at > now()` before
scoring.  Expired rows are hard-deleted by a periodic `olav kb gc` sweep.

### D4 — `references/` stays as direct injection; no longer indexed into global LanceDB

Agent `references/*.guide.yaml` files are used exclusively via
`dynamic_context` / `static_context` (direct prompt injection).
`prime_guides_from_dir` will no longer scan `references/` into the global
LanceDB.  Knowledge that should be globally searchable must be placed in
`olav_kb/` instead.

`prime_guides_from_dir` is retained for `olav kb import-guides` (backwards
compatibility) but scoped to explicit paths only — it is no longer called
automatically during `olav init` against the workspace.

### D5 — Delete existing `expert_knowledge` rows

On next `olav kb gc` run (or manually via `olav kb gc --purge-expert`),
all rows with `category = "expert_knowledge"` are deleted from LanceDB.
The content is not migrated — it was agent-generated and is no longer
classified as expert knowledge under this ADR.

### D6 — Delete `expert_kb.py`

`src/olav/core/memory/expert_kb.py` is deleted.  Its YAML schema
(`.expert.yaml` files) is retired.  `trace_learner.py` is updated to write
`category="reflection"` instead of `category="expert_knowledge"`.

`guide_kb.py` is retained for `import-guides` backwards compatibility but
is no longer the primary ingestion path.

## Consequences

### Positive

- **Trust is explicit**: AutoRecall can weight `reflection` (higher, recent)
  vs `expert_knowledge` (lower, foundation) distinctly.
- **Single KB location**: `olav_kb/` is version-controlled, PR-reviewable,
  browsable by operators without knowing OLAV internals.
- **Any format**: operators drop PDF/DOCX/Markdown — no YAML schema to learn.
- **No global LanceDB pollution**: agent-local `references/` no longer leaks
  into global recall.
- **reflection TTL**: prevents stale agent-observed facts from accumulating
  indefinitely.
- **Simpler code**: `expert_kb.py` deleted, one fewer YAML schema to maintain.

### Negative / Costs

- **`import-guides` → `import-kb` migration**: operators must update any
  scripts that call `olav kb import-guides` with workspace paths.
- **Loss of structured metadata**: raw documents lack `intent`/`keywords` fields
  that YAML guides provided for BM25 keyword boosting.  Precision of keyword
  recall may decrease for documents imported via `import-kb`.
- **Schema migration required**: `expires_at` column must be added to existing
  LanceDB tables.
- **Existing `expert_knowledge` rows deleted**: content is lost (intentional).

### Follow-ups

- ADR-0008 (SkillsMiddleware) — `references/` injection path unchanged.
- Governance test: `test_reflection_ttl_written` — assert reflection writes
  always have `expires_at` set.
- Governance test: `test_expert_kb_import_only` — assert no agent code writes
  `category="expert_knowledge"` outside `kb_import.py`.
- Open: `olav kb gc` scheduling (cron vs manual-only).
- Open: reranker weight config for `reflection` vs `expert_knowledge` tiers.
