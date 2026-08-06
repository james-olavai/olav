"""A wide row must stay a row. It used to become a string.

Found while probing whether execute_sql's auto-export is disclosed:

    olav --agent core "Show me the running-config text stored for <host>"
    → "the platform is currently experiencing a technical error
       ('str' object has no attribute 'items')"

`_sanitize_rows` passed each row to `_sanitize_value`, which looks right — a row
is a dict and that function handles dicts. But its dict branch returns a
*string* once the rendered form exceeds `_MAX_FIELD_CHARS` (800). Any row wide
enough to trip that, which is every query selecting stored config text, came
back as a str, and each consumer expecting a mapping died: `row.items()` in the
preview builder, `results[0].keys()` in the CSV writer.

The budget is per-field — one large JSON column must not flood the model's
context. Applying it to a whole row conflates "this cell is too big to show"
with "this record is too big to be a record".

Both copies are tested. `tools/execute_sql.py` (the @tool) and
`scripts/execute_sql.py` (the CLI script) are separate implementations, not
mirrors, and both carried the defect.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_COPIES = {
    "tool": REPO / "src/olav/data/workspace/core/tools/execute_sql.py",
    "script": REPO / "src/olav/data/workspace/core/scripts/execute_sql.py",
}


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"es_{path.parent.name}", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # pragma: no cover - import needs olav installed
        pytest.skip(f"cannot import {path.name}: {exc}")
    return mod


@pytest.fixture(params=sorted(_COPIES), ids=sorted(_COPIES))
def sql_mod(request):
    return _load(_COPIES[request.param])


def _wide_row(mod) -> dict:
    """A row whose rendered form comfortably exceeds the per-field budget."""
    return {
        "device_name": "alpha-core-6807v.net.demo.internal",
        "raw_output": "interface GigabitEthernet0/0\n" * 200,
    }


class TestRowsStayRows:
    def test_a_wide_row_is_still_a_mapping(self, sql_mod):
        row = _wide_row(sql_mod)
        assert len(str(row)) > sql_mod._MAX_FIELD_CHARS, "fixture must trip the budget"

        [out] = sql_mod._sanitize_rows([row])
        assert isinstance(out, dict), (
            f"row collapsed to {type(out).__name__} — every consumer that calls "
            f".items() or .keys() on it raises"
        )
        assert out.keys() == row.keys(), "column set must survive sanitising"

    def test_the_oversized_cell_is_still_truncated(self, sql_mod):
        """The budget must keep working at the level it was written for."""
        [out] = sql_mod._sanitize_rows([_wide_row(sql_mod)])
        assert len(out["raw_output"]) <= sql_mod._MAX_FIELD_CHARS + 20
        assert out["raw_output"].endswith("[truncated]")
        assert out["device_name"] == "alpha-core-6807v.net.demo.internal", (
            "a small field alongside a large one must be left alone"
        )

    def test_the_consumers_that_crashed_now_work(self, sql_mod):
        """Reproduce the two call shapes from the traceback, not a proxy."""
        rows = sql_mod._sanitize_rows([_wide_row(sql_mod)])
        dict(rows[0].items())  # preview builder
        assert list(rows[0].keys()), "CSV writer reads results[0].keys()"

    def test_a_narrow_row_is_unchanged(self, sql_mod):
        row = {"a": 1, "b": "short"}
        assert sql_mod._sanitize_rows([row]) == [row]

    def test_many_wide_rows_all_survive(self, sql_mod):
        rows = sql_mod._sanitize_rows([_wide_row(sql_mod) for _ in range(5)])
        assert all(isinstance(r, dict) for r in rows)


class TestFieldLevelSanitisingIsIntact:
    """The dict/list truncation `_sanitize_value` does for a *cell* is still
    wanted — this bug was in how it was applied, not in what it does."""

    def test_a_large_json_cell_is_still_flattened(self, sql_mod):
        cell = {f"k{i}": "v" * 40 for i in range(50)}
        [out] = sql_mod._sanitize_rows([{"parsed": cell}])
        assert isinstance(out["parsed"], str) and out["parsed"].endswith("[truncated]")

    def test_a_small_json_cell_stays_structured(self, sql_mod):
        [out] = sql_mod._sanitize_rows([{"parsed": {"version": "15.5"}}])
        assert out["parsed"] == {"version": "15.5"}
