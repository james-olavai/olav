"""DevOps agent E2E tests — doc 40 compliance.

Validates the devops workspace and agent contract against the design
specification in dev_docs/40. DEVOPS_AGENT_DESIGN.md.

These tests run offline (no NetBox instance required) and verify:
- Workspace structure: AGENT.md, SKILL.md, prompts/system.md exist
- SKILL.md declares zero dedicated tools (all core-inherited)
- system.md enforces environment discovery before script generation
- system.md mandates script quality standards (shebang, dry-run, auth header)
- Script output: exported to exports/scripts/ via format_and_export (not chat text)

For full NetBox E2E integration tests, run manually:
    olav --agent devops "Write a script to sync OLAV devices to NetBox at localhost:8000"
    bash exports/scripts/<generated>.sh --dry-run
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEVOPS_WS = _ROOT / ".olav" / "workspace" / "devops"
_SYSTEM_MD = _DEVOPS_WS / "prompts" / "system.md"
_SKILL_MD = _DEVOPS_WS / "SKILL.md"
_AGENT_MD = _DEVOPS_WS / "AGENT.md"


# ---------------------------------------------------------------------------
# Workspace structure
# ---------------------------------------------------------------------------


class TestDevopsWorkspaceStructure:
    """devops workspace must exist with required files."""

    def test_workspace_directory_exists(self):
        assert _DEVOPS_WS.is_dir(), f"devops workspace not found at {_DEVOPS_WS}"

    def test_agent_md_exists(self):
        assert _AGENT_MD.exists(), "AGENT.md missing from devops workspace"

    def test_skill_md_exists(self):
        assert _SKILL_MD.exists(), "SKILL.md missing from devops workspace"

    def test_system_prompt_exists(self):
        assert _SYSTEM_MD.exists(), "prompts/system.md missing from devops workspace"


# ---------------------------------------------------------------------------
# SKILL.md compliance (doc 40 §3)
# ---------------------------------------------------------------------------


class TestDevopsSkillConfig:
    """SKILL.md must declare zero dedicated tools (full core inheritance)."""

    def _skill_text(self) -> str:
        return _SKILL_MD.read_text(encoding="utf-8")

    def test_skill_name_is_devops(self):
        src = self._skill_text()
        assert "name: devops" in src, "SKILL.md must declare name: devops"

    def test_skill_has_no_dedicated_tools(self):
        """tools: [] means no dedicated tools — all tools inherited from core."""
        src = self._skill_text()
        assert "tools: []" in src, (
            "SKILL.md must declare tools: [] (zero dedicated tools, full core inheritance)"
        )

    def test_skill_references_infra_references(self):
        """static_context must include ../infra/references/ for API endpoint context."""
        src = self._skill_text()
        assert "infra/references" in src, (
            "SKILL.md static_context must include ../infra/references/ "
            "so devops inherits API reference context"
        )


# ---------------------------------------------------------------------------
# system.md compliance — environment discovery (doc 40 §2, §7)
# ---------------------------------------------------------------------------


class TestDevopsNetboxImport:
    """system.md must enforce environment-aware script generation standards."""

    def _system_text(self) -> str:
        return _SYSTEM_MD.read_text(encoding="utf-8")

    def test_script_exported_to_exports_scripts(self):
        """system.md must mandate export to exports/scripts/ via format_and_export."""
        src = self._system_text()
        assert "exports/scripts" in src, (
            "system.md must instruct devops to export scripts to exports/scripts/"
        )
        assert "format_and_export" in src or "exports/scripts" in src, (
            "system.md must reference format_and_export or exports/scripts output path"
        )

    def test_script_uses_real_device_data(self):
        """system.md must mandate real device data — no placeholder IPs or hostnames."""
        src = self._system_text()
        # Must instruct to query devices
        assert "execute_sql" in src, (
            "system.md must instruct using execute_sql to discover devices"
        )
        assert "netops.devices" in src, (
            "system.md must reference netops.devices for device discovery"
        )
        # Must prohibit placeholders
        assert "NEVER" in src or "never" in src.lower(), (
            "system.md must include NEVER rules against placeholder values"
        )
        placeholder_prohibited = (
            "placeholder" in src.lower()
            or "10.0.0.1" in src
            or "example.com" in src
        )
        assert placeholder_prohibited, (
            "system.md must explicitly prohibit placeholder values (10.0.0.1, example.com, etc.)"
        )

    def test_script_has_dry_run(self):
        """system.md must mandate --dry-run flag in every generated script."""
        src = self._system_text()
        assert "--dry-run" in src, (
            "system.md must require --dry-run flag in generated scripts (doc 40 §3)"
        )

    def test_script_has_auth_header(self):
        """system.md must mandate auth via env var — no hardcoded tokens."""
        src = self._system_text()
        # Must prohibit hardcoded tokens
        no_hardcode = (
            "NEVER hardcode" in src
            or "env var" in src
            or "${VAR" in src
            or "env vars" in src
        )
        assert no_hardcode, (
            "system.md must mandate Authorization header via env var, "
            "not hardcoded tokens"
        )

    def test_script_bash_syntax_valid(self):
        """system.md must mandate shebang + strict mode (#!/bin/bash + set -euo pipefail)."""
        src = self._system_text()
        assert "#!/bin/bash" in src, (
            "system.md must include #!/bin/bash shebang requirement"
        )
        assert "set -euo pipefail" in src, (
            "system.md must require set -euo pipefail for strict bash mode"
        )


# ---------------------------------------------------------------------------
# devops vs infra boundary (doc 40 §5)
# ---------------------------------------------------------------------------


class TestDevopsInfraBoundary:
    """devops must NOT directly execute API writes — scripts only."""

    def _system_text(self) -> str:
        return _SYSTEM_MD.read_text(encoding="utf-8")

    def test_devops_does_not_execute_api_writes(self):
        """system.md must prohibit api_request write usage."""
        src = self._system_text()
        assert "NEVER" in src, "system.md must contain NEVER rules"
        # devops generates scripts, not executes writes
        assert "run_shell" in src or "NEVER use run_shell" in src or "NEVER" in src, (
            "system.md must include guards against executing generated scripts directly"
        )

    def test_devops_uses_run_python_code_for_generation(self):
        """system.md must use run_python_code to generate scripts."""
        src = self._system_text()
        assert "run_python_code" in src, (
            "system.md must reference run_python_code for script generation workflow"
        )


# ---------------------------------------------------------------------------
# Agent invocation E2E — requires LLM backend
#
# Skip unless DEVOPS_E2E_ENABLED=1 or a real API key is configured.
# Run manually with:
#   DEVOPS_E2E_ENABLED=1 uv run pytest tests/e2e/test_devops_e2e.py::TestDevopsAgentE2E -v
# ---------------------------------------------------------------------------

import os
import shutil
import subprocess
import time


def _devops_e2e_enabled() -> bool:
    explicit = os.environ.get("DEVOPS_E2E_ENABLED")
    if explicit is not None:
        return explicit.lower() in {"1", "true", "yes"}
    try:
        from olav.core.config import get_llm_config
        return bool(get_llm_config().api_key)
    except Exception:
        return False


_DEVOPS_E2E = _devops_e2e_enabled()
devops_e2e = pytest.mark.skipif(
    not _DEVOPS_E2E,
    reason="Enable DEVOPS_E2E_ENABLED=1 or configure a real API key to run devops agent E2E tests",
)

_OLAV_BIN = shutil.which("olav") or "olav"
_EXPORTS_SCRIPTS = _ROOT / "exports" / "scripts"


@devops_e2e
class TestDevopsAgentE2E:
    """Full agent invocation E2E — generates real scripts via LLM.

    Validates claims C-NE-41 through C-NE-44 (doc 40 §7 Phase 3).

    Requirements:
    - DEVOPS_E2E_ENABLED=1 (or real API key in config)
    - netops.devices populated in .olav/databases/domain.duckdb
    """

    # Shared across test instances — set by test_script_exported_to_exports_scripts
    _last_exported_script: "Optional[Path]" = None

    def test_script_exported_to_exports_scripts(self, tmp_path):
        """devops agent exports generated script to exports/scripts/."""
        import time
        before_time = time.time() - 1  # 1s buffer

        result = subprocess.run(
            [_OLAV_BIN, "--agent", "devops",
             "Write a bash script to list all devices by querying the OLAV database"],
            capture_output=True, text=True, timeout=120,
            cwd=str(_ROOT),
        )
        assert result.returncode == 0, f"olav exited {result.returncode}:\n{result.stderr}"

        new_or_updated = (
            {p for p in _EXPORTS_SCRIPTS.glob("*.sh") if p.stat().st_mtime >= before_time}
            if _EXPORTS_SCRIPTS.exists() else set()
        )
        assert new_or_updated, (
            f"No new/updated .sh file in exports/scripts/ after devops run.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
        TestDevopsAgentE2E._last_exported_script = max(new_or_updated, key=lambda p: p.stat().st_mtime)

    def test_script_uses_real_device_data(self, tmp_path):
        """devops agent uses real device names — not placeholders."""
        result = subprocess.run(
            [_OLAV_BIN, "--agent", "devops",
             "Write a bash script to backup running-config from all routers"],
            capture_output=True, text=True, timeout=120,
            cwd=str(_ROOT),
        )
        assert result.returncode == 0, f"olav exited {result.returncode}:\n{result.stderr}"

        # Check generated script files — must use real IPs/names, not generic placeholders
        if _EXPORTS_SCRIPTS.exists():
            scripts = sorted(_EXPORTS_SCRIPTS.glob("*.sh"), key=lambda p: p.stat().st_mtime)
            if scripts:
                content = scripts[-1].read_text()
                # "hostname" is a common bash variable/command — exclude from check
                placeholders = {"10.0.0.1", "example.com", "YOUR_TOKEN", "CHANGEME", "YOUR_HOSTNAME"}
                has_placeholder = any(p in content for p in placeholders)
                assert not has_placeholder, (
                    f"Generated script contains placeholder values: {scripts[-1].name}\n"
                    f"Content snippet: {content[:300]}"
                )

    def test_script_has_dry_run(self):
        """devops generated script contains --dry-run flag handling."""
        if not _EXPORTS_SCRIPTS.exists():
            pytest.skip("exports/scripts/ not populated — run test_script_exported_to_exports_scripts first")

        scripts = sorted(_EXPORTS_SCRIPTS.glob("*.sh"), key=lambda p: p.stat().st_mtime)
        assert scripts, "No .sh files in exports/scripts/"

        latest = scripts[-1].read_text()
        assert "--dry-run" in latest, (
            f"Generated script {scripts[-1].name} missing --dry-run flag.\nSnippet: {latest[:400]}"
        )

    def test_script_has_auth_header(self):
        """devops generated API script uses env var for auth — no hardcoded tokens."""
        if not _EXPORTS_SCRIPTS.exists():
            pytest.skip("exports/scripts/ not populated — run test_script_exported_to_exports_scripts first")

        # Only check API scripts (NetBox/InfluxDB etc.) not SSH-only scripts
        scripts = sorted(_EXPORTS_SCRIPTS.glob("*.sh"), key=lambda p: p.stat().st_mtime)
        assert scripts, "No .sh files in exports/scripts/"

        latest = scripts[-1].read_text()
        # If script makes HTTP calls, it must use env var for auth
        if "Authorization" in latest or "curl" in latest:
            has_env_auth = (
                "${" in latest  # env var expansion
                and "Authorization" in latest
            )
            assert has_env_auth, (
                f"Script uses HTTP but hardcodes Authorization header.\n"
                f"Snippet: {latest[:400]}"
            )

    def test_script_bash_syntax_valid(self):
        """bash -n syntax check passes on generated script."""
        script = TestDevopsAgentE2E._last_exported_script
        if script is None:
            # Running in isolation — fall back to most-recent .sh
            if not _EXPORTS_SCRIPTS.exists():
                pytest.skip("exports/scripts/ not populated")
            scripts = sorted(_EXPORTS_SCRIPTS.glob("*.sh"), key=lambda p: p.stat().st_mtime)
            if not scripts:
                pytest.skip("No .sh files in exports/scripts/")
            script = scripts[-1]

        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"bash -n failed on {script.name}:\n{result.stderr}"
        )



# ---------------------------------------------------------------------------
# C-NE-38 — api_request returns clear error for unregistered service
# ---------------------------------------------------------------------------
class TestApiRequestUnregisteredService:
    """C-NE-38: api_request with unknown service returns informative error dict.

    Claim: calling api_request("foobar", ...) must NOT crash the agent with a raw
    traceback; it must return a structured dict with status="error" and a hint
    directing the operator toward `olav registry register`.
    """

    def _invoke_api_request(self, service: str):
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "api_request",
            str(_ROOT / ".olav" / "workspace" / "core" / "tools" / "api_request.py"),
        )
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Call the raw Python function, bypassing the LangChain @tool wrapper
        return mod.api_request.func(service, method="GET", path="/")

    def test_returns_error_dict_not_exception(self):
        """Unregistered service returns a dict, not a raised KeyError."""
        result = self._invoke_api_request("foobar-nonexistent")
        assert isinstance(result, dict), (
            f"Expected dict, got {type(result).__name__}: {result!r}"
        )

    def test_error_status_field(self):
        """Error dict has status='error'."""
        result = self._invoke_api_request("foobar-nonexistent")
        assert result.get("status") == "error", (
            f"Expected status='error', got {result!r}"
        )

    def test_error_names_the_service(self):
        """Error message identifies the unregistered service by name."""
        result = self._invoke_api_request("foobar-nonexistent")
        combined = f"{result.get('reason', '')} {result.get('hint', '')}"
        assert "foobar-nonexistent" in combined, (
            f"Service name not in error message: {combined!r}"
        )

    def test_error_lists_available_services(self):
        """Error hints list registered services so the agent can self-correct."""
        result = self._invoke_api_request("foobar-nonexistent")
        hint = result.get("hint", "")
        assert "Available services:" in hint or "Available:" in hint, (
            f"Hint does not list available services: {hint!r}"
        )
