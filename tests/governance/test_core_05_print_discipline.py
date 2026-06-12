"""CORE-05 Option B — print-in-core discipline pin (Round 30).

Decision (Round 30, issues.md rev 167): ``print()`` calls in
``src/olav/core/`` are retained **only** in CLI user-facing handler code.
Every such call must be in the allowlist below; any new ``print`` in
core code forces the author to choose:

* (a) Extend the allowlist with CORE-05 rationale, OR
* (b) Use ``logger.info/error`` instead.

The two allowed files are:

* ``api_registry.py`` — 11 prints across ``_cli_load``, ``_cli_list``,
  ``_cli_find``, ``_cli_fields``, ``_cli_verify``, and ``main`` (all
  module-level CLI handlers dispatched from ``python -m olav.core.api_registry``)
* ``version.py`` — 5 prints in the ``if __name__ == "__main__":`` block
  that emits the version banner + checksums

Migrating either to ``logger`` would route user-facing CLI output into log
files and break the CLI UX. This is the formalised Option B from the
Round 27 reconciliation (vs Option A which would build ``src/olav/cli/
printers.py`` — not worth the infrastructure for 16 CLI-only prints).
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CORE_DIR = REPO / "src" / "olav" / "core"


# File path (relative to repo root) → max allowed `print(` occurrences.
# Each entry is a deliberate exemption documented in the module header below.
ALLOWED_PRINTS: dict[str, int] = {
    "src/olav/core/api_registry.py": 11,  # _cli_* handlers + main usage
    "src/olav/core/version.py": 5,        # __main__ version banner
    # Standalone CLI entry points under core/ used by operators as scripts.
    "src/olav/core/memory/pattern_extractor.py": 1,  # _cli_main JSON output
    "src/olav/core/curator/discover_view_schemas.py": 1,  # __main__ JSON output
    "src/olav/core/curator/fuzzy_map_schema.py": 2,  # __main__ success/error JSON
}


_PRINT_CALL = re.compile(r"^\s*print\s*\(", re.MULTILINE)


def _count_prints(path: Path) -> int:
    """Count top-level ``print(`` calls. Includes lines preceded by whitespace
    (indented prints inside functions), matches start-of-statement only."""
    text = path.read_text(encoding="utf-8")
    return len(_PRINT_CALL.findall(text))


def _iter_core_py() -> list[Path]:
    return [
        p
        for p in CORE_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def test_core_05_no_untracked_prints():
    """Every ``print(`` in ``src/olav/core/`` must be accounted for.

    Regression: a contributor adding print() in, say, ``router.py`` without
    updating the allowlist fails here with a specific file+count message.
    """
    offenders: list[str] = []
    for py in _iter_core_py():
        rel = str(py.relative_to(REPO))
        count = _count_prints(py)
        allowed = ALLOWED_PRINTS.get(rel, 0)
        if count > allowed:
            offenders.append(f"{rel}: {count} print() calls (allowed {allowed})")
    assert not offenders, (
        "CORE-05: new print() calls appeared in src/olav/core/. Either\n"
        "  (a) migrate to logger.info/error (preferred for non-CLI code), OR\n"
        "  (b) extend ALLOWED_PRINTS with CORE-05 justification.\n"
        "Offenders:\n" + "\n".join(offenders)
    )


def test_core_05_allowlist_files_still_exist():
    """An allowlist entry that no longer matches a real file is dead policy."""
    missing = [rel for rel in ALLOWED_PRINTS if not (REPO / rel).is_file()]
    assert not missing, (
        f"CORE-05 allowlist references non-existent files: {missing}. "
        "Remove the allowlist entry or restore the file."
    )


def test_core_05_allowlist_counts_are_tight():
    """Allowlist counts must match reality.

    If a file's print count drops below its allowlist value, tighten the
    entry — keeps the ceiling honest instead of silently growing headroom.
    """
    loose: list[str] = []
    for rel, allowed in ALLOWED_PRINTS.items():
        actual = _count_prints(REPO / rel)
        if actual < allowed:
            loose.append(
                f"{rel}: allowlist permits {allowed}, actual is only {actual}. "
                "Tighten the entry."
            )
    assert not loose, "CORE-05 allowlist drift:\n" + "\n".join(loose)


def test_core_05_api_registry_prints_all_in_cli_handlers():
    """Narrow the trust surface: every ``api_registry.py`` print must sit
    inside a function whose name begins with ``_cli_`` or is ``main``.

    This stops someone from ab-using the allowlist quota on a random
    helper by funneling library-level output through print.
    """
    path = REPO / "src" / "olav" / "core" / "api_registry.py"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    def_pattern = re.compile(r"^\s*(async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    current_func: str | None = None
    offenders: list[str] = []

    for line_no, line in enumerate(lines, start=1):
        m = def_pattern.match(line)
        if m:
            current_func = m.group(2)
            continue
        if _PRINT_CALL.match(line):
            if not (current_func and (current_func.startswith("_cli_") or current_func == "main")):
                offenders.append(
                    f"api_registry.py:{line_no} print() inside {current_func!r} "
                    "is NOT a CLI handler — either move or use logger"
                )

    assert not offenders, (
        "CORE-05: api_registry.py prints must live in _cli_* or main().\n"
        + "\n".join(offenders)
    )
