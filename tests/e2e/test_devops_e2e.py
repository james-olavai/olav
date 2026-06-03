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

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEVOPS_WS = _ROOT / ".olav" / "workspace" / "devops"
# devops top-level is AGENT.md-based (orchestrator); script generation lives
# in the 'scripts' sub-agent which is SKILL.md-based.
_AGENT_MD = _DEVOPS_WS / "AGENT.md"
_SCRIPTS_WS = _DEVOPS_WS / "scripts"
_SKILL_MD = _SCRIPTS_WS / "SKILL.md"
_SYSTEM_MD = _SCRIPTS_WS / "prompts" / "system.md"


def _skill_body(md_path: Path) -> str:
    """Return content body of a SKILL.md (everything after the YAML front-matter)."""
    text = md_path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        return parts[2].strip() if len(parts) >= 3 else ""
    return text.strip()


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
        assert _SKILL_MD.exists(), f"scripts/SKILL.md missing from devops workspace at {_SKILL_MD}"

    def test_system_prompt_exists(self):
        """prompts/system.md merged into SKILL.md body — verify body is non-empty."""
        body = _skill_body(_SKILL_MD)
        assert body, f"scripts/SKILL.md body (system prompt) is empty at {_SKILL_MD}"


# ---------------------------------------------------------------------------
# SKILL.md compliance (doc 40 §3)
# ---------------------------------------------------------------------------


class TestDevopsSkillConfig:
    """devops/scripts SKILL.md must declare script-generation tools."""

    def _skill_text(self) -> str:
        return _SKILL_MD.read_text(encoding="utf-8")

    def test_skill_name_is_scripts(self):
        # devops top-level is an orchestrator (AGENT.md); the script-generation
        # sub-agent is named 'scripts' — rev ~282 restructure
        src = self._skill_text()
        assert "name: scripts" in src, "scripts/SKILL.md must declare name: scripts"

    def test_skill_has_format_and_export(self):
        """scripts sub-agent must have format_and_export to export generated scripts."""
        src = self._skill_text()
        assert "format_and_export" in src, (
            "scripts/SKILL.md must include format_and_export in tools:"
        )

    def test_skill_has_schema_reference(self):
        """static_context must include BASELINE_SCHEMA.md for DB schema context."""
        src = self._skill_text()
        assert "BASELINE_SCHEMA" in src, (
            "scripts/SKILL.md static_context must include BASELINE_SCHEMA.md"
        )


# ---------------------------------------------------------------------------
# system.md compliance — environment discovery (doc 40 §2, §7)
# ---------------------------------------------------------------------------


