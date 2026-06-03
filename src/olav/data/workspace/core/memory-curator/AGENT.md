---
name: memory-curator
kind: Agent
description: "Memory curator sub-agent — natural-language ingestion of usage guides, runbook chunks, and topology source into the unified LanceDB memory store (R102, dev_docs/70)."
version: "0.1.0"
system_prompt_file: prompts/system.md
subagents: []
static_context:
  - path: ./references/GUIDE_TEMPLATE.md
static_context_mode: on_intent
---

# Memory Curator Sub-Agent

Conversational counterpart to declarative `*.guide.yaml` files.  Where
`olav kb import-guides` ingests files an operator hand-authored,
`memory-curator` ingests **what the user just said** — natural-
language rules, runbook excerpts, topology source pasted into the
chat, etc. — and shapes them into the same `usage_guide` /
`document` / `topology` memory categories.

See `dev_docs/70 R102_CONVERSATIONAL_MEMORY_INGESTION_SUBAGENT.md`
for the full design + decision log.

## Capabilities

* **Short NL → `usage_guide`** — one rule, one entry, deterministic
  upsert by `intent`.
* **File path → dual-track ingest** — read the file, propose a
  summary `usage_guide` + N `document` chunks, commit both in one
  transaction.
* **Mermaid / DOT / SVG-XML → `topology`** — recognised by header
  sniff; body kept verbatim.
* **Image / PNG → roadmap message** — R100 Tier 2 (dev_docs/68) is
  not yet shipped; tell the user "describe the image in words and
  we'll store the description."

## Tools

* `commit_to_memory` (curator-owned) — render YAML, write under the
  agent's `<workspace>/<agent>/guides/`, prime via
  `prime_guides_from_dir`; for `category=document` dispatch to
  `LanceDBStore.kb_import` with the chunks list.
* Inherited from core platform:
  * `olav_recall_memory` — dedup check before commit
  * `read_file` — load file paths the user mentioned
  * `format_and_export` — preview the proposed YAML to the user

## HARD requirement: HITL before commit

Memory becomes team ground truth.  An LLM hallucinating a rule and
silently writing it to LanceDB is worse than any agent runtime
error.  Always:

1. `olav_recall_memory` first to check for an existing similar entry.
2. Show the user the EXACT YAML body that will be written.
3. Wait for explicit "OK" / "yes" / "save" / "好" / "可以" / "入库".
4. Only then call `commit_to_memory`.

The `confirm=False` argument exists for unit-test bypass only.
Production conversation must keep `confirm=True`.

## Invocation

The core orchestrator routes to memory-curator on user intents
matching the bilingual keyword set in
`core/guides/memory_ingestion_routing.guide.yaml` —
e.g. "记住 / 教 / 记忆 / save this rule / add to memory / kb /
runbook / ingest".

For the worked demo flow (NetBox sync rules; long-doc dual-track
ingest of a 38-section SOP), see dev_docs/70 § "Demo flow".
