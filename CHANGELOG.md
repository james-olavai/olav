# Changelog

All notable changes to OLAV will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

## [1.0.0] - 2026-02-25

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
