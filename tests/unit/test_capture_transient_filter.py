"""Auto-capture transient demotion — ISSUE-CAPTURE-TRANSIENT-FACTS.

Per-run artifacts (plan file paths, snapshot ids, "saved to …" statements)
used to be persisted as durable facts: 12 of 15 captures in one test day
were stale by the next run and crowded real knowledge out of the medium-tier
top_k=2 recall slots. Transient-looking captures now get a 24h expires_at
lease (ADR-0015 TTL column) and capped confidence instead of durability.
"""
from __future__ import annotations

from pathlib import Path

from olav.core.memory.middleware import _capture_expiry

REPO = Path(__file__).resolve().parents[2]


def test_run_artifact_captures_get_a_ttl():
    transients = [
        "AARNet redundancy change plan saved to exports/change_plans/aarnet_redundancy_alpha_20260718.md.",
        "Current change plan under validation: olav-demo/exports/change_plans/alpha_redundant_ebgp_uplink.md",
        "The audit report is located at exports/audit_reports/interface_health.json",
        "Snapshot snap_20260719_041337_imported contains 339 hosts.",
        "A change plan was drafted for a redundant eBGP uplink.",
    ]
    for text in transients:
        assert _capture_expiry(text) is not None, f"should be transient: {text!r}"


def test_durable_facts_stay_durable():
    durables = [
        "The alpha border router is alpha-border-4500x.net.demo.internal running Cisco IOS.",
        "Local AS for alpha-border-4500x is 136247 and AARNet peer AS is 7575.",
        "batfish/allinone is running and exposing ports 9996 and 9997.",
        "BGP compatibility issue identified with AARNet peer 10.112.177.205.",
        "The customer prefers reports in Simplified Chinese.",
    ]
    for text in durables:
        assert _capture_expiry(text) is None, f"should be durable: {text!r}"


def test_expiry_is_a_short_lease_not_a_far_future_date():
    from datetime import UTC, datetime, timedelta

    exp = _capture_expiry("plan saved to exports/change_plans/x_20260719.md")
    assert exp is not None
    assert exp - datetime.now(UTC) < timedelta(hours=25)


def test_store_path_wires_the_filter():
    """Wiring pin: the AutoCapture store loop must consult _capture_expiry
    and pass expires_at to add_memory."""
    src = (REPO / "src/olav/core/memory/middleware.py").read_text(encoding="utf-8")
    idx_cls = src.index("class AutoCaptureMiddleware")
    store_block = src[idx_cls:]
    assert "_capture_expiry(text)" in store_block
    assert "expires_at=_expires" in store_block
