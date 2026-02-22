# OLAV CLI Migration Plan v0.9.9 → deepagents-cli

**Date**: 2026-02-22
**Branch**: `feature/v0.9.9-deepagents-cli`
**Goal**: Complete migration to deepagents-cli framework, remove all fallbacks

---

## Executive Summary

### Current State (v0.9.8)
- **Framework**: Custom Typer-based CLI (995 lines)
- **Commands**: 15+ commands via Typer subcommands
- **Interactive**: Custom prompt-toolkit session (1191 lines)
- **Agent**: Custom OLAVAgent wrapper
- **Optimizations**: Three-tier response system (cache → daemon → in-process)

### Target State (v0.9.9)
- **Framework**: deepagents-cli (argparse-based)
- **Commands**: OLAV-specific commands as argparse subcommands
- **Interactive**: deepagents-cli interactive mode
- **Agent**: `create_deep_agent()` from deepagents
- **Optimizations**: Preserve three-tier caching as middleware

---

## Architecture Comparison

| Component | OLAV (v0.9.8) | deepagents-cli | Migration Action |
|-----------|---------------|----------------|------------------|
| CLI Parser | Typer | argparse | **REPLACE** |
| Entry Point | `cli_app.py` | `main.py` | **ADOPT** |
| Agent Creation | `OLAVAgent` | `create_deep_agent()` | **ADOPT** |
| Interactive | `OlavPromptSession` | `create_prompt_session()` | **ADOPT** |
| Config | `config/settings.py` | `Settings` dataclass | **HYBRID** |
| Skills | `.olav/skills/*/SKILL.md` | Same pattern | **KEEP** |
| Middleware | Custom | TodoList, Skills, HITL | **ADOPT** |

---

## Components to DELETE (No Fallbacks)

### From cli_app.py
- [ ] Typer app and all decorators
- [ ] `_get_cached_agent()` → use deepagents agent caching
- [ ] Custom `_stream_response()` → use deepagents execution

### From admin.py
- [ ] `admin_handler()` AI routing → use deepagents agent directly
- [ ] Fast-path commands → convert to argparse subcommands

### From session.py
- [ ] `OlavPromptSession` → use deepagents `create_prompt_session()`
- [ ] Custom history management → use deepagents memory

### From display.py
- [ ] Banner system → delete (cosmetic)
- [ ] Todo display → use deepagents TodoListMiddleware

### From commands/
- [ ] `base.py` → delete (unused)
- [ ] `builtin.py` → delete most, keep `/learn_cmd` as tool

---

## Components to KEEP (OLAV-Specific)

### Network Operations
- `devices` command → argparse subcommand
- `inspect` command → argparse subcommand (Nornir integration)
- `db-query`, `db-schema`, `db-status` → argparse subcommands

### Knowledge Base
- `kb-*` commands → argparse subcommands
- Vector search integration → preserve as tools

### Task Scheduling
- `task schedule/unschedule/status` → argparse subcommand
- Cron-based inspection → preserve

### Optimizations
- Three-tier caching → implement as middleware
- Daemon socket → preserve as optimization layer

---

## Migration Phases

### Phase 1: Setup & Tests (TDD)
```bash
# Create test structure
tests/
├── cli/
│   ├── test_main.py           # Entry point tests
│   ├── test_commands.py       # Command execution tests
│   └── test_interactive.py    # Interactive mode tests
```

**Tests to write:**
1. `test_cli_entry_point()` - Verify `olav` command works
2. `test_ask_command()` - Single query mode
3. `test_interactive_mode()` - Interactive session
4. `test_devices_command()` - Network device listing
5. `test_inspect_command()` - Snapshot execution
6. `test_db_commands()` - Database operations

### Phase 2: Core Migration
1. Create new `src/olav/cli/main.py` based on deepagents-cli
2. Implement `parse_args()` with OLAV-specific subcommands
3. Create `create_olav_agent()` using `create_deep_agent()`
4. Implement `cli_main()` entry point

