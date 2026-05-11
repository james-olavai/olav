"""Sprint 3 Step B — audit/designer merged into audit/auditor (round 17).

NOTE (rev 259, 2026-05-11): Step B's invariants are SUPERSEDED by the
Run/Author split experiment. ``audit/auditor/`` has been moved to
``_legacy_auditor/`` and replaced by two sub-agents: ``audit/runner/``
(Run mode) and ``audit/author/`` (Profile Authoring mode). The Step B
milestone (designer → auditor merge) is still true historically, but
the on-disk layout it checked no longer exists.

Tests in this file are marked ``xfail`` until the experiment outcome is
known. If Run/Author split is kept, delete this file or replace it with
``test_run_author_split.py`` that pins the new 3-sub-agent layout. If
the experiment is rolled back, the xfail comes off automatically.

Per v0.18.1 spec, the v0.18.0 `audit-designer` sub-agent is folded into
`audit-auditor`. The six designer tools move to `audit/auditor/tools/`;
the designer directory is removed; callers that referenced
`audit/designer/tools` or `--agent audit-designer` are updated.

Guards:

* ``audit/designer/`` must not exist.
* All six designer tools are now real files under ``audit/auditor/tools/``.
* ``audit/auditor/SKILL.md`` advertises a Profile Authoring section and
  the six tool names.
* ``core/tools/tool_help.py`` ``_TOOL_ROOTS`` no longer lists the
  designer path.
* ``audit/auditor/tools/map_engine.py`` error hint no longer references
  ``audit-designer``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(
    reason=(
        "rev 259 Run/Author split: audit/auditor/ moved to _legacy_auditor/; "
        "Step B (Round 17) milestone is historically true but the layout "
        "it asserts is gone. Delete this file or replace with a new layout "
        "test once the experiment outcome is decided."
    ),
    strict=False,
)


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"

_DESIGNER_TOOLS = (
    "analyze_thresholds.py",
    "append_jobs.py",
    "database_introspection.py",
    "read_profile.py",
    "save_profile.py",
    "test_map_query.py",
)


def test_designer_directory_removed():
    assert not (WORKSPACE / "audit" / "designer").exists(), (
        "audit/designer/ must be deleted after Step B merge into auditor"
    )


def test_designer_tools_moved_to_auditor():
    auditor_tools = WORKSPACE / "audit" / "auditor" / "tools"
    missing = [t for t in _DESIGNER_TOOLS if not (auditor_tools / t).is_file()]
    assert not missing, (
        f"designer tool(s) missing from auditor/tools/: {missing}"
    )


def test_moved_tools_are_real_files_not_symlinks():
    auditor_tools = WORKSPACE / "audit" / "auditor" / "tools"
    for name in _DESIGNER_TOOLS:
        p = auditor_tools / name
        assert p.is_file() and not p.is_symlink(), (
            f"{p} should be a real file (Step B moves content, not links)"
        )


def test_auditor_skill_md_advertises_profile_authoring():
    text = (WORKSPACE / "audit" / "auditor" / "SKILL.md").read_text(encoding="utf-8")
    assert "Profile Authoring" in text, (
        "auditor/SKILL.md must describe the Profile Authoring mode "
        "inherited from audit-designer"
    )
    for tool_name in _DESIGNER_TOOLS:
        stem = tool_name[:-3]
        assert stem in text, f"auditor/SKILL.md missing merged tool {stem!r}"


def test_auditor_system_prompt_describes_authoring_mode():
    text = (WORKSPACE / "audit" / "auditor" / "prompts" / "system.md").read_text(
        encoding="utf-8"
    )
    assert "Profile Authoring" in text, (
        "auditor/prompts/system.md must gain a Profile Authoring Mode section"
    )
    # Spot-check that the three authoring modes survived the merge.
    for marker in ("Intelligent Threshold", "Dynamic Threshold Tuning", "Appending Check Items"):
        assert marker in text, f"auditor prompt missing authoring mode {marker!r}"


def test_tool_help_tool_roots_excludes_designer():
    # Post-R65 (ARCH-23): tool_help.py relocated from core/tools/ to
    # core/admin/tools/.
    text = (WORKSPACE / "core" / "admin" / "tools" / "tool_help.py").read_text(encoding="utf-8")
    assert "audit/designer" not in text and "audit\" / \"designer\"" not in text, (
        "tool_help._TOOL_ROOTS must no longer reference audit/designer/tools"
    )


def test_map_engine_error_points_to_auditor_not_designer():
    text = (
        WORKSPACE / "audit" / "auditor" / "tools" / "map_engine.py"
    ).read_text(encoding="utf-8")
    assert "audit-designer" not in text, (
        "map_engine.py error hint must no longer suggest --agent audit-designer"
    )
    assert "audit-auditor" in text, (
        "map_engine.py error hint should redirect users to --agent audit-auditor"
    )
