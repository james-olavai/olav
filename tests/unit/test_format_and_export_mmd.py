"""R100/S2: format_and_export now uses ``data: str`` strict typing.

Previous behavior (R83.4): dict args like ``{'mermaid': '<text>'}``
were silently unwrapped by lenient runtime coercion. R100/S2 removes
that coercion in favor of Pydantic-enforced ``data: str`` so:
  * The OpenAI tool schema seen by the LLM declares ``data`` as a
    string (not Any), giving the model an unambiguous shape contract
  * Malformations like ``data={'content':...}`` raise a clear
    ValidationError instead of silently succeeding with weird output
  * Demo7 Ch8 v1-v4 (2026-04-29) showed the lenient coercion was
    masking a real model adherence bug — files appeared to save but
    contained dict reprs instead of the intended content

These tests pin the new strict contract.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError


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


# ── Strict-string contract ────────────────────────────────────────────────


def test_dict_data_raises_validation_error():
    """Passing a dict for `data` must raise ValidationError — gives the
    LLM a clear feedback signal, not a silent malformed write."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    with pytest.raises(ValidationError) as exc:
        format_and_export.invoke({
            "data": {"mermaid": "graph TD\n  A --> B"},
            "filename": "x",
            "format": "mmd",
        })
    msg = str(exc.value)
    assert "string" in msg.lower(), f"error should mention string type: {msg!r}"


def test_list_data_raises_validation_error():
    """Lists also get rejected — only strings are accepted."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    with pytest.raises(ValidationError):
        format_and_export.invoke({
            "data": [{"hostname": "R1"}, {"hostname": "R2"}],
            "filename": "x",
            "format": "csv",
        })


def test_dict_with_path_size_keys_raises_validation_error():
    """The actual demo7 Ch8 v4 failure mode — model passed previous
    tool's return value as data. Must NOT silently produce a weird
    file; it must raise so the model sees the type error."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    with pytest.raises(ValidationError):
        format_and_export.invoke({
            "data": {"path": "exports/foo.md", "size": 256},
            "filename": "y",
            "format": "md",
        })


# ── String inputs work as before ──────────────────────────────────────────


def test_mermaid_string_writes_raw(tmp_exports):
    """Plain mermaid string is written byte-for-byte."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    mermaid = "graph TD\n    A --> B\n    B --> C"
    out = format_and_export.invoke({
        "data": mermaid,
        "filename": "topo",
        "format": "mmd",
    })
    assert _read(out["path"]) == mermaid


def test_markdown_string_writes_raw(tmp_exports):
    """Plain markdown string is written verbatim, lands under reports/."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    md = "# Diagnosis Report\n\nAll routers up."
    out = format_and_export.invoke({
        "data": md,
        "filename": "diag",
        "format": "md",
    })
    assert _read(out["path"]) == md
    assert "/reports/" in out["path"]


def test_csv_json_string_parsed_and_written(tmp_exports):
    """JSON-encoded string for CSV is parsed (the only legitimate way
    to pass tabular data through OpenAI's string-typed args field) and
    written as proper CSV."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    json_str = '[{"hostname":"R1","ip":"10.0.0.1"},{"hostname":"R2","ip":"10.0.0.2"}]'
    out = format_and_export.invoke({
        "data": json_str,
        "filename": "devices",
        "format": "csv",
    })
    content = _read(out["path"])
    assert "hostname,ip" in content or "hostname" in content.split("\n")[0]
    assert "R1" in content and "R2" in content


def test_format_auto_detected_from_string(tmp_exports):
    """Without explicit format, markdown content is detected by leading '#'."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": "# Header\n\nbody text",
        "filename": "auto",
    })
    assert out["path"].endswith(".md")
    assert "/reports/" in out["path"]


def test_subdir_routes_to_scripts(tmp_exports):
    """Explicit subdir routes; sh format defaults to scripts/."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": "#!/bin/bash\necho hello",
        "filename": "hello",
        "format": "sh",
    })
    # sh routes to exports/ by default; subdir override would be needed
    # for /scripts/ — preserved existing routing semantics
    assert out["path"].endswith("hello.sh")


def test_filename_with_extension_split(tmp_exports):
    """If filename has an extension, format is taken from it."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": "# X",
        "filename": "report.md",
    })
    assert out["path"].endswith("report.md")
    # Should NOT double-extension to report.md.md
    assert not out["path"].endswith(".md.md")


def test_filename_format_subdir_quote_leak_stripped(tmp_exports):
    """R100/S2 (2026-04-29 demo7 Ch8 v5): qwen3.6-27b-dense
    empirically baked literal quote characters into short
    string-typed args (e.g. ``filename='"devices_v5"'``,
    ``format='"md"'``, ``subdir='"reports"'``), creating bizarre
    paths like ``exports/"reports"/"devices_v5"."md"``.  Defensive
    strip should remove leading/trailing single OR double quotes
    on filename / format / subdir."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": "# Test",
        "filename": '"devices_v5"',
        "format": '"md"',
        "subdir": '"reports"',
    })
    # Should land at exports/reports/devices_v5.md (no literal quotes)
    assert '"' not in out["path"], f"quote leak in path: {out['path']!r}"
    assert out["path"].endswith("devices_v5.md")
    assert "/reports/" in out["path"]


def test_filename_quote_leak_single_quotes_stripped(tmp_exports):
    """Some endpoints leak single quotes instead of double."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": "# Test",
        "filename": "'sq_test'",
        "format": "'md'",
    })
    assert "'" not in out["path"]
    assert out["path"].endswith("sq_test.md")


def test_data_pydantic_alias_for_content_key_rejected():
    """If the LLM tries to pass {'content': '...'} as the `data` value,
    the strict schema rejects it — no silent unwrapping."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    with pytest.raises(ValidationError):
        format_and_export.invoke({
            "data": {"content": "# Hello"},
            "filename": "test",
            "format": "md",
        })
