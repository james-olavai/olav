"""deploy_service health verdict — ISSUE-DEPLOY-SERVICE-FALSE-HEALTHY (2026-07-19).

The NetBox rehearsal exposed a false-healthy chain: `docker compose ps`
WITHOUT `-a` hides exited containers, so a crashed app container vanished
from the health check while its healthy DB/cache siblings made the stack
look green. `_wait_healthy` must see exited containers (ps -a) and treat a
non-zero exit as fatal.

The script is a workspace file — loaded by path via importlib (it is not an
installed module).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/olav/data/workspace/services/scripts/deploy_service.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("deploy_service_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ps_json(containers: list[dict]) -> str:
    return "\n".join(json.dumps(c) for c in containers)


def test_ps_uses_dash_a_so_exited_containers_are_visible():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "docker compose ps -a --format json" in src
    assert "docker compose ps --format json" not in src.replace(
        "docker compose ps -a --format json", ""
    ), "a bare `compose ps` (no -a) hides exited containers"


def test_wait_healthy_fails_on_exited_app_container(monkeypatch, tmp_path):
    """The observed crash: netbox app Exited(1), redis+postgres running —
    must be a FAILURE naming the dead container, not 'running'."""
    mod = _load_module()

    def fake_run(cmd, cwd, timeout=15):
        assert "ps -a" in cmd
        return 0, _ps_json([
            {"Name": "netbox-netbox-1", "State": "exited", "ExitCode": 1, "Health": ""},
            {"Name": "netbox-redis-1", "State": "running", "Health": ""},
            {"Name": "netbox-postgres-1", "State": "running", "Health": "healthy"},
        ]), ""

    monkeypatch.setattr(mod, "_run", fake_run)
    ok, msg = mod._wait_healthy(tmp_path, timeout=5)
    assert ok is False
    assert "netbox-netbox-1" in msg and "1" in msg


def test_wait_healthy_tolerates_exit_zero_init_container(monkeypatch, tmp_path):
    """One-shot init containers exit 0 by design — not a failure."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_run", lambda cmd, cwd, timeout=15: (0, _ps_json([
        {"Name": "app-migrate-1", "State": "exited", "ExitCode": 0, "Health": ""},
        {"Name": "app-web-1", "State": "running", "Health": "healthy"},
    ]), ""))
    ok, msg = mod._wait_healthy(tmp_path, timeout=5)
    assert ok is True


def test_wait_healthy_times_out_on_restart_loop(monkeypatch, tmp_path):
    """A crash-looping container (state=restarting) must never pass."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_run", lambda cmd, cwd, timeout=15: (0, _ps_json([
        {"Name": "app-web-1", "State": "restarting", "Health": ""},
    ]), ""))
    ok, msg = mod._wait_healthy(tmp_path, timeout=1)
    assert ok is False and "not ready" in msg


def test_services_skill_md_declares_deploy_timeout_and_grounded_grader():
    """Companion fixes: deploy_service declares timeout: 600 (the 120s
    execute_skill_script default killed its health-wait loop mid-flight),
    and the services agent runs the grounded deterministic grader (it
    hallucinated 'successfully deployed, all healthy' on a timed-out
    error envelope)."""
    import yaml

    skill_md = REPO / "src/olav/data/workspace/services/SKILL.md"
    fm = yaml.safe_load(skill_md.read_text(encoding="utf-8").split("---")[1])
    entry = next(e for e in fm["scripts"] if e.get("file") == "deploy_service.py")
    assert entry.get("timeout") == 600
    # TOP-LEVEL flags (the dev_docs/97 nested-metadata trap)
    assert fm.get("deterministic_synthesis_grader") is True
    assert fm.get("grader_require_tool_success") is True
