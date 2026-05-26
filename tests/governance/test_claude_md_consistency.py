"""Round 20 — CLAUDE.md stays in sync with the real workspace + ARCH-22 D pin.

CLAUDE.md is project-level agent instructions: it's auto-loaded into
context on every Claude Code session. When the file references paths
that no longer exist (after Round 18 ops-lab deletion, ARCH-20 Phase 1
config/ removal, Round 16 services/ addition), agents get incorrect
background and may suggest stale commands.

This test suite keeps the doc honest.

Also pins ARCH-22 D: every ``legacy`` / ``deprecated`` reference under
``src/olav/`` must either carry an explicit ``LEGACY-{KEEP,REMOVE-v0.19,
UNCHECKED}`` tag OR be in the allowlist of files where the word is used
legitimately (Sphinx RST directive, user-facing error string, CLI help,
docstring describing legacy behavior).
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"


# ── CLAUDE.md drift guards ──────────────────────────────────────────────────


def test_claude_md_workspace_paths_exist():
    """Every ``.olav/workspace/<dir>/`` row in the Repository Structure
    table must be a live directory."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # Table rows look like:  | `.olav/workspace/<name>/` | <owner> | <status> |
    rows = re.findall(r"`(\.olav/workspace/[a-zA-Z0-9_-]+/)`", text)
    missing = [p for p in rows if not (REPO / p).is_dir()]
    assert not missing, (
        f"CLAUDE.md references workspace paths that don't exist: {missing}. "
        "Update the Repository Structure / git-whitelist tables."
    )


def test_claude_md_no_stale_ops_lab_reference():
    """Round 18 deleted ``.olav/workspace/ops-lab/``; the doc must follow."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert ".olav/workspace/ops-lab" not in text, (
        "CLAUDE.md still references the deleted ops-lab/ top-level shell."
    )


def test_claude_md_no_stale_workspace_config_reference():
    """ARCH-20 Phase 1 deleted ``.olav/workspace/config/``; doc must follow."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # Strict: we don't want the deleted path advertised in repo-structure
    # or git-whitelist sections. Allow case-insensitive match to be safe.
    bad = [line for line in text.splitlines() if ".olav/workspace/config" in line]
    assert not bad, (
        f"CLAUDE.md still references deleted .olav/workspace/config/: {bad}"
    )


def test_claude_md_no_stale_config_schemas_reference():
    """``.olav/config/schemas/`` does not exist (never materialised on disk)."""
    if (REPO / ".olav" / "config" / "schemas").exists():
        # If the directory gets re-created later, this test becomes redundant
        # rather than a regression.
        return
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert ".olav/config/schemas" not in text, (
        "CLAUDE.md references .olav/config/schemas/ but the directory is absent."
    )


