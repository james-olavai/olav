"""R83.4 / Chapter 4: SaveAssertionMiddleware unit tests.

Pins the post-processing assertion that closes the
"agent claims save without calling the save tool" hallucination class.

Three behavior contracts:
1. No-claim fast path — most replies are unaffected (sub-millisecond);
2. Claim + tool evidence — trust the agent, no rewrite;
3. Claim without evidence — extract the artifact (Mermaid) and save it
   directly; on failure, append a clear warning note.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


# ── Test fixtures ──────────────────────────────────────────────────


class _AIMessage:
    """Minimal AIMessage-like object with role + content + tool_calls."""

    def __init__(self, content="", tool_calls=None, role="assistant"):
        self.role = role
        self.type = role
        self.content = content
        self.tool_calls = tool_calls or []


class _ToolMessage:
    """Minimal ToolMessage-like object."""

    def __init__(self, name, content=""):
        self.role = "tool"
        self.type = "tool"
        self.name = name
        self.content = content


@pytest.fixture
def tmp_exports(monkeypatch, tmp_path):
    """Run with EXPORTS_DIR redirected to a tmp dir."""
    from olav.core import config as _cfg
    monkeypatch.chdir(tmp_path)
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(_cfg, "EXPORTS_DIR", exports)
    return exports


def _run(coro):
    """Run an async function in a fresh loop."""
    return asyncio.run(coro)


# ── 1. Detection helpers ──────────────────────────────────────────


def test_no_claim_returns_none():
    """Plain reply with no save phrasing → fast path, no work."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content="Here are the results: 6 devices.")]}
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None


def test_claim_phrase_detection():
    """Save phrases (English + Chinese) should trigger inspection."""
    from olav.plugins.middleware.save_assertion import _looks_like_save_claim

    assert _looks_like_save_claim("Saved to /exports/topology.mmd")
    assert _looks_like_save_claim("Mermaid saved as /tmp/x.mmd")
    assert _looks_like_save_claim("Report saved: /exports/foo.md")
    assert _looks_like_save_claim("已保存到 exports/ 目录")
    assert not _looks_like_save_claim("Here are 8 links from the topology table")


def test_claim_with_format_and_export_tool_message_trusted():
    """Tool message in history = save actually happened, trust it."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    state = {
        "messages": [
            _ToolMessage(name="format_and_export", content='{"path": "exports/foo.mmd"}'),
            _AIMessage(content="Saved to /exports/foo.mmd"),
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None  # trusted, no supplements added


def test_writer_delegation_no_longer_save_evidence():
    """R85 (dev_docs/58 § "R85 inline-save"): writer is demoted from
    save-bottleneck to optional polish/edit subagent.  After R85 every
    agent inherits format_and_export from core and calls it directly;
    olav_delegate('writer', ...) is NO LONGER a save signal.

    If an agent still delegates to writer AND claims a save AND no
    direct format_and_export tool call happened, SaveAssertion treats
    that as a hallucination — runs the recovery path (auto-saves
    mermaid/markdown) or attaches a warning.

    The previous behaviour ("writer delegation = trust" — added in
    R83.4 Chapter 4 and tightened in 24778df to require path-result)
    was specific to the writer-as-save-bottleneck era; R85 removes
    that role entirely.
    """
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    delegation = _AIMessage(
        content="",
        tool_calls=[{
            "id": "tc_1",
            "name": "olav_delegate",
            "args": {"subagent_name": "writer", "task_description": "save mermaid"},
        }],
    )
    delegation_result = _ToolMessage(
        name="olav_delegate",
        content='{"path": "exports/diagrams/topology.mmd", "size": 940}',
    )
    delegation_result.tool_call_id = "tc_1"
    state = {
        "messages": [
            delegation,
            delegation_result,
            _AIMessage(content="Saved to /exports/topology.mmd"),
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    # Not None — supplements should include a warning since writer
    # is no longer a save delegation.
    assert out is not None
    sups = out.get("_output_supplements") or []
    assert any("warning" in s.lower() for s in sups)


def test_render_report_tool_trusted():
    """audit/auditor's ``render_report`` is its own save tool — must
    count as save evidence so audit reports don't trigger warnings."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    state = {
        "messages": [
            _ToolMessage(name="render_report", content="exports/audit_reports/x.md"),
            _AIMessage(content="Report saved: exports/audit_reports/x.md"),
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None


def test_save_lab_config_tool_trusted():
    """ops/lab's ``save_lab_config`` writes config — count as save."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    state = {
        "messages": [
            _ToolMessage(name="save_lab_config", content="ok"),
            _AIMessage(content="Lab config saved to /tmp/lab/r1.cfg"),
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None


def test_audit_auditor_delegation_with_path_result_trusted():
    """olav_delegate('audit-auditor', ...) trusted when the delegation
    result carries a path (mirrors the writer rule in 24778df).
    """
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    delegation = _AIMessage(
        content="",
        tool_calls=[{
            "id": "tc_audit",
            "name": "olav_delegate",
            "args": {"subagent_name": "audit-auditor", "task_description": "run audit"},
        }],
    )
    delegation_result = _ToolMessage(
        name="olav_delegate",
        content='{"path": "exports/audit_reports/health.md", "size": 2048}',
    )
    delegation_result.tool_call_id = "tc_audit"
    state = {
        "messages": [
            delegation,
            delegation_result,
            _AIMessage(content="Report saved at /exports/audit_reports/health.md"),
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None


# ── 2. Hallucination + Mermaid recovery ──────────────────────────


def test_hallucinated_save_with_mermaid_block_recovers(tmp_exports):
    """Claim 'saved' + ```mermaid``` block in content + no tool evidence
    → middleware extracts the block and writes the file itself."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mermaid = "graph TD\n    A --> B\n    B --> C"
    final = (
        f"Here is the topology:\n\n```mermaid\n{mermaid}\n```\n\n"
        "Saved to /exports/topology.mmd"
    )
    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content=final)]}
    out = _run(mw.aafter_agent(state, runtime=None))

    # Supplements should include the auto-recovery note
    assert out is not None
    sups = out.get("_output_supplements") or []
    assert any("Auto-recovered" in s for s in sups)
    # The recovered file should exist on disk
    diagrams = tmp_exports / "diagrams"
    files = list(diagrams.glob("recovered_*.mmd"))
    assert len(files) == 1
    assert files[0].read_text() == mermaid


