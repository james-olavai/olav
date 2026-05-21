"""Round 32 + dev_docs/85 migration — collector sub-agent structure.

History:
  Round 32 (ADR-0005): ops/probe → ops/collect rename.
  dev_docs/85 AGENT_ARCHITECTURE_V2: ops/collect migrated to netops/collect.

Guards (current state):
  * ``netops/collect/`` directory exists with SKILL.md, prompts/system.md,
    tools/, and config/.
  * ``execute_cli_parallel.py`` is present in tools/.
  * ``netops/collect/SKILL.md`` frontmatter declares ``name: collector``.
  * ``ops/probe/`` is gone (probe rename is permanent).
  * ADR-0005 still exists as a historical record.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"
COLLECT = WORKSPACE / "netops" / "collector"


# ── Directory structure ─────────────────────────────────────────────────────


def test_collect_directory_exists():
    assert COLLECT.is_dir(), f"netops/collect/ missing: {COLLECT}"
    # tools/ deleted in rev ~298 (@tool→scripts migration complete); prompts/ still required
    for sub in ("prompts",):
        assert (COLLECT / sub).is_dir(), f"netops/collect/{sub}/ missing"


def test_collect_has_skill_and_system_prompt():
    assert (COLLECT / "SKILL.md").is_file()
    assert (COLLECT / "prompts" / "system.md").is_file()


def test_probe_directory_removed():
    assert not (WORKSPACE / "ops" / "probe").exists(), (
        "ops/probe/ must be removed after Step D-后半 lite rename"
    )


# ── Tool ────────────────────────────────────────────────────────────────────


def test_execute_cli_parallel_present():
    # scripts-化: execute_cli_parallel moved from tools/ to scripts/
    p = COLLECT / "scripts" / "execute_cli_parallel.py"
    assert p.is_file(), f"missing tool: {p}"


# ── SKILL.md frontmatter ────────────────────────────────────────────────────


def _skill_frontmatter() -> dict:
    text = (COLLECT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "netops/collect/SKILL.md missing YAML frontmatter"
    front = text.split("---", 2)[1]
    return yaml.safe_load(front) or {}


def test_skill_md_name_is_collector():
    meta = _skill_frontmatter()
    assert meta.get("name") == "collector", (
        f"frontmatter name should be 'collector' (post-netops migration), "
        f"got {meta.get('name')!r}"
    )


def test_skill_md_has_required_tools():
    """collector SKILL.md must declare the three canonical scripts."""
    meta = _skill_frontmatter()
    # Check both tools: and scripts: fields (post-scripts-化 migration)
    tools_joined = " ".join(str(t) for t in (meta.get("tools") or []))
    for entry in (meta.get("scripts") or []):
        if isinstance(entry, dict):
            tools_joined += " " + (entry.get("name", "") or entry.get("path", ""))
        elif isinstance(entry, str):
            tools_joined += " " + entry
    for tool_name in ("execute_cli_parallel", "take_snapshot", "search_commands"):
        assert tool_name in tools_joined, (
            f"netops/collect/SKILL.md tools: list missing {tool_name!r}"
        )


def test_skill_md_has_agent_type_api():
    meta = _skill_frontmatter()
    assert meta.get("agent_type") == "api", (
        "netops/collect/SKILL.md must declare agent_type: api "
        "(pure tool-execution sub-agent, no TodoListMiddleware)"
    )


# ── ADR-0005 still exists as historical record ─────────────────────────────


def test_adr_0005_present():
    adr = REPO / "docs" / "adr" / "0005-probe-to-collect-rename-lab-stays-standalone.md"
    assert adr.is_file(), f"ADR-0005 missing at {adr}"
    text = adr.read_text(encoding="utf-8")
    assert "supersedes" in text.lower() and "ADR-0003" in text, (
        "ADR-0005 must mark itself as superseding ADR-0003 in its Status section"
    )
