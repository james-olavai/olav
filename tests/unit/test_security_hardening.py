"""TDD — §20 SECURITY_MODEL 三项加固措施实施。

6.1  DuckDB sandbox monkey-patch    — sandbox 内强制 read_only=True
6.2  网络命名空间隔离                — OLAV_SANDBOX_NETNS=1 时用 unshare --net
6.3  service_call 写方法审批        — DELETE/POST/PUT/PATCH 返回 requires_approval
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── 6.1  DuckDB monkey-patch ─────────────────────────────────────────────────


class TestDuckDBMonkeyPatch:
    """sandbox wrapper 注入 DuckDB 只读强制补丁。"""

    def _get_wrapper(self, code: str = "_result = 1") -> str:
        """Return the wrapper script string that would be written to disk."""
        from olav.platform.sandbox import _build_wrapper
        return _build_wrapper(code)

    def test_wrapper_contains_duckdb_prologue(self):
        """Wrapper script begins with DuckDB monkey-patch prologue."""
        wrapper = self._get_wrapper()
        assert "duckdb" in wrapper
        assert "read_only=True" in wrapper

    def test_wrapper_prologue_before_user_code(self):
        """DuckDB patch appears before _result = None and user code."""
        wrapper = self._get_wrapper("x = duckdb.connect('test.db')")
        patch_pos = wrapper.index("read_only=True")
        result_pos = wrapper.index("_result = None")
        assert patch_pos < result_pos

    def test_duckdb_connect_forced_readonly_in_subprocess(self, tmp_path, monkeypatch):
        """Subprocess actually gets a read_only connection even without read_only=True."""
        monkeypatch.chdir(tmp_path)
        db_path = tmp_path / "test.db"
        # Create a real duckdb file so connect works
        import duckdb
        con = duckdb.connect(str(db_path))
        con.execute("CREATE TABLE t (x INT)")
        con.execute("INSERT INTO t VALUES (1)")
        con.close()

        from olav.platform.sandbox import execute_in_sandbox
        result = execute_in_sandbox(
            f"import duckdb\n"
            f"con = duckdb.connect('{db_path}')\n"   # no read_only arg
            f"rows = con.execute('SELECT x FROM t').fetchall()\n"
            f"_result = rows[0][0]",
            timeout=15,
        )
        # Read should still work
        assert result["status"] == "success"
        assert result["result"] == 1

    def test_duckdb_write_blocked_in_subprocess(self, tmp_path, monkeypatch):
        """Sandbox cannot write to DuckDB even without explicit read_only=True."""
        monkeypatch.chdir(tmp_path)
        db_path = tmp_path / "write_test.db"
        import duckdb
        duckdb.connect(str(db_path)).close()  # create empty db

        from olav.platform.sandbox import execute_in_sandbox
        result = execute_in_sandbox(
            f"import duckdb\n"
            f"con = duckdb.connect('{db_path}')\n"  # no read_only — should be patched
            f"con.execute('CREATE TABLE evil (x INT)')\n"
            f"_result = 'wrote'",
            timeout=15,
        )
        # Write must fail — either error status or requires_approval
        assert result["status"] in ("error", "requires_approval")

    def test_duckdb_explicit_readonly_still_works(self, tmp_path, monkeypatch):
        """Code that already uses read_only=True continues to work normally."""
        monkeypatch.chdir(tmp_path)
        db_path = tmp_path / "ro_test.db"
        import duckdb
        con = duckdb.connect(str(db_path))
        con.execute("CREATE TABLE s (v INT)")
        con.execute("INSERT INTO s VALUES (42)")
        con.close()

        from olav.platform.sandbox import execute_in_sandbox
        result = execute_in_sandbox(
            f"import duckdb\n"
            f"con = duckdb.connect('{db_path}', read_only=True)\n"
            f"_result = con.execute('SELECT v FROM s').fetchone()[0]",
            timeout=15,
        )
        assert result["status"] == "success"
        assert result["result"] == 42


# ── 6.2  Network namespace isolation ─────────────────────────────────────────


class TestNetworkNamespaceIsolation:
    """sandbox subprocess uses unshare --net via network_isolation param or env var."""

    # ── _build_sandbox_cmd: parameter-based API ───────────────────────────────

    def test_no_unshare_by_default(self, monkeypatch):
        """Default (network_isolation=False) does NOT include unshare."""
        from olav.platform.sandbox import _build_sandbox_cmd
        cmd = _build_sandbox_cmd("/usr/bin/python3", "/tmp/script.py")
        assert "unshare" not in " ".join(cmd)
        assert cmd == ["/usr/bin/python3", "/tmp/script.py"]

    def test_unshare_prepended_when_param_true(self, monkeypatch):
        """network_isolation=True prepends unshare --net to command."""
        with patch("shutil.which", return_value="/usr/bin/unshare"):
            from olav.platform.sandbox import _build_sandbox_cmd
            cmd = _build_sandbox_cmd("/usr/bin/python3", "/tmp/script.py", network_isolation=True)
        assert cmd[0].endswith("unshare")
        assert "--net" in cmd
        assert "/usr/bin/python3" in cmd
        assert "/tmp/script.py" in cmd

    def test_param_false_overrides_env_var(self, monkeypatch):
        """network_isolation=False suppresses isolation even if OLAV_SANDBOX_NETNS=1."""
        monkeypatch.setenv("OLAV_SANDBOX_NETNS", "1")
        with patch("shutil.which", return_value="/usr/bin/unshare"):
            from olav.platform.sandbox import _build_sandbox_cmd
            cmd = _build_sandbox_cmd("/usr/bin/python3", "/tmp/script.py", network_isolation=False)
        assert "unshare" not in " ".join(cmd)
        assert cmd == ["/usr/bin/python3", "/tmp/script.py"]

    def test_falls_back_gracefully_when_unshare_missing(self, monkeypatch):
        """If unshare is not on PATH, fall back to direct execution (no crash)."""
        with patch("shutil.which", return_value=None):
            from olav.platform.sandbox import _build_sandbox_cmd
            cmd = _build_sandbox_cmd("/usr/bin/python3", "/tmp/script.py", network_isolation=True)
        assert "unshare" not in " ".join(cmd)
        assert cmd == ["/usr/bin/python3", "/tmp/script.py"]

    # ── execute_in_sandbox: env var fallback ──────────────────────────────────

    def test_env_var_enables_isolation_when_param_is_none(self, tmp_path, monkeypatch):
        """OLAV_SANDBOX_NETNS=1 applies isolation when network_isolation param is not given."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OLAV_SANDBOX_NETNS", "1")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(returncode=0, stdout="__OLAV_RESULT__:1", stderr="")

        with patch("shutil.which", return_value="/usr/bin/unshare"):
            with patch("subprocess.run", side_effect=fake_run):
                from importlib import reload
                import olav.platform.sandbox as _sb
                reload(_sb)
                _sb.execute_in_sandbox("_result = 1", timeout=5)

        assert captured.get("cmd") is not None
        assert any("unshare" in str(c) for c in captured["cmd"])

    def test_execute_in_sandbox_network_isolation_param(self, tmp_path, monkeypatch):
        """execute_in_sandbox passes network_isolation to _build_sandbox_cmd."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OLAV_SANDBOX_NETNS", raising=False)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(returncode=0, stdout="__OLAV_RESULT__:99", stderr="")

        with patch("shutil.which", return_value="/usr/bin/unshare"):
            with patch("subprocess.run", side_effect=fake_run):
                from olav.platform.sandbox import execute_in_sandbox
                execute_in_sandbox("_result = 99", timeout=5, network_isolation=True)

        assert captured.get("cmd") is not None
        assert any("unshare" in str(c) for c in captured["cmd"])


# ── 6.3  service_call write approval ─────────────────────────────────────────


class TestServiceCallWriteApproval:
    """service_call blocks write methods before making any HTTP request."""

    def _make_svc_registry(self, monkeypatch):
        """Patch ServiceRegistry to return a minimal ServiceConfig."""
        from olav.platform.services.registry import ServiceConfig, AuthConfig
        mock_svc = ServiceConfig(
            name="testsvc",
            endpoint="http://localhost:9999",
            readonly_only=False,
            auth=AuthConfig(type="none"),
        )
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_svc
        monkeypatch.setattr(
            "olav.platform.services.client.ServiceRegistry.get_instance",
            lambda: mock_registry,
        )

    def test_delete_returns_requires_approval(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        from olav.platform.services.client import service_call
        result = service_call("testsvc", "DELETE", "/api/v1/labs/prod")
        assert isinstance(result, dict)
        assert result["status"] == "requires_approval"
        assert result["method"] == "DELETE"

    def test_post_returns_requires_approval(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        from olav.platform.services.client import service_call
        result = service_call("testsvc", "POST", "/api/v1/labs", body={"name": "x"})
        assert result["status"] == "requires_approval"
        assert result["method"] == "POST"

    def test_put_returns_requires_approval(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        from olav.platform.services.client import service_call
        result = service_call("testsvc", "PUT", "/api/v1/resource/1")
        assert result["status"] == "requires_approval"

    def test_patch_returns_requires_approval(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        from olav.platform.services.client import service_call
        result = service_call("testsvc", "PATCH", "/api/v1/resource/1")
        assert result["status"] == "requires_approval"

    def test_requires_approval_contains_path_and_reason(self, monkeypatch):
        self._make_svc_registry(monkeypatch)
        from olav.platform.services.client import service_call
        result = service_call("testsvc", "DELETE", "/api/v1/labs/prod")
        assert "path" in result
        assert result["path"] == "/api/v1/labs/prod"
        assert "reason" in result
        assert "suggested_action" in result

    def test_get_does_not_require_approval(self, monkeypatch):
        """GET requests bypass approval and attempt actual HTTP (will fail on mock)."""
        self._make_svc_registry(monkeypatch)
        with patch("httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"items": []}
            mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp

            from olav.platform.services.client import service_call
            result = service_call("testsvc", "GET", "/api/v1/labs")

        # Should NOT return requires_approval — reaches HTTP layer
        assert not (isinstance(result, dict) and result.get("status") == "requires_approval")

    def test_head_does_not_require_approval(self, monkeypatch):
        """HEAD is a safe method — no approval needed."""
        self._make_svc_registry(monkeypatch)
        with patch("httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.side_effect = Exception("no body")
            mock_resp.text = ""
            mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp

            from olav.platform.services.client import service_call
            result = service_call("testsvc", "HEAD", "/api/v1/labs")

        assert not (isinstance(result, dict) and result.get("status") == "requires_approval")

    def test_write_methods_never_reach_httpx(self, monkeypatch):
        """Write methods return requires_approval WITHOUT making any HTTP request."""
        self._make_svc_registry(monkeypatch)
        with patch("httpx.Client") as mock_client_cls:
            from olav.platform.services.client import service_call
            service_call("testsvc", "DELETE", "/api/v1/labs/prod")
            service_call("testsvc", "POST", "/api/v1/labs")

        # httpx.Client should never be instantiated for write methods
        mock_client_cls.assert_not_called()
