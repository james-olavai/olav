"""Regression: the services-agent ``register_service`` script must write an
entry that ``ServiceRegistry`` parses back with auth INTACT.

The script used to write flat ``auth_type`` / ``auth_token_env`` keys, but
``ServiceRegistry._parse_auth`` reads a NESTED ``auth: {type, token_env}``
block (``raw.get("auth", {})``). The mismatch meant every agent-registered
service silently loaded as ``auth.type="none"`` — the Authorization header was
never sent, so authenticated calls 403'd. Verified live against NetBox 4.5's
bearer tokens (flat → 403, nested → 200). This test is the round-trip the
original unit tests skipped (they only checked the file was written, not that
the registry could read auth back).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "src/olav/data/workspace/services/scripts/register_service.py"
)


def _load_register_service(project_root: Path):
    spec = importlib.util.spec_from_file_location("_register_service_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The script pins _PROJECT_ROOT at import from __file__ (the real repo);
    # redirect it at the tmp project so the test never writes the real
    # .olav/config/services.yaml. _services_yaml_path() reads this global.
    mod._PROJECT_ROOT = project_root
    return mod.register_service


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A tmp project root the script + registry both resolve relative to cwd."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# register_service's _VALID_AUTH_TYPES accepts these (api_key is registry-only).
@pytest.mark.parametrize("auth_type", ["bearer", "basic"])
def test_registered_auth_survives_registry_load(project, auth_type):
    register_service = _load_register_service(project)
    res = register_service(
        name="netbox",
        endpoint="http://localhost:8000/api",
        auth_type=auth_type,
        auth_token_env="NETBOX_TOKEN",
    )
    assert res["status"] == "success", res

    # Reload the registry from the freshly-written services.yaml.
    from olav.platform.services.registry import ServiceRegistry

    ServiceRegistry.reset()
    svc = ServiceRegistry.get_instance().get("netbox")
    assert svc.auth.type == auth_type, (
        f"auth.type parsed back as {svc.auth.type!r}, not {auth_type!r} — "
        "register_service wrote a shape the registry can't read"
    )
    assert svc.auth.token_env == "NETBOX_TOKEN"


def test_none_auth_roundtrips(project):
    register_service = _load_register_service(project)
    register_service(name="public", endpoint="http://x/api", auth_type="none")
    from olav.platform.services.registry import ServiceRegistry

    ServiceRegistry.reset()
    svc = ServiceRegistry.get_instance().get("public")
    assert svc.auth.type == "none"
