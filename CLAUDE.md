# CLAUDE.md — OLAV Platform Repository Instructions

## Repository Structure

This is the `olav` root repository — the **platform base** (control plane, runtime, CLI, plugin contracts, shared infrastructure). Five delivery units coexist:

| Unit | Location | Role |
|---|---|---|
| `olav` | `src/olav/`, root configs | Platform core — CLI, runtime, workspace lifecycle, audit, auth, DB, memory |
| `olav-netops` | `olav-netops/` | Network domain extension (OpenConfig, topology, CLAB, collectors) |
| `olav-ent` | `olav-ent/` | Enterprise extension (enterprise auth, compliance, governance) |
| `olav-doc` | `olav-doc/` | Public docs site (MkDocs Material) — `docs.olavai.com` |
| `olav-web` | `olav-web/` | Marketing website + edge application (Astro + Cloudflare Worker + R2) — `olavai.com` |
| `olav-post` | `olav-post/` | Local-only content archive — never published to any remote |

## Repo Boundary Rules

Governance docs: `dev_docs/99. REPO_BOUNDARY_AND_OWNERSHIP.md` + [ADR-0002](docs/adr/0002-repo-boundary-ownership.md). Architecture policy decisions live in `docs/adr/` (see [ADR-0004](docs/adr/0004-new-top-level-agent-extension-policy.md) for the new top-level agent extension policy).

**Allowed dependency directions:**
- `olav-netops -> olav` (platform contract)
- `olav-ent -> olav` (platform contract)
- `olav-doc -> none` (no runtime dependency)
- `olav-web -> none` (no runtime dependency)
- `olav-post -> none` (no runtime dependency, local-only)

**Reverse coupling** (`olav -> olav-netops`, `olav -> olav-ent`) is only allowed via:
- Entry-point / plugin discovery (dynamic)
- Guarded optional imports
- Never as a hard startup dependency

**Forbidden:**
- `olav-doc` importing `src/olav` runtime code
- `olav-web` importing `src/olav` runtime code
- `olav-post` importing `src/olav` runtime code
- `olav` core hardcoding network-domain or enterprise-specific semantics
- Dual-source editing of docs/web in both root and `olav-doc`
- Publishing `olav-post` content to any remote (git, PyPI, CDN)

## Ownership Manifest

**Single source of truth:** `ownership_manifest.yaml` at repo root.

Every path in the repo is covered by a rule with:
- `owner`: which delivery unit owns it
- `class`: asset category (platform, netops, enterprise, docs, etc.)
- `status`: authoritative / transitional / externalized / misplaced / generated
- `git`: track / ignore / secret

**Key commands:**
```bash
# Scan all paths against manifest — should be 0 ERROR
uv run python scripts/scan_ownership.py --summary

# Show only warnings and errors
uv run python scripts/scan_ownership.py --errors-only

# Regenerate .gitignore from manifest (NEVER edit .gitignore manually)
uv run python scripts/gen_gitignore.py --write
```

## .gitignore is Generated

`.gitignore` is **auto-generated** from `ownership_manifest.yaml`. Do not edit it manually.

When you add a new path or change a rule's `git` field in the manifest, run:
```bash
uv run python scripts/gen_gitignore.py --write
```

The `git` field on each manifest rule controls tracking:
- `git: track` — committed to this repo
- `git: ignore` — on disk for dev, not committed
- `git: secret` — never committed (credentials, env files)

File-type patterns (`*.pyc`, `*.so`, etc.) are in the manifest's `gitignore_file_patterns` section.

## olav-doc is the Authoritative Docs Source

As of 2026-04-04, `olav-doc/` is the **sole authoritative source** for:
- `docs/` — MkDocs documentation content
- `mkdocs.yml` — MkDocs configuration

Root `docs/`, `web/`, `mkdocs.yml` have been removed. Do not recreate them.
`olav-doc/web/` has been removed — the marketing website is now in `olav-web/`.

## olav-web is the Target Website Source

`olav-web/` (monorepo subdir, co-located with `olav-netops` and `olav-ent`) is the **target authoritative source** for:
- Astro marketing website (`olavai.com`)
- Cloudflare Worker edge logic
- R2 asset governance

