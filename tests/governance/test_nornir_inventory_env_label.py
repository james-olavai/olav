"""ARCH-08 Phase 1: every Nornir inventory device carries ``data.environment``.

The ``environment`` field lets downstream tooling scope collection /
dispatch (``--environment lab``) so lab hostnames don't collide with
production inventory. Phase 1 only adds the field; the corresponding
filter logic in ``execute_cli`` / ``take_snapshot`` lands in Phase 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


HOSTS_YAML = (
    Path(__file__).resolve().parents[2]
    / ".olav" / "workspace" / "netops" / "collector" / "config" / "nornir" / "hosts.yaml"
)
GROUPS_YAML = HOSTS_YAML.parent / "groups.yaml"

_VALID_ENV = {"lab", "prod", "staging", "dev"}


def test_hosts_yaml_exists():
    assert HOSTS_YAML.exists(), f"Nornir hosts.yaml missing at {HOSTS_YAML}"


def test_every_device_has_environment_field():
    data = yaml.safe_load(HOSTS_YAML.read_text(encoding="utf-8")) or {}
    assert data, "hosts.yaml parsed as empty"

    missing: list[str] = []
    invalid: list[str] = []
    for name, device in data.items():
        if not isinstance(device, dict):
            continue
        env = (device.get("data") or {}).get("environment")
        if env is None:
            missing.append(name)
            continue
        if env not in _VALID_ENV:
            invalid.append(f"{name}={env!r}")

    assert not missing, (
        f"Devices lacking data.environment: {missing}. "
        "ARCH-08 Phase 1 requires every device to be tagged lab/prod/staging/dev."
    )
    assert not invalid, (
        f"Devices with unknown environment value: {invalid}. "
        f"Allowed: {sorted(_VALID_ENV)}"
    )


def test_groups_yaml_declares_env_groups():
    """Environment group stubs must exist so hosts can inherit env by group."""
    if not GROUPS_YAML.exists():
        pytest.skip("groups.yaml absent — skip group-level check")

    data = yaml.safe_load(GROUPS_YAML.read_text(encoding="utf-8")) or {}
    for env_name in ("lab", "prod"):
        group = data.get(env_name)
        assert group is not None, (
            f"groups.yaml missing '{env_name}' group — ARCH-08 Phase 1 adds "
            "lab/prod/staging env groups so inventory can inherit by tag."
        )
        env_value = (group.get("data") or {}).get("environment")
        assert env_value == env_name, (
            f"Group '{env_name}' must set data.environment={env_name!r}, got {env_value!r}"
        )