def test_hallucinated_save_without_mermaid_appends_warning(tmp_exports):
    """Claim 'saved' but no extractable artifact → warning note (no
    file created)."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content="Saved to /exports/result.csv")]}
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is not None
    sups = out.get("_output_supplements") or []
    assert any("Save assertion warning" in s for s in sups)
    # No file should have been created (no recoverable artifact)
    diagrams = tmp_exports / "diagrams"
    assert not diagrams.exists() or not list(diagrams.glob("*"))


def test_bare_mermaid_syntax_recovered(tmp_exports):
    """Mermaid syntax NOT inside code fence — bare 'graph TD\\n...'
    should still be detected and saved."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    final = (
        "Here is the topology, saved as /exports/topology.mmd:\n\n"
        "graph LR\n    R1 --> R2\n    R2 --> R3\n\n"
        "Each link is up."
    )
    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content=final)]}
    out = _run(mw.aafter_agent(state, runtime=None))
    sups = out.get("_output_supplements") or []
    assert any("Auto-recovered" in s for s in sups)
    files = list((tmp_exports / "diagrams").glob("recovered_*.mmd"))
    assert len(files) == 1
    content = files[0].read_text()
    assert content.startswith("graph LR")
    assert "R1 --> R2" in content


# ── 3. Path-exists pre-emption ─────────────────────────────────────


def test_existing_path_on_disk_trusted(tmp_exports):
    """If the claimed path exists on disk (e.g. agent saved via
    ``run_shell`` or any other route), do not warn or recover."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    target = tmp_exports / "manual_topo.mmd"
    target.write_text("graph TD\n    X --> Y", encoding="utf-8")

    mw = SaveAssertionMiddleware()
    state = {
        "messages": [
            _AIMessage(content=f"Saved to exports/manual_topo.mmd")
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None  # path exists, trust it


# ── 4. Edge cases ─────────────────────────────────────────────────


def test_empty_messages_returns_none():
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    out = _run(mw.aafter_agent({"messages": []}, runtime=None))
    assert out is None


def test_dict_message_format_supported():
    """Some message states use dict-shaped messages instead of objects."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    state = {
        "messages": [
            {"role": "tool", "name": "format_and_export", "content": "ok"},
            {"role": "assistant", "content": "Saved to /exports/x.mmd"},
        ]
    }
    out = _run(mw.aafter_agent(state, runtime=None))
    assert out is None  # tool message detected, trusted


