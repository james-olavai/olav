"""The scratchpad's docstring names a migration; that name must be real.

For months it said the anti-fabrication invariants were enforced "in v0_23
migration". The platform's `v0_23_audit_routing` only adds two routing columns
to `audit_runs` — it has nothing to do with exploration. The real constraints
live in `olav_netops.migrations.v0_23_exploration`: same version number,
different package. A reader following the docstring would have opened the wrong
file and concluded the invariants did not exist.

Prose drifts silently, which is the whole reason it was wrong. So the facts it
asserts are pinned here: the migration it names exists, and the two DB-level
invariants it promises are actually declared there. If the module moves, the
migration is renamed, or a constraint is dropped, this fails instead of the
docstring quietly becoming fiction again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRATCHPAD = _REPO / "src/olav/core/explorer/scratchpad.py"
_MIGRATION = (
    _REPO / "olav-netops/src/olav_netops/migrations/v0_23_exploration.py"
)


@pytest.fixture(scope="module")
def doc() -> str:
    text = _SCRATCHPAD.read_text(encoding="utf-8")
    m = re.match(r'\s*"""(.*?)"""', text, re.DOTALL)
    assert m, "scratchpad.py has no module docstring"
    return m.group(1)


class TestTheNamedMigrationExists:
    def test_the_docstring_names_the_netops_migration(self, doc):
        assert "olav_netops.migrations.v0_23_exploration" in doc, (
            "the docstring must name the migration that actually creates the "
            "exploration tables"
        )

    def test_that_migration_file_is_present(self):
        assert _MIGRATION.is_file(), (
            f"{_MIGRATION} is gone — the docstring now points at nothing"
        )

    def test_the_module_imports_exactly_that_migration(self):
        """Docstring and code must agree; they did not before."""
        src = _SCRATCHPAD.read_text(encoding="utf-8")
        assert "from olav_netops.migrations.v0_23_exploration import apply_migration" in src


class TestThePromisedInvariantsAreReallyDeclared:
    """The docstring's specific claims about the DB layer."""

    @pytest.fixture(scope="class")
    def migration_sql(self) -> str:
        return _MIGRATION.read_text(encoding="utf-8")

    def test_evidence_sql_is_not_null(self, migration_sql):
        assert re.search(r"evidence_sql\s+TEXT\s+NOT NULL", migration_sql), (
            "the anti-fabrication invariant — a finding must cite the query "
            "that proved it — is no longer enforced at the DB layer"
        )

    def test_summary_is_unique_within_a_run(self, migration_sql):
        assert re.search(r"UNIQUE\s*\(\s*run_id\s*,\s*summary\s*\)", migration_sql), (
            "duplicate findings within one run are no longer rejected by the DB"
        )


class TestTheBoundaryClaimHolds:
    """The docstring explains why this module stays in the platform. If the
    reverse import stops being guarded, that explanation becomes false and
    ADR-0002 is breached — a hard startup dependency on olav-netops."""

    def test_the_netops_import_is_guarded(self):
        src = _SCRATCHPAD.read_text(encoding="utf-8")
        idx = src.index("from olav_netops.migrations.v0_23_exploration")
        before = src[max(0, idx - 400):idx]
        assert "try:" in before, (
            "the reverse import into olav_netops must stay inside a try/except "
            "— unguarded, it makes olav-netops a hard dependency of the platform"
        )
        after = src[idx:idx + 600]
        assert "ImportError" in after, "the guard must handle ImportError"
        assert "Install olav-netops" in after, (
            "the failure must tell the operator what to install, not raise a "
            "bare ModuleNotFoundError"
        )

    def test_the_import_is_not_at_module_level(self):
        """A top-level import would run at platform import time regardless of
        whether anyone uses the explorer."""
        src = _SCRATCHPAD.read_text(encoding="utf-8")
        for line in src.splitlines():
            if line.startswith("from olav_netops") or line.startswith("import olav_netops"):
                pytest.fail(f"module-level netops import: {line!r}")
