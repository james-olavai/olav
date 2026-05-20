"""Regression pin: tools modified across Rounds 24-60 must live in the
installer source (``src/olav/data/workspace/...``) in addition to the
deployment tree (``.olav/workspace/...``).

Background (discovered during T2 execution, post-Round-60):

* Deployment copies live at ``.olav/workspace/core/tools/`` or subagent
  ``tools/`` folders (post-R64 ARCH-23 distribution).
* ``olav init`` bootstraps a fresh install from
  ``src/olav/data/workspace/core/`` mirroring the same layout.
* If a tool is modified in deployment but never copied into the
  installer source, a wheel-install user gets the old (or entirely
  missing) file — T2-29 caught exactly this for ``describe_table.py``.

R64 (ARCH-23 closure): core orchestrator trimmed to 3 tools; others
relocated into ``{admin, db_query, writer, api_query, remote}/tools/``
sub-agent folders. This pin now tracks the post-R64 canonical location
per tool; deployment may still carry legacy monolithic copies (being
dismantled in a later round) so we match against the installer layout
as the source of truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY_CORE = REPO / ".olav" / "workspace" / "core"
INSTALLER_CORE = REPO / "src" / "olav" / "data" / "workspace" / "core"

# Post-R64 layout: (tool_filename, subagent-folder-or-"tools")
# Anything not in ``tools/`` is under ``<subagent>/tools/``.
_PLATFORM_CORE_TOOLS_LAYOUT = [
    # describe_table removed: now in core/db_query/scripts/ (scripts migration).
    ("execute_sql.py",        "tools"),     # R41 (ARCH-16 tier-aware rows)
    # get_static_context, load_reference, tool_help removed: core/admin dissolved;
    # files now live in admin/editor/scripts/ which is outside the core installer tree.
    ("recall_memory.py",      "tools"),     # R40 (ARCH-16 tier default)
    ("search_logs.py",        "tools"),     # R100/S5 — promoted from admin/ to shared core/tools/
    ("web_search.py",         "tools"),     # R43 (docstring search_knowledge → recall_memory)
]

_PLATFORM_CORE_TOOLS = [t for t, _ in _PLATFORM_CORE_TOOLS_LAYOUT]


def _installer_path(tool: str) -> Path:
    folder = dict(_PLATFORM_CORE_TOOLS_LAYOUT)[tool]
    if folder == "tools":
        return INSTALLER_CORE / "tools" / tool
    return INSTALLER_CORE / folder / "tools" / tool


def _deploy_path(tool: str) -> Path:
    # Deployment may still carry the monolithic copy in core/tools/, the
    # canonical sub-agent copy, or (common) both during the transition.
    folder = dict(_PLATFORM_CORE_TOOLS_LAYOUT)[tool]
    sub = DEPLOY_CORE / folder / "tools" / tool if folder != "tools" else None
    flat = DEPLOY_CORE / "tools" / tool
    if sub and sub.exists():
        return sub
    return flat

# References map used by load_reference.py — all must ship in installer.
_PLATFORM_CORE_REFERENCES = [
    "REQUIRED_INFO_CHECK.md",
    "SCHEMA_REFERENCE.md",
    "SKILL_DEVELOPMENT.md",
    "viz_drawio.md",
    "viz_infographic.md",
    "viz_mermaid.md",
    "viz_plantuml_network.md",
]


@pytest.mark.parametrize("tool", _PLATFORM_CORE_TOOLS)
def test_platform_tool_in_installer_source(tool: str):
    deploy = _deploy_path(tool)
    installer = _installer_path(tool)

    # Skip symlinks — those come from extension packages (olav-netops).
    if deploy.is_symlink():
        pytest.skip(f"{tool} is a symlink in deployment (extension-delivered)")

    assert deploy.is_file(), f"deployment missing platform tool: {deploy}"
    assert installer.is_file(), (
        f"installer source missing {tool} — a wheel install would lack "
        f"this tool and any T1/T2 helper that imports it would fail "
        f"(T2-29 caught exactly this for describe_table.py). "
        f"Post-R64 canonical path: {installer}. "
        f"Fix: copy {deploy} → {installer}."
    )


@pytest.mark.parametrize("tool", _PLATFORM_CORE_TOOLS)
def test_platform_tool_content_matches_deployment(tool: str):
    """Deployment and installer source should match byte-for-byte. Drift
    means the next ``olav init`` ships a different version than what the
    dev env is running against."""
    deploy = _deploy_path(tool)
    installer = _installer_path(tool)

    if deploy.is_symlink():
        pytest.skip(f"{tool} is a symlink in deployment (extension-delivered)")
    if not installer.is_file():
        pytest.skip(f"{tool} installer-source missing (covered by other test)")

    deploy_bytes = deploy.read_bytes()
    installer_bytes = installer.read_bytes()
    if deploy_bytes != installer_bytes:
        # Produce a short diff summary rather than the full bytes.
        pytest.fail(
            f"{tool} content drift — deployment ({deploy.stat().st_size} B, "
            f"{deploy}) vs installer ({installer.stat().st_size} B, "
            f"{installer}). Copy deployment → installer to resync, or "
            f"consciously accept the divergence and document it here."
        )


@pytest.mark.parametrize("ref", _PLATFORM_CORE_REFERENCES)
def test_reference_doc_in_installer_source(ref: str):
    installer = REPO / "src" / "olav" / "data" / "workspace" / "core" / "references" / ref
    assert installer.is_file(), (
        f"reference {ref} missing from installer source. "
        f"load_reference.py's _AVAILABLE map lists it — a wheel-installed "
        f"caller would get 'Reference file not found on disk'."
    )
