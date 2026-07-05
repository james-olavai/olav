"""NETOPS-02: core and netops code use timezone-aware datetime calls.

``datetime.utcnow()`` is deprecated in Python 3.12 and ``datetime.now()``
without a ``tz=`` argument returns a naive local timestamp. Either path
corrupts snapshot_id / audit timestamps across deployments. Code paths
must go through :func:`olav.core.utils.utc_now` or pass ``tz=UTC``
explicitly.

Scope: hot-path source under ``src/olav/core/``, ``src/olav/services/``,
``olav-netops/src/`` and the active netops_init pipeline. Vendored CLI
tools that only use datetime for local filename timestamps are excluded.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR

REPO = Path(__file__).resolve().parents[2]

SCAN_ROOTS = [
    REPO / "src" / "olav" / "core",
    REPO / "src" / "olav" / "services",
    REPO / "olav-netops" / "src",
    NETOPS_INIT_DIR,
]

# Files exempt from the strict rule. Keep the list short and justified.
EXEMPT = {
    # utils.py defines the replacement helper and intentionally mentions
    # the deprecated names in its docstring.
    REPO / "src" / "olav" / "core" / "utils.py",
}

NAIVE_NOW = re.compile(r"\bdatetime\.now\s*\(\s*\)")
UTCNOW = re.compile(r"\bdatetime\.utcnow\s*\(")


def _offending_lines(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        # Ignore comments/docstrings — allow documentation to reference
        # the deprecated names without triggering.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if NAIVE_NOW.search(line) or UTCNOW.search(line):
            hits.append((i, line.strip()))
    return hits


def test_no_naive_datetime_in_hot_paths():
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if py in EXEMPT:
                continue
            if "__pycache__" in py.parts:
                continue
            # data/skillpack is a byte-exact wheel bundle of the workspace
            # tree (0.22.0, dev_docs/99 §7.6 follow-up); its canonical
            # copies live under .olav/workspace/ (outside SCAN_ROOTS) and
            # the workspace drift gate keeps the mirror identical —
            # scanning it would only double-report the same content.
            if "skillpack" in py.parts:
                continue
            for lineno, snippet in _offending_lines(py):
                offenders.append(f"{py.relative_to(REPO)}:{lineno}: {snippet}")

    assert not offenders, (
        "Found naive datetime.now()/utcnow() in hot-path code — use "
        "olav.core.utils.utc_now() or datetime.now(UTC)/datetime.now(tz=UTC):\n"
        + "\n".join(offenders)
    )
