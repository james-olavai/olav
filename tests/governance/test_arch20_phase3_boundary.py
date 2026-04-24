"""ARCH-20 Phase 3 — topology_engine + auto_learn live in olav_netops now.

Round 13 hard-cut the modules out of platform core; there's no
back-compat shim under ``src/olav/core/`` any more. This suite guards
against accidental re-introduction and against breaking the canonical
netops location.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_topology_engine_moved_to_olav_netops():
    # Canonical location must have the file.
    canonical = (
        REPO / "olav-netops" / "src" / "olav_netops" / "core" / "topology_engine.py"
    )
    assert canonical.exists(), f"canonical topology_engine missing: {canonical}"

    # Old platform location must be gone — hard-cut, no shim.
    legacy = REPO / "src" / "olav" / "core" / "topology_engine.py"
    assert not legacy.exists(), (
        f"{legacy} re-appeared — ARCH-20 Phase 3 regression. "
        "Import via olav_netops.core.topology_engine instead."
    )


def test_auto_learn_fully_deleted():
    """v0.21.0: ``auto_learn.py`` was completely removed.

    ARCH-20 Phase 3 moved it to ``olav-netops`` with ``auto_learn_failed_parses``
    marked DEPRECATED; Round 72 (ISSUE-LEARNER-BATCH-CUT) decided batch learning
    should not live in the pipeline at all.  v0.21.0 finishes the job: the whole
    module is gone and ``netops_init`` reports parse-coverage instead.  Surviving
    classifier helpers (``should_learn`` / ``_estimate_data_rows``) moved to
    ``olav_netops.core.parse_helpers``.
    """
    deleted_paths = [
        REPO / "olav-netops" / "src" / "olav_netops" / "core" / "auto_learn.py",
        REPO / "src" / "olav" / "core" / "auto_learn.py",
    ]
    for p in deleted_paths:
        assert not p.exists(), (
            f"{p} re-appeared — v0.21.0 batch-learner cut must stay dead."
        )

    # The replacement home for the surviving helpers must exist.
    helpers = (
        REPO / "olav-netops" / "src" / "olav_netops" / "core" / "parse_helpers.py"
    )
    assert helpers.exists(), (
        f"{helpers} missing — parser_learner + command_learner still import "
        "should_learn / _estimate_data_rows from this module."
    )


def test_canonical_imports_work():
    # topology_engine still resolves from olav_netops.  The parse classifier
    # helpers moved out of the deleted auto_learn module into parse_helpers.
    from olav_netops.core.topology_engine import extract_lldp_topology  # noqa: F401
    from olav_netops.core.parse_helpers import should_learn, _estimate_data_rows  # noqa: F401


def test_legacy_imports_are_broken():
    """Legacy ``olav.core.topology_engine`` must now raise ImportError."""
    import importlib
    import sys

    # Clear any stale pyc cache first.
    sys.modules.pop("olav.core.topology_engine", None)
    sys.modules.pop("olav.core.auto_learn", None)

    try:
        importlib.import_module("olav.core.topology_engine")
    except ImportError:
        pass
    else:
        raise AssertionError(
            "legacy olav.core.topology_engine still imports — ARCH-20 "
            "Phase 3 needs a hard-cut, not a shim."
        )

    try:
        importlib.import_module("olav.core.auto_learn")
    except ImportError:
        pass
    else:
        raise AssertionError(
            "legacy olav.core.auto_learn still imports — ARCH-20 Phase 3 "
            "needs a hard-cut."
        )


def test_no_stale_callers_reference_legacy_paths():
    """No source file should still use the old import path."""
    import re

    legacy_re = re.compile(r"from\s+olav\.core\.(topology_engine|auto_learn)")
    searched: list[Path] = []
    for root in (
        REPO / "src",
        REPO / "olav-netops" / "src",
        REPO / ".olav" / "workspace",
        REPO / "tests",
    ):
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            searched.append(py)

    offenders = []
    for py in searched:
        text = py.read_text(encoding="utf-8", errors="ignore")
        for match in legacy_re.finditer(text):
            offenders.append(f"{py.relative_to(REPO)}: {match.group(0)}")

    assert not offenders, (
        "Stale imports still using olav.core.topology_engine / auto_learn. "
        "Update them to olav_netops.core.<name>:\n" + "\n".join(offenders)
    )
