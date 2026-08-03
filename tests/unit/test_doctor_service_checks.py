"""doctor checks every registered service — dev_docs/113.

`services.yaml` is already the registry of what this install has, so a service
the user registers (NetBox, gitea) is probed with no extra step. A skill that
knows more about its own readiness ships a `healthcheck.yaml` naming the
service; doctor discovers it and adopts its results.

The severity split is the load-bearing part. doctor renders not-ok **without**
a `fix` as a soft ⚠ and not-ok **with** one as ✗, so:

* the lab host being down is an environment fact, not a broken install;
* an unset credential is actionable and says what to export;
* a service nobody registered produces **no check at all** — an unused
  integration must never turn `olav doctor` red, or people stop reading it.
"""
from __future__ import annotations

import json

import pytest
import yaml

from olav.cli.commands.doctor import DoctorCommand


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".olav" / "config").mkdir(parents=True)
    return tmp_path


def _write_services(root, services: dict):
    (root / ".olav" / "config" / "services.yaml").write_text(
        yaml.safe_dump({"services": services}), encoding="utf-8")


def _run(monkeypatch, reachable=True):
    """Call _check_services with a stubbed socket module."""
    import socket as real_socket

    class _Sock:
        error = OSError

        @staticmethod
        def create_connection(addr, timeout=None):
            if not reachable:
                raise OSError("unreachable")
            return real_socket.socket()

    monkeypatch.setattr("socket.create_connection", _Sock.create_connection)
    return DoctorCommand()._check_services()


# --- an unused integration must not turn doctor red -------------------------


def test_no_services_yaml_produces_no_checks(workspace, monkeypatch):
    assert DoctorCommand()._check_services() == []


def test_an_empty_registry_produces_no_checks(workspace, monkeypatch):
    _write_services(workspace, {})
    assert DoctorCommand()._check_services() == []


# --- the generic probe, derived from the entry itself -----------------------


def test_a_registered_service_is_probed_with_no_extra_step(workspace, monkeypatch):
    """This is what makes case 2 (user deploys NetBox) free."""
    _write_services(workspace, {
        "netbox": {"endpoint": "http://nb.example:8080",
                   "auth": {"type": "api_key", "token_env": "NETBOX_TOKEN"}}})
    monkeypatch.setenv("NETBOX_TOKEN", "t")
    checks = _run(monkeypatch)
    assert [c["name"] for c in checks] == ["service:netbox"]
    assert checks[0]["ok"], checks[0]


def test_an_unreachable_endpoint_is_a_soft_warning_not_an_error(workspace, monkeypatch):
    """No `fix` key: doctor renders it ⚠. The host being down is not something
    the operator broke, and a red install report for it teaches people to
    ignore the report."""
    _write_services(workspace, {"clab": {"endpoint": "https://down.example:8090"}})
    check = _run(monkeypatch, reachable=False)[0]
    assert check["ok"] is False
    assert "fix" not in check
    assert "unreachable" in check["detail"]


def test_a_missing_credential_is_actionable(workspace, monkeypatch):
    _write_services(workspace, {
        "gitea": {"endpoint": "http://git.example:3000",
                  "auth": {"type": "api_key", "token_env": "GITEA_TOKEN"}}})
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    check = _run(monkeypatch)[0]
    assert check["ok"] is False
    assert "GITEA_TOKEN" in check["fix"]


def test_an_entry_without_an_endpoint_is_actionable(workspace, monkeypatch):
    _write_services(workspace, {"broken": {"description": "no endpoint"}})
    check = _run(monkeypatch)[0]
    assert check["ok"] is False and "endpoint" in check["fix"]


def test_the_pre_v015_list_shape_is_read_not_rejected(workspace, monkeypatch):
    """The installer still accepts it, so calling it unparseable would report
    a fault that is not there."""
    (workspace / ".olav" / "config" / "services.yaml").write_text(
        yaml.safe_dump({"services": [{"name": "old", "endpoint": "http://h:1"}]}),
        encoding="utf-8")
    names = [c["name"] for c in _run(monkeypatch)]
    assert names == ["service:old"]


# --- a skill contributes what only it knows ---------------------------------


def _install_skill(root, service: str, script_body: str, spec_extra=""):
    d = root / ".olav" / "workspace" / "services" / "lab"
    (d / "scripts").mkdir(parents=True)
    (d / "healthcheck.yaml").write_text(
        f"service: {service}\nscript: healthcheck.py\n{spec_extra}", encoding="utf-8")
    (d / "scripts" / "healthcheck.py").write_text(script_body, encoding="utf-8")
    return d


def test_a_skills_own_checks_are_discovered_and_adopted(workspace, monkeypatch):
    """Discovered from the installed skill — nothing is written back into
    services.yaml, which is user-owned."""
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill(workspace, "containerlab",
                   "import json;print(json.dumps({'checks':["
                   "{'name':'images','ok':True,'detail':'3 images'}]}))")
    checks = _run(monkeypatch)
    assert [c["name"] for c in checks] == ["service:containerlab",
                                           "containerlab: images"]
    assert checks[1]["detail"] == "3 images"


def test_a_skill_check_can_fail_with_its_own_fix(workspace, monkeypatch):
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill(workspace, "containerlab",
                   "import json;print(json.dumps({'checks':[{'name':'images',"
                   "'ok':False,'detail':'none','fix':'supply an image'}]}))")
    assert _run(monkeypatch)[1]["fix"] == "supply an image"