# ── 5. Markdown report recovery (audit / sim / drift hallucinations) ─


def test_hallucinated_audit_report_recovered(tmp_exports):
    """Audit-style hallucination: claim 'Report saved' + report-shaped
    markdown content + no render_report tool call → recover the
    markdown to exports/reports/recovered_<ts>.md."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    final = (
        "# Health Report — Network Audit\n\n"
        "## Executive Summary\n"
        "All 6 devices are reachable; 0 critical findings.\n\n"
        "## Device Coverage\n\n"
        "| Device | Status | Last Seen |\n"
        "|--------|--------|-----------|\n"
        "| R1 | up | 2026-04-26 |\n"
        "| R2 | up | 2026-04-26 |\n\n"
        "## Findings\n\n"
        "- All BGP neighbors established\n"
        "- No drift detected vs last snapshot\n\n"
        "Report saved: /exports/reports/audit_report.md"
    )
    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content=final)]}
    out = _run(mw.aafter_agent(state, runtime=None))
    sups = out.get("_output_supplements") or []
    assert any("Auto-recovered markdown" in s for s in sups)
    files = list((tmp_exports / "reports").glob("recovered_*.md"))
    assert len(files) == 1
    saved = files[0].read_text()
    assert "# Health Report" in saved
    assert "## Executive Summary" in saved


def test_short_reply_with_save_claim_no_recovery(tmp_exports):
    """Bare 'Saved to /exports/x.csv' with no extractable content
    should NOT be turned into a recovered .md (too short, not
    report-shaped).  Warning path instead."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    final = "Saved to /exports/devices.csv"
    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content=final)]}
    out = _run(mw.aafter_agent(state, runtime=None))
    sups = out.get("_output_supplements") or []
    # Should warn — not recover
    assert any("Save assertion warning" in s for s in sups)
    # Warning should mention csv
    assert any(".csv" in s for s in sups)
    # No recovered files anywhere
    assert not list((tmp_exports / "reports").glob("recovered_*"))
    assert not list((tmp_exports / "diagrams").glob("recovered_*"))


def test_warning_mentions_extension(tmp_exports):
    """Warning text cites the specific extension claimed (csv/json/yaml)
    so the user knows what to redo."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    for ext in ("csv", "json", "yaml"):
        state = {
            "messages": [_AIMessage(
                content=f"Saved to /exports/data.{ext}"
            )]
        }
        out = _run(mw.aafter_agent(state, runtime=None))
        sups = out["_output_supplements"]
        assert any(f".{ext}" in s for s in sups), (
            f"warning for .{ext} should mention the extension; got: {sups}"
        )


def test_script_extension_deferred_to_output_formatter(tmp_exports):
    """``.sh`` and ``.py`` save claims are handled by
    OutputFormatterPlugin — SaveAssertion must not double-warn."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    mw = SaveAssertionMiddleware()
    for ext in ("sh", "py"):
        state = {
            "messages": [_AIMessage(
                content=f"Saved to /exports/scripts/deploy.{ext}"
            )]
        }
        out = _run(mw.aafter_agent(state, runtime=None))
        assert out is None, (
            f".{ext} should be deferred (OutputFormatter handles it); "
            f"SaveAssertion got: {out}"
        )


def test_mermaid_takes_precedence_over_markdown(tmp_exports):
    """When both a Mermaid block AND report-shaped markdown are
    present, Mermaid handler wins (more specific, less ambiguous)."""
    from olav.plugins.middleware.save_assertion import SaveAssertionMiddleware

    final = (
        "# Topology Report\n\n"
        "## Diagram\n\n"
        "```mermaid\n"
        "graph TD\n    R1 --> R2\n"
        "```\n\n"
        "## Notes\n\n"
        "- 2 devices\n"
        "- 1 link\n\n"
        "Saved to /exports/topology.mmd"
    )
    mw = SaveAssertionMiddleware()
    state = {"messages": [_AIMessage(content=final)]}
    out = _run(mw.aafter_agent(state, runtime=None))
    sups = out["_output_supplements"]
    assert any("Auto-recovered mermaid" in s for s in sups)
    # Mermaid file written, not .md
    assert list((tmp_exports / "diagrams").glob("recovered_*.mmd"))
    # No competing .md recovery
    assert not list((tmp_exports / "reports").glob("recovered_*.md"))
