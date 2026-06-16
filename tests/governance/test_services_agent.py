"""dev_docs/80 AGENT_ARCHITECTURE_V2 — ``admin/`` top-level agent is wired up.

The ``services/`` agent was renamed to ``admin/`` (platform self-management).
This test guards the new ``admin`` agent structure and the canonical tool files
it depends on (deploy/stop/cron/health/log/ingest in admin/ops/tools/).

Historical note: the previous version of this test checked ``services/`` which
was decommissioned in dev_docs/80.  Tool behaviour assertions are kept verbatim
because the underlying register_service logic did not change — only the path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"
ADMIN = WORKSPACE / "admin"
# ADR-0014: services is now a platform top-level agent (was a devops sub-agent).
# register_service et al. live at .olav/workspace/services/scripts/.
DEVOPS_SERVICES_TOOLS = WORKSPACE / "services" / "scripts"
ADMIN_OPS_TOOLS = WORKSPACE / "admin" / "ops" / "scripts"


# ── scaffold ─────────────────────────────────────────────────────────────────


def test_admin_root_exists():
    assert ADMIN.is_dir(), f"admin top-level agent missing at {ADMIN}"


def test_admin_has_agent_md_with_frontmatter():
    text = (ADMIN / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "admin/SKILL.md lacks YAML frontmatter"
    for key in ("name: admin", "route_keywords:"):
        assert key in text, f"admin/SKILL.md missing {key!r}"


def test_admin_has_ops_subagent():
    ops_skill = ADMIN / "ops" / "SKILL.md"
    assert ops_skill.is_file(), f"admin/ops/SKILL.md missing: {ops_skill}"
    text = ops_skill.read_text(encoding="utf-8")
    for tool_name in ("check_health", "export_logs", "manage_cron"):
        assert tool_name in text, f"admin/ops/SKILL.md missing {tool_name!r}"


def test_admin_has_installer_and_editor_subagents():
    installer_skill = ADMIN / "installer" / "SKILL.md"
    assert installer_skill.is_file(), f"admin/installer/SKILL.md missing: {installer_skill}"
    editor_skill = ADMIN / "editor" / "SKILL.md"
    assert editor_skill.is_file(), f"admin/editor/SKILL.md missing: {editor_skill}"


def test_admin_has_system_prompt():
    # admin system prompt lives in SKILL.md body (post prompts/ migration)
    skill_md = ADMIN / "SKILL.md"
    assert skill_md.is_file(), f"admin/SKILL.md missing: {skill_md}"
    text = skill_md.read_text()
    # body content is everything after the closing --- of frontmatter
    parts = text.split("---", 2)
    body = parts[2].strip() if len(parts) >= 3 else ""
    assert body, "admin/SKILL.md body (system prompt) is empty"


# ── admin/ops/tools — canonical ops admin tool files ─────────────────────────


def test_admin_ops_tools_has_expected_files():
    # v0.11.0: deploy_service + stop_service merged into manage_service.
    # post-R-AGENT-HIERARCHY (Direction A): manage_service removed from admin/ops;
    # service lifecycle is devops/services authority.
    # workspace_health removed (redundant with admin/editor/audit_workspace).
    expected = {
        "check_health.py",
        "export_logs.py",
        "manage_cron.py",
        "analyze_logs.py",
        "bulk_ingest.py",
    }
    actual = {p.name for p in ADMIN_OPS_TOOLS.iterdir() if p.suffix == ".py"}
    missing = expected - actual
    assert not missing, (
        f"admin/ops/tools/ missing expected files: {missing}"
    )


def test_api_request_lives_in_api_query_tools():
    api_request = WORKSPACE / "core" / "api-query" / "scripts" / "api_request.py"
    assert api_request.is_file(), (
        f"api_request.py should be in core/api-query/scripts/, not found: {api_request}"
    )


# ── register_service behaviour (canonical location: devops/services/tools/) ─


def _load_register_service():
    path = DEVOPS_SERVICES_TOOLS / "register_service.py"
    spec = importlib.util.spec_from_file_location("register_service_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _invoke(tool_obj, **kwargs):
    return tool_obj.invoke(kwargs) if hasattr(tool_obj, "invoke") else tool_obj(**kwargs)


def test_register_service_validates_auth_type(monkeypatch, tmp_path):
    fake = tmp_path / ".olav" / "config" / "services.yaml"
    fake.parent.mkdir(parents=True)
    mod = _load_register_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    result = _invoke(mod.register_service, name="x", endpoint="http://x", auth_type="magic_wand")
    assert result["status"] == "error"
    assert "auth_type" in result["message"]


def test_register_service_requires_token_env_for_bearer(monkeypatch, tmp_path):
    fake = tmp_path / "services.yaml"
    mod = _load_register_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    result = _invoke(mod.register_service, name="x", endpoint="http://x", auth_type="bearer")
    assert result["status"] == "error"
    assert "auth_token_env" in result["message"]


def test_register_service_appends_to_fresh_file(monkeypatch, tmp_path):
    fake = tmp_path / "services.yaml"
    mod = _load_register_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    result = _invoke(mod.register_service, name="testsvc", endpoint="http://testsvc.local", auth_type="none")
    assert result["status"] == "success"
    import yaml
    data = yaml.safe_load(fake.read_text(encoding="utf-8"))
    assert "services" in data
    assert "testsvc" in data["services"]
    assert data["services"]["testsvc"]["endpoint"] == "http://testsvc.local"


def test_register_service_refuses_to_overwrite(monkeypatch, tmp_path):
    fake = tmp_path / "services.yaml"
    mod = _load_register_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    _invoke(mod.register_service, name="dup", endpoint="http://a", auth_type="none")
    result = _invoke(mod.register_service, name="dup", endpoint="http://b", auth_type="none")
    assert result["status"] == "already_registered"
    assert "existing" in result


def test_register_service_rejects_empty_name(monkeypatch, tmp_path):
    fake = tmp_path / "services.yaml"
    mod = _load_register_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    result = _invoke(mod.register_service, name="", endpoint="http://x")
    assert result["status"] == "error"


# ── PLATFORM.md lists admin ────────────────────────────────────────────────


def test_platform_md_lists_admin():
    import yaml

    platform_md = WORKSPACE / "olav.md"
    text = platform_md.read_text(encoding="utf-8")
    assert text.startswith("---")
    meta = yaml.safe_load(text.split("---", 2)[1]) or {}
    agents = set(meta.get("agents", []))
    assert "admin" in agents, (
        f"olav.md missing admin (run `olav refresh`): {agents}"
    )
    # ADR-0014: `services` is a legitimate top-level agent again (platform
    # service-lifecycle). The old self-mgmt services→admin rename is asserted
    # by `admin in agents` above; admin's presence proves the old one is gone.
    assert "services" in agents, (
        f"olav.md missing the platform `services` agent (ADR-0014): {agents}"
    )


# ── deregister_service ────────────────────────────────────────────────────


def _load_deregister_service():
    path = DEVOPS_SERVICES_TOOLS / "deregister_service.py"
    assert path.is_file(), f"deregister_service.py missing at {path}"
    spec = importlib.util.spec_from_file_location("deregister_service_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_deregister_service_script_exists():
    assert (DEVOPS_SERVICES_TOOLS / "deregister_service.py").is_file()


def test_deregister_preview_without_confirmed(monkeypatch, tmp_path):
    import yaml
    fake = tmp_path / "services.yaml"
    fake.write_text(yaml.safe_dump({"services": {"mysvc": {"endpoint": "http://x"}}}))
    mod = _load_deregister_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    result = _invoke(mod.deregister_service, name="mysvc")
    assert result["status"] == "preview"
    # YAML must be unchanged — confirmed=False must not mutate
    data = yaml.safe_load(fake.read_text())
    assert "mysvc" in data["services"]


def test_deregister_removes_entry_when_confirmed(monkeypatch, tmp_path):
    import yaml
    fake = tmp_path / "services.yaml"
    fake.write_text(yaml.safe_dump({"services": {"mysvc": {"endpoint": "http://x"}}}))
    mod = _load_deregister_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    # Patch DuckDB sync so it doesn't touch real DB
    monkeypatch.setattr(mod, "__builtins__", mod.__builtins__)
    import olav.platform.services.registry_sync as sync_mod
    monkeypatch.setattr(sync_mod, "delete_service", lambda name: None)
    result = _invoke(mod.deregister_service, name="mysvc", confirmed=True)
    assert result["status"] == "ok"
    data = yaml.safe_load(fake.read_text())
    assert "mysvc" not in data.get("services", {})


def test_deregister_not_found_returns_error(monkeypatch, tmp_path):
    import yaml
    fake = tmp_path / "services.yaml"
    fake.write_text(yaml.safe_dump({"services": {}}))
    mod = _load_deregister_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)
    result = _invoke(mod.deregister_service, name="ghost", confirmed=True)
    assert result["status"] == "not_found"


# ── services SKILL.md registers new scripts ──────────────────────────────


def test_services_skill_md_registers_deregister_service():
    text = (WORKSPACE / "services" / "SKILL.md").read_text(encoding="utf-8")
    assert "deregister_service" in text, (
        "services SKILL.md must register deregister_service script"
    )


def test_services_skill_md_registers_bootstrap_registry():
    text = (WORKSPACE / "services" / "SKILL.md").read_text(encoding="utf-8")
    assert "bootstrap_registry" in text, (
        "services SKILL.md must register bootstrap_registry script"
    )


# ── register_service syncs to DuckDB (best-effort) ───────────────────────


def test_register_service_calls_upsert_service(monkeypatch, tmp_path):
    """register_service must attempt to upsert to api_registry.services after YAML write."""
    import yaml
    fake = tmp_path / "services.yaml"
    mod = _load_register_service()
    monkeypatch.setattr(mod, "_services_yaml_path", lambda: fake)

    upsert_calls = []

    import olav.platform.services.registry_sync as sync_mod
    monkeypatch.setattr(sync_mod, "upsert_service",
                        lambda name, entry: upsert_calls.append((name, entry)))

    _invoke(mod.register_service, name="newsvc", endpoint="http://newsvc", auth_type="none")
    assert upsert_calls, "register_service must call upsert_service after YAML write"
    assert upsert_calls[0][0] == "newsvc"
