"""TDD tests for physical boundary migrations: NETOPS-1 and ENT-1.

NETOPS-1: workspace assets for ops/sync/learner must be physically present
          inside olav-netops/.olav/workspace/ (not just the monorepo root).

ENT-1:    olav-ent/src/olav/enterprise/ must exist as an independent source
          copy with its own __init__.py, and olav-ent/pyproject.toml must
          reference src/olav/enterprise (no ../ path escaping).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_NETOPS_ROOT = _ROOT / "olav-netops"
_ENT_ROOT = _ROOT / "olav-ent"

# olav-ent is a SEPARATE git repository with its own gitea remote — the platform
# checkout does not contain it (`git ls-files olav-ent` is empty). Every
# assertion below that reads a file under olav-ent/ is therefore unrunnable in
# platform CI, where it produced 26 of the 39 failures that
# `continue-on-error: true` on the gitea unit step had been hiding.
#
# Skipped rather than deleted: with both repos checked out — the dev-box case —
# these still guard the boundary from the platform side, which is where the split
# was defined. The alternative is moving them into olav-ent's own suite (now that
# it has CI); worth considering, but that is a cross-repo move of 26 tests, not a
# fix for a masked failure.
requires_ent = pytest.mark.skipif(
    not (_ROOT / "olav-ent" / "pyproject.toml").exists(),
    reason="olav-ent not checked out — it is a separate repository (dev_docs/114 §11)",
)



# ===========================================================================
# NETOPS-1: Physical workspace migration into olav-netops/
# ===========================================================================


class TestNetops1PhysicalMigration:
    """Workspace assets must be physically present inside olav-netops/.olav/workspace/."""

    _NW = _NETOPS_ROOT / ".olav" / "workspace"

    def test_netops_olav_workspace_dir_exists(self):
        """olav-netops/.olav/workspace/ directory must exist."""
        assert self._NW.is_dir(), (
            f"olav-netops/.olav/workspace/ not found at {self._NW}. "
            "NETOPS-1: workspace asset directory not created in olav-netops/"
        )

    @pytest.mark.xfail(reason="ops/ merged into netops/ in Phase 3 dedup — workspace no longer separate", strict=False)
    def test_ops_manifest_in_olav_netops(self):
        """olav-netops/.olav/workspace/ops/MANIFEST.yaml must exist."""
        manifest = self._NW / "ops" / "MANIFEST.yaml"
        assert manifest.exists(), (
            f"ops MANIFEST.yaml not found at {manifest}. "
            "NETOPS-1: ops workspace must be physically migrated to olav-netops/"
        )

    @pytest.mark.xfail(reason="ops/ merged into netops/ in Phase 3 dedup — workspace no longer separate", strict=False)
    def test_ops_agent_md_in_olav_netops(self):
        """olav-netops/.olav/workspace/ops/AGENT.md must exist."""
        agent_md = self._NW / "ops" / "AGENT.md"
        assert agent_md.exists(), (
            f"ops AGENT.md not found at {agent_md}. "
            "NETOPS-1: ops workspace assets must be fully migrated"
        )

    @pytest.mark.xfail(reason="NETOPS-1: physical migration to olav-netops/ not yet planned", strict=False)
    def test_config_sync_manifest_in_olav_netops(self):
        """olav-netops/.olav/workspace/config/sync/MANIFEST.yaml must exist."""
        manifest = self._NW / "config" / "sync" / "MANIFEST.yaml"
        assert manifest.exists(), (
            f"config/sync MANIFEST.yaml not found at {manifest}. "
            "NETOPS-1: config/sync workspace must be physically migrated to olav-netops/"
        )

    @pytest.mark.xfail(reason="NETOPS-1: physical migration to olav-netops/ not yet planned", strict=False)
    def test_config_sync_skill_md_in_olav_netops(self):
        """olav-netops/.olav/workspace/config/sync/SKILL.md must exist."""
        skill_md = self._NW / "config" / "sync" / "SKILL.md"
        assert skill_md.exists(), (
            f"config/sync SKILL.md not found at {skill_md}. "
            "NETOPS-1: config/sync workspace assets must be fully migrated"
        )

    @pytest.mark.xfail(reason="NETOPS-1: physical migration to olav-netops/ not yet planned", strict=False)
    def test_config_learner_manifest_in_olav_netops(self):
        """olav-netops/.olav/workspace/config/learner/MANIFEST.yaml must exist."""
        manifest = self._NW / "config" / "learner" / "MANIFEST.yaml"
        assert manifest.exists(), (
            f"config/learner MANIFEST.yaml not found at {manifest}. "
            "NETOPS-1: config/learner workspace must be physically migrated to olav-netops/"
        )

    @pytest.mark.xfail(reason="NETOPS-1: physical migration to olav-netops/ not yet planned", strict=False)
    def test_config_learner_skill_md_in_olav_netops(self):
        """olav-netops/.olav/workspace/config/learner/SKILL.md must exist."""
        skill_md = self._NW / "config" / "learner" / "SKILL.md"
        assert skill_md.exists(), (
            f"config/learner SKILL.md not found at {skill_md}. "
            "NETOPS-1: config/learner workspace assets must be fully migrated"
        )

    @pytest.mark.xfail(reason="ops/ merged into netops/ in Phase 3 dedup — workspace no longer separate", strict=False)
    def test_ops_tools_present_in_olav_netops(self):
        """olav-netops/.olav/workspace/ops/tools/ directory must exist."""
        tools = self._NW / "ops" / "tools"
        assert tools.is_dir(), (
            f"ops/tools/ not found at {tools}. "
            "NETOPS-1: full ops tool tree must be migrated, not just top-level files"
        )

    def test_monorepo_config_sync_workspace_removed(self):
        """After migration, .olav/workspace/config/sync/ must NOT exist in monorepo root."""
        monorepo_sync = _ROOT / ".olav" / "workspace" / "config" / "sync"
        assert not monorepo_sync.exists(), (
            f"config/sync workspace still found at monorepo root {monorepo_sync}. "
            "NETOPS-1: config/sync must be removed from monorepo after migration"
        )

    def test_monorepo_config_learner_workspace_removed(self):
        """After migration, .olav/workspace/config/learner/ must NOT exist in monorepo root."""
        monorepo_learner = _ROOT / ".olav" / "workspace" / "config" / "learner"
        assert not monorepo_learner.exists(), (
            f"config/learner workspace still found at monorepo root {monorepo_learner}. "
            "NETOPS-1: config/learner must be removed from monorepo after migration"
        )


# ===========================================================================
# ENT-1: Independent source boundary in olav-ent/
# ===========================================================================


@requires_ent
class TestEnt1IndependentSourceBoundary:
    """olav-ent/src/olav/enterprise/ must exist as an independent source copy."""

    _ENT_SRC = _ENT_ROOT / "src" / "olav" / "enterprise"

    def test_ent_src_dir_exists(self):
        """olav-ent/src/olav/enterprise/ directory must exist."""
        assert self._ENT_SRC.is_dir(), (
            f"olav-ent/src/olav/enterprise/ not found at {self._ENT_SRC}. "
            "ENT-1: independent source directory not created"
        )

    def test_ent_src_init_exists(self):
        """olav-ent/src/olav/enterprise/__init__.py must exist."""
        init = self._ENT_SRC / "__init__.py"
        assert init.exists(), (
            f"__init__.py not found at {init}. "
            "ENT-1: enterprise package init missing in olav-ent/src/"
        )

    def test_ent_src_cli_bridge_exists(self):
        """olav-ent/src/olav/enterprise/cli_bridge.py must exist."""
        f = self._ENT_SRC / "cli_bridge.py"
        assert f.exists(), (
            f"cli_bridge.py not found at {f}. "
            "ENT-1: cli_bridge must be present in olav-ent/src/ for independent distribution"
        )

    def test_ent_src_audit_dataset_export_exists(self):
        """olav-ent/src/olav/enterprise/audit_dataset_export.py must exist."""
        f = self._ENT_SRC / "audit_dataset_export.py"
        assert f.exists(), (
            f"audit_dataset_export.py not found at {f}. "
            "ENT-1: all enterprise source files must be present in olav-ent/src/"
        )

    def test_ent_src_dataset_encryption_exists(self):
        """olav-ent/src/olav/enterprise/dataset_encryption.py must exist."""
        f = self._ENT_SRC / "dataset_encryption.py"
        assert f.exists(), (
            f"dataset_encryption.py not found at {f}. "
            "ENT-1: all enterprise source files must be present in olav-ent/src/"
        )

    def test_ent_pyproject_packages_no_dotdot(self):
        """olav-ent/pyproject.toml packages path must NOT contain '../' (path escape)."""
        pyproject = _ENT_ROOT / "pyproject.toml"
        src = pyproject.read_text(encoding="utf-8")
        # Find the packages = [...] line
        for line in src.splitlines():
            if "packages" in line and "../" in line:
                pytest.fail(
                    f"olav-ent/pyproject.toml packages path still uses '../': {line.strip()!r}. "
                    "ENT-1: packages must reference src/olav/enterprise (self-contained)"
                )

    def test_ent_pyproject_packages_references_src(self):
        """olav-ent/pyproject.toml packages must reference 'src/olav/enterprise'."""
        pyproject = _ENT_ROOT / "pyproject.toml"
        src = pyproject.read_text(encoding="utf-8")
        assert '"src/olav/enterprise"' in src or "'src/olav/enterprise'" in src, (
            "olav-ent/pyproject.toml packages must reference 'src/olav/enterprise' (not '../src/...'). "
            "ENT-1: independent source boundary requires self-contained path"
        )

    def test_ent_src_namespace_init_exists(self):
        """olav-ent/src/olav/__init__.py must exist for namespace package."""
        ns_init = _ENT_ROOT / "src" / "olav" / "__init__.py"
        assert ns_init.exists(), (
            f"Namespace init not found at {ns_init}. "
            "ENT-1: olav namespace package init required for proper Python packaging"
        )
