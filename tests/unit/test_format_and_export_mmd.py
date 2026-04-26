"""R83.4 / Chapter 4: format_and_export Mermaid handling.

Background: writer subagent was passing
``data={'mermaid': '<mermaid_text>'}`` to ``format_and_export``, and the
.mmd file ended up containing the dict's repr instead of raw Mermaid.
LLM had no way to recover — file looked saved, but unusable downstream.

Pins:
1. Single-key wrapper dicts ({'mermaid': str}, {'diagram': str},
   {'mmd': str}) auto-unwrap to the raw string.
2. Wrapper key disambiguates format='mmd' when not specified.
3. Mermaid-syntax detection (``graph TD`` opener) salvages arbitrary
   single-key wrappers like {'foo': 'graph TD\\n...'}.
4. Triple-backtick ```mermaid fence stripped before write.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_exports(monkeypatch, tmp_path):
    """Redirect EXPORTS_DIR to a tmp dir under cwd.

    ``format_and_export`` returns a path via ``filepath.relative_to(Path.cwd())``
    which only succeeds when the export dir is under the working
    directory.  Run the test from the tmp dir so the relative_to call
    behaves the same as in production.
    """
    from olav.core import config as _cfg
    monkeypatch.chdir(tmp_path)
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(_cfg, "EXPORTS_DIR", exports)
    return exports


def _read(rel_path: str) -> str:
    """Read by relative path (returned by format_and_export) from cwd."""
    return Path(rel_path).read_text(encoding="utf-8")


def test_mermaid_wrapper_dict_unwrapped(tmp_exports):
    """``data={'mermaid': '<text>'}`` should produce raw Mermaid file."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    mermaid = "graph TD\n    A --> B\n    B --> C"
    out = format_and_export.invoke({
        "data": {"mermaid": mermaid},
        "filename": "test_topo",
        "format": "mmd",
    })
    content = _read(out["path"])
    assert content == mermaid
    # Should NOT contain dict repr
    assert "{'mermaid'" not in content
    assert "graph TD" in content


def test_diagram_wrapper_dict_unwrapped(tmp_exports):
    """``data={'diagram': '<text>'}`` also unwraps."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": {"diagram": "graph LR\n    X --> Y"},
        "filename": "test_diag",
        "format": "mmd",
    })
    assert "graph LR" in _read(out["path"])
    assert "{'diagram'" not in _read(out["path"])


def test_mermaid_wrapper_sets_format_when_missing(tmp_exports):
    """Wrapper key 'mermaid' disambiguates format=mmd even if not passed."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": {"mermaid": "graph TD\n    A --> B"},
        "filename": "test_implicit_mmd",
        # format omitted
    })
    assert out["path"].endswith(".mmd")


def test_mermaid_syntax_salvages_unknown_wrapper(tmp_exports):
    """Single-key dict whose VALUE starts with 'graph TD' unwraps to mmd."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": {"foo": "graph TD\n    A --> B"},
        "filename": "test_salvage",
        # format omitted — should auto-detect mmd from value content
    })
    content = _read(out["path"])
    assert content == "graph TD\n    A --> B"
    assert out["path"].endswith(".mmd")


def test_mermaid_fence_stripped(tmp_exports):
    """Triple-backtick ```mermaid fence should be stripped from .mmd output."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    fenced = "```mermaid\ngraph TD\n    A --> B\n```"
    out = format_and_export.invoke({
        "data": fenced,
        "filename": "test_fence",
        "format": "mmd",
    })
    content = _read(out["path"])
    assert content == "graph TD\n    A --> B"
    assert "```" not in content


def test_plain_mermaid_string_passes_through(tmp_exports):
    """Bare-string Mermaid (no wrapper, no fence) writes as-is."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    mermaid = "graph LR\n    R1 --> R2"
    out = format_and_export.invoke({
        "data": mermaid,
        "filename": "test_plain",
        "format": "mmd",
    })
    assert _read(out["path"]) == mermaid


def test_list_of_strings_joined_for_mmd(tmp_exports):
    """LLM sometimes passes ``data=['line1', 'line2', ...]`` for Mermaid;
    must join with newlines, not write the list repr."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": ["graph LR", "    R1 --> R2", "    R2 --> R3"],
        "filename": "test_list_lines",
        "format": "mmd",
    })
    content = _read(out["path"])
    assert content == "graph LR\n    R1 --> R2\n    R2 --> R3"
    # Must NOT be the list repr
    assert not content.startswith("[")


def test_python_repr_dict_string_unwrapped(tmp_exports):
    """LLM sometimes serialises dict via Python ``repr()`` (single quotes)
    instead of JSON.  ``ast.literal_eval`` fallback should still recover
    the dict so the mermaid wrapper is unwrapped correctly.
    """
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    # Note: single-quoted dict repr — would fail json.loads but parse OK
    # under ast.literal_eval.
    repr_str = "{'mermaid': 'graph TD\\n    A --> B'}"
    out = format_and_export.invoke({
        "data": repr_str,
        "filename": "test_repr",
        "format": "mmd",
    })
    content = _read(out["path"])
    assert content == "graph TD\n    A --> B"
    assert "{'mermaid'" not in content


def test_dict_repr_with_real_newlines_unwrapped(tmp_exports):
    """Worst-case LLM serialisation: dict-shaped string where the inner
    value contains a real LF byte (not ``\\n`` escape).  Both
    ``json.loads`` and ``ast.literal_eval`` fail on this; the regex
    fallback ``_extract_known_wrapper`` salvages the content."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    # Real newline character in the inner value
    real_newline_str = "{'mermaid': 'graph TD\n    A --> B\n    B --> C'}"
    out = format_and_export.invoke({
        "data": real_newline_str,
        "filename": "test_real_newline",
        "format": "mmd",
    })
    content = _read(out["path"])
    assert content == "graph TD\n    A --> B\n    B --> C"
    assert "{'mermaid'" not in content


def test_dict_repr_auto_detects_mmd_format(tmp_exports):
    """When wrapper key is 'mermaid', format should auto-resolve to mmd
    even if not explicitly passed."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    real_newline_str = "{'mermaid': 'graph LR\n    X --> Y'}"
    out = format_and_export.invoke({
        "data": real_newline_str,
        "filename": "test_auto_mmd",
        # no format= argument
    })
    assert out["path"].endswith(".mmd")


def test_existing_content_key_still_works(tmp_exports):
    """Regression: pre-existing ``{'content': '# Title'}`` extraction
    must still work after the new keys are added."""
    from olav.data.workspace.core.tools.format_and_export import format_and_export

    out = format_and_export.invoke({
        "data": {"content": "# Diagnosis Report\n\nHello"},
        "filename": "test_content_key",
        "format": "md",
    })
    content = _read(out["path"])
    assert content.startswith("# Diagnosis Report")
    assert "{'content'" not in content
