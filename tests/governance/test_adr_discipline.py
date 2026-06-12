"""ADR discipline — pin ``docs/adr/`` structure established in Round 29.

ADRs under ``docs/adr/`` capture architectural decisions (see ADR-0001).
This test suite ensures:

* the directory and its scaffolding files exist,
* all ADR files follow the ``NNNN-kebab-case.md`` naming convention,
* every ADR has the four required sections (Status / Context /
  Decision / Consequences),
* the README ``Index`` table lists every ADR file in the directory
  (so the index never drifts out of sync with the files),
* ADR-0003 and ADR-0004 — the first two "real" policy ADRs — exist.

If a future refactor deletes or renames the ADR structure, this test
fires and forces the refactor to be deliberate.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ADR_DIR = REPO / "docs" / "adr"


_ADR_FILENAME = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_REQUIRED_SECTIONS = ("Status", "Context", "Decision", "Consequences")


def _adr_files() -> list[Path]:
    """All numbered ADR files (excludes README.md and template.md)."""
    return sorted(
        p for p in ADR_DIR.iterdir()
        if p.is_file() and p.suffix == ".md" and _ADR_FILENAME.match(p.name)
    )


def test_adr_directory_exists():
    assert ADR_DIR.is_dir(), f"ADR directory missing: {ADR_DIR}"


def test_adr_readme_and_template_exist():
    assert (ADR_DIR / "README.md").is_file(), "docs/adr/README.md missing"
    assert (ADR_DIR / "template.md").is_file(), "docs/adr/template.md missing"


def test_every_adr_follows_naming_convention():
    """Numbered ADRs must match ``NNNN-kebab-case.md``."""
    offenders: list[str] = []
    for p in ADR_DIR.iterdir():
        if not p.is_file() or p.suffix != ".md":
            continue
        if p.name in ("README.md", "template.md"):
            continue
        if not _ADR_FILENAME.match(p.name):
            offenders.append(p.name)
    assert not offenders, (
        f"ADR naming drift — expected ``NNNN-kebab-case.md``: {offenders}"
    )


def test_every_adr_has_required_sections():
    """Every numbered ADR must carry Status/Context/Decision/Consequences."""
    failures: list[str] = []
    for adr in _adr_files():
        text = adr.read_text(encoding="utf-8")
        for section in _REQUIRED_SECTIONS:
            # MADR headings are usually ``## Section`` or ``**Section**:``
            pattern = re.compile(
                rf"(?mi)^(?:##\s+{section}\b|\*\*{section}\*\*\s*:)"
            )
            if not pattern.search(text):
                failures.append(f"{adr.name}: missing ``{section}`` section")
    assert not failures, "\n".join(failures)


def test_adr_readme_index_lists_every_numbered_adr():
    """README ``Index`` table must have a row per numbered ADR on disk."""
    readme = (ADR_DIR / "README.md").read_text(encoding="utf-8")
    for adr in _adr_files():
        stem = adr.stem  # e.g. "0003-audit-ops-sub-agent-parity"
        number = stem.split("-", 1)[0]  # "0003"
        # Match either ``[0003](0003-...)`` markdown-link form.
        link_pattern = rf"\[{number}\]\({re.escape(adr.name)}\)"
        assert re.search(link_pattern, readme), (
            f"README.md Index missing link to {adr.name} "
            f"(expected markdown link with pattern {link_pattern})"
        )


def test_adr_0003_audit_ops_parity_exists():
    """Round 29 committed ADR-0003 to close ARCH-21 C."""
    matches = [p for p in _adr_files() if p.name.startswith("0003-")]
    assert matches, "ADR-0003 (audit/ops parity) missing from docs/adr/"


def test_adr_0004_new_top_level_agent_policy_exists():
    """Round 29 committed ADR-0004 to close ARCH-21 D."""
    matches = [p for p in _adr_files() if p.name.startswith("0004-")]
    assert matches, "ADR-0004 (new top-level agent policy) missing from docs/adr/"


def test_adr_numbers_are_unique_and_contiguous():
    """No duplicate numbers; no unexplained gaps."""
    numbers = [int(p.stem.split("-", 1)[0]) for p in _adr_files()]
    assert len(numbers) == len(set(numbers)), (
        f"Duplicate ADR numbers: {sorted(numbers)}"
    )
    # Contiguous from 1 (supersessions are still on-disk, just marked in Status)
    expected = list(range(1, len(numbers) + 1))
    assert numbers == expected, (
        f"ADR numbering gap: {numbers} vs expected {expected}"
    )
