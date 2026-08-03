"""Service credential env vars name the SERVICE, not OLAV.

The shipped entries are `GITEA_TOKEN`, `NETBOX_TOKEN`,
`INFLUXDB_NETOPS_TOKEN`, `CLAB_USERNAME`. The `OLAV_` prefix belongs to OLAV's
own knobs — `OLAV_EMBEDDING_MODE`, `OLAV_LAB_USERNAME`, `OLAV_CLAB_SSH` — which
configure OLAV's behaviour rather than authenticate to somebody else's API.

The distinction is not cosmetic. `olav agent install` auto-primes a
containerlab entry, and it wrote `OLAV_CLAB_USERNAME` while every doc, test and
existing entry used `CLAB_USERNAME`. Each half was internally consistent — the
runtime reads whatever name the entry declares — so nothing failed loudly. A
fresh install simply asked the operator to set a variable no documentation
mentioned, and an operator who followed the documentation got an
unauthenticated client (2026-08-03).

This checks what the code *produces*, not what its source text says: a string
assertion would pass on a refactor that renamed the constant and changed the
value.
"""
from __future__ import annotations

import json

import pytest
import yaml

_CRED_KEYS = ("username_env", "password_env", "token_env", "api_key_env")


def _primed_entry(tmp_path, monkeypatch):
    """Run the real auto-prime and return the containerlab entry it wrote."""
    from olav.cli.commands import skill as skill_cmd

    ws = tmp_path / "workspace"
    cfg_dir = ws / "netops" / "lab" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"base_url": "https://clab.example:8090", "auth_type": "jwt"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    conf = tmp_path / ".olav" / "config"
    conf.mkdir(parents=True)
    # The prime deliberately does not repair a missing services.yaml — `olav
    # init` creates the stub, and a prime that invented one would be papering
    # over a skipped init. Provide the stub the same way init does.
    (conf / "services.yaml").write_text("services: {}\n", encoding="utf-8")

    out = skill_cmd._prime_lab_services_from_config(ws)
    assert "⚠" not in out, out
    doc = yaml.safe_load((tmp_path / ".olav" / "config" / "services.yaml").read_text())
    return (doc.get("services") or {}).get("containerlab") or {}


def test_auto_prime_writes_a_usable_containerlab_entry(tmp_path, monkeypatch):
    entry = _primed_entry(tmp_path, monkeypatch)
    assert entry.get("endpoint") == "https://clab.example:8090"
    assert (entry.get("auth") or {}).get("type") == "jwt"


def test_auto_primed_credentials_name_the_service_not_olav(tmp_path, monkeypatch):
    """The regression itself: a fresh install must ask for the same variables
    the documentation and the e2e tests use."""
    auth = _primed_entry(tmp_path, monkeypatch).get("auth") or {}
    assert auth.get("username_env") == "CLAB_USERNAME"
    assert auth.get("password_env") == "CLAB_PASSWORD"


@pytest.mark.parametrize("key", _CRED_KEYS)
def test_no_credential_env_carries_the_olav_prefix(key, tmp_path, monkeypatch):
    """`OLAV_` marks OLAV's own configuration. A credential for someone else's
    API named that way reads as ours and drifts from the service's own docs."""
    value = (_primed_entry(tmp_path, monkeypatch).get("auth") or {}).get(key)
    if value:
        assert not value.startswith("OLAV_"), (
            f"{key}={value!r} — service credentials name the service "
            f"(GITEA_TOKEN, NETBOX_TOKEN, CLAB_USERNAME); OLAV_ is for OLAV's "
            f"own knobs"
        )


def test_a_users_own_services_yaml_follows_the_same_rule():
    """Advisory on the live config: it is user-owned and gitignored, so this
    only runs when one exists and only checks the shape we ship."""
    from pathlib import Path

    live = Path(".olav") / "config" / "services.yaml"
    if not live.is_file():
        pytest.skip("no live services.yaml")
    doc = yaml.safe_load(live.read_text()) or {}
    offenders = []
    for name, svc in (doc.get("services") or {}).items():
        for key in _CRED_KEYS:
            val = (svc.get("auth") or {}).get(key)
            if val and val.startswith("OLAV_"):
                offenders.append(f"{name}.{key}={val}")
    assert not offenders, (
        "service credentials should name the service, not OLAV:\n  "
        + "\n  ".join(offenders)
    )