During the two-phase migration, `olav-doc/web/` and `olav-web/` coexist. Once `olav-web/` is stable, `olav-doc/web/` will be removed per the migration rules in `dev_docs/25.WEB_REPO_SPLIT_AND_CLOUDFLARE_ARCHITECTURE.md`.

## Workspace Layout

`.olav/workspace/` is the runtime workspace control plane:

| Path | Owner | Status |
|---|---|---|
| `.olav/workspace/core/` | olav | authoritative (platform agent) |
| `.olav/workspace/audit/` | olav | authoritative (audit orchestrator + sub-agents) |
| `.olav/workspace/netops/` | olav-netops | transitional (network-domain extension workspace) |
| `.olav/workspace/admin/` | olav | authoritative (admin/operator workflows) |

`.olav/databases/` and `.olav/logs/` are runtime-generated, never committed.

## Git Tracking Model

`.olav/` uses a **whitelist model** — everything is ignored by default. As of
the WORKSPACE-DUAL-COPY-DEBT Phase 3 dedup, **NO `.olav/workspace/*` runtime is
tracked** — they are all generated mirrors. Tracked under `.olav/`: only
`.olav/config/*.example`.

**Generated runtime (git:ignore — deployed at bootstrap, NOT tracked):**
- `.olav/workspace/{core,audit,admin,devops,services}/**` — platform agents,
  byte-exact mirror of `src/olav/data/workspace/*` (wheel). `olav init` deploys
  them (editable install → exact).
- `.olav/workspace/netops/**` — mirror of `olav-netops/.olav/workspace/netops/`.
  `olav skill install olav-netops` deploys it.

**CI (test.yml) runs `olav init` + `olav skill install olav-netops`** before
tests so they read the runtime from a plain checkout.

> WORKSPACE-DUAL-COPY-DEBT Phase 3 COMPLETE (2026-06-03): all 7 runtime dirs
> untracked → generated/ignore. Sole tracked authority: `src/olav/data/
> workspace/*` (platform) + `olav-netops/.olav/workspace/*` (netops). The 4
> netops cross-domain tools have a deliberate @tool↔script dual-version split
> (tools/X = @tool wrapper w/ `full` flag; scripts/X = CLI script) — both wrap
> olav_netops.core.* impl; allowlisted in test_tool_dedup_phase2._DELIBERATE_DIVERGENCE.
> Retired: scripts/sync_netops_workspace.py → scripts/workspace_drift.py.
> ⚠️ The `olav init` + `skill install` CI steps must be confirmed green on the
> next actual CI run (verified locally/sandbox; CI-env not yet exercised).

## What Gets Released (tracked in git)

Only platform core source and essential configs:
- `src/olav/**` — platform Python package
- `pyproject.toml` — package metadata
- `README.md`, `LICENSE` — release metadata
- `ownership_manifest.yaml` — boundary governance
- `.olav/config/*.example` — config templates
- `src/olav/data/workspace/{core,audit,admin,devops,services}/**` — authoritative platform workspace source (wheel; sole tracked authority for those 5 agents). Incl. `src/olav/data/workspace/services/**` (ADR-0014 service-integration agent). NOTE: `.olav/workspace/*` runtime is NOT tracked (generated by `olav init` / `olav skill install`).

Everything else (sub-repos, exports, databases) stays on disk for development but is not in the release.

`tests/**`, `dev_docs/**`, and `scripts/**` are **tracked in git**
(authoritative content was gitignored until the 2026-06-13/14 policy
flip, which had left ~57% of tests and ~65% of design docs invisible to
CI and review). They are still excluded from the release wheel by the
packaging rule (`packages = ["src/olav"]`) — **release hygiene is the
wheel's job, not gitignore's**. Plain `git add` works; no `-f` needed.
Rule of thumb: if it's `class: authoritative` in the manifest, it
belongs in git.

## Design Principles (small-model-first)

OLAV is **designed for local small models** (qwen3 7–30B, small DeepSeek,
Llama). The whole architecture exists to get production output from
models that hit planning ceilings — **fix the prompt, not the model**.
Every agent/tool/prompt change is judged against this. The hard,
governance-enforced rules that follow from it:

