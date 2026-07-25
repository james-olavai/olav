"""Public GitHub mirror must not leak enterprise (olav-presales) content.

scripts/publish_github_mirrors.py strips the proprietary enterprise units
(olav-ent/, olav-presales/, olav_kb/presales/) from the public mirror's whole
history. But presales tests that live under the SHARED root tests/ (not
olav-presales/tests/) are only stripped by their exact paths in
``_ENTERPRISE_UNIT_PATHS`` — so a NEW presales test added under tests/ and not
listed there would leak to the public mirror (and, if it imports olav_presales,
ImportError there — the package is gone). This gate fails the internal build
until such a file is added to the strip list (2026-07-26).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MIRROR_SCRIPT = _REPO / "scripts" / "publish_github_mirrors.py"
_IMPORTS_PRESALES = re.compile(r"^\s*(?:from|import)\s+olav_presales\b", re.MULTILINE)


def _strip_paths() -> set[str]:
    """The literal ``_ENTERPRISE_UNIT_PATHS`` list, read via AST (no execution —
    the module's top-level ``from workspace_drift import …`` needs scripts/ on the
    path, and importing it just to read a constant is fragile)."""
    tree = ast.parse(_MIRROR_SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_ENTERPRISE_UNIT_PATHS"
                for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError("_ENTERPRISE_UNIT_PATHS not found in publish_github_mirrors.py")


def _covered(rel: str, strip: set[str]) -> bool:
    return rel in strip or any(rel.startswith(p) for p in strip)


def _tracked(under: str) -> list[str]:
    """Git-tracked paths under ``under`` — exactly the files the mirror carries
    (so .pyc / __pycache__ and other untracked cruft are excluded)."""
    out = subprocess.run(["git", "-C", str(_REPO), "ls-files", under],
                         capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if ln]


def test_presales_files_under_root_tests_are_stripped_from_public_mirror():
    strip = _strip_paths()

    # (a) every presales-NAMED tracked file under the shared root tests/
    named = {f for f in _tracked("tests") if "presales" in Path(f).name}
    # (b) every tracked tests/ .py that actually imports olav_presales (would
    #     ImportError in the public mirror where the package is stripped)
    importers = {
        f for f in _tracked("tests") if f.endswith(".py")
        and _IMPORTS_PRESALES.search((_REPO / f).read_text(encoding="utf-8", errors="ignore"))
    }

    leaks = sorted(f for f in (named | importers) if not _covered(f, strip))
    assert not leaks, (
        "presales content under root tests/ is NOT stripped from the public GitHub "
        "mirror — add these exact paths to _ENTERPRISE_UNIT_PATHS in "
        f"scripts/publish_github_mirrors.py (literal paths, so the leak-verify covers "
        f"them): {leaks}")
