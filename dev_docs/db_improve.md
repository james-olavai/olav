# OLAV Multi-User Session & Audit Improvement Plan (v0.11.0)

## 1. Vision
To support a BAU team of 10+ users operating on thousands of devices, we must transition from a "single-user local" model to a **Secure-Isolated & Central-Audited** architecture. This prevents DuckDB resource locking and enables regulatory session auditing.

## 2. Storage Strategy: Isolation vs. Auditing

| Content Type | Storage Location | Level | Purpose |
| :--- | :--- | :--- | :--- |
| **Checkpoints** | `~/.olav/sessions/checkpoints.duckdb` | **Isolated (Home)** | Prevents file locks and data leaks between users. |
| **Command History** | `.olav/logs/users/{user}.log` | **Centralized (Project)** | Unified audit trail for all operations, grouped by user. |
| **LLM Cache** | `~/.olav/cache/llm_cache.db` | **Isolated (Home)** | Avoids cross-user response contamination. |
| **Snapshot Data** | `./exports/snapshots/` | **Shared (Project)** | Single source of truth for network state. |

---

## 3. Implementation Roadmap (TDD)

### Phase 1: Config Path Standardization (User Audit)
**Goal**: Enforce centralized logging in `.olav/logs` with `.log` suffix.

- **Test (TDD)**: `tests/unit/test_config_audit_paths.py`
  - Verify `LOGS_DIR / "users" / f"{user}.log"` is the resolved history path.
  - Ensure the path is relative to the PROJECT root for shared auditing.
- **Action**: Update `src/olav/core/config.py` to redefine `USER_HISTORY_DIR`.

### Phase 2: Session Isolation Refactor
**Goal**: Move runtime state (LangGraph checkpoints) to the User's Home directory.

- **Test (TDD)**: `tests/unit/test_session_isolation.py`
  - Initialize `OLAVAgent`.
  - Assert `checkpointer` path points to `/home/{user}/.olav/...` and NOT the project root.
- **Action**: Update `src/olav/agents/agent.py` to use home-based paths for `DuckDBSaver`.

### Phase 3: Centralized Audit Logger
**Goal**: Implement a middleware or utility that streams every CLI command to the central log file.

- **Test (TDD)**: `tests/unit/test_audit_logging.py`
  - Execute a query via `OLAVAgent`.
  - Assert the command string is appended to `.olav/logs/users/{user}.log` with a timestamp.
- **Action**: Add an audit hook in `src/olav/cli/main.py` or the agent's middleware chain.

### Phase 4: CLI Session Recovery
**Goal**: Allow users to restore their specific isolated session.

- **Test (TDD)**: `tests/unit/test_cli_recovery.py`
  - Run `olav --session my-troubleshooting`.
  - Verify that it mounts the user's private DuckDB checkpoint file.
- **Action**: Update `src/olav/cli/main.py` to accept session IDs and pass them to the agent.

---

## 4. Engineering Standards
- **Suffix Standard**: All history files must end in `.log`.
- **Concurrency**: By moving checkpoints to `~`, we enable 100% concurrent operation without DuckDB "Resource Locked" errors (since each user has their owned DB file).
- **Cleanup**: Delete redundant `USER_SESSION_DIR` from the project's root `.olav` directory.

## 5. Definition of Done
1. [ ] No DuckDB locks occur when 2 users operate CLI simultaneously.
2. [ ] Admin can view `./.olav/logs/users/admin_user.log` to see a full history of commands.
3. [ ] Users can exit and resume their private sessions using a unique ID stored in their home directory.