- **Context budget by tier** — usable context is ~8K (small) / ~32K
  (medium) / ≥200K (large). AutoRecall `top_k` = 1 / 2 / 13;
  `execute_sql` context rows = 10 / 20 / 50 (`TIER_DEFAULTS`).
- **Orchestrator = thin router** — the top-level agent's job is to route
  intent to **one** sub-agent and **return that sub-agent's output
  verbatim** (no re-synthesis/summarising). It holds only the few truly
  cross-domain tools (`execute_sql`, `olav_recall_memory`/`_store`,
  `web_search`); **all capability lives in sub-agents, never the
  orchestrator.** Prune the FS tools deepagents injects into the
  orchestrator graph (12→4 fixed admin-cron routing). Enforced bounds:
  **≤7** orchestrator tools, **≤5** tools per sub-agent, **≤5**
  sub-agents (ADR-0003/0005/0006, ARCH-18; `test_step_c_analyze_merge` +
  subagent-cap gates). Tool-list bloat burns context AND raises
  tool-selection error — fewer is better, the caps are ceilings not targets.
- **`@tool` docstrings ≤15 lines** — full docs behind `tool_help()`
  (ARCH-18 #1, `test_docstring_budget`); each tool's schema costs
  ~150–300 prompt tokens on *every* call.
- **WHAT, not HOW prompting** — give the goal + constraints, not
  phase/per-device step lists; HOW-specs make small models loop
  mechanically (proven across a 5-attempt CH11 experiment).
- **Empty collection arg = discovery, not "none"** — a tool called with
  an empty optional collection (e.g. `inspect_devices(devices=[])`) must
  return **all** items, not `{}`. Unspecified intent means "show me
  everything"; returning empty sends small models into a synonym-retry
  loop (ADR-0009 Tier-1 #5).
- **Fat tools for N-item work** — Python iterates, the LLM calls once
  (`generate_change_plan`: 0 SQL calls vs 60–80). Create one when
  N×(per-item LLM call) > ~5.
- **Steer behavior via memory, not code** — to change how an agent
  behaves, add a `*.guide.yaml` (→ `usage_guide`) or let L1/L2 capture
  distill `expert_knowledge`; AutoRecall injects the relevant ones into
  **every** model call (scope-filtered, quota-capped), and failure
  constraints come back as `reflection` (global). Prefer authoring a
  guide over editing prompts/middleware — it's the steering layer
  (ADR-0015 + the Self-Improving Loop). This is also *why* the Tool
  Architecture below defaults to scripts over `@tool`.

## Tool Architecture: Python-first, MCP only when justified

**Tool I/O is load-bearing for small models.** When a downstream tool
takes a string, pass a **raw string + comment metadata**, not a JSON
envelope — small models lose the round-trip re-emitting JSON-encoded
content as the next tool's args (gemma4 100% deploy-block in R88). And
fix call-*construction* errors (wrong arg shape) at the **Pydantic
coercion layer**, not with prompt imperatives: prose rules change
*whether* a small model calls the tool, never *how correctly* (V2 §M3).

**Execution model**: agents call deterministic logic in one of two ways:

- **`execute_skill_script`** — runs a plain Python file under
  `<skill>/scripts/` as a subprocess. No sandbox. Full filesystem and
  network access. Suitable for stateless transforms, DB queries,
  data processing.
- **`@tool` (MCP tool)** — called in-process by LangChain. Required
  when the operation cannot be expressed as a stateless subprocess.

> **Note**: `run_python_simulation` referenced in ADR-0007 was never
> implemented. `execute_in_sandbox` (`src/olav/platform/sandbox.py`)
> exists but is only used by `netops/learner` to validate potentially-
> broken TextFSM parser code. It is **not** a general agent execution
> mechanism. Do not reference it as one.

**Rule**: **Default to `execute_skill_script` + a script file.**
**Only escalate to `@tool`** when the operation satisfies AT LEAST ONE of:

1. **Process-external privilege** — CLAB REST API + auth, prod SSH
   (scrapli), privileged docker, external network services that require
   persistent connections or auth state across calls.
2. **Cross-process write target** — operation writes to a location
   that a later tool call must read from the same process context
   (e.g. `save_lab_config` writes to a tmpdir that `deploy_and_push_lab`
   reads). The "where" requires in-process coordination.
3. **Critical audit** — every invocation must be a row in
   `audit.duckdb.audit_tool_calls` (e.g. `register_service`,
   `record_network_event`, `take_snapshot`). A subprocess call inside
   a script cannot guarantee this.
4. **Persistent in-process state** — tool maintains module-level
   caches or connections across calls (e.g. snapshot cache in
   `batfish_q`, circuit breaker state in `execute_cli_parallel`).

**Failing all four → use a script.** Put the function in
`<skill>/scripts/`, register it in `SKILL.md` under `scripts:` with
name-form entries, and call it via `execute_skill_script`.

**Why this matters**: every MCP tool's docstring + Pydantic args
schema costs ~150-300 prompt tokens, paid on every agent
invocation. 16 tools = ~3200 tokens permanent overhead. For
small models (grok-4.1-fast, etc.), that's a meaningful chunk
of context budget. Tool-list bloat also raises the chance of
tool-selection error.

See `dev_docs/00 § ISSUE-MCP-OVER-TOOLING` for the full
architectural reflection + the 7-tool refactor candidate list.

The rule applies retroactively: before adding a new MCP tool, check
whether a script would suffice. The deterministic core is always
Python; the `@tool` wrapper is only justified by the four criteria
above.

---

## SKILL.md Authoring Rules

These rules encode the hard lessons from the rev ~282–299 `@tool→scripts`
migration. Violations are caught by governance tests in `tests/governance/`.

### Scripts go in `scripts/`, not `tools/`

Plain Python functions (no `@tool` decorator, no Pydantic schemas) live in
`<skill>/scripts/`. The `tools/` directory is **only** for platform @tool pools
(e.g. `netops/tools/`, `core/tools/`). Don't put plain scripts in `tools/`.

### `scripts:` entries must use name-form, not path-form

**Canonical (correct):**
```yaml
scripts:
  - name: query_evidence
    description: "Unified text search across syslog/command_output/config"
    file: query_evidence.py
```

**Broken (path-form — never use):**
```yaml
scripts:
  - path: ./scripts/query_evidence.py   # SkillsMiddleware cannot inject description
```

The `name` + `description` + `file` triplet is what `SkillsMiddleware` reads
to inject the script description into the agent's system prompt. Path-form
entries produce empty or missing descriptions — the LLM won't know the script
exists or how to call it.

### `execute_skill_script` must appear in `tools:` for LLM-callable scripts

If an agent needs the LLM to call scripts at runtime, `execute_skill_script`
**must** be in the `tools:` list. Without it, scripts are visible in the system
prompt (via `SkillsMiddleware`) but uncallable:

```yaml
tools:
  - execute_skill_script   # ← required for LLM-callable scripts
  - execute_sql            # any other @tools the agent needs
scripts:
  - name: describe_table
    description: "..."
    file: describe_table.py
```

Exception: `tools: []` or omitting `execute_skill_script` is valid when scripts
are invoked by the **pipeline** (Python-side), not by the LLM. In that case,
scripts are documentation-only in the system prompt.

### Two-workspace sync: always update both copies

Every workspace agent exists in **two copies**:

| Copy | Path | Purpose |
|---|---|---|
| Authoritative | `olav-netops/.olav/workspace/<domain>/` | Ships with wheel |
| Dev mirror | `.olav/workspace/<domain>/` | Local development |

When editing a SKILL.md or script file, **update both copies**. They must stay
identical. The governance test `test_known_duplicates_are_symlink_or_identical`
enforces this for canonical files.

### `netops/tools/` is a domain-level @tool pool

Sub-agents in `netops/` that don't have their own `tools/` directory inherit
from the parent `netops/tools/` pool via `parent_tools_dir` in `agent.py`.
Files that moved from `tools/` to `scripts/` as part of the migration (e.g.
`execute_cli_parallel.py`) must be removed from the `tools/` pool — they are
no longer @tools and will cause `ImportError` if loaded as such.

The canonical source for shared netops scripts is `netops/scripts/`. Files
duplicated across sub-agents must be identical to the canonical source — use
`scripts/scan_ownership.py` to verify.

---

## Definition of Done: wiring must be verified from a real entry point

A module is NOT done when its unit tests pass. Four shipped features
reached green TDD and were never reachable from any entry point — in
two cases for months: the trace-learn loop (wrote memories no recall
path could return), `/trace-review` (handler + tests + help text, no
dispatch), `LifecycleManager` and `generate_permission_rules` (only
their own tests ever called them).

**Every new module/feature must include at least one integration test
that exercises it through its real entry point** — CLI verb or
slash-command dispatch (`execute_command`), middleware chain, API
route, plugin discovery, or scheduled hook. A test that imports the
module directly does not count as wiring proof. If reachability is
config-driven (scope filters, category quotas, registry entries), the
integration test must run with production-default config — the
trace-learn loop was "wired" under a scope no production caller used.

Related gates: `tests/governance/test_no_shadowed_tests.py` (a
shadowed test is a test that silently stopped guarding) and
`tests/governance/test_workspace_drift_gate.py` (drift detection on
every governance run, not on demand).

## Signal hygiene: keep governance + unit at 0 failures

Never tolerate a "known/pre-existing failure" backlog. A 48-failure
backlog once masked a real OOM regression — new failures lost all
signal value. Fix to zero, or mark explicit `xfail` with a reason +
owner. `ci.yml` (Unit + Governance + E2E-fast, no LLM) is the **merge
gate** and must be green; `e2e-nightly.yml` (full LLM) is advisory —
it is LLM-endpoint-latency-gated, so a red e2e is usually infra, not
code (confirm before "fixing" code). In tests, set env via
`monkeypatch`/yield-restore, never `os.environ.setdefault` (it leaks
across the session). CI embed must be `OLAV_EMBEDDING_MODE: local` —
the job container cannot reach the internal Ollama at `…:11434`.
**Agent-behaviour issues need N≥3 runs to call closed** — LLM output
variance on identical input (same model, config, prompt) can exceed the
patch's effect (one run made 0 tool calls, the next 31). A single green
run is not signal; track a success rate or run ≥3 before declaring a
behavioural fix done (V2_VALIDATION_RETROSPECTIVE §M4).

## Versioning & Release

`olav` and `olav-netops` ship **as a unit** — bump them together or
`tests/governance/test_package_version_parity.py` fails. A version bump
touches **5 places**: `pyproject.toml` version (source of truth),
`src/olav/__init__.py` `__version__`, `olav-netops/pyproject.toml`
version **and** its `"olav>=X"` pin, `olav-netops/src/olav_netops/__init__.py`
`__version__`, plus `BUILD_DATE`/`RELEASE_DATE` in `src/olav/core/version.py`
(VERSION itself auto-reads package metadata). Add a `CHANGELOG.md` entry.

Validate releases from a **fresh venv + built wheel**, never an editable
install (it masks ~20 bug categories). Pre-publish: `uv build` →
`twine check` → fresh-venv install + `olav version` smoke → scan the
artifacts for leaked secrets.

**Production PyPI is a manual step**: `twine upload` with the root
`.pypirc` (`[pypi]`). `release.yml` only creates a GitHub Release;
`scripts/release.sh` only targets TestPyPI; **pushing a git tag does
NOT auto-publish to PyPI**. The wheel is `packages=["src/olav"]` (no
`enterprise/`, no `web/`, no `olav_netops/`); secrets live outside
`src/olav` so they never package.

## Safety

- `--dangerously-skip-permissions` bypasses approval gates for testing only. See `src/olav/platform/safety/permissions.py`.
- DuckDB `read_only=True` is a data-integrity constraint and is never bypassed.
- Never mount `/` in a privileged container with `rm -rf` — always mount specific directories and guard empty path variables.
- Embedding **dimension mismatch must fail-fast** (`EmbeddingDimMismatchError`, `src/olav/core/memory/__init__.py`), never silently drop the table — a 768→2048-dim switch once wiped the entire memory table. `OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION=1` is debug-only (ISSUE-EMBEDDING-FALLBACK-DIM-MISMATCH-DESTROYS-DATA).

## 工作语言与汇报规范

**所有汇总、状态报告、分析结论一律使用简体中文输出。**

- 代码、commit message、文档（CLAUDE.md / dev_docs / ADR）保持英文
- 与用户的交互对话、分析判断、进度汇报使用中文
- 错误诊断和根因分析也用中文，代码片段内嵌英文注释正常
