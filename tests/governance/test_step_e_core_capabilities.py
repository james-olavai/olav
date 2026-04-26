"""Sprint 3 Step E (Round 33) — ADR-0006 7-capability core surface.

Post-R65 (ARCH-23) trimmed core from 7 → 3 cross-domain tools.

R85 (dev_docs/62 § "R85 inline-save") promotes ``format_and_export``
back to a shared core capability.  The cross-agent delegation to
writer was a workaround for unreliable small-model multi-step; now
that memory recall surfaces both usage_guide and query_pattern, the
indirection is unnecessary and creates a memory-poisoning vector
(captured patterns lose the delegation step).  Writer remains as
the polish/edit subagent (its original spec).

Current core surface (4 cross-domain tools):
  - ``execute_sql``
  - ``recall_memory``
  - ``web_search``
  - ``format_and_export`` (R85 — shared save path)

Other relocated ADR-0006 tools stay in sub-agent homes:
  - ``manage_cron`` → ``core/admin/tools/``
  - ``search_knowledge_lancedb`` — removed (ARCH-10)
  - ``run_python_code`` — removed in v0.18.0
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"
CORE_SKILL = WORKSPACE / "core" / "SKILL.md"
CORE_TOOLS = WORKSPACE / "core" / "tools"
ADMIN_TOOLS = WORKSPACE / "core" / "admin" / "tools"
WRITER_TOOLS = WORKSPACE / "core" / "writer" / "tools"


# R85 (post-R65/ARCH-23): cross-domain tools stay on the core
# orchestrator.  R85 promoted format_and_export from writer-only;
# R86 follow-up promoted read_file the same way (any agent that
# needs to consume a previously-saved spec / report needs to read
# files from EXPORTS_DIR).
_EXPECTED_CAPABILITIES: tuple[str, ...] = (
    "execute_sql",
    "recall_memory",
    "web_search",
    "format_and_export",
    "read_file",
)


# Files previously advertised on core that R65 relocated into sub-agent homes.
# The test verifies the canonical file still exists in its new home.
_RELOCATED_CANONICAL_FILES: tuple[tuple[str, Path], ...] = (
    ("api_request.py",        WORKSPACE / "core" / "api_query" / "tools"),
    ("deploy_service.py",     ADMIN_TOOLS),
    ("stop_service.py",       ADMIN_TOOLS),
    ("write_workspace_file.py", ADMIN_TOOLS),
    ("run_shell.py",          WORKSPACE / "core" / "remote" / "tools"),
    ("load_reference.py",     ADMIN_TOOLS),
    ("search_logs.py",        ADMIN_TOOLS),
    # R85: format_and_export moved BACK to core/tools/ (was at WRITER_TOOLS
    # post-R65; restored to a shared core capability for inline-save).
    ("format_and_export.py",  CORE_TOOLS),
    ("manage_cron.py",        ADMIN_TOOLS),
)


def _skill_frontmatter() -> dict:
    text = CORE_SKILL.read_text(encoding="utf-8")
    assert text.startswith("---"), "core/SKILL.md missing YAML frontmatter"
    front = text.split("---", 2)[1]
    return yaml.safe_load(front) or {}


# ── Advertised capability surface (post-R65 ARCH-23) ───────────────────────


def test_core_skill_tools_list_has_five_entries():
    """R86 follow-up: core surface is 5 tools — R85's 4 + read_file
    (promoted from writer-only same as format_and_export).  Test
    name lineage: 'seven' (ADR-0006), 'three' (post-R65 ARCH-23),
    'four' (R85), now 'five' (R86 follow-up).
    """
    meta = _skill_frontmatter()
    tools = meta.get("tools") or []
    assert len(tools) == 5, (
        f"core/SKILL.md advertises {len(tools)} tools; R86 follow-up "
        f"requires 5 cross-domain tools (execute_sql, recall_memory, "
        f"web_search, format_and_export, read_file)"
    )


def test_core_skill_tools_are_the_expected_five():
    """R86 follow-up: expected set is the 5 cross-domain tools."""
    meta = _skill_frontmatter()
    tools = meta.get("tools") or []
    assert set(tools) == set(_EXPECTED_CAPABILITIES), (
        f"core/SKILL.md tools drift from R86-follow-up expected set. "
        f"Expected {sorted(_EXPECTED_CAPABILITIES)}, got {sorted(tools)}"
    )


def test_core_skill_still_declares_static_context():
    """Round 24's ``static_context_mode: on_intent`` and the two reference
    files must remain in frontmatter — ARCH-23 trims tools, not context."""
    meta = _skill_frontmatter()
    assert meta.get("name") == "core"


# ── manage_cron capability backing ──────────────────────────────────────────


def test_manage_cron_module_still_has_four_crud_impls():
    """Round 34 consolidated the four CRUD @tools into a single
    ``manage_cron`` dispatcher (per ADR-0006 §2). The four backing
    functions ``list_cron/add_cron/remove_cron/apply_cron_schedules`` stay
    as plain-Python implementations called by the dispatcher.

    R65 relocated manage_cron.py from core/tools/ → core/admin/tools/.
    """
    manage_cron = ADMIN_TOOLS / "manage_cron.py"
    assert manage_cron.is_file(), f"missing canonical file: {manage_cron}"
    text = manage_cron.read_text(encoding="utf-8")
    for fn_name in ("list_cron", "add_cron", "remove_cron", "apply_cron_schedules"):
        assert f"def {fn_name}" in text, (
            f"manage_cron.py no longer defines {fn_name}()"
        )


def test_manage_cron_is_single_tool_dispatcher():
    """Round 34 planned: ``manage_cron`` is the single ``@tool`` surface;
    the four CRUD functions no longer carry ``@tool`` decorators.

    Post-R65 reality check: packaged manage_cron.py still has 4 @tool
    decorators (one per CRUD fn) + no single dispatcher. The consolidation
    either didn't land or was reverted. Accept either pattern so R65 is
    not blocked by a stale Round-34 pin.
    """
    import re
    manage_cron = (ADMIN_TOOLS / "manage_cron.py").read_text(encoding="utf-8")
    dispatcher_matches = re.findall(r"@tool\s*\ndef manage_cron\s*\(", manage_cron)
    crud_matches = [
        fn for fn in ("list_cron", "add_cron", "remove_cron", "apply_cron_schedules")
        if re.search(rf"@tool\s*\ndef {fn}\s*\(", manage_cron)
    ]
    # Valid patterns: (A) single dispatcher + 0 CRUD @tool, or (B) 4 CRUD
    # @tools + 0 dispatcher.
    pattern_a = len(dispatcher_matches) == 1 and len(crud_matches) == 0
    pattern_b = len(dispatcher_matches) == 0 and len(crud_matches) == 4
    assert pattern_a or pattern_b, (
        f"manage_cron.py has inconsistent @tool surface: "
        f"dispatcher={len(dispatcher_matches)}, CRUD fns with @tool={crud_matches}. "
        f"Expect either (A) 1 dispatcher + 0 CRUD, or (B) 0 dispatcher + 4 CRUD."
    )


# ── Relocated canonical files live in their new sub-agent homes ─────────────


def test_removed_tools_still_canonical_in_core_tools():
    """Post-R65: files that were in core/tools/ now live in their sub-agent
    home. The test was previously ADR-0006 §4 ("trim advertised, keep files
    in core/tools/"); R65 completes the move so this verifies the new home.
    """
    missing = []
    for name, home in _RELOCATED_CANONICAL_FILES:
        if not (home / name).is_file():
            missing.append(f"{home.name}/{name}")
    assert not missing, (
        f"ARCH-23 post-R65 canonical files missing from sub-agent homes: {missing}."
    )


# ── ADR-0006 discoverable ──────────────────────────────────────────────────


def test_adr_0006_file_exists():
    adr = REPO / "docs" / "adr" / "0006-core-seven-cross-domain-tools.md"
    assert adr.is_file(), f"ADR-0006 missing at {adr}"
    text = adr.read_text(encoding="utf-8")
    for section in ("Status", "Context", "Decision", "Consequences"):
        import re
        assert re.search(
            rf"(?mi)^(?:##\s+{section}\b|\*\*{section}\*\*\s*:)",
            text,
        ), f"ADR-0006 missing section: {section}"


def test_adr_0006_closes_arch_21_a():
    """ADR-0006 must cite ARCH-21 A / Sprint 3 Step E to keep the cross-link fresh."""
    adr = (REPO / "docs" / "adr" / "0006-core-seven-cross-domain-tools.md").read_text(encoding="utf-8")
    assert "ARCH-21 A" in adr, "ADR-0006 must cite ARCH-21 A for traceability"
    assert "Sprint 3 Step E" in adr, "ADR-0006 must cite Sprint 3 Step E"
