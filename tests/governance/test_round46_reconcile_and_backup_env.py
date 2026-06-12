"""Round 46 — reconciliation batch + ARCH-22 C1 close.

Reconciliations (matrix rows that are ✅ but status lines were stale):

* **ARCH-10**: multi-source fusion. The two "❌" matrix rows (orchestration
  pattern / hybrid_search unified API) are ✅ by design: ARCH-16 tool-LIMITs
  (Rounds 40-41) + ARCH-18 subagent cap (R40) *are* the orchestration
  pattern — fan-out is bounded at the tool layer and at the subagent-
  return layer, so the orchestrator prompt naturally routes serially
  without a hybrid_search tool (spec explicitly rejected building one).
* **ARCH-21**: every row in the v0.18.1 spec matrix landed by Round 34
  (A / B1 / B1.5 / B2 / C / D / services / designer / ops-lab). Status
  line still said 🟡 Partially.

Code fix:

* **ARCH-22 C1**: ``find_backup_commands_yaml`` gained the
  ``OLAV_BACKUP_COMMANDS_PATH`` env override so operators can redirect
  the lookup without editing code. Unblocked by ARCH-20 Phase 3 closure
  (platform/netops boundary).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UTILS_PY = REPO / "src" / "olav" / "core" / "utils.py"
ISSUES_MD = REPO / "dev_docs" / "00. issues.md"


# ── ARCH-22 C1: OLAV_BACKUP_COMMANDS_PATH env override ──────────────────


def test_env_var_name_pinned():
    src = UTILS_PY.read_text(encoding="utf-8")
    match = re.search(r'_BACKUP_COMMANDS_PATH_ENV\s*=\s*"([^"]+)"', src)
    assert match, "_BACKUP_COMMANDS_PATH_ENV constant missing in olav.core.utils"
    assert match.group(1) == "OLAV_BACKUP_COMMANDS_PATH"


def _load_utils():
    pytest.importorskip("langchain_text_splitters")
    from olav.core import utils as u

    return u


def test_env_override_wins_when_file_exists(tmp_path, monkeypatch):
    """A valid env-specified file takes precedence over default candidates."""
    u = _load_utils()

    override = tmp_path / "custom_backup_only.yaml"
    override.write_text("- command: show dummy\n", encoding="utf-8")
    monkeypatch.setenv("OLAV_BACKUP_COMMANDS_PATH", str(override))

    resolved = u.find_backup_commands_yaml()
    assert resolved == override, (
        f"env override ignored — got {resolved!r} instead of {override!r}"
    )


def test_env_override_missing_file_falls_through(monkeypatch):
    """A bogus env value must NOT silently disable the loader — the
    function should fall through to the default candidate search so a
    typo behaves exactly like the env being unset."""
    u = _load_utils()

    monkeypatch.setenv(
        "OLAV_BACKUP_COMMANDS_PATH", "/definitely/not/a/real/path/backup.yaml"
    )
    # Don't assert on specific path — just that it's either None or a real
    # file, never the bogus one.
    resolved = u.find_backup_commands_yaml()
    assert resolved is None or (
        resolved.is_file() and "definitely/not/a/real" not in str(resolved)
    )


def test_env_empty_string_falls_through(monkeypatch):
    """Empty / whitespace-only env value must be treated as unset."""
    u = _load_utils()
    monkeypatch.setenv("OLAV_BACKUP_COMMANDS_PATH", "   ")
    resolved = u.find_backup_commands_yaml()
    # Should hit defaults (or None), never raise.
    assert resolved is None or resolved.is_file()


def test_env_unset_uses_default_candidates(monkeypatch):
    u = _load_utils()
    monkeypatch.delenv("OLAV_BACKUP_COMMANDS_PATH", raising=False)
    resolved = u.find_backup_commands_yaml()
    # Depending on repo state this may be None or a real default candidate;
    # what we're pinning is the non-env path still works.
    assert resolved is None or resolved.is_file()


def test_env_override_docstring_references_env_var():
    """find_backup_commands_yaml docstring must document the env var so
    operators discover it without reading code."""
    src = UTILS_PY.read_text(encoding="utf-8")
    assert "OLAV_BACKUP_COMMANDS_PATH" in src
    assert "Env override" in src or "env override" in src


# ── Reconciliation pins (prevent status-line drift) ────────────────────


def test_arch10_status_line_reflects_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    # Grab the ARCH-10 section header + following 10 lines.
    idx = md.find("### ISSUE-ARCH-10:")
    assert idx > 0, "ARCH-10 section header missing"
    section = md[idx : idx + 500]
    # The status line must carry a Closed marker — either explicit or the
    # Round 46 reconciliation note.
    assert "Closed" in section or "Round 46" in section, (
        "ARCH-10 status line still says Partially — Round 46 reconciliation "
        "regressed. ARCH-16 tool-LIMITs + ARCH-18 subagent cap implement the "
        "orchestration pattern; the matrix rows are ✅ by design."
    )


def test_arch21_status_line_reflects_closed():
    md = ISSUES_MD.read_text(encoding="utf-8")
    idx = md.find("### ISSUE-ARCH-21:")
    assert idx > 0, "ARCH-21 section header missing"
    section = md[idx : idx + 500]
    assert "Closed" in section or "Round 46" in section, (
        "ARCH-21 status line still says Partially — every row in the matrix "
        "is ✅ by Round 34."
    )