def test_claude_md_mentions_services_agent():
    """Round 16 added ``services/``; CLAUDE.md must advertise it so agents
    know it's a real release artifact."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "services/" in text, (
        "CLAUDE.md no longer mentions the services/ agent added in Round 16."
    )


# ── ARCH-22 D: legacy/deprecated refs either tagged or in allowlist ─────────


# Files where the words ``legacy`` / ``deprecated`` appear in legitimate
# context — docstrings, user-facing error strings, CLI help, Sphinx RST
# deprecation directives. Any NEW occurrence outside these files or
# without an explicit LEGACY-* tag is a regression.
_LEGITIMATE_USAGE_FILES: frozenset[str] = frozenset({
    "src/olav/platform/services/registry.py",
    "src/olav/platform/services/permission_generator.py",
    "src/olav/agents/static_context_resolver.py",
    "src/olav/core/config.py",
    "src/olav/core/embedder.py",
    "src/olav/core/workspace.py",
    # Round 50: SemanticCache emits DeprecationWarning strings for ARCH-22 C5
    # kwargs; the LEGACY-KEEP-tagged param lines don't match _LEGACY_TAG on
    # the warning message lines themselves.
    "src/olav/core/memory/__init__.py",
    "src/olav/core/memory/middleware.py",
    # Round-60 installer-source sync: tool_help.py's docstring uses
    # "legacy behaviour" to describe a backward-compat fallback —
    # load-bearing wording, not tech debt. Same file in deployment has
    # LEGACY-KEEP at module top; allowlist covers the installer copy.
    # Round 64 (ARCH-23): tool_help.py moved from core/tools/ → admin/tools/.
    "src/olav/data/workspace/core/admin/tools/tool_help.py",
    "src/olav/core/memory/migrate.py",
    "src/olav/core/utils.py",
    "src/olav/cli/commands/kb.py",
    "src/olav/data/workspace/services/tools/analyze_logs.py",
    # Compatibility and migration modules where legacy wording is
    # intentional (layout fallback docs, backward-compatible aliases, etc.).
    "src/olav/agents/agent.py",
    "src/olav/server/tool_loader.py",
    "src/olav/migrate/v0_20_layout.py",
    "src/olav/core/workspace_discovery.py",
    "src/olav/core/skill_runner.py",
    "src/olav/core/llm.py",
    "src/olav/api/app.py",
    "src/olav/cli/admin.py",
    "src/olav/plugins/middleware/_mode.py",
    "src/olav/plugins/middleware/save_assertion.py",
    "src/olav/data/workspace/services/tools/manage_cron.py",
    "src/olav/data/workspace/audit/audit-runner/tools/map_engine.py",
    "src/olav/data/workspace/audit/audit-runner/scripts/map_engine.py",
    "src/olav/data/workspace/audit/audit-author/scripts/load_profile.py",
    "src/olav/data/workspace/core/tools/format_and_export.py",
    "src/olav/data/workspace/core/tools/recall_memory.py",
    "src/olav/data/workspace/core/scripts/format_and_export.py",
    "src/olav/data/workspace/core/scripts/recall_memory.py",
    "src/olav/data/workspace/core/memory_curator/scripts/commit_to_memory.py",
    "src/olav/cli/commands/skill.py",
    "src/olav/cli/commands/explain.py",
    "src/olav/core/ingest/platform_discovery.py",
    "src/olav/core/migrations/v0_22_audit_collection_source.py",
    "src/olav/core/memory/guide_kb.py",
    "src/olav/core/sim/__init__.py",
    "src/olav/core/auth/keyring_store.py",
    "src/olav/core/auth/token.py",
    "src/olav/cli/main.py",
})

_LEGACY_TAG = re.compile(r"LEGACY-(KEEP|REMOVE-v0\.19|UNCHECKED)")
_LEGACY_WORD = re.compile(r"\blegacy\b|\bLEGACY\b|\bdeprecated\b|\bDEPRECATED\b")


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if "_legacy_archived" in p.parts:
            continue
        yield p


def test_arch22_d_no_untagged_legacy_tech_debt():
    """Each legacy/deprecated occurrence must be tagged or in the allowlist."""
    offenders: list[str] = []
    for p in _iter_python_files(REPO / "src" / "olav"):
        rel = str(p.relative_to(REPO))
        text = p.read_text(encoding="utf-8")
        for m in _LEGACY_WORD.finditer(text):
            # Find the line containing the match.
            line_no = text.count("\n", 0, m.start()) + 1
            line = text.splitlines()[line_no - 1]
            # A line is OK if it carries an explicit tag…
            if _LEGACY_TAG.search(line):
                continue
            # …or the enclosing file is in the legitimate-usage allowlist.
            if rel in _LEGITIMATE_USAGE_FILES:
                continue
            offenders.append(f"{rel}:{line_no}: {line.strip()[:90]}")
    assert not offenders, (
        f"ARCH-22 D regressed: untagged legacy/deprecated tech debt ({len(offenders)}):\n"
        + "\n".join(offenders[:15])
    )
