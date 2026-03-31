"""
tests/unit/test_manifest_deps.py
─────────────────────────────────
TDD tests for HP-1 / HP-2: MANIFEST dependency declarations.

Tests verify:
  1. AgentManifest has new dependency fields (provider_package, required_modules, required_binaries, config_namespace)
  2. from_yaml parses these new fields from MANIFEST.yaml
  3. from_yaml defaults to empty when fields are absent
  4. check_dependencies() returns availability state (available / unavailable)
  5. check_dependencies() detects missing Python modules
  6. check_dependencies() detects missing binaries (shutil.which)
  7. check_dependencies() detects missing provider_package
  8. check_dependencies() returns 'available' when all deps satisfied
  9. discover_agents populates new fields from YAML
 10. availability_state property returns correct AvailabilityState enum
"""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest


# ── 1. New fields exist on AgentManifest ──────────────────────────────────────


def test_agent_manifest_has_dependency_fields():
    """HP-2: AgentManifest must have provider_package, required_modules, required_binaries, config_namespace."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Skill",
        version="0.11.0",
        path=Path("/fake/MANIFEST.yaml"),
        provider_package="olav-netops",
        required_modules=["nornir", "netmiko"],
        required_binaries=["traceroute"],
        config_namespace="netops",
    )
    assert m.provider_package == "olav-netops"
    assert m.required_modules == ["nornir", "netmiko"]
    assert m.required_binaries == ["traceroute"]
    assert m.config_namespace == "netops"


def test_agent_manifest_dependency_fields_default_empty():
    """HP-2: New fields default to None/empty when not specified."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Agent",
        version="0.11.0",
        path=Path("/fake/MANIFEST.yaml"),
    )
    assert m.provider_package is None
    assert m.required_modules == []
    assert m.required_binaries == []
    assert m.config_namespace is None


# ── 2. from_yaml parses dependency fields ─────────────────────────────────────


def test_from_yaml_parses_dependency_fields(tmp_path):
    """HP-2: from_yaml must read provider_package, required_modules, required_binaries, config_namespace."""
    from olav.core.agent_registry import AgentManifest

    p = tmp_path / "MANIFEST.yaml"
    p.write_text("""\
kind: Skill
name: ops-netops
version: "0.11.0"
agent: ops
provider_package: olav-netops
required_modules:
  - nornir
  - netmiko
  - scrapli
required_binaries:
  - traceroute
config_namespace: netops
route_keywords:
  - troubleshoot
requires:
  - olav-netops>=0.11
""")
    m = AgentManifest.from_yaml(p)
    assert m.provider_package == "olav-netops"
    assert m.required_modules == ["nornir", "netmiko", "scrapli"]
    assert m.required_binaries == ["traceroute"]
    assert m.config_namespace == "netops"


def test_from_yaml_defaults_when_dep_fields_absent(tmp_path):
    """HP-2: from_yaml gracefully handles missing dependency fields."""
    from olav.core.agent_registry import AgentManifest

    p = tmp_path / "MANIFEST.yaml"
    p.write_text("""\
kind: Agent
name: audit
version: "0.12.0"
""")
    m = AgentManifest.from_yaml(p)
    assert m.provider_package is None
    assert m.required_modules == []
    assert m.required_binaries == []
    assert m.config_namespace is None


# ── 3. check_dependencies() ──────────────────────────────────────────────────


def test_check_dependencies_all_satisfied(tmp_path):
    """HP-2: check_dependencies returns available when all deps met."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Agent",
        version="0.11.0",
        path=tmp_path / "MANIFEST.yaml",
        required_modules=["os", "sys"],  # stdlib always available
        required_binaries=[],
    )
    result = m.check_dependencies()
    assert result.state == "available"
    assert result.missing_modules == []
    assert result.missing_binaries == []


def test_check_dependencies_missing_module(tmp_path):
    """HP-2: check_dependencies detects missing Python modules."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Skill",
        version="0.11.0",
        path=tmp_path / "MANIFEST.yaml",
        required_modules=["nonexistent_module_xyz_12345"],
    )
    result = m.check_dependencies()
    assert result.state == "unavailable"
    assert "nonexistent_module_xyz_12345" in result.missing_modules


def test_check_dependencies_missing_binary(tmp_path):
    """HP-2: check_dependencies detects missing binaries."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Skill",
        version="0.11.0",
        path=tmp_path / "MANIFEST.yaml",
        required_binaries=["nonexistent_binary_xyz_12345"],
    )
    result = m.check_dependencies()
    assert result.state == "unavailable"
    assert "nonexistent_binary_xyz_12345" in result.missing_binaries


def test_check_dependencies_missing_provider_package(tmp_path):
    """HP-2: check_dependencies detects missing provider_package."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Skill",
        version="0.11.0",
        path=tmp_path / "MANIFEST.yaml",
        provider_package="nonexistent-package-xyz-12345",
    )
    result = m.check_dependencies()
    assert result.state == "unavailable"
    assert result.missing_provider is True


def test_check_dependencies_no_deps_means_available(tmp_path):
    """HP-2: No dependencies declared = always available."""
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="test",
        kind="Agent",
        version="0.11.0",
        path=tmp_path / "MANIFEST.yaml",
    )
    result = m.check_dependencies()
    assert result.state == "available"


# ── 4. DependencyCheckResult dataclass ────────────────────────────────────────


def test_dependency_check_result_importable():
    """HP-2: DependencyCheckResult is importable from agent_registry."""
    from olav.core.agent_registry import DependencyCheckResult

    r = DependencyCheckResult(state="available")
    assert r.state == "available"
    assert r.missing_modules == []
    assert r.missing_binaries == []
    assert r.missing_provider is False


def test_dependency_check_result_has_summary():
    """HP-2: DependencyCheckResult.summary() returns human-readable string."""
    from olav.core.agent_registry import DependencyCheckResult

    r = DependencyCheckResult(
        state="unavailable",
        missing_modules=["nornir"],
        missing_binaries=["traceroute"],
        missing_provider=True,
    )
    summary = r.summary()
    assert "nornir" in summary
    assert "traceroute" in summary


# ── 5. discover_agents picks up new fields ────────────────────────────────────


def test_discover_agents_populates_dependency_fields(tmp_path):
    """HP-2: discover_agents picks up new dependency fields from MANIFEST."""
    from olav.core.agent_registry import discover_agents

    skill_dir = tmp_path / "netops-ops"
    skill_dir.mkdir()
    (skill_dir / "MANIFEST.yaml").write_text("""\
kind: Skill
name: netops-ops
version: "0.11.0"
agent: ops
provider_package: olav-netops
required_modules:
  - nornir
required_binaries:
  - traceroute
config_namespace: netops
""")
    result = discover_agents(tmp_path)
    m = result["netops-ops"]
    assert m.provider_package == "olav-netops"
    assert m.required_modules == ["nornir"]
    assert m.required_binaries == ["traceroute"]
    assert m.config_namespace == "netops"
