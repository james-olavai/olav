"""An identical result set must not leave a second CSV behind.

Measured on the core agent, N=3: one run in three issued the same query twice,
and `execute_sql` wrote two byte-identical CSVs 5 seconds apart —

    18:51:14  query_20260806_185114.csv  15387  md5 7dbc74de…
    18:51:19  query_20260806_185119.csv  15387  md5 7dbc74de…

— of which only the second was ever cited. The first is litter the operator has
no way to distinguish from real output.

A guide already tells the model not to re-export (authored 2026-08-05, and it
does work: `format_and_export` was never called in any run). But a guide cannot
help here, because the duplicate is not a wrong tool choice — it is the *right*
tool called twice. Per CLAUDE.md, prose changes WHETHER a small model calls a
tool, never how correctly or how often; that class of defect belongs in the tool
layer.

So the export is content-addressed: the digest of the rows is part of the
filename, and an existing file with the same digest is reused instead of
rewritten. The duplicate becomes impossible by construction, for any number of
calls, on any model.

Both implementations are exercised — tools/execute_sql.py (@tool) and
scripts/execute_sql.py (CLI script) are separate code, and the previous bug in
this area was present in both.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_COPIES = {
    "tool": REPO / "src/olav/data/workspace/core/tools/execute_sql.py",
    "script": REPO / "src/olav/data/workspace/core/scripts/execute_sql.py",
}


@pytest.fixture(params=sorted(_COPIES), ids=sorted(_COPIES))
def source(request) -> str:
    return _COPIES[request.param].read_text(encoding="utf-8")


class TestTheExportIsContentAddressed:
    """Source-level, because the export block sits inside a long tool body that
    cannot be called without a live DuckDB — but the three pieces that make
    dedup work are each checkable, and each is what a refactor would drop."""

    def test_the_digest_is_computed_from_the_payload(self, source):
        assert "hashlib.sha256(payload.encode" in source, (
            "the digest must come from the rendered rows, not from the SQL — "
            "two differently-worded queries can produce the same result set"
        )

    def test_the_digest_is_part_of_the_filename(self, source):
        assert 'f"query_{timestamp}_{digest}.csv"' in source

    def test_an_existing_file_with_the_same_digest_is_reused(self, source):
        assert 'glob(f"query_*_{digest}.csv")' in source
        tree = ast.parse(source)
        # The reuse branch must actually skip the write, not just log.
        assert "existing[0]" in source, "the found file's path must be returned"

    def test_the_write_happens_only_in_the_else_branch(self, source):
        """If the write is unconditional the digest is decoration."""
        block = source[source.index("existing = sorted("):]
        block = block[: block.index("message = None")] if "message = None" in block else block
        assert block.index("existing[0]") < block.index("open(csv_path"), (
            "the reuse path must come before the write path"
        )
        assert "else:" in block


class TestDedupSemantics:
    """The behaviour the source above is meant to produce, run for real.

    Mirrors the shipped logic against a temp directory. This is a copy — which
    the source tests above exist to keep honest — but without it nothing proves
    the *semantics*, only that certain tokens are present.
    """

    @staticmethod
    def _export(export_dir: Path, results: list[dict]) -> tuple[Path, bool]:
        from datetime import datetime

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
        payload = buf.getvalue()
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]

        existing = sorted(export_dir.glob(f"query_*_{digest}.csv"))
        if existing:
            return existing[0], False
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = export_dir / f"query_{ts}_{digest}.csv"
        with open(path, "w", newline="") as f:
            f.write(payload)
        return path, True

    @pytest.fixture
    def export_dir(self, tmp_path) -> Path:
        d = tmp_path / "exports" / "queries"
        d.mkdir(parents=True)
        return d

    def _rows(self, n: int = 60) -> list[dict]:
        return [{"hostname": f"dev{i}", "platform": "cisco_ios"} for i in range(n)]

    def test_three_identical_exports_leave_one_file(self, export_dir):
        """The observed defect, at the count that matters."""
        paths = [self._export(export_dir, self._rows())[0] for _ in range(3)]
        assert len(list(export_dir.glob("*.csv"))) == 1
        assert len(set(paths)) == 1, "the cited path must also be stable"

    def test_only_the_first_call_writes(self, export_dir):
        wrote = [self._export(export_dir, self._rows())[1] for _ in range(3)]
        assert wrote == [True, False, False]

    def test_a_different_result_set_gets_its_own_file(self, export_dir):
        """Dedup must not collapse genuinely different exports."""
        p1, _ = self._export(export_dir, self._rows(60))
        p2, _ = self._export(export_dir, self._rows(61))
        assert p1 != p2
        assert len(list(export_dir.glob("*.csv"))) == 2

    def test_column_order_change_is_a_different_export(self, export_dir):
        a = [{"hostname": "d1", "platform": "ios"}] * 60
        b = [{"platform": "ios", "hostname": "d1"}] * 60
        p1, _ = self._export(export_dir, a)
        p2, _ = self._export(export_dir, b)
        assert p1 != p2, "the header row differs, so the file differs"

    def test_the_reused_file_is_not_rewritten(self, export_dir):
        """Reuse must not touch mtime — an operator watching the directory
        should see one event, not one per call."""
        path, _ = self._export(export_dir, self._rows())
        before = path.stat().st_mtime_ns
        again, wrote = self._export(export_dir, self._rows())
        assert again == path and wrote is False
        assert path.stat().st_mtime_ns == before

    def test_the_contents_are_a_valid_csv_of_every_row(self, export_dir):
        """Dedup is worthless if the surviving file is short — the whole point
        of the export is that the FULL result is on disk."""
        path, _ = self._export(export_dir, self._rows(60))
        rows = list(csv.DictReader(path.read_text().splitlines()))
        assert len(rows) == 60
        assert rows[0]["hostname"] == "dev0" and rows[-1]["hostname"] == "dev59"
