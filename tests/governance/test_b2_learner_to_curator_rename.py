"""ARCH-21 B.2 — audit/learner → audit/curator rename (Round 34).

Per [ADR-0003](../../docs/adr/0003-audit-ops-sub-agent-parity.md) §B.2 and
executed in Round 34 (following the same playbook as probe → collect in
Round 32). The rename reflects the sub-agent's broader role (schema + trace
+ pattern curation), not just learning.

Guards:

* ``audit/curator/`` directory exists with SKILL.md, tools/, prompts/.
* SKILL.md frontmatter has ``name: curator`` and cites ``learner`` as
  replaced.
* All 5 tool files are present under ``audit/curator/tools/``.
* ``audit/learner/`` is gone.
* ``audit/AGENT.md`` subagents list references ``./curator/SKILL.md`` and
  does NOT reference ``./learner/SKILL.md``.
* ``core/tools/tool_help.py`` ``_TOOL_ROOTS`` was updated to point at
  ``audit/curator/tools``.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"
CURATOR = WORKSPACE / "audit" / "curator"


_EXPECTED_TOOLS: tuple[str, ...] = (
    "fuzzy_map_schema.py",
    "scaffold_domain_agent.py",
)


def test_curator_directory_exists():
    assert CURATOR.is_dir(), f"audit/curator/ missing: {CURATOR}"
    for sub in ("scripts", "prompts"):
        assert (CURATOR / sub).is_dir(), f"audit/curator/{sub}/ missing"


def test_learner_directory_removed():
    assert not (WORKSPACE / "audit" / "learner").exists(), (
        "audit/learner/ must be removed after Round 34 rename"
    )


def test_curator_skill_md_name_and_replaces():
    text = (CURATOR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "audit/curator/SKILL.md missing YAML frontmatter"
    front = text.split("---", 2)[1]
    meta = yaml.safe_load(front) or {}
    assert meta.get("name") == "curator", (
        f"frontmatter name should be 'curator', got {meta.get('name')!r}"
    )
    replaces = meta.get("metadata", {}).get("replaces", [])
    replaces_joined = " | ".join(str(x) for x in replaces)
    assert "learner" in replaces_joined, (
        f"metadata.replaces must cite learner as predecessor, got {replaces!r}"
    )


def test_curator_has_expected_direct_wrappers():
    # Post-scripts-migration: tools live in scripts/ not tools/.
    missing = [t for t in _EXPECTED_TOOLS if not (CURATOR / "scripts" / t).is_file()]
    assert not missing, (
        f"audit/curator/scripts/ missing: {missing}"
    )


def test_curator_skill_mentions_script_bridge_for_remaining_ops():
    text = (CURATOR / "SKILL.md").read_text(encoding="utf-8")
    # Post-scripts-migration: execute_skill_script bridge replaced by scripts: YAML field.
    # Verify scripts are listed in the SKILL.md instead.
    for script_name in (
        "discover_view_schemas.py",
        "sync_schema_reference.py",
        "trace_learner.py",
    ):
        assert script_name in text, (
            f"curator SKILL should document bridged script: {script_name}"
        )


def test_audit_agent_md_references_curator_not_learner():
    text = (WORKSPACE / "audit" / "AGENT.md").read_text(encoding="utf-8")
    assert "./curator/SKILL.md" in text, (
        "audit/AGENT.md must reference ./curator/SKILL.md in subagents"
    )
    assert "./learner/SKILL.md" not in text, (
        "audit/AGENT.md must no longer reference ./learner/SKILL.md"
    )


def test_tool_help_tool_roots_uses_curator_path():
    # v0.11.0: tool_help.py moved from core/admin/tools/ to admin/developer/tools/.
    # post-R-AGENT-HIERARCHY: admin/developer/ split; tool_help.py now in admin/editor/tools/.
    text = (WORKSPACE / "admin" / "editor" / "scripts" / "tool_help.py").read_text(encoding="utf-8")
    assert "audit/curator/tools" in text or "\"curator\" / \"tools\"" in text or \
        'audit" / "curator"' in text, (
        "admin/editor/tools/tool_help.py _TOOL_ROOTS must point at audit/curator/tools "
        "(not audit/learner/tools)"
    )
    assert "learner" not in text, (
        "admin/editor/tools/tool_help.py must no longer reference audit/learner"
    )