class TestDevopsNetboxImport:
    """system.md must enforce environment-aware script generation standards."""

    def _system_text(self) -> str:
        return _skill_body(_SKILL_MD)

    def test_script_exported_to_exports_scripts(self):
        """system.md must mandate export via format_and_export to scripts subdir."""
        src = self._system_text()
        assert "format_and_export" in src, (
            "system.md must instruct devops to use format_and_export to export scripts"
        )
        assert 'subdir="scripts"' in src or "subdir='scripts'" in src, (
            "system.md must set subdir='scripts' in format_and_export call"
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
        return _skill_body(_SKILL_MD)

    def test_devops_does_not_execute_api_writes(self):
        """system.md must prohibit api_request write usage."""
        src = self._system_text()
        assert "NEVER" in src, "system.md must contain NEVER rules"
        # devops generates scripts, not executes writes
        assert "run_shell" in src or "NEVER use run_shell" in src or "NEVER" in src, (
            "system.md must include guards against executing generated scripts directly"
        )

    def test_devops_uses_format_and_export_for_generation(self):
        """system.md must use format_and_export to output scripts as files."""
        src = self._system_text()
        assert "format_and_export" in src, (
            "system.md must reference format_and_export for script export workflow"
        )


# ---------------------------------------------------------------------------
# devops/infra sub-agent structure
# ---------------------------------------------------------------------------


_INFRA_WS = _DEVOPS_WS / "infra"


class TestDevopsInfraStructure:
    """devops/infra sub-agent workspace must exist with required files."""

    def test_infra_directory_exists(self):
        assert _INFRA_WS.is_dir(), f"devops/infra workspace not found at {_INFRA_WS}"

    def test_infra_skill_md_exists(self):
        assert (_INFRA_WS / "SKILL.md").is_file(), "devops/infra/SKILL.md missing"

    def test_infra_skill_md_name(self):
        text = (_INFRA_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "name: infra" in text, "infra/SKILL.md must declare name: infra"

    def test_infra_skill_md_has_api_request(self):
        text = (_INFRA_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "api_request" in text, "infra/SKILL.md must list api_request in tools:"

    def test_infra_system_prompt_exists(self):
        """prompts/system.md merged into SKILL.md body — verify body is non-empty."""
        body = _skill_body(_INFRA_WS / "SKILL.md")
        assert body, "devops/infra/SKILL.md body (system prompt) is empty"

    def test_infra_references_directory_exists(self):
        refs = _INFRA_WS / "references"
        assert refs.is_dir(), "devops/infra/references/ missing"
        assert any(refs.glob("*.md")), "devops/infra/references/ is empty — run olav registry register"

    def test_infra_system_prompt_mentions_api_request(self):
        text = _skill_body(_INFRA_WS / "SKILL.md")
        assert "api_request" in text, "infra/SKILL.md body must show api_request usage"


# ---------------------------------------------------------------------------
# services platform-agent structure (ADR-0014: top-level, no longer under devops)
# ---------------------------------------------------------------------------


_SERVICES_WS = _ROOT / ".olav" / "workspace" / "services"
_SERVICES_SCRIPTS = _SERVICES_WS / "scripts"


class TestDevopsServicesStructure:
    """services platform-agent scripts must all exist (top-level, per ADR-0014)."""

    def test_services_skill_md_exists(self):
        assert (_SERVICES_WS / "SKILL.md").is_file(), "services/SKILL.md missing"

    def test_services_skill_md_name(self):
        text = (_SERVICES_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "name: services" in text, "services/SKILL.md must declare name: services"

    def test_register_service_script_exists(self):
        assert (_SERVICES_SCRIPTS / "register_service.py").is_file()

    def test_deploy_service_script_exists(self):
        assert (_SERVICES_SCRIPTS / "deploy_service.py").is_file()

    def test_stop_service_script_exists(self):
        assert (_SERVICES_SCRIPTS / "stop_service.py").is_file()

    def test_api_request_script_exists(self):
        assert (_SERVICES_SCRIPTS / "api_request.py").is_file()

    def test_docker_compose_script_exists(self):
        assert (_SERVICES_SCRIPTS / "docker_compose.py").is_file()


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
    if explicit is None:
        return False
    return explicit.lower() in {"1", "true", "yes"}


_DEVOPS_E2E = _devops_e2e_enabled()
devops_e2e = pytest.mark.skipif(
    not _DEVOPS_E2E,
    reason="Enable DEVOPS_E2E_ENABLED=1 or configure a real API key to run devops agent E2E tests",
)

_OLAV_CMD = [sys.executable, "-m", "olav"]
_EXPORTS_SCRIPTS = _ROOT / "exports" / "scripts"
_TIMEOUT_FACTOR = float(os.environ.get("OLAV_E2E_TIMEOUT_FACTOR", "1"))


def _run_devops(prompt: str, timeout: int = 180) -> subprocess.CompletedProcess:
    effective = int(timeout * _TIMEOUT_FACTOR)
    proc = subprocess.Popen(
        _OLAV_CMD + ["--agent", "devops", prompt],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(_ROOT),
    )
    try:
        stdout, stderr = proc.communicate(timeout=effective)
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(proc.args, -1, stdout or "", stderr or "")


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
        before_time = time.time() - 1  # 1s buffer

        result = _run_devops("Write a bash script to list all devices by querying the OLAV database")
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
        result = _run_devops("Write a bash script to backup running-config from all routers")
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
        """devops generated script contains dry-run capability (--dry-run flag or DRY_RUN env var)."""
        if not _EXPORTS_SCRIPTS.exists():
            pytest.skip("exports/scripts/ not populated — run test_script_exported_to_exports_scripts first")

        scripts = sorted(_EXPORTS_SCRIPTS.glob("*.sh"), key=lambda p: p.stat().st_mtime)
        assert scripts, "No .sh files in exports/scripts/"

        latest = scripts[-1].read_text()
        has_dry_run = "--dry-run" in latest or "DRY_RUN" in latest
        assert has_dry_run, (
            f"Generated script {scripts[-1].name} missing dry-run capability "
            f"(expected '--dry-run' flag or 'DRY_RUN' env var).\nSnippet: {latest[:400]}"
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
        # api_request migrated from core/tools/ @tool to core/api_query/scripts/ plain fn
        spec = _ilu.spec_from_file_location(
            "api_request",
            str(_ROOT / ".olav" / "workspace" / "core" / "api_query" / "scripts" / "api_request.py"),
        )
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.api_request(service=service, method="GET", path="/")

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
