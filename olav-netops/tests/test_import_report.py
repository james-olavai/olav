"""The ingest must say what it did NOT parse, and why.

Measured on the runsheet's 339-device bundle (dev_docs/116): 8761 command
outputs landed, 2278 parsed, and the summary reported only "9 command types
parsed". The other 6483 vanished with no record — which is also how Ch2 came to
answer 317 devices instead of 339: 22 devices produced no parsed row at all and
nothing said so.

``_parse_one`` used to fold three different outcomes into a bare ``None``. These
tests pin the reasons and the classification, and that a reporting failure can
never fail an ingest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from olav_netops.core.ingest import landing


class _StubConn:
    """Minimal stand-in for a DuckDB connection returning a commands SSOT."""

    def __init__(self, rows, raises=False):
        self._rows = rows
        self._raises = raises

    def execute(self, sql):  # noqa: D102
        if self._raises:
            raise RuntimeError("netops.commands does not exist")
        assert "netops.commands" in sql
        return self

    def fetchall(self):  # noqa: D102
        return self._rows


class TestParseOneReasons:
    def test_success_reports_ok(self, monkeypatch):
        monkeypatch.setattr(
            "olav_netops.tools.textfsm_parse.parse_output",
            lambda p, c, b: [{"a": 1}],
        )
        payload, reason = landing._parse_one("cisco_ios", "show version", "x")
        assert reason == "ok"
        assert json.loads(payload) == [{"a": 1}]

    def test_empty_parse_reports_no_rows(self, monkeypatch):
        monkeypatch.setattr(
            "olav_netops.tools.textfsm_parse.parse_output", lambda p, c, b: []
        )
        payload, reason = landing._parse_one("cisco_ios", "show version", "x")
        assert payload is None and reason == "no_rows"

    def test_exception_names_the_error_instead_of_swallowing_it(self, monkeypatch):
        def _boom(p, c, b):
            raise ValueError("bad template")

        monkeypatch.setattr("olav_netops.tools.textfsm_parse.parse_output", _boom)
        payload, reason = landing._parse_one("cisco_ios", "show version", "x")
        assert payload is None
        assert reason == "parser_error:ValueError", (
            "an exception used to be indistinguishable from an empty parse"
        )


class TestClassifyUnparsed:
    """The SSOT is what separates 'chose not to parse' from 'nothing registered'
    from 'parser matched nothing' — the distinction the report exists to make."""

    SSOT = [
        ("cisco_ios", "show running-config", "raw_only"),
        ("cisco_ios", "show interfaces status", "ntc"),
    ]

    def test_raw_only_is_by_design(self):
        rows = landing._classify_unparsed(
            _StubConn(self.SSOT), {("cisco_ios", "show running-config"): 338}, {}
        )
        assert rows[0]["reason"] == "raw_only"
        assert "by design" in rows[0]["detail"]

    def test_registered_parser_that_matched_nothing(self):
        rows = landing._classify_unparsed(
            _StubConn(self.SSOT), {("cisco_ios", "show interfaces status"): 315}, {}
        )
        assert rows[0]["reason"] == "parser_no_match"

    def test_command_absent_from_the_ssot(self):
        rows = landing._classify_unparsed(
            _StubConn(self.SSOT), {("cisco_ios", "show ip igmp snooping group"): 281}, {}
        )
        assert rows[0]["reason"] == "no_parser_registered"

    def test_parse_error_wins_over_ssot_lookup(self):
        key = ("cisco_ios", "show interfaces status")
        rows = landing._classify_unparsed(
            _StubConn(self.SSOT), {key: 3}, {key: "parser_error:TypeError"}
        )
        assert rows[0]["reason"] == "parser_error:TypeError"

    def test_missing_ssot_degrades_honestly(self):
        rows = landing._classify_unparsed(
            _StubConn([], raises=True), {("cisco_ios", "show version"): 5}, {}
        )
        assert rows[0]["reason"] == "unclassified", (
            "without the SSOT the reason is unknown — do not guess one"
        )
        assert "olav init" in rows[0]["detail"]

    def test_sorted_by_volume_so_the_biggest_loss_is_first(self):
        rows = landing._classify_unparsed(
            _StubConn(self.SSOT),
            {
                ("cisco_ios", "show interfaces status"): 10,
                ("cisco_ios", "show running-config"): 400,
            },
            {},
        )
        assert [r["count"] for r in rows] == [400, 10]


class TestWriteImportReport:
    def _write(self, tmp_path, **kw):
        defaults = dict(
            snapshot_id="snap_test",
            bundle_id="b-1",
            collection_source="bundle:test:1",
            hosts={"d1", "d2", "d3"},
            hosts_with_parsed={"d1"},
            pairs_total=100,
            pairs_parsed=25,
            unparsed_rows=[
                {"platform": "cisco_ios", "command": "show running-config",
                 "count": 50, "reason": "raw_only", "detail": "by design"},
                {"platform": "cisco_ios", "command": "show ip arp",
                 "count": 25, "reason": "parser_no_match", "detail": "mismatch"},
            ],
            parser_fills={"show version": 25},
        )
        defaults.update(kw)
        path = landing._write_import_report(tmp_path / "import_reports", **defaults)
        return path, Path(path).read_text(encoding="utf-8")

    def test_names_the_devices_with_no_structured_data(self, tmp_path):
        _, text = self._write(tmp_path)
        assert "2 of 3 devices" in text
        assert "`d2`" in text and "`d3`" in text
        assert "`d1`" not in text.split("## Why")[0].split("no structured data")[1], (
            "a device that DID parse must not be listed as silent"
        )

    def test_reports_both_totals_and_the_gap(self, tmp_path):
        _, text = self._write(tmp_path)
        assert "**Command outputs landed**: 100" in text
        assert "**Parsed into structured rows**: 25 (25%)" in text
        assert "**Not parsed**: 75 (75%)" in text

    def test_explains_that_raw_data_is_still_queryable(self, tmp_path):
        _, text = self._write(tmp_path)
        assert "raw_output_store" in text, (
            "the point is not-parsed != not-imported; say where the data is"
        )

    def test_breaks_down_by_reason_and_by_command(self, tmp_path):
        _, text = self._write(tmp_path)
        assert "`raw_only` | 50" in text
        assert "`parser_no_match` | 25" in text
        assert "show running-config" in text

    def test_clean_import_says_so(self, tmp_path):
        _, text = self._write(
            tmp_path, hosts_with_parsed={"d1", "d2", "d3"}, unparsed_rows=[],
            pairs_total=100, pairs_parsed=100,
        )
        assert "Every device produced at least one parsed command output." in text
        assert "Nothing was dropped." in text

    def test_unwritable_directory_returns_none_rather_than_raising(self, tmp_path):
        blocker = tmp_path / "import_reports"
        blocker.write_text("not a directory")  # mkdir will fail
        path = landing._write_import_report(
            blocker,
            snapshot_id="s", bundle_id="b", collection_source="c",
            hosts=set(), hosts_with_parsed=set(), pairs_total=0, pairs_parsed=0,
            unparsed_rows=[], parser_fills={},
        )
        assert path is None, "a reporting failure must never fail the ingest"


def test_ingest_result_carries_the_report_fields():
    r = landing.IngestResult(
        bundle_id="b", snapshot_id="s", bundle_sha256="x",
        collection_source="c", hosts=1, commands=1, parser_fills={},
    )
    assert r.parse_report == {} and r.report_path is None, (
        "defaults must keep existing callers working"
    )