def test_a_broken_readiness_script_is_reported_not_swallowed(workspace, monkeypatch):
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill(workspace, "containerlab", "raise SystemExit('boom')")
    check = _run(monkeypatch)[1]
    assert check["ok"] is False and "readiness script" in check["detail"]


def test_a_spec_naming_a_missing_script_says_so(workspace, monkeypatch):
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    d = workspace / ".olav" / "workspace" / "services" / "lab"
    d.mkdir(parents=True)
    (d / "healthcheck.yaml").write_text(
        "service: containerlab\nscript: gone.py\n", encoding="utf-8")
    check = _run(monkeypatch)[1]
    assert check["ok"] is False and "reinstall" in check["fix"]


def test_a_spec_for_an_unregistered_service_is_not_run(workspace, monkeypatch):
    """The registry decides what exists; a skill cannot conjure a service."""
    _write_services(workspace, {"other": {"endpoint": "http://h:1"}})
    _install_skill(workspace, "containerlab",
                   "import json;print(json.dumps({'checks':[{'name':'x','ok':True,'detail':''}]}))")
    assert [c["name"] for c in _run(monkeypatch)] == ["service:other"]


# --- doctor stays a read-only, seconds-long command -------------------------


def test_the_shipped_clab_spec_declares_a_read_only_script():
    """doctor is typed casually; it must never deploy a lab. Proving the code
    still works end to end is the e2e's job, on a schedule, against a host it
    is allowed to mutate."""
    from pathlib import Path

    src = Path("olav-ent/workspace/services/lab/scripts/healthcheck.py")
    if not src.is_file():
        pytest.skip("olav-ent not checked out")
    body = src.read_text(encoding="utf-8")
    for mutating in ("deploy_lab", "destroy_lab", "push(", "run_validation"):
        assert mutating not in body, f"readiness script calls {mutating!r}"


def test_a_silent_readiness_script_is_a_finding(workspace, monkeypatch):
    """A script that exits 0 and prints nothing looked exactly like a healthy
    one — `json.loads("{}")` succeeds and the empty check list vanished."""
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill(workspace, "containerlab", "pass")
    check = _run(monkeypatch)[1]
    assert check["ok"] is False and "no checks" in check["detail"]


def test_non_json_output_is_a_finding(workspace, monkeypatch):
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill(workspace, "containerlab", "print('not json')")
    check = _run(monkeypatch)[1]
    assert check["ok"] is False and "non-JSON" in check["detail"]


# --- readiness vs proof: an operator must be able to ask for the second -----


def _install_skill_with_verify(root, body_health, body_verify):
    d = root / ".olav" / "workspace" / "services" / "lab"
    (d / "scripts").mkdir(parents=True)
    (d / "healthcheck.yaml").write_text(
        "service: containerlab\nscript: healthcheck.py\nverify_script: verify.py\n",
        encoding="utf-8")
    (d / "scripts" / "healthcheck.py").write_text(body_health, encoding="utf-8")
    (d / "scripts" / "verify.py").write_text(body_verify, encoding="utf-8")


_OK = ("import json;print(json.dumps({'checks':[{'name':'%s','ok':True,"
       "'detail':'d'}]}))")


def test_a_bare_doctor_never_runs_the_proof(workspace, monkeypatch):
    """It creates and destroys real resources. `olav doctor` is typed
    casually; only an explicit flag may spend infrastructure."""
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill_with_verify(workspace, _OK % "ready", _OK % "proof")
    names = [c["name"] for c in DoctorCommand()._check_services()]
    assert "containerlab: proof" not in names
    assert "containerlab: ready" in names


def test_verify_runs_the_proof(workspace, monkeypatch):
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill_with_verify(workspace, _OK % "ready", _OK % "proof")
    names = [c["name"] for c in DoctorCommand()._check_services(deep=True)]
    assert "containerlab: proof" in names


def test_a_service_with_no_proof_says_so_rather_than_implying_one(workspace):
    """Silence would read as "verified"."""
    _write_services(workspace, {"containerlab": {"endpoint": "http://h:8090"}})
    _install_skill(workspace, "containerlab", _OK % "ready")
    checks = DoctorCommand()._check_services(deep=True)
    tail = [c for c in checks if c["name"].endswith("verify")]
    assert tail and tail[0]["ok"] and "no end-to-end proof" in tail[0]["detail"]


def test_the_cli_forwards_verify(monkeypatch):
    """The first version parsed `--verify` and forwarded only `--json`, so the
    flag existed in `--help` and did nothing."""
    import inspect

    from olav.cli import main as cli_main

    src = inspect.getsource(cli_main.cli_main_impl)
    doctor_block = src[src.index('args.command == "doctor"'):][:900]
    assert '"--verify"' in doctor_block, "doctor's --verify is never forwarded"


def test_the_shipped_proof_tears_its_lab_down():
    """A verify that leaves a lab behind has damaged the thing it checked."""
    from pathlib import Path

    src = Path("olav-ent/workspace/services/lab/scripts/verify.py")
    if not src.is_file():
        pytest.skip("olav-ent not checked out")
    body = src.read_text(encoding="utf-8")
    assert "finally:" in body and "destroy_lab" in body