### Phase 3: Commands Migration
Convert each Typer command to argparse subcommand:

| Typer Command | argparse Implementation |
|---------------|------------------------|
| `olav -m "query"` | `olav ask "query"` or `olav "query"` |
| `olav admin status` | `olav status` |
| `olav devices` | `olav devices` |
| `olav inspect` | `olav inspect` |
| `olav db-query` | `olav db query` |
| `olav task schedule` | `olav task schedule` |

### Phase 4: Interactive Mode
1. Use deepagents `create_prompt_session()`
2. Add OLAV-specific slash commands:
   - `/learn_cmd` → TextFSM learning
   - `/kb` → Knowledge base search
3. Preserve three-tier caching as middleware

### Phase 5: Cleanup
1. Delete old Typer-based code
2. Remove all fallbacks
3. Update `pyproject.toml` entry point
4. Update documentation

---

## New CLI Structure

```python
# src/olav/cli/main.py

def parse_args():
    parser = argparse.ArgumentParser(description="OLAV - Network Operations AI")
    subparsers = parser.add_subparsers(dest="command")
    
    # Interactive (default, no subcommand)
    parser.add_argument("query", nargs="?", help="Single query mode")
    
    # Network commands
    devices_parser = subparsers.add_parser("devices", help="List network devices")
    inspect_parser = subparsers.add_parser("inspect", help="Run network snapshot")
    
    # Database commands
    db_parser = subparsers.add_parser("db", help="Database operations")
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_subparsers.add_parser("status", help="Show database status")
    db_subparsers.add_parser("query", help="Execute SQL query")
    db_subparsers.add_parser("schema", help="Show database schema")
    
    # Task commands
    task_parser = subparsers.add_parser("task", help="Manage periodic tasks")
    task_subparsers = task_parser.add_subparsers(dest="task_command")
    task_subparsers.add_parser("schedule", help="Schedule a task")
    task_subparsers.add_parser("status", help="Show task status")
    
    # Admin commands
    subparsers.add_parser("status", help="Show OLAV status")
    subparsers.add_parser("backup", help="Backup OLAV data")
    subparsers.add_parser("restore", help="Restore from backup")
    
    return parser.parse_args()
```

---

## Entry Point Update

```toml
# pyproject.toml
[project.scripts]
olav = "olav.cli.main:cli_main"
```

---

## Dependencies Update

```toml
# Add to dependencies
"deepagents-cli>=0.1.0",

# Remove (if present)
# "typer>=0.9.0",  # Keep for now, may have other uses
```

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Loss of Typer features | argparse is sufficient for OLAV's needs |
| Breaking existing workflows | Provide migration guide for command changes |
| Three-tier caching loss | Implement as middleware layer |
| Interactive mode differences | Add OLAV-specific slash commands |

---

## Rollback Plan

If migration fails:
1. Revert to `refactor/v2.0-deepagents` branch
2. Tag current state as `v0.9.9-rc1-failed`
3. Analyze failure points
4. Create fix branch

---

## Success Criteria

- [ ] All 15+ commands work via argparse
- [ ] Interactive mode functions correctly
- [ ] Three-tier caching preserved
- [ ] All E2E tests pass
- [ ] No Typer dependencies in CLI layer
- [ ] Clean entry point: `olav.cli.main:cli_main`
- [ ] No fallback code remaining

---

## Timeline

- **Day 1**: Phase 1-2 (Tests + Core migration)
- **Day 2**: Phase 3 (Commands migration)
- **Day 3**: Phase 4 (Interactive mode)
- **Day 4**: Phase 5 (Cleanup + Documentation)

---

## Next Steps

1. ✅ Create branch `feature/v0.9.9-deepagents-cli`
2. ⬜ Write TDD tests for CLI commands
3. ⬜ Implement new `main.py` with argparse
4. ⬜ Migrate commands one by one
5. ⬜ Test and verify
6. ⬜ Delete old code
7. ⬜ Update documentation
