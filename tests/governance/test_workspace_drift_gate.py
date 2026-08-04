"""Workspace multi-copy sync gate.

The two-workspace sync rule (CLAUDE.md) requires every workspace
agent's source / runtime / bundle copies to stay byte-identical.
History shows manual discipline fails: the audit SKILL.md drifted
unnoticed for a week, and 60eba6f7 committed *different* wording to
two copies in a single commit. scripts/workspace_drift.py detects
this, but until 2026-06-12 nothing ran it automatically — this gate
makes every governance run a drift check, so divergence is caught at
test time instead of during the next incident.

Missing dirs (e.g. runtime before `olav init`, retired domains) are
skipped by the script itself, so this passes on a fresh checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_workspace_copies_in_sync():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "workspace_drift.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    assert proc.returncode == 0, (
        "workspace copies have drifted — run `python scripts/workspace_drift.py` "
        "and sync (always edit source + runtime + bundle together):\n"
        + proc.stdout[-3000:]
    )


def _load_drift_module():
    """Import scripts/workspace_drift.py (not on sys.path) as a module.

    Registered in ``sys.modules`` before execution because ``@dataclass``
    resolves annotations via ``sys.modules[cls.__module__]`` — without it the
    module's own Domain dataclass raises AttributeError at import.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "workspace_drift", REPO / "scripts" / "workspace_drift.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[spec.name]
        raise
    return mod


def test_every_platform_agent_is_a_declared_domain():
    """The drift gate must not silently skip a workspace agent.

    dev_docs/114 §7.7 ②: `admin` and `services` were never listed in
    workspace_drift.DOMAINS, so the script reported ALL COPIES IN SYNC while an
    edited admin tool sat out of sync with its runtime mirror. A gate whose
    coverage is a hand-maintained list needs a gate on the list — otherwise the
    next platform agent added is unguarded from birth and nothing says so.
    """
    mod = _load_drift_module()

    shipped = {
        p.name for p in (REPO / "src" / "olav" / "data" / "workspace").iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    }
    declared = {d.name for d in mod.DOMAINS}

    assert shipped <= declared, (
        "platform workspace agents missing from workspace_drift.DOMAINS "
        f"(unguarded): {sorted(shipped - declared)}"
    )


def test_wheel_sourced_domains_compare_python_too():
    """Platform mirrors are byte-exact per CLAUDE.md, so their Python counts.

    The six files that had drifted were all under `scripts/`, which the
    metadata-only scope excluded — the drift was invisible even for the domains
    that *were* listed.
    """
    mod = _load_drift_module()

    wheel_root = REPO / "src" / "olav" / "data" / "workspace"
    for dom in mod.DOMAINS:
        if wheel_root in dom.source.parents:
            assert dom.compare_code, (
                f"domain '{dom.name}' is sourced from the wheel tree "
                "(byte-exact mirror) but compares metadata only"
            )
