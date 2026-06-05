"""DevOps agent E2E tests.

Static tests (no LLM): workspace structure + automation library conventions.
LLM E2E tests (DEVOPS_E2E_ENABLED=1): natural-language NetBox workflow.

NetBox workflow (two-phase):
  Phase 1 — services deploys NetBox via natural language.
  Phase 2 — devops/infra writes a device-import script to .olav/automations/.

Run LLM tests manually:
    DEVOPS_E2E_ENABLED=1 uv run pytest tests/e2e/test_devops_e2e.py::TestNetboxWorkflowE2E -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEVOPS_WS = _ROOT / ".olav" / "workspace" / "devops"
_INFRA_WS = _DEVOPS_WS / "infra"
_SERVICES_WS = _ROOT / ".olav" / "workspace" / "services"
_SERVICES_SCRIPTS = _SERVICES_WS / "scripts"
_AUTOMATIONS = _ROOT / ".olav" / "automations"


def _skill_body(md_path: Path) -> str:
    """Return SKILL.md body (everything after the YAML front-matter)."""
    text = md_path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        return parts[2].strip() if len(parts) >= 3 else ""
    return text.strip()


# ---------------------------------------------------------------------------
# Workspace structure — devops orchestrator
# ---------------------------------------------------------------------------


class TestDevopsWorkspaceStructure:
    def test_workspace_directory_exists(self):
        assert _DEVOPS_WS.is_dir(), f"devops workspace not found at {_DEVOPS_WS}"

    def test_orchestrator_skill_md_exists(self):
        assert (_DEVOPS_WS / "SKILL.md").is_file(), "devops/SKILL.md missing"

    def test_orchestrator_routes_to_infra(self):
        text = (_DEVOPS_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "infra" in text, "devops orchestrator must route to infra sub-agent"

    def test_scripts_subagent_removed(self):
        """devops/scripts sub-agent absorbed into infra — directory must not exist."""
        assert not (_DEVOPS_WS / "scripts").is_dir(), (
            "devops/scripts/ still exists — should have been removed; "
            "script-generation capability is now in devops/infra"
        )


# ---------------------------------------------------------------------------
# devops/infra sub-agent structure
# ---------------------------------------------------------------------------


class TestDevopsInfraStructure:
    def test_infra_directory_exists(self):
        assert _INFRA_WS.is_dir(), f"devops/infra workspace not found at {_INFRA_WS}"

    def test_infra_skill_md_exists(self):
        assert (_INFRA_WS / "SKILL.md").is_file(), "devops/infra/SKILL.md missing"

    def test_infra_skill_md_name(self):
        text = (_INFRA_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "name: infra" in text

    def test_infra_has_execute_skill_script(self):
        """infra must have execute_skill_script to call automation library scripts."""
        text = (_INFRA_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "execute_skill_script" in text

    def test_infra_has_api_request(self):
        text = (_INFRA_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "api_request" in text

    def test_infra_references_exists(self):
        refs = _INFRA_WS / "references"
        assert refs.is_dir()
        assert any(refs.glob("*.md"))

    def test_infra_skill_body_nonempty(self):
        assert _skill_body(_INFRA_WS / "SKILL.md"), "infra SKILL.md body is empty"


# ---------------------------------------------------------------------------
# Automation library scripts
# ---------------------------------------------------------------------------


_INFRA_SCRIPTS = _INFRA_WS / "scripts"

_REQUIRED_SCRIPTS = [
    "write_automation.py",
    "list_automations.py",
    "run_automation.py",
    "validate_script.py",
]


class TestAutomationLibraryScripts:
    """infra/scripts/ must contain the four automation library scripts."""

    def test_scripts_directory_exists(self):
        assert _INFRA_SCRIPTS.is_dir(), f"devops/infra/scripts/ missing at {_INFRA_SCRIPTS}"

    @pytest.mark.parametrize("script_name", _REQUIRED_SCRIPTS)
    def test_script_file_exists(self, script_name):
        assert (_INFRA_SCRIPTS / script_name).is_file(), (
            f"devops/infra/scripts/{script_name} missing"
        )

    def test_skill_md_registers_all_scripts(self):
        """infra SKILL.md scripts: section must declare all four scripts."""
        text = (_INFRA_WS / "SKILL.md").read_text(encoding="utf-8")
        for name in ("write_automation", "list_automations", "run_automation", "validate_script"):
            assert name in text, f"infra SKILL.md missing script registration for '{name}'"

    def test_run_automation_has_boundary_check(self):
        """run_automation.py must only allow scripts inside .olav/automations/."""
        src = (_INFRA_SCRIPTS / "run_automation.py").read_text(encoding="utf-8")
        assert "automations" in src, "run_automation.py must enforce .olav/automations/ boundary"
        assert "ValueError" in src or "relative_to" in src, (
            "run_automation.py must reject paths outside .olav/automations/"
        )

    def test_run_automation_has_confirmed_gate(self):
        """run_automation.py must require confirmed=True to execute."""
        src = (_INFRA_SCRIPTS / "run_automation.py").read_text(encoding="utf-8")
        assert "confirmed" in src
        assert "preview" in src, "run_automation.py must return preview when confirmed=False"

    def test_write_automation_valid_categories(self):
        """write_automation.py must define the canonical category set."""
        src = (_INFRA_SCRIPTS / "write_automation.py").read_text(encoding="utf-8")
        for cat in ("backup", "sync", "bulk", "monitoring", "netbox"):
            assert cat in src, f"write_automation.py missing category '{cat}'"

    def test_validate_script_runs_py_compile(self):
        src = (_INFRA_SCRIPTS / "validate_script.py").read_text(encoding="utf-8")
        assert "py_compile" in src

    def test_validate_script_runs_bash_n(self):
        src = (_INFRA_SCRIPTS / "validate_script.py").read_text(encoding="utf-8")
        assert "bash" in src and "-n" in src


# ---------------------------------------------------------------------------
# Automation library conventions in SKILL.md
# ---------------------------------------------------------------------------


class TestAutomationLibraryPrompt:
    """infra SKILL.md body must describe the automation workflow correctly."""

    def _body(self) -> str:
        return _skill_body(_INFRA_WS / "SKILL.md")

    def test_automation_directory_is_olav_automations(self):
        assert ".olav/automations" in self._body()

    def test_list_automations_before_generate(self):
        """Prompt must instruct checking library before generating a new script."""
        body = self._body()
        assert "list_automations" in body

    def test_validate_before_run(self):
        """Prompt must require validate_script before run_automation."""
        body = self._body()
        assert "validate_script" in body
        assert "run_automation" in body

    def test_no_placeholder_values(self):
        body = self._body()
        assert "NEVER use placeholder" in body or "NEVER" in body

    def test_real_device_discovery_via_sql(self):
        body = self._body()
        assert "execute_sql" in body
        assert "netops.devices" in body

    def test_dry_run_required(self):
        body = self._body()
        assert "--dry-run" in body

    def test_six_step_write_workflow(self):
        """Prompt must describe 6-step write workflow for interactive ≤5 item changes."""
        body = self._body()
        assert "6" in body or "six" in body.lower() or "Step" in body


# ---------------------------------------------------------------------------
# services platform-agent structure
# ---------------------------------------------------------------------------


class TestDevopsServicesStructure:
    def test_services_skill_md_exists(self):
        assert (_SERVICES_WS / "SKILL.md").is_file()

    def test_services_skill_md_name(self):
        text = (_SERVICES_WS / "SKILL.md").read_text(encoding="utf-8")
        assert "name: services" in text

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

    def test_services_has_write_compose_file(self):
        assert (_SERVICES_SCRIPTS / "write_compose_file.py").is_file()

    def test_services_confirms_state_changes(self):
        """docker_compose.py must require confirmed=True for state-changing ops."""
        src = (_SERVICES_SCRIPTS / "docker_compose.py").read_text(encoding="utf-8")
        assert "confirmed" in src
        assert "preview" in src


# ---------------------------------------------------------------------------
# api_request — unregistered service returns structured error (C-NE-38)
# ---------------------------------------------------------------------------


class TestApiRequestUnregisteredService:
    def _invoke_api_request(self, service: str) -> dict:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "api_request",
            str(_ROOT / ".olav" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py"),
        )
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.api_request(service=service, method="GET", path="/")

    def test_returns_error_dict_not_exception(self):
        result = self._invoke_api_request("foobar-nonexistent")
        assert isinstance(result, dict)

    def test_error_status_field(self):
        result = self._invoke_api_request("foobar-nonexistent")
        assert result.get("status") == "error"

    def test_error_names_the_service(self):
        result = self._invoke_api_request("foobar-nonexistent")
        combined = f"{result.get('reason', '')} {result.get('hint', '')}"
        assert "foobar-nonexistent" in combined

    def test_error_lists_available_services(self):
        result = self._invoke_api_request("foobar-nonexistent")
        hint = result.get("hint", "")
        assert "Available services:" in hint or "Available:" in hint


# ---------------------------------------------------------------------------
# LLM E2E — NetBox workflow (two-phase)
#
# Phase 1: services deploys latest NetBox via natural language.
# Phase 2: devops/infra writes a device-import script to .olav/automations/.
#
# Gate: DEVOPS_E2E_ENABLED=1
# Run:
#   DEVOPS_E2E_ENABLED=1 uv run pytest tests/e2e/test_devops_e2e.py::TestNetboxWorkflowE2E -v -s
# ---------------------------------------------------------------------------


def _e2e_enabled() -> bool:
    return os.environ.get("DEVOPS_E2E_ENABLED", "").lower() in {"1", "true", "yes"}


_E2E_SKIP = pytest.mark.skipif(not _e2e_enabled(), reason="Set DEVOPS_E2E_ENABLED=1 to run")
_TIMEOUT = int(float(os.environ.get("OLAV_E2E_TIMEOUT_FACTOR", "1")) * 240)
_OLAV = [sys.executable, "-m", "olav"]


def _run(agent: str, prompt: str, timeout: int = _TIMEOUT) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        _OLAV + ["--agent", agent, prompt],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(_ROOT),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(proc.args, -1, stdout or "", stderr or "")


@_E2E_SKIP
class TestNetboxWorkflowE2E:
    """Two-phase NetBox workflow: deploy via services → import script via devops.

    Phase 1 verifies services agent correctly:
      - web_searches for the latest NetBox docker image
      - writes a docker-compose.yml under .olav/services/netbox/
      - returns a HITL preview (confirmed=False), not an actual deployment

    Phase 2 verifies devops/infra agent correctly:
      - queries netops.devices for real device data
      - generates a Python import script
      - saves it to .olav/automations/netbox/
      - validates the script passes py_compile
      - script contains --dry-run flag and no placeholder values
    """

    # ------------------------------------------------------------------ Phase 1

    def test_phase1_services_writes_compose_file(self):
        """services agent writes docker-compose.yml for NetBox to .olav/services/netbox/."""
        compose_dir = _ROOT / ".olav" / "services" / "netbox"
        before = compose_dir / "docker-compose.yml"
        before_mtime = before.stat().st_mtime if before.exists() else 0.0

        result = _run(
            "services",
            "部署最新版本的 NetBox，先生成 compose 文件给我看，不要直接部署",
        )
        assert result.returncode == 0, (
            f"services agent exited {result.returncode}:\n{result.stderr[:500]}"
        )

        compose = _ROOT / ".olav" / "services" / "netbox" / "docker-compose.yml"
        assert compose.exists(), (
            f"services agent did not write .olav/services/netbox/docker-compose.yml\n"
            f"stdout: {result.stdout[:800]}"
        )
        assert compose.stat().st_mtime > before_mtime, (
            "docker-compose.yml was not updated by this run"
        )

    def test_phase1_compose_references_netbox_image(self):
        """docker-compose.yml must reference a real netbox image, not a placeholder."""
        compose = _ROOT / ".olav" / "services" / "netbox" / "docker-compose.yml"
        if not compose.exists():
            pytest.skip("Phase 1 compose file not yet generated — run test_phase1_services_writes_compose_file first")

        content = compose.read_text(encoding="utf-8")
        assert "netbox" in content.lower(), "Compose file does not reference a netbox image"
        placeholder_values = {"YOUR_IMAGE", "example.com", "CHANGEME", "latest-dev"}
        for p in placeholder_values:
            assert p not in content, f"Compose file contains placeholder '{p}'"

    def test_phase1_returns_preview_not_running_container(self):
        """services agent must not start the container unprompted — HITL gate."""
        result = _run(
            "services",
            "部署最新版本的 NetBox，先生成 compose 文件给我看，不要直接部署",
        )
        # Agent should mention preview / confirm / 确认 — NOT report containers running
        stdout_lower = result.stdout.lower()
        assert "preview" in stdout_lower or "confirm" in stdout_lower or "确认" in result.stdout, (
            f"services agent did not show HITL confirmation step.\nstdout: {result.stdout[:600]}"
        )
        assert "running" not in stdout_lower or "preview" in stdout_lower, (
            "services agent appears to have started the container without confirmation"
        )

    # ------------------------------------------------------------------ Phase 2

    def test_phase2_infra_writes_import_script(self):
        """devops/infra writes a NetBox device-import script to .olav/automations/netbox/."""
        netbox_automations = _AUTOMATIONS / "netbox"
        before_scripts = set(netbox_automations.glob("*.py")) if netbox_automations.exists() else set()

        result = _run(
            "devops",
            "写一个 Python 脚本，把 OLAV 数据库中的所有设备导入到 NetBox，"
            "保存到自动化库，加上 --dry-run 参数",
        )
        assert result.returncode == 0, (
            f"devops agent exited {result.returncode}:\n{result.stderr[:500]}"
        )

        after_scripts = set(netbox_automations.glob("*.py")) if netbox_automations.exists() else set()
        new_scripts = after_scripts - before_scripts
        assert new_scripts, (
            f"devops/infra did not write any .py file to .olav/automations/netbox/\n"
            f"stdout: {result.stdout[:800]}"
        )

    def test_phase2_script_has_dry_run(self):
        """Generated import script must have --dry-run flag."""
        netbox_automations = _AUTOMATIONS / "netbox"
        if not netbox_automations.exists():
            pytest.skip("Phase 2 not yet run")
        scripts = sorted(netbox_automations.glob("*.py"), key=lambda p: p.stat().st_mtime)
        assert scripts, "No .py files in .olav/automations/netbox/"
        content = scripts[-1].read_text(encoding="utf-8")
        assert "--dry-run" in content or "dry_run" in content, (
            f"Import script missing --dry-run flag: {scripts[-1].name}\n{content[:400]}"
        )

    def test_phase2_script_uses_real_devices(self):
        """Generated script must NOT contain placeholder IPs or hostnames."""
        netbox_automations = _AUTOMATIONS / "netbox"
        if not netbox_automations.exists():
            pytest.skip("Phase 2 not yet run")
        scripts = sorted(netbox_automations.glob("*.py"), key=lambda p: p.stat().st_mtime)
        assert scripts
        content = scripts[-1].read_text(encoding="utf-8")
        for placeholder in ("10.0.0.1", "YOUR_TOKEN", "CHANGEME", "example.com"):
            assert placeholder not in content, (
                f"Import script contains placeholder '{placeholder}': {scripts[-1].name}"
            )

    def test_phase2_script_passes_syntax_check(self):
        """Generated import script must pass py_compile syntax check."""
        netbox_automations = _AUTOMATIONS / "netbox"
        if not netbox_automations.exists():
            pytest.skip("Phase 2 not yet run")
        scripts = sorted(netbox_automations.glob("*.py"), key=lambda p: p.stat().st_mtime)
        assert scripts
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(scripts[-1])],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"py_compile failed on {scripts[-1].name}:\n{r.stderr}"
        )

    def test_phase2_script_uses_env_var_for_token(self):
        """Generated script must use env var for NetBox token — no hardcoded secrets."""
        netbox_automations = _AUTOMATIONS / "netbox"
        if not netbox_automations.exists():
            pytest.skip("Phase 2 not yet run")
        scripts = sorted(netbox_automations.glob("*.py"), key=lambda p: p.stat().st_mtime)
        assert scripts
        content = scripts[-1].read_text(encoding="utf-8")
        # Must reference env var for auth, not a literal token string
        uses_env = "os.environ" in content or "os.getenv" in content or "${" in content
        assert uses_env, (
            f"Import script does not use env var for NetBox token: {scripts[-1].name}\n"
            f"{content[:400]}"
        )
