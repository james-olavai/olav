"""WRITER-01 — T2-14 tool-call-count threshold pin.

History:
    Round 28 (b): bumped threshold 3 → 8 to accommodate writer-arch
    ``olav_delegate`` internals that started counting against the ``🔧``
    grep (baseline ~5 → ~16).

    Round 39 (a): added origin tag ``🔧[orch]`` / ``🔧[sub]`` at the CLI
    emission point (``src/olav/cli/main.py``). Tier2 now filters on
    ``🔧[orch]`` so delegate internals drop out of the count, and the
    threshold can return to the original ``≤5`` baseline.

This test pins:

1. The threshold stays at 5 (post-Round-39 tight budget).
2. The T2-14 block greps on ``🔧[orch]`` (not bare ``🔧``).
3. The block carries WRITER-01 rationale so future readers understand why
   5 isn't arbitrary.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
TIER2_SCRIPT = REPO / "tests" / "ci" / "tier2_integration.sh"


def _t2_14_block() -> str:
    """Return just the T2-14 test block (from comment header to end-of-if)."""
    text = TIER2_SCRIPT.read_text(encoding="utf-8")
    start_match = re.search(r"^    # T2-14:.*$", text, re.MULTILINE)
    assert start_match, "Cannot find T2-14 block header in tier2_integration.sh"
    start = start_match.start()
    # Find the end of the enclosing `if` — the next line that starts with `fi`
    # at 4-space indent.
    end_match = re.search(r"^    fi$", text[start:], re.MULTILINE)
    assert end_match, "Cannot find end of T2-14 block"
    return text[start : start + end_match.end()]


def test_t2_14_block_exists():
    assert TIER2_SCRIPT.is_file(), f"missing CI script: {TIER2_SCRIPT}"
    block = _t2_14_block()
    assert "T2-14" in block


def test_t2_14_threshold_is_five_post_round_39():
    """Post-Round-39 threshold is 5 (orch-only filter replaces loose ≤8)."""
    block = _t2_14_block()
    assert re.search(r"-le\s+5\b", block), (
        "WRITER-01 regressed: T2-14 threshold is no longer ``-le 5``. "
        "If changing, update this test, the rationale comment, and document "
        "whether the origin tag is still doing its job."
    )
    # Pre-Round-39 values must not reappear.
    assert not re.search(r"-le\s+3\b", block), (
        "T2-14 threshold dropped back to ``-le 3`` — pre-writer-arch value."
    )
    assert not re.search(r"-le\s+8\b", block), (
        "T2-14 threshold is still the loose Round-28 ``-le 8`` — Round 39 "
        "added the origin tag specifically so we could tighten to 5."
    )


def test_t2_14_filters_on_orch_origin_tag():
    """Grep must target ``🔧[orch]`` — otherwise delegate internals leak in
    and the tight ≤5 budget fails on any delegation-heavy query."""
    block = _t2_14_block()
    assert "🔧[orch]" in block or r"🔧\[orch\]" in block, (
        "T2-14 no longer filters on 🔧[orch]; counts all tool calls including "
        "delegate internals — Round 39 WRITER-01 (a) regression."
    )


def test_t2_14_pass_and_warn_messages_use_five():
    """Human-readable threshold in messages should match the numeric check."""
    block = _t2_14_block()
    assert "≤5" in block, "pass_test message should say ≤5 (matches -le 5)"
    assert "> 5" in block, "warn_test message should say > 5 (matches -le 5)"


def test_t2_14_block_documents_writer_01_rationale():
    """The block must document *why* the threshold is what it is."""
    block = _t2_14_block()
    markers_any = ["WRITER-01", "olav_delegate", "origin tag", "orchestrator"]
    assert any(marker in block for marker in markers_any), (
        "T2-14 block missing WRITER-01 / origin-tag rationale comment. "
        "Future readers will think the threshold is arbitrary."
    )
