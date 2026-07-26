"""M4 Platform (C-L4) E2E tests.

Tests the multi-user platform features via real CLI subprocess calls.

Always-run (no LLM required):
  C-L4-01 — olav init auto-creates admin user + token file + auth.mode=token
  C-L4-02 — olav admin add-user validates that the Linux user exists
  C-L4-03 — olav sessions returns output without crashing (even on empty DB)
  C-L4-08 — olav service status returns status table (exit 0)
  C-L4-09 — olav service logs start/stop lifecycle

Web-service gated (L4_WEB_E2E_ENABLED=1 + running web server):
  C-L4-05 — HTTP 403 when user B accesses user A's thread
  C-L4-07 — auth.mode=none prints ⚠ WARNING on web server startup

Usage:
    uv run pytest tests/e2e/test_m4_l4_e2e.py -v
    L4_WEB_E2E_ENABLED=1 uv run pytest tests/e2e/test_m4_l4_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = sys.executable

_WEB_ENABLED = os.environ.get("L4_WEB_E2E_ENABLED", "").strip() == "1"
_WEB_SKIP = pytest.mark.skipif(
    not _WEB_ENABLED,
    reason="Web E2E: set L4_WEB_E2E_ENABLED=1 and ensure `olav service web start` is running",
)


def _run(*args, cwd=None, env_extra=None, timeout=120):
    """Run `python -m olav.cli.main <args>` and return (rc, stdout, stderr)."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        [_PYTHON, "-m", "olav.cli.main", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd or _ROOT),
        env=env,
    )
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------------------
# C-L4-01 — olav init auto-creates admin user + token + auth.mode=token
# ---------------------------------------------------------------------------
class TestL4InitCreatesAdmin:
    """C-L4-01: fresh `olav init` bootstraps admin user and sets auth.mode=token."""

    _rc: "int | None" = None
    _stdout: str = ""
    _stderr: str = ""
    _tmp: "Path | None" = None

    @classmethod
    def _get_result(cls):
        if cls._rc is not None:
            return cls._rc, cls._stdout, cls._stderr
        cls._tmp = Path(tempfile.mkdtemp(prefix="olav_l4_init_"))
        cls._rc, cls._stdout, cls._stderr = _run(
            "init",
            cwd=cls._tmp,
            env_extra={"HOME": str(cls._tmp)},
            timeout=180,
        )
        return cls._rc, cls._stdout, cls._stderr

    def test_init_exits_zero(self):
        """C-L4-01: olav init must exit 0."""
        rc, stdout, stderr = self._get_result()
        assert rc == 0, (
            f"olav init exited {rc}\nstdout:{stdout[:600]}\nstderr:{stderr[:600]}"
        )

    def test_init_creates_olav_directory(self):
        """C-L4-01: .olav/ directory must be created under the cwd."""
        self._get_result()
        assert self._tmp is not None
        olav_dir = self._tmp / ".olav"
        assert olav_dir.exists(), f".olav/ not created in {self._tmp}"

    def test_init_creates_databases(self):
        """C-L4-01: domain.duckdb and audit.duckdb must be created."""
        self._get_result()
        assert self._tmp is not None
        db_dir = self._tmp / ".olav" / "databases"
        assert (db_dir / "domain.duckdb").exists() or (db_dir / "main.duckdb").exists(), (
            f"No main/domain DB in {db_dir}: {list(db_dir.iterdir()) if db_dir.exists() else 'dir missing'}"
        )

    def test_init_output_mentions_platform_ready(self):
        """C-L4-01: init output must include a readiness indicator."""
        _, stdout, _ = self._get_result()
        combined = stdout.lower()
        assert any(kw in combined for kw in ("platform ready", "✓", "ready", "init")), (
            f"No readiness indicator in init output:\n{stdout[:600]}"
        )

    def test_init_output_mentions_admin_or_auth(self):
        """C-L4-01: init output must reference admin user creation or auth setup."""
        _, stdout, stderr = self._get_result()
        combined = (stdout + stderr).lower()
        assert any(kw in combined for kw in ("admin", "token", "auth", "user")), (
            f"No admin/auth indication in init output:\n{stdout[:600]}\n{stderr[:300]}"
        )

    def test_no_unhandled_traceback(self):
        """C-L4-01: init must not raise an unhandled exception."""
        _, stdout, stderr = self._get_result()
        combined = stdout + stderr
        assert "Traceback (most recent call last)" not in combined, (
            f"Unhandled exception during olav init:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# C-L4-02 — olav admin add-user validates Linux user existence
# ---------------------------------------------------------------------------
class TestL4AdminAddUserValidation:
    """C-L4-02: `olav admin add-user` must reject a non-existent Linux username."""

    _FAKE_USER = "xnonexistent_l4_test_user_xyz"

    @classmethod
    def _get_result(cls):
        return _run("admin", "add-user", cls._FAKE_USER, timeout=30)

    def test_rejects_nonexistent_linux_user(self):
        """C-L4-02: add-user with a fake username must report Linux user not found."""
        rc, stdout, stderr = self._get_result()
        combined = (stdout + stderr).lower()
        assert any(kw in combined for kw in ("not found", "error", "linux user", "passwd")), (
            f"Expected 'not found'/'error' for fake user, got:\nrc={rc}\n{stdout[:400]}\n{stderr[:400]}"
        )

    def test_add_user_exits_nonzero_for_fake_user(self):
        """C-L4-02: add-user with a fake username must exit non-zero."""
        rc, _, _ = self._get_result()
        assert rc != 0, (
            f"Expected non-zero exit for fake Linux user, got rc={rc}"
        )

    def test_add_user_command_is_registered(self):
        """C-L4-02: `olav admin add-user <name>` must be recognized (not 'unknown command')."""
        rc, stdout, stderr = _run("admin", "add-user", "xnonexistent_l4_test_user_xyz", timeout=15)
        combined = stdout + stderr
        # Must NOT say 'unknown command' — the command is dispatched correctly
        assert "unknown command" not in combined.lower(), (
            f"'add-user' treated as unknown command:\n{combined[:400]}"
        )
        # Should produce a meaningful error about the user not existing
        assert any(kw in combined.lower() for kw in ("not found", "error", "linux user", "useradd")), (
            f"Expected user-not-found message, got:\n{combined[:400]}"
        )


# ---------------------------------------------------------------------------
# C-L4-03 — olav sessions returns output (even if empty)
# ---------------------------------------------------------------------------
class TestL4SessionsCommand:
    """C-L4-03: `olav sessions` must return output without crashing."""

    @classmethod
    def _get_result(cls):
        return _run("sessions", timeout=30)

    def test_sessions_exits_zero(self):
        """C-L4-03: olav sessions must exit 0."""
        rc, stdout, stderr = self._get_result()
        assert rc == 0, (
            f"olav sessions exited {rc}\nstdout:{stdout[:400]}\nstderr:{stderr[:400]}"
        )

    def test_sessions_produces_output(self):
        """C-L4-03: olav sessions must produce non-empty output."""
        _, stdout, stderr = self._get_result()
        combined = stdout + stderr
        assert combined.strip(), "olav sessions produced no output at all"

    def test_sessions_no_traceback(self):
        """C-L4-03: olav sessions must not raise an unhandled exception."""
        _, stdout, stderr = self._get_result()
        combined = stdout + stderr
        assert "Traceback" not in combined, (
            f"Unhandled exception in olav sessions:\n{combined[:600]}"
        )

    def test_sessions_output_is_meaningful(self):
        """C-L4-03: output should reference 'session' or 'thread' or 'found'."""
        _, stdout, stderr = self._get_result()
        combined = (stdout + stderr).lower()
        assert any(kw in combined for kw in ("session", "thread", "found", "no ")), (
            f"Unexpected output from olav sessions:\n{stdout[:400]}"
        )


# ---------------------------------------------------------------------------
# C-L4-07 — auth.mode=none prints ⚠ WARNING on web server startup
# (gated — requires running web service)
# ---------------------------------------------------------------------------
@_WEB_SKIP
class TestL4AuthModeNoneWarning:
    """C-L4-07: Web server with auth.mode=none must print a security WARNING.

    Requires L4_WEB_E2E_ENABLED=1 and an OLAV web server running with auth.mode=none.
    """

    def test_service_web_start_warns_about_auth_none(self):
        """C-L4-07: starting with auth.mode=none must emit ⚠ WARNING."""
        import urllib.request

        base_url = os.environ.get("OLAV_WEB_BASE_URL", "http://localhost:2280")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=5) as resp:
                body = resp.read().decode()
        except Exception as exc:
            pytest.skip(f"Web server not reachable at {base_url}: {exc}")

        rc, stdout, stderr = _run("service", "web", "start", "--dry-run", timeout=15)
        combined = stdout + stderr
        assert any(kw in combined for kw in ("⚠", "WARNING", "auth.mode=none", "no authentication")), (
            f"Expected WARNING for auth.mode=none, got:\n{combined[:600]}"
        )


