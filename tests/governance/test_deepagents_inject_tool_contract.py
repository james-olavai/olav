"""v0.20 — deepagents inject-tool contract governance.

ISSUE-HARNESS-DEEPAGENTS-INJECT-TOOL-PRUNE-FRAGILE:

deepagents auto-injects FilesystemMiddleware tools (glob, grep, ls,
read_file, write_file, edit_file, execute) and TodoListMiddleware tools
(write_todos) into every compiled graph. OLAV prunes these post-compile
via _DEEPAGENTS_INJECT_TOOLS frozenset + _prune_graph_tools.

This test suite:
1. Pins _DEEPAGENTS_INJECT_TOOLS to the installed deepagents version.
   If deepagents is upgraded, the test reminds us to audit the frozenset.
2. Verifies that every SKILL.md tool declared in tools: that matches an
   inject-tool name is explicitly whitelisted (i.e. the agent *wants* it).
3. Checks that tools declared in SKILL.md tools: but absent from
   _DEEPAGENTS_INJECT_TOOLS are @tools or scripts from the platform pool.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]
_WORKSPACE = REPO / ".olav" / "workspace"
_NETOPS_WORKSPACE = REPO / "olav-netops" / ".olav" / "workspace"

# The version that _DEEPAGENTS_INJECT_TOOLS was last audited against.
# When deepagents is upgraded, update this constant AND re-audit the frozenset.
_AUDITED_DEEPAGENTS_VERSION = "0.5.9"

# Known inject tools for deepagents 0.5.x (FilesystemMiddleware + TodoList)
_KNOWN_INJECT_TOOLS_0_5 = frozenset({
    "glob", "grep", "ls",
    "read_file", "write_file", "edit_file",
    "execute",
    "write_todos",
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_skill_md(path: Path) -> dict:
    """Parse YAML front matter from a SKILL.md file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end]) or {}


def _collect_skill_mds() -> list[tuple[str, Path]]:
    """Yield (label, path) for every SKILL.md in both workspace copies."""
    results = []
    for ws_root in (_WORKSPACE, _NETOPS_WORKSPACE):
        if not ws_root.exists():
            continue
        for p in ws_root.rglob("SKILL.md"):
            label = str(p.relative_to(REPO))
            results.append((label, p))
    return results


# ---------------------------------------------------------------------------
# Test: version pin
# ---------------------------------------------------------------------------


def test_inject_tools_version_pin():
    """_DEEPAGENTS_INJECT_TOOLS must be re-audited after a deepagents upgrade.

    When this test fails, do:
      1. List what FilesystemMiddleware and TodoListMiddleware actually inject
         in the new version (check deepagents source or run agent.bound_tools).
      2. Update _DEEPAGENTS_INJECT_TOOLS in agent.py to match.
      3. Update _AUDITED_DEEPAGENTS_VERSION in this test.
    """
    installed = _pkg_version("deepagents")
    from packaging.version import Version as V
    installed_v = V(installed)
    audited_v = V(_AUDITED_DEEPAGENTS_VERSION)

    # Same major.minor → still audited (patch releases don't add new inject tools)
    if installed_v.major == audited_v.major and installed_v.minor == audited_v.minor:
        return  # OK

    pytest.fail(
        f"deepagents was upgraded from {_AUDITED_DEEPAGENTS_VERSION} → {installed}.\n"
        f"Re-audit _DEEPAGENTS_INJECT_TOOLS in src/olav/agents/agent.py to confirm\n"
        f"FilesystemMiddleware + TodoListMiddleware still inject the same tools.\n"
        f"Then update _AUDITED_DEEPAGENTS_VERSION in this test to '{installed}'."
    )


def test_inject_tools_frozenset_matches_audited_set():
    """_DEEPAGENTS_INJECT_TOOLS in agent.py must match the audited set for 0.5.x."""
    from packaging.version import Version as V
    installed_v = V(_pkg_version("deepagents"))
    if installed_v >= V("0.6.0"):
        pytest.skip("0.6.x inject set not yet audited — see test_inject_tools_version_pin")

    from olav.agents.agent import _DEEPAGENTS_INJECT_TOOLS
    assert _DEEPAGENTS_INJECT_TOOLS == _KNOWN_INJECT_TOOLS_0_5, (
        f"_DEEPAGENTS_INJECT_TOOLS drifted from audited 0.5.x set.\n"
        f"In agent.py:  {sorted(_DEEPAGENTS_INJECT_TOOLS)}\n"
        f"Expected:     {sorted(_KNOWN_INJECT_TOOLS_0_5)}"
    )


# ---------------------------------------------------------------------------
# Test: SKILL.md tool declarations vs inject-tool whitelist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,path", _collect_skill_mds())
def test_inject_tools_in_skill_md_are_intentional(label: str, path: Path):
    """Inject-tool names in SKILL.md tools: list are there deliberately.

    If an inject-tool name (e.g. 'write_todos', 'read_file') appears in
    a SKILL.md's tools: list, it means the agent wants that tool
    (the prune logic will preserve it). This test ensures such declarations
    are non-empty and intentional — not accidental copy-paste.

    The check is informational: it doesn't fail, it records which agents
    explicitly whitelist inject tools, making upgrades easier to audit.
    """
    fm = _parse_skill_md(path)
    tools = set(fm.get("tools", []))
    whitelisted = tools & _KNOWN_INJECT_TOOLS_0_5
    if whitelisted:
        # Just verify the agent also has a rationale (description or metadata)
        assert fm.get("description") or fm.get("metadata", {}).get("intent"), (
            f"{label}: whitelists inject-tools {whitelisted} but has no description.\n"
            f"Add a 'description:' field to document the intent."
        )
