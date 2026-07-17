# Changelog

All notable changes to OLAV will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.22.2] - 2026-07-17

Patch: fresh-install fixes surfaced by the V3 demo runsheet.

- **Cap `deepagents-code<0.1.17`.** Upstream deleted `config.SessionState`
  in 0.1.17 (still present through 0.1.16); we import it for interactive
  mode. With the old open-ended `>=0.1.8` pin, a fresh `pip install olav`
  resolved to the latest (0.1.41) and died at first interactive run with
  `cannot import name 'SessionState'`. Editable/dev installs masked it by
  holding an older wheel. Verified all overlay-patched internals still
  exist on 0.1.16; added 0.1.16 to `tui_overlay._SUPPORTED_VERSIONS`.
- **Declare `langchain-anthropic`.** The first-run provider selector's
  "Anthropic (Claude)" option writes `model_provider="anthropic"`, which
  langchain backs with this package. It was only present transitively.
- **Bootstrap key check now honours `shared.api_key` + `ANTHROPIC_API_KEY`.**
  `_ensure_bootstrapped` only looked at `llm.api_key` + `OPENAI_API_KEY`/
  `OLAV_LLM_API_KEY`, so a key set in `shared.api_key` (the documented
  homogeneous-deploy pattern) wrongly re-prompted "No LLM API key
  configured yet". It now mirrors the runtime resolution order.
- **Importer honours its advertised inputs (netops).** The importer's
  SKILL.md advertises "directory or **zip file** / rancid backup / vendor
  dump", but `survey_bundle` rejected anything that wasn't an already-
  extracted canonical directory — a compressed `.tar.gz` backup returned a
  bare `{"error": "not a directory — zip not yet supported"}` with no
  `notes`, and the agent looped trying to extract it by hand and delegating
  to every sub-agent. `survey_bundle` now transparently (a) **extracts
  archives** (`.tar.gz`/`.tgz`/`.tar`/`.zip`, with path-traversal
  guards), (b) **normalises a raw collector dump** (command-major
  `network_data/<command>/<host>`) into a canonical bundle, and (c)
  returns the ready-to-ingest `path` plus a structured `notes` field on
  failure so the agent **stops instead of looping**. New helper
  `_bundle_prepare.py`; idempotent temp-dir conversion (safe on read-only
  source mounts). Runsheet Ch2 now imports the `.tar.gz` directly.
- **Actionable "agent not deployed" error.** `--agent netops` when the
  `olav-netops` package is pip-installed but its workspace was never
  deployed used to raise a bare `Workspace agent 'core/netops' does not
  exist` traceback. It now detects the installed-but-not-deployed case and
  tells the user the one command that fixes it: `olav skill install
  olav-netops`. Generic over any `olav-<name>` extension.
- **Test hygiene:** `test_api_key_precedence` no longer leaks a tmp
  OpenRouter config into the global singleton (poisoned governance smoke
  tests that then tried to init ChatOpenRouter).

## [0.22.1] - 2026-07-06

Patch: local OpenAI-compatible embedding backends. 0.22.0's default
(local `BAAI/bge-small-zh-v1.5`) and cloud embedding are unaffected;
this fixes the conversational switch to a **local** embedding server.

### Fixed
- **Local embedding servers (Ollama / llama.cpp / vLLM)**: `get_embeddings`
  now sends raw-string input (sets `check_embedding_ctx_length=False`) for
  any non-`openai.com` embedding endpoint. OpenAIEmbeddings otherwise
  tiktoken-tokenises input into integer-ID arrays, which those servers
  reject with HTTP 400 "invalid input type". Generic rule keyed on the
  endpoint URL, not hardcoded to any one server.

### Added
- `update_embedding_config` gains a `base_url` argument, so the admin
  editor sub-agent can point the embedding backend at a local
  OpenAI-compatible server conversationally (validated before commit,
  rollback-able) — e.g. `olav --agent admin "switch embedding to api mode
  using the local Ollama model embeddinggemma at http://localhost:11434/v1"`.
  This is what the docs (getting-started/installation, dev_docs/100 Ch8b)
  already describe; 0.22.1 makes the shipped wheel match.

## [0.22.0] - 2026-07-05

"Software understands the human" release — the full design + implementation
record is dev_docs/99. The theme: a first-time user should never need to
read docs before OLAV is useful, and a mistake should never cost a working
setup.

