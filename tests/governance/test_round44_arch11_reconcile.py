"""Round 44 — ARCH-11 matrix reconciliation + parse_src_token groundwork.

ARCH-11 "evidence token" was listed in Round 25's matrix as mostly ❌ but
auditing the code shows Phase 1 (``_source`` dicts + ``[src: …]`` tag
rendering + ``_build_evidence_block``) and Phase 2 (``render_report_linter``
enforcing citations on every non-empty section) are both shipped and
test-covered (``test_evidence_sources.py`` / ``test_citation_linter.py``).

This module:

* **Reconciles** the matrix by pinning Phase 1 + Phase 2 infrastructure
  symbols as present — so future doc drift can't hide regressions.
* **Adds Round 44 groundwork**: ``parse_src_token()`` round-trips the tag
  format produced by ``_format_source_suffix``. This is the parsing piece
  a future ``olav explain <token>`` CLI needs; shipping it as a helper
  (without the CLI) keeps the format locked in before callers multiply.

``_format_source_suffix`` format (stable across versions)::

    [src: <table>[#<snapshot_id>][; device=<name>][; row=<n>]]
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.governance._paths import AUDIT_RUNNER_TOOLS

REPO = Path(__file__).resolve().parents[2]
AUDITOR_TOOLS = AUDIT_RUNNER_TOOLS
RENDER_REPORT_PY = AUDITOR_TOOLS / "render_report.py"
LINTER_PY = AUDITOR_TOOLS / "render_report_linter.py"


def _load(mod_name: str):
    path = AUDITOR_TOOLS / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(f"{mod_name}_r44", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── ARCH-11 Phase 1 infrastructure pins (reconciliation) ──────────────────


def test_phase1_format_source_suffix_exists():
    mod = _load("render_report")
    assert callable(getattr(mod, "_format_source_suffix", None)), (
        "ARCH-11 Phase 1 helper _format_source_suffix missing — evidence tag "
        "rendering regressed."
    )


def test_phase1_build_evidence_block_exists():
    mod = _load("render_report")
    assert callable(getattr(mod, "_build_evidence_block", None)), (
        "ARCH-11 Phase 1 helper _build_evidence_block missing — Evidence "
        "markdown block generation regressed."
    )


def test_phase1_assemble_prompt_uses_evidence_block():
    """The per-section prompt assembly must consume _build_evidence_block
    so the LLM sees citations outside the JSON fence (where it's tempted
    to re-quote them)."""
    src = RENDER_REPORT_PY.read_text(encoding="utf-8")
    assert "_build_evidence_block(findings)" in src, (
        "render_report._assemble_prompt no longer invokes _build_evidence_block; "
        "ARCH-11 Phase 1 wiring regressed."
    )


# ── ARCH-11 Phase 2 infrastructure pins (reconciliation) ──────────────────


def test_phase2_linter_module_exists():
    assert LINTER_PY.is_file(), (
        f"ARCH-11 Phase 2 linter module missing: {LINTER_PY}"
    )


def test_phase2_linter_wired_to_render_report():
    """render_report must invoke the linter when the profile opts in via
    emit_sources: true."""
    src = RENDER_REPORT_PY.read_text(encoding="utf-8")
    assert "lint_report_file" in src, (
        "render_report no longer calls lint_report_file — Phase 2 linter "
        "wiring dropped."
    )
    assert 'emit_sources' in src, (
        "render_report lost the emit_sources gate — linter will run on "
        "profiles that don't opt in."
    )


# ── ARCH-11 Round 44 groundwork: parse_src_token ──────────────────────────


def test_parse_src_token_is_public():
    mod = _load("render_report")
    fn = getattr(mod, "parse_src_token", None)
    assert callable(fn), "parse_src_token helper missing"


def test_parse_src_token_roundtrip_full():
    """Round-trip: format → parse → format yields identical output for the
    full (table, snapshot_id, device, row_index) shape."""
    mod = _load("render_report")
    src = {
        "table": "parsed_outputs",
        "snapshot_id": "snap_20260418_0201",
        "device": "R1",
        "row_index": 12,
    }
    tag = mod._format_source_suffix(src)
    assert tag == "[src: parsed_outputs#snap_20260418_0201; device=R1; row=12]"
    parsed = mod.parse_src_token(tag)
    assert parsed is not None
    # Order-independent dict equality — parse_src_token picks up every field.
    assert parsed == src
    # Format again must produce the same tag.
    assert mod._format_source_suffix(parsed) == tag


def test_parse_src_token_roundtrip_minimal():
    """Minimal shape (table only) must also round-trip."""
    mod = _load("render_report")
    src = {"table": "bgp_neighbors"}
    tag = mod._format_source_suffix(src)
    assert tag == "[src: bgp_neighbors]"
    assert mod.parse_src_token(tag) == src


def test_parse_src_token_roundtrip_device_only():
    mod = _load("render_report")
    src = {"table": "interfaces", "device": "R2"}
    tag = mod._format_source_suffix(src)
    parsed = mod.parse_src_token(tag)
    assert parsed == src
    assert mod._format_source_suffix(parsed) == tag


def test_parse_src_token_returns_none_on_invalid():
    mod = _load("render_report")
    assert mod.parse_src_token("") is None
    assert mod.parse_src_token("no token here") is None
    assert mod.parse_src_token("[src:]") is None
    assert mod.parse_src_token("[src: ]") is None
    assert mod.parse_src_token(None) is None  # type: ignore[arg-type]


def test_parse_src_token_tolerates_surrounding_text():
    """The parser should find a tag even when it's embedded in a line of
    markdown — callers will likely feed whole report lines in."""
    mod = _load("render_report")
    line = "- BGP flap on R1 [src: parsed_outputs#snap_a; device=R1; row=4] — repeat"
    parsed = mod.parse_src_token(line)
    assert parsed == {
        "table": "parsed_outputs",
        "snapshot_id": "snap_a",
        "device": "R1",
        "row_index": 4,
    }


def test_parse_src_token_ignores_unknown_key():
    """Graceful forward-compat: unknown segments (e.g. future ``col=...``)
    must not break the parser, just be skipped."""
    mod = _load("render_report")
    parsed = mod.parse_src_token("[src: t#s; device=R1; future_key=X; row=2]")
    assert parsed == {
        "table": "t",
        "snapshot_id": "s",
        "device": "R1",
        "row_index": 2,
    }


def test_parse_src_token_ignores_malformed_row_int():
    """Non-integer row value must be skipped, not raise."""
    mod = _load("render_report")
    parsed = mod.parse_src_token("[src: t#s; row=notanint]")
    assert parsed == {"table": "t", "snapshot_id": "s"}
