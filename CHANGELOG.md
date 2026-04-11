# Changelog

All notable changes to OLAV will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