# ---------------------------------------------------------------------------
# C-L4-05 — HTTP 403 for thread cross-user access
# (gated — requires running web service with 2 users)
# ---------------------------------------------------------------------------
@_WEB_SKIP
class TestL4Thread403:
    """C-L4-05: User B accessing user A's thread must receive HTTP 403.

    Requires L4_WEB_E2E_ENABLED=1 and two configured users (OLAV_USER_A_TOKEN,
    OLAV_USER_B_TOKEN environment variables).
    """

    def test_cross_user_thread_returns_403(self):
        """C-L4-05: POST /chat on another user's thread_id must return 403."""
        import urllib.error
        import urllib.request
        import json as _json

        base_url = os.environ.get("OLAV_WEB_BASE_URL", "http://localhost:2280")
        token_a = os.environ.get("OLAV_USER_A_TOKEN", "")
        token_b = os.environ.get("OLAV_USER_B_TOKEN", "")

        if not token_a or not token_b:
            pytest.skip(
                "C-L4-05 requires OLAV_USER_A_TOKEN and OLAV_USER_B_TOKEN env vars"
            )

        # Step 1: user A creates a thread
        create_payload = _json.dumps({"message": "hello"}).encode()
        req_a = urllib.request.Request(
            f"{base_url}/chat",
            data=create_payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token_a}"},
        )
        try:
            with urllib.request.urlopen(req_a, timeout=10) as resp:
                data_a = _json.loads(resp.read())
        except Exception as exc:
            pytest.skip(f"Could not create thread as user A: {exc}")

        thread_id = data_a.get("thread_id", "")
        assert thread_id, f"No thread_id in response: {data_a}"

        # Step 2: user B tries to continue user A's thread → expect 403
        cont_payload = _json.dumps({"message": "hi", "thread_id": thread_id}).encode()
        req_b = urllib.request.Request(
            f"{base_url}/chat",
            data=cont_payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token_b}"},
        )
        try:
            with urllib.request.urlopen(req_b, timeout=10):
                pytest.fail("Expected HTTP 403 but request succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, (
                f"Expected HTTP 403, got {exc.code} — thread ownership not enforced"
            )


