# OLAV - PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-21
**Version:** v0.9.8

## OVERVIEW

Network operations AI assistant built on DeepAgents + LangGraph. Uses DuckDB as ground truth, Nornir/Netmiko for network automation. 3 SubAgents: olav-ops (query), olav-config (infrastructure/write), olav-audit (governance + health checks).

## STRUCTURE

```
./
├── src/olav/           # Framework: agents/, cli/, core/
├── config/             # Settings: settings.py, paths.py, tasks.py
├── .olav/              # User data: skills/, databases/, config/
├── docs/               # User guides
└── dev_docs/          # Planning docs
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new tool | `.olav/skills/<skill>/tools/` | Auto-discovered via `@tool` |
| Add new skill | `.olav/skills/<name>/SKILL.md` | Register in `.olav/OLAV.md` |
| Modify config | `config/settings.py` | Three-layer: env > .env > settings.json |
| DB schema | `.olav/databases/main.duckdb` | Synced from Nornir hosts.yaml |
| CLI entry | `pyproject.toml` → `olav.cli.cli_app:app` |

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** hardcode paths in tools — use args with defaults from config/settings.py
- **NEVER** create SubAgent in code — must be registered in `.olav/OLAV.md`
- **NEVER** cross-reference Skills — each Skill independent, auto-loaded
- **NEVER** use Mock data in E2E tests — must use real Nornir inventory
- **NEVER** skip DeepAgents/LangChain native components — use DuckDBSaver, SubAgent, etc.

## CONVENTIONS

- Language: English for code/variables/comments, Chinese for user-facing docs only
- Skills: One SKILL.md + tools/ + prompts/ per Skill
- Tools: `@tool` decorator, docstring = LLM routing signal
- Config: Three-layer priority (env vars > .env > settings.json > defaults)

## COMMANDS

```bash
# Run
uv run olav ask "How many devices?"
uv run olav interactive

# Dev
uv run pytest tests/ -v
uv run olav admin status
```

## NOTES

- Single Source of Truth: Nornir hosts.yaml → DuckDB devices table (sync via olav-config)
- HITL: olav-config requires human approval for write operations
- Intent-Based: olav-audit uses YAML configs with intents (not hardcoded commands)

## TROUBLESHOOTING

### CLI fails to start
- Run `uv run olav --help` to verify CLI works
- Check `.env` has valid `LLM_API_KEY`
- Verify skills exist: `ls .olav/skills/`

### SubAgent prompt not found
- Error: `RuntimeError: SubAgent 'xxx': prompt file not found`
- Check `.olav/OLAV.md` subagents section references valid skills
- Ensure skill has `prompts/system.md` file

### Tool discovery errors
- Modules without `@tool` decorators are gracefully skipped
- Helper modules (e.g., `audit_engine.py`) should NOT have `@tool` decorators
- Tool discovery logs at DEBUG level, not ERROR
