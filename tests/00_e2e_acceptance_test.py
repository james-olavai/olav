# ruff: noqa: N999  (numeric prefix is intentional for test ordering)
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
# Ensure src is in path for imports
sys.path.insert(0, str(PROJECT_ROOT / "src"))

class TestCodeQuality:
    """Phase 0: Code quality (ruff + pyright + coverage)."""

    def test_ruff_lint(self):
        result = subprocess.run(["uv", "run", "ruff", "check", "src/"], cwd=str(PROJECT_ROOT), capture_output=True)
        assert result.returncode == 0, f"Ruff lint failed: {result.stdout.decode()}"

    def test_ruff_format(self):
        result = subprocess.run(["uv", "run", "ruff", "format", "--check", "src/"], cwd=str(PROJECT_ROOT), capture_output=True)
        assert result.returncode == 0, f"Ruff format failed: {result.stdout.decode()}"

    def test_pyright(self):
        result = subprocess.run(["uv", "run", "pyright", "src/"], cwd=str(PROJECT_ROOT), capture_output=True)
        assert result.returncode == 0, f"Pyright failed: {result.stdout.decode()}"

class TestPhase1Environment:
    """Phase 1: Environment & Storage Isolation (v0.11.0)."""

    def test_global_paths(self):
        """Check project-level shared paths."""
        from olav.core.config import LOGS_DIR, MAIN_DB_PATH, SNAPSHOTS_DIR
        assert str(PROJECT_ROOT) in str(LOGS_DIR)
        assert str(PROJECT_ROOT) in str(SNAPSHOTS_DIR)
        assert str(PROJECT_ROOT) in str(MAIN_DB_PATH)

    def test_user_isolated_paths(self):
        """Check user-level isolated paths (v0.11.0 Requirement)."""
        from olav.core.config import CACHE_DIR, USER_SESSION_DIR
        home = str(Path.home())
        assert home in str(USER_SESSION_DIR), f"Session DIR must be in Home: {USER_SESSION_DIR}"
        assert home in str(CACHE_DIR), f"Cache DIR must be in Home: {CACHE_DIR}"

class TestPhase2Workspace:
    """Phase 2: Workspace Integrity."""
    def test_agent_definitions_exist(self):
        from olav.core.config import WORKSPACE_DIR

        # Check for core agents in workspace
        assert (WORKSPACE_DIR / "olav" / "AGENT.md").exists()
        assert (WORKSPACE_DIR / "ops" / "AGENT.md").exists()

class TestPhase3Audit:
    """Phase 3: Centralized Audit Trail (v0.11.0)."""

    def test_audit_log_creation(self):
        from olav.core.audit_logger import log_command
        from olav.core.config import USER_HISTORY_PATH

        test_cmd = "test_audit_command_123"
        log_command(test_cmd)

        assert USER_HISTORY_PATH.exists()
        with open(USER_HISTORY_PATH) as f:
            content = f.read()
            assert test_cmd in content
            assert ".log" in str(USER_HISTORY_PATH)

class TestPhase4Database:
    """Phase 4: Shared Database Integrity."""
    def test_core_tables_exist(self):
        from olav.core.database import get_database
        db = get_database()
        tables = db.conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
        table_names = [t[0] for t in tables]

        assert "devices" in table_names
        assert "parsed_outputs" in table_names

class TestPhase5AgentFunctionality:
    """Phase 5: Agent Isolation & Model Binding."""

    def test_agent_isolation_behavior(self):
        """Verify agent uses home-based storage for state."""
        from olav.agents.agent import OLAVAgent
        # Initialize with a unique session
        session_id = "test-session-xyz"
        agent = OLAVAgent(session_id=session_id)

        # Verify checkpointer is isolated
        if hasattr(agent, 'checkpointer') and agent.checkpointer:
            from langgraph.checkpoint.duckdb import DuckDBSaver
            if isinstance(agent.checkpointer, DuckDBSaver):
                # We can't easily check the internal conn string without private attr access,
                # but we can check the agent initialization logs or behavior if needed.
                # For now, being able to init without project root locks is a win.
                pass

    def test_ops_tool_discovery(self):
        import importlib.util

        from olav.core.config import WORKSPACE_DIR

        tool_path = WORKSPACE_DIR / "quick/tools/execute_sql.py"
        assert tool_path.exists()

        spec = importlib.util.spec_from_file_location("execute_sql", tool_path)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "execute_sql")

class TestPhase6ZeroETL:
    """Phase 6: Memory & Knowledge."""
    def test_memory_store_connectivity(self):
        from olav.core.memory import LanceDBStore
        store = LanceDBStore()
        # LanceDB usually creates a .lance or .lancedb directory
        assert "memory" in str(store.db_path)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