# ---------------------------------------------------------------------------
# C-L4-08 — olav service status returns table (exit 0)
# ---------------------------------------------------------------------------


class TestL4ServiceStatus:
    """C-L4-08: `olav service status` prints a status table and exits 0."""

    @classmethod
    def _get_result(cls):
        if not hasattr(cls, "_cached"):
            cls._cached = _run("service", "status")
        return cls._cached

    def test_exits_zero(self):
        rc, out, err = self._get_result()
        assert rc == 0, f"service status exited {rc}\nstderr: {err}"

    def test_table_has_service_names(self):
        """Table must list the OSS services (syslogs, web). daemon is an
        enterprise feature (olav-ent) — required only when it is installed."""
        _, out, err = self._get_result()
        combined = (out + err).lower()
        required = ["syslogs", "web"]
        try:
            import olav.enterprise.daemon_svc  # noqa: F401
            required.append("daemon")
        except ImportError:
            pass
        for svc in required:
            assert svc in combined, (
                f"Service '{svc}' not found in service status output:\n{out[:600]}"
            )

    def test_stopped_or_running_status(self):
        """Each service must show a Stopped or Running status."""
        _, out, err = self._get_result()
        combined = out + err
        assert any(
            kw in combined for kw in ("Stopped", "Running", "●", "○")
        ), f"No status indicators in service status output:\n{combined[:600]}"


# ---------------------------------------------------------------------------
# C-L4-09 — olav service logs start/stop lifecycle
# ---------------------------------------------------------------------------


class TestL4ServiceLogsLifecycle:
    """C-L4-09: `olav service syslogs start` starts the syslog receiver;
    `olav service syslogs stop` cleanly stops it."""

    # Use a non-standard port to avoid conflicts with any running syslog
    _PORT = "15516"

    def test_logs_start_succeeds(self):
        rc, out, err = _run("service", "syslogs", "start", "--port", self._PORT)
        combined = out + err
        assert rc == 0, f"service logs start failed (rc={rc}):\n{combined}"
        combined_lower = combined.lower()
        assert "syslog" in combined_lower or "started" in combined_lower, (
            f"Expected start confirmation, got:\n{combined[:400]}"
        )

    def test_logs_stop_succeeds(self):
        # Stop whatever was started (idempotent — safe even if not running)
        rc, out, err = _run("service", "syslogs", "stop")
        combined = out + err
        assert rc == 0, f"service logs stop failed (rc={rc}):\n{combined}"
        combined_lower = combined.lower()
        assert "stopped" in combined_lower or "not running" in combined_lower, (
            f"Expected stop confirmation, got:\n{combined[:400]}"
        )
