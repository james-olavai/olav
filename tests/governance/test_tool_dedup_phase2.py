"""ARCH-20 Phase 2 — workspace tool files are symlinks (or content-identical)
pointing to a single canonical source.

Post-R65 (ARCH-23) note: core's monolithic ``core/tools/`` collection was
relocated into sub-agent ``tools/`` folders. Only 3 cross-domain tools remain
in core/tools/ (``execute_sql`` / ``recall_memory`` / ``web_search``); everything
else now lives in its sub-agent home as a real file (not a symlink). The
previous "canonical-in-core/tools/ + symlink-in-subagent" pattern was retired.

Post-dev_docs/85 (ops→netops rename): the four formerly-ops cross-domain tools
now have canonical sources in ``.olav/workspace/netops/tools/``.

Invariants this suite guards:

* The four netops cross-domain tools have canonical sources in
  ``.olav/workspace/netops/tools/``.
* The three truly-cross-domain tools in ``core/tools/`` are real files.
* When the same filename appears more than once under ``.olav/workspace/``,
  the copies are either symlinks to a common canonical, byte-identical,
  or explicitly allowlisted as deliberate divergence.
* No broken symlinks remain.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"


# Canonical location per tool. Keys are file basenames; values are the
# directory (relative to WORKSPACE) whose copy is the single source of
# truth. Everywhere else the file should appear as a symlink or be
# content-identical.
# Post-dev_docs/85: formerly "ops" cross-domain tools now live in netops/tools/.
_NETOPS_CANONICAL = {"execute_cli_parallel.py", "diff_configs.py", "search_commands.py", "take_snapshot.py"}
_OPS_CANONICAL = _NETOPS_CANONICAL  # alias kept for test backward-compat

# Post-R65: core/tools/ canonicals reduced to 3 truly-cross-domain tools.
_CORE_CANONICAL = {
    "web_search.py",
    "execute_sql.py",
    "recall_memory.py",
}

# Deliberate divergence: the same filename may appear in multiple sub-agent
# homes with different content because the tool has distinct implementations
# per sub-agent scope. Skipped in ``test_known_duplicates_are_symlink_or_identical``.
_DELIBERATE_DIVERGENCE: set[str] = {
    # core/tools/execute_sql.py is the orchestrator cross-domain version
    # (mutating-SQL approval gate, tier-aware context rows); the
    # core/db_query/tools/execute_sql.py is a simpler delegate wrapper.
    "execute_sql.py",
}


def _md5(path: Path) -> str:
    return hashlib.md5(path.resolve().read_bytes()).hexdigest()


def _canonical_dir(name: str) -> Path:
    if name in _NETOPS_CANONICAL:
        return WORKSPACE / "netops" / "tools"
    if name in _CORE_CANONICAL:
        return WORKSPACE / "core" / "tools"
    raise AssertionError(f"no canonical mapping for {name}")


# ── canonical presence ───────────────────────────────────────────────────────


def test_ops_canonical_files_exist_as_regular_files():
    """Post-dev_docs/85: netops/tools/ is the canonical home (ops→netops rename)."""
    for name in _NETOPS_CANONICAL:
        p = WORKSPACE / "netops" / "tools" / name
        assert p.exists(), f"canonical netops tool missing: {p}"
        assert not p.is_symlink(), (
            f"{p} is a symlink — it's supposed to be the canonical source."
        )


def test_core_canonical_files_exist_as_regular_files():
    for name in _CORE_CANONICAL:
        p = WORKSPACE / "core" / "tools" / name
        assert p.exists(), f"canonical core tool missing: {p}"
        assert not p.is_symlink(), (
            f"{p} is a symlink — it's supposed to be the canonical source."
        )


# ── no divergence / no broken symlinks ───────────────────────────────────────


def _all_py_occurrences(basename: str) -> list[Path]:
    return sorted(
        p for p in WORKSPACE.rglob(basename)
        if p.is_file() or p.is_symlink()
    )


def test_known_duplicates_are_symlink_or_identical():
    checked = (_OPS_CANONICAL | _CORE_CANONICAL) - _DELIBERATE_DIVERGENCE
    for name in checked:
        canonical = _canonical_dir(name) / name
        if not canonical.exists():
            # covered by ``test_*_canonical_files_exist`` above
            continue
        canonical_md5 = _md5(canonical)
        for occ in _all_py_occurrences(name):
            if occ.samefile(canonical):
                continue
            occ_md5 = _md5(occ)
            assert occ_md5 == canonical_md5, (
                f"divergence: {occ.relative_to(REPO)} ≠ {canonical.relative_to(REPO)} "
                "(either make it a symlink, keep content in sync, or add to "
                "_DELIBERATE_DIVERGENCE)."
            )


def test_no_broken_symlinks_under_workspace():
    broken = []
    for p in WORKSPACE.rglob("*.py"):
        if p.is_symlink() and not p.resolve().exists():
            broken.append(str(p.relative_to(REPO)))
    assert not broken, f"broken symlinks detected: {broken}"


# ── direction-specific guards (post-R65 retired) ────────────────────────────
#
# The ``test_cross_domain_tools_symlink_from_core_to_ops`` and
# ``test_sub_agent_tools_symlink_up_to_core`` and
# ``test_pre_existing_diff_configs_symlink_still_present`` tests previously
# asserted specific symlink structures that ARCH-23 R65 replaced by moving
# files into sub-agent homes. They're preserved here as no-ops so test IDs
# referenced elsewhere (e.g. tracking docs) don't dangle; the real contract
# is now just "no divergent duplicates", enforced above.


def test_cross_domain_tools_symlink_from_core_to_ops():
    """Retired post-R65: the 4 ops cross-domain tools are no longer mirrored
    into core/tools/. Core delegates via olav_delegate instead of aliasing."""
    # Verify the opposite: those 4 files should NOT appear in core/tools/.
    for name in _OPS_CANONICAL:
        core_copy = WORKSPACE / "core" / "tools" / name
        assert not core_copy.exists(), (
            f"Post-R65 {core_copy} should not exist — core delegates to ops "
            f"via olav_delegate rather than aliasing."
        )


def test_sub_agent_tools_symlink_up_to_core():
    """Retired post-R65: sub-agent tools are now canonical real files in
    their sub-agent homes, not symlinks up to core/tools/."""
    # Nothing to assert — this contract no longer applies.


def test_pre_existing_diff_configs_symlink_still_present():
    """Post-dev_docs/85: ops/analyze no longer exists (→ netops/analyzer).
    diff_configs.py is a real file in netops/tools/ — no symlink required."""
    p = WORKSPACE / "netops" / "tools" / "diff_configs.py"
    assert p.exists(), f"netops/tools/diff_configs.py missing after ops→netops rename"
    assert not p.is_symlink(), (
        "netops/tools/diff_configs.py should be a canonical real file, not a symlink"
    )
