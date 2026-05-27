"""Tests for devops/services/scripts/deploy_service.py and stop_service.py."""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY_PATH = _ROOT / ".olav" / "workspace" / "devops" / "services" / "scripts" / "deploy_service.py"
_STOP_PATH = _ROOT / ".olav" / "workspace" / "devops" / "services" / "scripts" / "stop_service.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def deploy_mod():
    return _load(_DEPLOY_PATH, "_deploy_mod")


@pytest.fixture(scope="module")
def stop_mod():
    return _load(_STOP_PATH, "_stop_mod")


# ── deploy_service: file existence and signature ──────────────────────────────


def test_deploy_service_script_exists():
    assert _DEPLOY_PATH.is_file(), f"deploy_service.py missing at {_DEPLOY_PATH}"


def test_deploy_service_callable(deploy_mod):
    assert hasattr(deploy_mod, "deploy_service") and callable(deploy_mod.deploy_service)


def test_deploy_service_signature(deploy_mod):
    sig = inspect.signature(deploy_mod.deploy_service)
    params = set(sig.parameters)
    assert {"name", "health_url", "health_timeout"}.issubset(params), (
        f"deploy_service missing expected params; found: {params}"
    )


# ── deploy_service: missing service dir → structured error ───────────────────


def test_deploy_service_missing_dir_returns_error(deploy_mod, tmp_path):
    with patch.object(deploy_mod, "PROJECT_ROOT", tmp_path):
        result = deploy_mod.deploy_service(name="nonexistent_xyz")
    assert result["success"] is False
    assert "exist" in result.get("error", "").lower() or "exist" in result.get("hint", "").lower()


def test_deploy_service_missing_compose_file_returns_error(deploy_mod, tmp_path):
    svc_dir = tmp_path / ".olav" / "services" / "no_compose"
    svc_dir.mkdir(parents=True)
    with patch.object(deploy_mod, "PROJECT_ROOT", tmp_path):
        result = deploy_mod.deploy_service(name="no_compose")
    assert result["success"] is False
    assert "docker-compose" in result.get("error", "").lower() or "compose" in result.get("hint", "").lower()


# ── stop_service: file existence and signature ────────────────────────────────


def test_stop_service_script_exists():
    assert _STOP_PATH.is_file(), f"stop_service.py missing at {_STOP_PATH}"


def test_stop_service_callable(stop_mod):
    assert hasattr(stop_mod, "stop_service") and callable(stop_mod.stop_service)


def test_stop_service_signature(stop_mod):
    sig = inspect.signature(stop_mod.stop_service)
    params = set(sig.parameters)
    assert {"name", "remove"}.issubset(params), (
        f"stop_service missing expected params; found: {params}"
    )


# ── stop_service: missing service dir → structured error with hint ────────────


def test_stop_service_missing_dir_returns_error_with_hint(stop_mod, tmp_path):
    with patch.object(stop_mod, "PROJECT_ROOT", tmp_path):
        result = stop_mod.stop_service(name="ghost_service_xyz")
    assert result["success"] is False
    assert "hint" in result, "stop_service must return a 'hint' key on failure"
    assert "ghost_service_xyz" in result.get("error", "")


# ── stop_service: list_services returns dict ─────────────────────────────────


def test_list_services_returns_dict(stop_mod, tmp_path):
    with patch.object(stop_mod, "PROJECT_ROOT", tmp_path):
        result = stop_mod.list_services()
    assert isinstance(result, dict)
    assert "services" in result


# ── devops orchestrator routes to services sub-agent ─────────────────────────


def test_devops_orchestrator_routes_services():
    prompt = (_ROOT / ".olav" / "workspace" / "devops" / "prompts" / "orchestrator.md").read_text()
    assert "deploy_service" in prompt, "orchestrator.md must mention deploy_service in delegation table"
    assert "stop_service" in prompt, "orchestrator.md must mention stop_service in delegation table"
    assert 'task("services"' in prompt, "orchestrator.md must delegate to services sub-agent"
