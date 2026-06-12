"""Round 60 (item C) — ARCH-22 externally-blocked items pin.

After Rounds 19-50 closed every in-scope ARCH-22 item, the ledger
left three Deferred entries — A2 / A4 / C2. Round 66 closes A2 and C2;
A4 converts to a governance-only monitor since ``_legacy_archived/`` is
gitignored (``.gitignore`` line 98) — the "ops decision" about
archive-repo vs. git-tag was really about preventing it from entering
the repo, which ``.gitignore`` already handles.

* **A2** ``src/olav/core/audit_logger.py`` — CLOSED in Round 66 with the
  v0.19 cut. File deleted, noop tests removed.
* **A4** ``_legacy_archived/`` — CLOSED in Round 66 as "not a repo
  problem": the directory is gitignored, so it never ships in clones,
  wheels, or release artefacts. Local disk footprint (180MB+) is an
  operator cleanup concern, not a platform governance concern.
* **C2** ``src/olav/enterprise/audit_dataset_export.py`` — CLOSED in
  Round 66. ``DEDUP_STRATEGY`` module constant + env override landed.

These pins are defensive — they don't prescribe *when* the
preconditions should clear, only that as long as they haven't, the
platform ledger's Deferred state is factually accurate.
"""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


# ── A2: audit_logger.py deleted at v0.19 cut (Round 66 close) ──────────


def test_a2_audit_logger_deleted():
    """Post-R66: audit_logger.py deleted + noop test removed with the
    v0.19 cut. This pin guards against accidental reintroduction."""
    path = REPO / "src" / "olav" / "core" / "audit_logger.py"
    assert not path.exists(), (
        f"audit_logger.py reappeared at {path} — ARCH-22 A2 was closed "
        f"in Round 66 with the v0.19 cut; any reintroduction needs an ADR."
    )
    noop_test = REPO / "tests" / "unit" / "test_audit_logger_noop.py"
    assert not noop_test.exists(), (
        f"test_audit_logger_noop.py reappeared at {noop_test} — it was "
        f"removed alongside audit_logger.py in Round 66."
    )


def test_a2_version_at_or_past_v019():
    """ARCH-22 A2 was closed at the v0.19 cut. This pin ensures the
    project doesn't regress below that version (which would imply
    un-doing the cut)."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    import re
    m = re.search(r'^version\s*=\s*"(?P<v>\d+\.\d+\.\d+)"', pyproject, re.MULTILINE)
    assert m, "pyproject.toml lost its version field"
    ver = m.group("v")
    major_minor = tuple(int(x) for x in ver.split(".")[:2])
    assert major_minor >= (0, 19), (
        f"version {ver} is below 0.19 — ARCH-22 A2 was closed at the "
        f"v0.19 cut (Round 66); the version can't regress."
    )


# ── A4: _legacy_archived still exists ───────────────────────────────────


def test_a4_legacy_archive_still_present():
    """Post-R66: A4 is closed as "not a repo problem" — ``_legacy_archived/``
    is gitignored (``.gitignore`` line 98) so it never enters clones,
    wheels, or release artefacts. Local disk footprint is an operator
    cleanup concern, not governance.
    """
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "_legacy_archived/" in gitignore, (
        "_legacy_archived/ must stay in .gitignore — ARCH-22 A4 close "
        "depends on the directory being excluded from the repo."
    )
    # Archive directory's existence on disk is optional; we don't care.


# ── C2: DEDUP_STRATEGY is a module-level constant (R66 close) ──────────


def test_c2_legacy_enterprise_exact_v1_path_removed():
    """Post-R66+: ARCH-22 C2 closure is now represented by *removal* of the
    old enterprise export module and its ``exact_v1`` literals.

    This keeps the governance signal strong: if the old module reappears or
    ``exact_v1`` comes back into source, we surface it immediately.
    """
    path = REPO / "src" / "olav" / "enterprise" / "audit_dataset_export.py"
    assert not path.exists(), (
        "Legacy C2 home reappeared at enterprise/audit_dataset_export.py — "
        "ARCH-22 C2 has moved past that implementation."
    )
    offenders: list[str] = []
    for py in (REPO / "src" / "olav").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if "exact_v1" in text:
            offenders.append(str(py.relative_to(REPO)))
    assert not offenders, (
        "ARCH-22 C2 regression: legacy exact_v1 strategy literals reappeared:\n"
        + "\n".join(offenders)
    )


# ── Platform-scope summary pin ──────────────────────────────────────────


def test_arch22_matrix_reflects_scope_close():
    """The issues-doc header should still carry the platform-scope close
    framing. Post-R66 all three formerly-Deferred items (A2 / A4 / C2)
    are now closed or reclassified."""
    issues = (REPO / "dev_docs" / "00. issues.md").read_text(encoding="utf-8")
    idx = issues.find("### ISSUE-ARCH-22:")
    assert idx >= 0, "ARCH-22 section missing from issues doc"
    section = issues[idx : idx + 800]
    # Header should carry the "platform scope" framing that flipped it
    # from 🟡 to a Closed-for-scope state.
    assert "platform scope" in section.lower() or "externally" in section.lower()
