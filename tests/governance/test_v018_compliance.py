"""Workspace top-level agent compliance tests.

Post-dev_docs/85 (ops→netops rename, services→admin rename):

* ``admin/``          — platform self-management (formerly services/)
* ``audit/``          — audit orchestrator (platform)
* ``core/``           — platform agent (unified entry point)
* ``devops/``         — DevOps automation scripts agent
* ``netops/``         — network operations (domain extension); learner/ sub-agent handles parser learning
* ``ops/``            — transitional (contains only netops_init)
* ``PLATFORM.md``     — auto-generated registry

Deleted in ARCH-20 Phase 1 (v0.17 residuals):
  audit-auditor, audit-designer, config, gitea, infra

Renamed in dev_docs/85 (v0.11.0):
  services → admin
  ops (main) → netops
  devops re-added as live top-level agent
"""

from __future__ import annotations

from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2] / ".olav" / "workspace"


# Directories that must not exist (deleted in ARCH-20 Phase 1 + dev_docs/85)
_REMOVED_AGENTS = frozenset(
    {
        "audit-auditor",
        "audit-designer",
        "config",           # → core/admin/ (ARCH-20 Phase 1)
        "gitea",
        "infra",
        # NOTE: "services" removed from removed-set — ADR-0014 reclaimed the
        # name for the platform service-lifecycle agent. The old self-mgmt
        # services became `admin` (dev_docs/85); admin present = old one gone.
        "command_learner",  # → netops/learner/ (2026-05-20)
    }
)

# Current canonical top-level set (post dev_docs/85 ops→netops rename;
# ADR-0014 added platform `services`).
_EXPECTED_TOP_LEVEL_DIRS = frozenset(
    {
        "admin",           # formerly the self-mgmt services/ (dev_docs/85)
        "audit",
        "core",
        "devops",
        "netops",          # formerly ops/ (main); learner/ is a netops sub-agent
        "services",        # ADR-0014: platform service-lifecycle agent (NEW)
        "ops",             # transitional — contains only netops_init
    }
)


_TRANSITIONAL_DIRS = frozenset({"ops"})  # transitional: ops/ contains only netops_init


def _top_level_dirs() -> set[str]:
    return {p.name for p in WORKSPACE.iterdir() if p.is_dir()}


def test_removed_v017_agents_absent():
    current = _top_level_dirs()
    leaked = _REMOVED_AGENTS & current
    assert not leaked, (
        f"v0.17 residual agent(s) reintroduced under .olav/workspace/: {sorted(leaked)}. "
        "These were deleted in ARCH-20 Phase 1 and must stay gone."
    )


def test_top_level_matches_v018_target():
    current = _top_level_dirs()
    unexpected = current - _EXPECTED_TOP_LEVEL_DIRS
    missing = _EXPECTED_TOP_LEVEL_DIRS - current
    assert not unexpected, (
        f"Unexpected top-level workspace dirs: {sorted(unexpected)} "
        f"(expected: {sorted(_EXPECTED_TOP_LEVEL_DIRS)})"
    )
    assert not missing, (
        f"Missing expected top-level workspace dirs: {sorted(missing)}"
    )


def test_platform_md_agent_list_matches():
    """PLATFORM.md's `agents:` frontmatter must list the registered agent dirs.

    Transitional dirs (ops/) are excluded — they exist on disk but are not
    registered as top-level agents in PLATFORM.md.
    """
    import yaml

    platform_md = WORKSPACE / "olav.md"
    assert platform_md.exists(), f"olav.md missing at {platform_md}"

    text = platform_md.read_text(encoding="utf-8")
    assert text.startswith("---"), "olav.md lacks YAML frontmatter"
    front = text.split("---", 2)[1]
    meta = yaml.safe_load(front) or {}

    agents_listed = set(meta.get("agents", []))
    registered_dirs = _top_level_dirs() - _TRANSITIONAL_DIRS
    assert agents_listed == registered_dirs, (
        f"olav.md agents list ({sorted(agents_listed)}) out of sync with "
        f"workspace dirs ({sorted(registered_dirs)}). Run `olav refresh`."
    )
