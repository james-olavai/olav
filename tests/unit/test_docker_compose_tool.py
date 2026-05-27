"""Unit tests — docker_compose tool security model and interface contract.

Security model:
- ALLOWED_SUBCOMMANDS frozenset (allowlist-first)
- No shell=True
- Blocked subcommands return {"success": False, "blocked": True}
- All invocations return a dict (no bare exceptions)
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = (
    _ROOT / ".olav" / "workspace" / "devops" / "services" / "scripts" / "docker_compose.py"
)


def _load_module():
    """Load docker_compose.py via importlib."""
    if not _TOOL_PATH.exists():
        pytest.skip(f"docker_compose.py not found at {_TOOL_PATH}")
    spec = importlib.util.spec_from_file_location("docker_compose_tool", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# TestDockerComposeAllowlist — ALLOWED_SUBCOMMANDS frozenset contract
# ---------------------------------------------------------------------------


class TestDockerComposeAllowlist:
    """ALLOWED_SUBCOMMANDS must be defined and contain safe operations only."""

    def test_allowed_subcommands_defined(self):
        mod = _load_module()
        assert hasattr(mod, "ALLOWED_SUBCOMMANDS"), (
            "docker_compose module must define ALLOWED_SUBCOMMANDS"
        )
        assert isinstance(mod.ALLOWED_SUBCOMMANDS, frozenset), (
            "ALLOWED_SUBCOMMANDS must be a frozenset (immutable allowlist)"
        )

    def test_ps_in_allowlist(self):
        mod = _load_module()
        assert "ps" in mod.ALLOWED_SUBCOMMANDS, (
            "'ps' (list running containers) must be in ALLOWED_SUBCOMMANDS"
        )

    def test_logs_in_allowlist(self):
        mod = _load_module()
        assert "logs" in mod.ALLOWED_SUBCOMMANDS, (
            "'logs' (view service logs) must be in ALLOWED_SUBCOMMANDS"
        )

    def test_up_in_allowlist(self):
        mod = _load_module()
        assert "up" in mod.ALLOWED_SUBCOMMANDS, (
            "'up' (start services) must be in ALLOWED_SUBCOMMANDS"
        )

    def test_down_in_allowlist(self):
        mod = _load_module()
        assert "down" in mod.ALLOWED_SUBCOMMANDS, (
            "'down' (stop services) must be in ALLOWED_SUBCOMMANDS"
        )

    def test_exec_not_in_allowlist(self):
        mod = _load_module()
        assert "exec" not in mod.ALLOWED_SUBCOMMANDS, (
            "'exec' must NOT be in ALLOWED_SUBCOMMANDS — "
            "docker compose exec allows arbitrary command execution inside containers"
        )

    def test_run_not_in_allowlist(self):
        mod = _load_module()
        assert "run" not in mod.ALLOWED_SUBCOMMANDS, (
            "'run' must NOT be in ALLOWED_SUBCOMMANDS — "
            "docker compose run starts a container with an arbitrary command"
        )


# ---------------------------------------------------------------------------
# TestDockerComposeSecurityGates — blocked commands return structured error
# ---------------------------------------------------------------------------


class TestDockerComposeSecurityGates:
    """Blocked subcommands must return {'success': False, 'blocked': True}."""

    def _func(self):
        mod = _load_module()
        assert hasattr(mod, "docker_compose"), "docker_compose function not found on module"
        return mod.docker_compose

    def test_blocks_exec_subcommand(self):
        """docker compose exec is blocked — allows arbitrary container commands."""
        result = self._func()(subcommand="exec sh -c 'id'")
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}: {result!r}"
        assert result.get("success") is False, (
            f"Expected success=False for blocked 'exec' subcommand, got: {result!r}"
        )
        assert result.get("blocked") is True, (
            f"Expected blocked=True for disallowed subcommand, got: {result!r}"
        )

    def test_blocks_run_subcommand(self):
        """docker compose run is blocked — starts container with arbitrary command."""
        result = self._func()(subcommand="run alpine sh")
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}: {result!r}"
        assert result.get("success") is False, (
            f"Expected success=False for blocked 'run' subcommand, got: {result!r}"
        )
        assert result.get("blocked") is True, (
            f"Expected blocked=True for disallowed subcommand, got: {result!r}"
        )

    def test_blocks_shell_injection_semicolon(self):
        """Subcommand containing shell metacharacters must be blocked."""
        result = self._func()(subcommand="ps; rm -rf /")
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}: {result!r}"
        assert result.get("success") is False, (
            f"Expected success=False for injection attempt 'ps; rm -rf /', got: {result!r}"
        )
        assert result.get("blocked") is True, (
            f"Expected blocked=True for shell injection attempt, got: {result!r}"
        )

    def test_no_shell_true_in_source(self):
        """Security invariant: subprocess must never be called with shell=True."""
        if not _TOOL_PATH.exists():
            pytest.skip("docker_compose.py not yet implemented")
        source = _TOOL_PATH.read_text(encoding="utf-8")
        assert "shell=True" not in source, (
            "docker_compose tool contains 'shell=True' — this enables shell injection; "
            "use a list of arguments instead"
        )

    def test_returns_dict(self):
        """Valid allowed subcommand must return a dict (even if docker isn't running)."""
        func = self._func()
        # Docker may not be available in CI — we just assert no bare exception is raised
        # and the return type is a dict
        try:
            result = func(subcommand="ps", service_dir="")
        except SystemExit as e:
            pytest.fail(f"docker_compose raised SystemExit({e}) instead of returning a dict")
        assert isinstance(result, dict), (
            f"docker_compose must return a dict (got {type(result).__name__}: {result!r}); "
            "subprocess errors should be caught and returned as structured dicts"
        )


# ---------------------------------------------------------------------------
# TestDockerComposeToolSignature — LangChain @tool interface contract
# ---------------------------------------------------------------------------


class TestDockerComposeToolSignature:
    """docker_compose plain function must expose the required parameters."""

    def _mod(self):
        return _load_module()

    def test_tool_is_callable(self):
        mod = self._mod()
        assert hasattr(mod, "docker_compose"), (
            "docker_compose attribute missing from module"
        )
        assert callable(mod.docker_compose), "docker_compose must be callable"

    def test_tool_has_subcommand_param(self):
        mod = self._mod()
        sig = inspect.signature(mod.docker_compose)
        assert "subcommand" in sig.parameters, (
            f"docker_compose missing 'subcommand' parameter; "
            f"found: {list(sig.parameters)}"
        )

    def test_tool_has_service_dir_param(self):
        mod = self._mod()
        sig = inspect.signature(mod.docker_compose)
        assert "service_dir" in sig.parameters, (
            f"docker_compose missing 'service_dir' parameter; "
            f"found: {list(sig.parameters)}"
        )

    def test_tool_has_timeout_param(self):
        mod = self._mod()
        sig = inspect.signature(mod.docker_compose)
        assert "timeout" in sig.parameters, (
            f"docker_compose missing 'timeout' parameter; "
            f"found: {list(sig.parameters)}"
        )