### Added
- **Zero-ritual onboarding**: bare `olav` on a fresh directory now runs
  the (idempotent) init sequence itself and prompts once for the LLM API
  key — no separate `olav init` step, no hand-editing `api.json`.
  `olav init` remains as the non-interactive CI/scripted path.
- **`olav doctor` + TUI `/doctor`**: deterministic zero-LLM health check
  (scaffolding, LLM connectivity, embedding backend); every failing check
  carries an actionable `fix:` line. `--json` for machines.
- **State-aware welcome screen**: real findings replace random tips —
  embedding-backend failures, extension empty-state guidance ("netops has
  no device data yet — run /netops_init / import a snapshot"), and
  returning-user context ("Welcome back — last time (2h ago): …").
- **`olav.first_run_checks` entry-point contract**: extensions register
  deterministic "am I initialized?" checks; the platform only discovers
  and displays (repo-boundary safe). olav-netops ships the first provider.
- **Conversational self-configuration** (admin/editor):
  `update_llm_config` / `update_embedding_config` @tools with
  validate-before-commit — a candidate config is tested against the live
  provider before being written; rejects preserve the working config.
  `rollback_config` restores the pre-change snapshot in one sentence.
- **Generalized undo**: workspace file writes and cron changes are
  journaled (`olav.core.undo_journal`, `.olav/run/undo/`);
  `undo_last_action` (editor) reverts the most recent action —
  restore/delete for files, remove/reschedule/re-add for cron.
- **Actionable failure recovery**: mid-session LLM failures (401 / quota /
  unreachable endpoint) print a classified one-line hint (doctor + the
  rollback phrase) instead of a bare traceback.

### Fixed
- **admin router stale sub-agent names**: routing table still said
  `task("developer", …)` after the rename to `editor`, and never routed
  to `installer` — any config/self-management request fell through to raw
  filesystem search. Found by the new behavioural e2e.
- **`refresh.py` dead routing path removed**: `_update_main_agent_routing`
  targeted `core/prompts/system.md`, which no longer exists post-SKILL.md
  migration (always a no-op). `tests/unit/test_refresh_command.py`
  salvaged from `collect_ignore` (stale AGENT.md-era assertions fixed;
  20/20 passing).
- **api_request docstring + recall-tool tier docs** aligned with the
  script-first architecture and TIER_DEFAULTS (governance-pinned in
  `test_hardcoded_fallbacks.py`).

### Changed
- **Syslog storage rename**: `LOG_STORAGE_DIR` → `SYSLOG_STORAGE_DIR`,
  `.olav/databases/logs/` → `.olav/databases/syslogs/`, `olav service
  logs` → `olav service syslogs`.
- Docs (README en/zh, docs.olavai.com installation/first-query + new
  Self-Configuration & Recovery guide) rewritten around the zero-config
  flow.

## [0.21.0] - 2026-06-15

Consolidated release covering the 0.20.x line (deepagents/langchain
platform cutover) plus the 0.21 governance, docs-accuracy, and CI
hardening work. (No separate 0.20.0 changelog entry was published; the
major 0.20 items are folded in here.)

### Added
- **ADR-0015 unified memory + global KB**: single LanceDB `memory` table
  with `reflection` / `expert_knowledge` split; `olav kb` command group
  (import/sync/search/status/graph) over a global `olav_kb/` store;
  R102 `memory_curator` conversational ingestion (two-turn HITL drafts).
- **Self-improving loop wired end-to-end**: `trace_learner` now writes
  failure constraints as `category=reflection, scope=global` with real
  embeddings and a reserved AutoRecall quota, so lessons reach every
  agent (previously write-only). `/trace-review` slash command restored.
- **LLM providers**: Google AI Studio (native `ChatGoogleGenerativeAI`),
  NVIDIA NIM embedding config, local embeddinggemma embedding endpoint.
- **Headless line REPL**: piped stdin (`echo "/quit" | olav`) routes to a
  non-TTY REPL instead of hanging the full-screen Textual TUI.
- **CI**: Parquet+zstd demo-DB fixtures for fast e2e seeding; Batfish
  live integration tests; WebGUI browser e2e via browserless-chrome.

### Changed
- **deepagents/langchain platform cutover (0.20)**: langchain 1.3.x /
  langchain-core 1.4.x / langgraph 1.2.x / deepagents 0.6.7; P5 langgraph
  graph factory; interactive REPL migrated `deepagents-cli` →
  `deepagents-code`.
- **Workspace single-config**: merged `AGENT.md` → `SKILL.md`; flattened
  `guides/` → `references/`; `prompts/` content moved into `SKILL.md`
  bodies. RubricMiddleware / TodoListMiddleware are opt-in per SKILL.md.
- **Config over hardcoding**: business params (e.g. `reflection_ttl_days`)
  read from `.olav/config/api.json`, not literals.
- Embedding client now sends raw strings and bounds its timeout/retries.

### Fixed
- Router index build no longer 400s against local OpenAI-compat embed
  endpoints (`check_embedding_ctx_length=False`).
- `olav init` / `olav skill install` no longer hang on a slow/unreachable
  embed endpoint (embed client `timeout`/`max_retries`).
- `olav skill install` uses `uv pip install` (no more "No module named
  pip" in uv-created venvs).

### Removed
- `[enterprise]` pip extra (its deps were wheel-excluded and never
  loaded); enterprise features ship via the `olav-ent` package.
- `src/olav/web/` (WebGUI dev tree) excluded from the wheel/sdist — the
  exported site ships from `src/olav/api/static`.

### Governance & CI
- Tracking policy flipped to `git:track` for `tests/**`, `dev_docs/**`,
  `scripts/**` (previously ~57% of tests, 65% of design docs were
  untracked — invisible to CI and review).
- New governance gates: workspace-drift check and duplicate-shadowed-test
  detector; Definition-of-Done rule (new modules need a real entry-point
  integration test).
- Test-failure backlog cleared (48 → 0); e2e CI hardened (embed-local
  fallback, embedder pre-warm, realistic CLI timeouts, job timeout-minutes).

## [0.19.0] - 2026-04-19

### 🏗️ Architecture — ARCH-23 MVC Core Refactor (R64 + R65)

- **Core 3 orchestrator tools + 5 sub-agents**: `core/tools/` trimmed to
  the 3 truly-cross-domain tools (`execute_sql`, `olav_recall_memory`,
  `web_search`); 17 tools relocated into sub-agent homes:
  - `core/admin/tools/` — 11 tools (`analyze_logs`, `bulk_ingest`,
    `deploy_service`, `get_static_context`, `load_reference`,
    `manage_cron`, `search_logs`, `stop_service`, `tool_help`,
    `workspace_health`, `write_workspace_file`)
  - `core/api_query/tools/` — `api_request`, `service_health`
  - `core/db_query/tools/` — `describe_table`, `execute_sql`
  - `core/remote/tools/` — `remote_execute`, `run_shell`
  - `core/writer/tools/` — `format_and_export`, `read_file`
- **`core/AGENT.md` frontmatter** carries `subagents:` list (5 entries);
  packaged + deployment aligned byte-for-byte for tool files.
- **`api_request.py` compact envelope**: `_COMPACT_LIST_CAP=50` with
  `status: truncated` envelope for DRF-pagination responses
  (ARCH-18 #2 pattern).

### 🗑️ Removed — ARCH-22 A2 v0.19 Cut (R66)

- **`src/olav/core/audit_logger.py`** — 148 LOC no-op shim deleted.
  `AuditEventRecorder` has been the authoritative audit write path
  since Round 18; audit_logger.py carried a `LEGACY-REMOVE-v0.19`
  marker for this cut. 0 importers under `src/olav` verified before
  deletion.

### 🔧 Fixed

- **Tier 0 B11 (nornir resolver)** — `_resolve_nornir_config_path()`
  adds priority 0 for the post-R32 canonical
  `.olav/workspace/ops/collect/config/nornir/config.yaml`; the older
  `probe/` path demoted to priority 1 for pre-R32 deployments.
- **ARCH-22 C2 DEDUP_STRATEGY** — `exact_v1` literal extracted to a
  module-level `DEDUP_STRATEGY` constant in
  `src/olav/enterprise/audit_dataset_export.py` with
  `OLAV_DEDUP_STRATEGY` env override. 2 call sites use the constant.
- **Version sync** — `src/olav/__init__.py::__version__` bumped from
  0.15.0 → 0.19.0, fixing pre-existing drift from `pyproject.toml`.

### ♻️ ARCH-22 Matrix — Platform Scope Closed

Post-R66: **9 Closed / 3 Fixed / 0 Deferred** + 1 Warning-only (C5
`store` param physical removal left for next major). A4
(`_legacy_archived/` 180MB archive) reclassified as non-governance:
already gitignored (line 98), never enters clones/wheels/release
artefacts; local disk footprint is an operator cleanup concern.

## [0.15.0] - 2026-04-12

### 🏗️ Architecture — Unified Core Agent
- **Quick → Core merge**: `quick` workspace 合并入 `core`。用户不再需要 `--agent quick` — 所有日常查询直接 `olav "问题"`
- **Writer subagent**: `core/writer/` — 报告润色能力（PlantUML 拓扑图 + Infographic KPI + draw.io 可编辑图），作为 core 的子技能而非独立 agent
- **Skill injection**: `workspace.yaml` 新增 `inject_into_core` 字段 — `olav skill install` 自动将工具符号链接到 core/tools/，卸载时清理
- **Semantic Router wired**: `olav refresh` 调用 `initialize_router()` 建 `agent_intent_index`；`cli/main.py` 用 `route_query()` 结果选 agent（score > 0.85 → 专业 agent，< 0.85 → core）
- **`load_reference` tool**: 大文件 reference 改为按需加载（渐进式披露），static_context 只保留 ≤50 行核心规则
- **Runtime Reflection**: PLATFORM.md R1-R4 规则 — agent 遇到工具错误自动重试（最多 2 次），不直接报错给用户

### 🚀 Features
- **`olav refresh`**: 扫描 workspace/*/AGENT.md → 重写 PLATFORM.md + 更新 main agent routing table；auto-hook 到 `olav init` + `olav skill install`
- **`audit_workspace` 扩展**: `_check_platform_md_stale()` 检测 PLATFORM.md 过时
- **Memory recall bump**: `AutoRecallMiddleware.enrich()` 命中后更新 `access_count`（C-KB-08 高频保护生效）
- **Time decay scheduling**: daemon 启动时 asyncio 24h 循环调用 `apply_time_decay()`（document/user 不衰减，agent 60d 半衰期）

### 🗑️ Removed
- `.olav/workspace/quick/` — 工具合并入 core
- `.olav/workspace/olav/` — 空壳 main agent，core 替代
- `.olav/workspace/venv-test-skill/` — 测试残留
- `.olav/workspace/labs/` — 空目录
- `cli/main.py` `"quick"` 硬编码 — 默认改为 `"core"`
- `router.py` fallback `"quick"` — 改为 `"core"`

### 🐛 Bug Fixes
- `00_e2e_acceptance_test.py`: 12 处 "quick" 引用 → "core"
- `query_runner.py:22`: SCHEMA_REFERENCE 路径从 `quick/` → `core/`
- `agents/agent.py:151`: 默认 agent_id 从 `"quick"` → `"core"`
- `builtin.py:28`: 默认 agent_id 从 `"quick"` → `"core"`
- 7 个 workspace fallback 测试更新断言（`"netops"` → `"core"` 当目录不存在时）

### 🧪 Tests
- 1544 passed, 0 FAIL (unit + gate + e2e + integration)
- 16 TDD claims (C-V15-01~16) — core 升级 / skill 注入 / 语义路由
- `test_v15_cleanup.py`: 12 tests (workspace 清理验证)
- `test_v15_core_e2e.py`: 13 tests (core agent + writer + list)
- `test_v15_skill_inject.py`: 4 tests (inject_into_core lifecycle)
- `test_v15_router.py`: 4 tests (semantic router integration)

### 📚 Documentation
- olav-doc: 22 页 "Quick Agent" → "Core Agent" 更新（EN + ZH）
- `guides/report-writer.en.md` + `.zh.md`: writer 使用指南
- `guides/build-a-skill.en.md`: `inject_into_core` 字段说明
- `42. DEMO_RUNSHEET.md`: v0.15.0 全面更新
- `44. VISUALIZATION_SKILLS_INTEGRATION.md`: Mermaid 默认 + writer 润色设计

## [0.14.0] - 2026-04-11

### 🚀 Features — Unified Knowledge Store (M3)
- **Knowledge Base CLI**: `olav kb` command group — `status`, `export`, `sync`, `import`, `search`, `graph`, `backfill-tags`, `migrate` (C-KB-01~28, C-L3-UKS)
- **Unified Storage**: Single LanceDB `memory` table replaces legacy `kb_chunks` + `memory` dual tables. New columns: `origin` (agent/document/user/audit), `confidence` (0.0-1.0), `tags` (JSON array)
- **Knowledge Graph**: `materialize_graph()` — LanceDB vector similarity as implicit edges + tags co-occurrence as explicit edges; vis.js interactive HTML export (`olav kb graph`)
- **Obsidian Export**: `olav kb export` → `.olav/knowledge/` vault with YAML frontmatter + `[[wikilinks]]` + `_entities/` index pages
- **Bidirectional Sync**: `olav kb sync` — markdown file changes sync back to LanceDB (insert/update/delete diff); `--dry-run` support
- **AutoCapture Tags**: `_EXTRACT_PROMPT` extracts 2-5 entity/topic tags per captured memory; `backfill-tags` retroactively tags existing entries via LLM
- **Time Decay Differentiation**: `document`/`user` origin never decays; `agent` decays normally (half_life=60d); `audit` slow decay (365d); high-frequency recall (access_count>=5) halves decay rate

### 🚀 Features — Multi-User & Sessions (M4)
- **Auto User Creation**: `olav init` auto-creates admin user from `$USER`, writes token to `~/.olav/token`, sets `auth.mode=token` (C-L4-01)
- **Linux User Validation**: `olav admin add-user` verifies Linux user exists via `pwd.getpwnam()`; `--no-verify` flag for containers (C-L4-02)
- **Session Sync**: `sessions` table in `audit.duckdb`; `olav sessions` lists current-user sessions; `olav --resume <thread_id>` resumes across CLI/TUI/Web (C-L4-03/04)
- **Thread Ownership**: API `stream_run()` enforces 403 for non-owner access; admin role bypasses (C-L4-05)
- **Auth Security**: `secure=True` on session cookies; `auth.mode=none` emits startup WARNING (C-L4-07)

### 🚀 Features — Platform
- **Syslog Consumer**: `search_logs` core skill — DuckDB `read_parquet()` queries on syslog Parquet files; registered in core SKILL.md (C-L4-06)
- **Agent Registry**: `olav refresh` — scans `.olav/workspace/*/AGENT.md`, generates `PLATFORM.md`, updates main agent routing table; auto-triggered by `olav init` + `olav skill install`
- **Topology Engine**: `extract_lldp_topology()` — CDP/LLDP parsed_outputs ETL to topology_links; bidirectional link ID deduplication; `src != dst` self-loop filter
- **IngestManager Pipeline**: `netops_init/run.py` uses staging JSON → `IngestManager.bulk_load()` → `extract_lldp_topology()` (replaces direct INSERT)

### 🗑️ Removed
- **NETCONF**: `netconf_collector.py` (281 lines) + `ncclient` dependency — SSH/TextFSM pipeline replaces NETCONF collection
- **OpenConfig**: `schema_engine.py`, `schema_cache.py`, `schema_mutation_service.py` (950+ lines) — OC normalization architecture removed
- **OC Discovery Tools**: `classify_field.py`, `trigger_schema_evolve.py`, `create_unified_view.py`, `register_api_schema.py` — dead imports to missing schema_engine
- **Legacy KB**: `KnowledgeBase` class, `kb_chunks`/`kb_query_cache` LanceDB tables, `search_knowledge_lancedb.py` tool, `config/knowledge/` workspace tools — replaced by unified `memory` table + `olav kb` CLI
- **Dead Dependencies**: `pygnmi`, `xmltodict`, `pyang`, `yangson` — zero code imports
- **Dead Tests**: `test_netconf_collector.py`, `test_kb_semantic_cache.py`, `test_gate_phase2_normalization.py`, 9 unconditional-skip tests, `test_tracking_doc_consistency.py`

### 🐛 Bug Fixes
- `kb.py _get_store()`: `MemoryConfig.db_path` AttributeError → fallback to wrong path; fixed to direct `get_store()` call
- `kb.py --output` argparse default `"_graph.html"` overrode vault path logic; fixed to `default=None`
- `export_obsidian()`: tags containing `/` crashed file creation (e.g. `FastEthernet0/0`); added `_safe_tag()` sanitizer
- `search_by_text()`: return dict missing `origin`/`confidence`/`tags` fields; aligned with `search_by_vector()`
- `olav sessions`: not registered as argparse subparser → treated as NL query; added to subparser + `known_commands`
- `olav admin add-user bob`: args parsing only took first token; fixed `" ".join(args.args)`
- `olav admin add-user <nonexistent>`: printed error but exit 0; fixed to `raise SystemExit(1)`
- `manage_cron.py` source template: hardcoded `/home/yhvh/Olav`; fixed to `_get_project_root()`
- CLAB IP `192.168.100.12`: hardcoded in `run_shell.py` regex + agent prompts; extracted to `OLAV_CLAB_HOST` env var
- `topology_links` self-loops: `topology_engine.py` added `src_dev != dst_dev` filter
- Gate tests `prefixes_received` column: referenced non-existent column in `v_bgp_neighbors`; removed from 13 files
- 5 unit tests hardcoded `/home/yhvh/Olav`; fixed to `Path(__file__).parents[2]`

### 🧹 Cleanup
- **deepagents-cli**: Added as formal dependency with `[tool.uv] override-dependencies` resolving version conflict (no more `--no-deps`)
- **DB rebuild**: `main.duckdb` full rebuild from clean SSH collection; legacy OC tables removed
- **Test restructuring**: 86 fake E2E tests → `tests/gates/`; 24 fake claim tests → `olav-netops/tests/gates/`; CI `test.yml` workflow added
- **Phase tests**: `_HAS_LAB_DATA` fine-grained skipif per phase (mapping_rules, topology_links, v_bgp_neighbors_auto)
- **Pyc artifacts**: deleted orphaned `__pycache__/*.pyc` from removed source files
- **`config_evolve.py`**: `_write_to_lancedb()` returns False (schema_engine deleted)

### 🧪 Tests
- **1490 passed, 0 FAIL** (unit + gate + e2e + integration)
- 119 claims in registry (C-L1 + C-L2 + C-NE + C-KB + C-L3 + C-L4)
- `test_m4_l4_e2e.py`: 13 always-run tests (C-L4-01/02/03)
- `test_m3_kb_llm_e2e.py`: 10 LLM-gated tests (C-KB-22/28 + C-KB-04)
- `test_uks_*.py`: 28 TDD unit tests (C-KB-01~28)
- `test_m4_*.py`: 5 unit test files (init_user, search_logs, sessions_cli, sessions_table, thread_ownership)
- All `.func()` calls replaced with `.invoke()` across test suite

### 📚 Documentation
- `guides/knowledge-base.en.md`: Rewritten for UKS (olav kb CLI, Obsidian export, graph visualization)
- `guides/services.en.md`: Added `search_logs` warning banner (v0.12+)
- `reference/users-and-roles.en.md`: Added `olav init` user creation flow, `olav sessions`, thread ownership
- `concepts/security-model.en.md`: Corrected session storage location + thread ownership enforcement
- `reference/claim-registry.en.md`: Added Level 3 (C-L3-UKS + C-KB-01~28) and Level 4 (C-L4-01~07)
- `42. DEMO_RUNSHEET.md`: Rewritten for v0.14.0 with 12 chapters including KB, syslog, multi-user

## [0.13.0] - 2026-04-09

### 🚀 Features
- **DevOps Agent**: New `olav --agent devops` — generates production-ready, environment-aware automation scripts; queries `netops.devices` for real device data; exports to `exports/scripts/` with `--dry-run` + error handling (C-NE-41~44)
- **DevOps Agent**: Infra write mode — `--enable-api-write` flag with dry-run gate and mandatory approval for write operations (C-NE-39)
- **DevOps Agent**: `devops/references/` static context — `BASELINE_SCHEMA.md` and `OLAV_PLATFORM_HEALTH.md` loaded as agent context
- **Platform**: `get_domain_prompt()` — entry-point based domain extension loading; netops/ent domains inject context at startup
- **CLI**: `olav --agent devops "write a script..."` natural language script generation workflow

### 🗑️ Removed
- **Config Agent**: Skill Builder removed — `write_skill_code`, `generate_skill_config`, `read_api_schema` tools deleted from `config/system`
- **Config Agent**: `config-creator` delegation route removed from config orchestrator SKILL.md
- **Config Agent**: `create skill` route keyword removed from `config/MANIFEST.yaml`
- Modern replacement: use `olav registry register <url>` for API onboarding + `olav --agent devops` for script generation

### 🧹 Cleanup
- `tool_generator.py`: removed 2 stale NOTE comment blocks referencing legacy architecture
- `delegate_tool.py`: docstring example updated from `config-creator` to `config-discovery`
- `ops-lab/tools/destroy_lab.py`: fixed missing symlink to `ops/lab/tools/destroy_lab.py`
- `ops-lab/tools/__init__.py`: removed empty clutter file

### 🧪 Tests
- Added `TestDevopsAgentE2E` (5 LLM-gated tests) — validates C-NE-41~44 end-to-end
- `DEVOPS_E2E_ENABLED=1` env var gates live LLM invocation (mirrors `NL_QUERY_ENABLED` pattern)

### 📚 Documentation
- `olav-doc`: Rewrote `guides/creator-agent` — Skill Builder removed; redirects to devops agent + registry register
- `olav-doc`: Updated `guides/connect-a-service` — removed Creator Agent section; documents DevOps agent script generation
- `olav-doc`: Claim C-L2-20 remapped to DevOps agent (v0.13.0); C-NE-41~44 bumped to v0.13.0
- `olav-doc`: devops-agent index EN+ZH claim versions bumped to v0.13.0

## [0.12.0] - 2026-04-02

### 🚀 Features
- **Platform**: Creator Agent 6-step workflow — auto-generates skills from any OpenAPI service
- **Platform**: Docker full lifecycle — `deploy_service`, `stop_service`, `list_services` tools
- **Platform**: Core tools workspace — 8 platform tools migrated to `core/` and injected into all agents
- **Platform**: `olav_delegate` — deep-agent tool isolation fix; all subagents as `CompiledSubAgent`
- **Security**: Multi-user audit concurrency — short-lived DuckDB connections + threading lock + retry
- **Security**: `readonly_post_paths` enforced in HTTP client write gate

### 🐛 Bug Fixes
- Fixed `service_call` ignoring `readonly_post_paths` whitelist (POST /query was blocked)
- Fixed Creator Agent function name hallucination (Step 4b: reads generated file for real names)
- Fixed `deploy_service` not finding `.yaml` extension (only checked `.yml`)
- Fixed schema probe paths expanded to 17 entries (InfluxDB, SpringDoc, K8s, FastAPI)

### 🗑️ Removed
- `ping_device`, `traceroute`, `port_scan` tools (use `run_shell` instead)
- `call_api.py` (hardcoded IP) — replaced by `service_call("clab", ...)`
- `v0_10_raw_diffs.py` ghost migration (unreferenced)

## [0.10.0] - 2026-02-25

### 🚀 Features

- **Architecture**: Complete migration to DeepAgents + LangGraph framework
- **CLI**: Full migration to deepagents-cli with native components
- **CLI**: Migration to argparse for argument parsing
- **CLI**: Add daemon mode for persistent agent process
- **Ops**: Implement skill independence for diff and web search tools
- **Ops**: Add search_cache tool for semantic cache lookup
- **Ops**: Add execute_sql table output
- **Core**: Add ResponseCache with snapshot-aware invalidation
- **Knowledge Base**: Integrate unified KB system with DuckDB
- **Cron**: Implement periodic task scheduler with python-crontab
- **Command Learner**: Implement Command Learner Agent v2.1.0
- **Admin**: Implement ultra-minimalist Admin Agent v2.1.0
- **Reporting**: Enhance report quality with deep LLM analysis and root cause reasoning

### ⚡ Performance

- Add DuckDB response cache for instant repeated queries
- Add --prewarm flag for faster first query
- Make prewarm default, optimize cache check order
- Implement lazy loading + large data handling
- Add streaming output + direct SQL mode

### 🐛 Bug Fixes

- Fix CLI startup and tool discovery issues
- Add prewarm to interactive mode
- Eliminate duplicate output by replacing streaming with single invoke+render
- Replace hardcoded snapshot commands with NTC-based dynamic resolution

### 🔧 Maintenance

- Refactor CLI: remove dead code, cli_main.py and stale cache functions
- Consolidate hardcoded parameters into KnowledgeSettings config
- CLI simplification: remove admin prefix

### 📚 Documentation

- Complete AUDIT user guide in Chinese and English
- Unified documentation structure
- Clean up legacy code
- Implement Map-Reduce batch fix script functionality

---

## [0.9.x] - 2026-01 to 2026-02 (Legacy)

Previous versions documentation is available in `_legacy_archived/` directory.

- v0.9.9: DeepAgents CLI migration phase 1-3
- v0.9.8: Command Learner Agent v2.0
- v0.9.7: Knowledge Base integration
- v0.9.6: Response caching
- v0.9.5: Cron scheduler
- v0.9.0-v0.9.4: Legacy architecture
