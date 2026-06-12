"""Phase D — TDD for ``format_and_export`` append mode.

User requirement (2026-05-14): for any agent that's in REPORT MODE
(emitting a Markdown report), every react step should append its
evidence to the report file as soon as the reflection completes.
This prevents the "summarize at the end loses detail" failure mode
seen in Phase C v3.

Design:
- New param ``mode: str | None`` — accepts 'overwrite' (default) and 'append'.
- 'append' opens with mode='a' for text formats; creates the file if missing.
- 'append' is rejected for structured formats (json/csv/yaml) because
  appending bytes corrupts the parse — must raise ValueError.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_exports(monkeypatch, tmp_path):
    from olav.core import config as _cfg
    monkeypatch.chdir(tmp_path)
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(_cfg, "EXPORTS_DIR", exports)
    return exports


def _read(rel_path: str) -> str:
    return Path(rel_path).read_text(encoding="utf-8")


def test_append_creates_file_if_missing(tmp_exports):
    """First append on a non-existing file just creates it."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    out = format_and_export(
        data="# Report\n\n## Step 1: discover\n",
        filename="live_report",
        format="md",
        mode="append",
    )
    assert _read(out["path"]) == "# Report\n\n## Step 1: discover\n"


def test_append_grows_existing_file(tmp_exports):
    """Second append on the same filename concatenates content."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    format_and_export(
        data="# Report\n\n## Step 1: discover\nfound A.\n",
        filename="live_report",
        format="md",
        mode="append",
    )
    format_and_export(
        data="\n## Step 2: verify\nA confirmed via X.\n",
        filename="live_report",
        format="md",
        mode="append",
    )
    out = format_and_export(
        data="\n## Synthesis\nThe answer is A.\n",
        filename="live_report",
        format="md",
        mode="append",
    )
    body = _read(out["path"])
    assert "## Step 1: discover\nfound A." in body
    assert "## Step 2: verify\nA confirmed via X." in body
    assert "## Synthesis\nThe answer is A." in body
    assert body.index("Step 1") < body.index("Step 2") < body.index("Synthesis")


def test_default_mode_is_overwrite_back_compat(tmp_exports):
    """Default mode must remain 'overwrite' — existing callers untouched."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    format_and_export(data="v1", filename="back_compat", format="md")
    out = format_and_export(data="v2", filename="back_compat", format="md")
    assert _read(out["path"]) == "v2"


def test_explicit_overwrite_mode(tmp_exports):
    """Explicit mode='overwrite' must behave like default."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    format_and_export(data="v1", filename="back_compat", format="md", mode="overwrite")
    out = format_and_export(data="v2", filename="back_compat", format="md", mode="overwrite")
    assert _read(out["path"]) == "v2"


def test_append_rejected_for_json(tmp_exports):
    """JSON append would corrupt the parse — must raise ValueError."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    with pytest.raises(ValueError, match=r"append.*json|json.*append"):
        format_and_export(data='{"a": 1}', filename="data", format="json", mode="append")


def test_append_rejected_for_csv(tmp_exports):
    """CSV append would duplicate the header — must raise ValueError."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    with pytest.raises(ValueError, match=r"append.*csv|csv.*append"):
        format_and_export(data="a,b\n1,2\n", filename="data", format="csv", mode="append")


def test_append_routes_md_to_reports_subdir(tmp_exports):
    """Append must preserve normal format → subdir routing."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    out = format_and_export(data="## Step 1\n", filename="routed", format="md", mode="append")
    assert "reports/" in out["path"], f"md should route to exports/reports/: {out['path']}"


def test_size_reflects_full_file_after_append(tmp_exports):
    """Returned `size` should be the file's total size after the append,
    not the size of just the appended chunk — gives the caller an
    accurate handle on report growth."""
    from olav.data.workspace.core.scripts.format_and_export import format_and_export

    first = format_and_export(data="AAAAA", filename="growing", format="md", mode="append")
    second = format_and_export(data="BBBBB", filename="growing", format="md", mode="append")
    assert first["size"] == 5
    assert second["size"] == 10
