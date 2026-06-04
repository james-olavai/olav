"""Tests for ISSUE-AUDIT-NO-ALERTING-CHANNEL (P2, 2026-05-12).

``render_report._post_critical_alert`` POSTs an audit summary to
``OLAV_ALERT_WEBHOOK_URL`` when Critical findings (or a stale-data
warning) exist. Verified properties:

  * webhook URL unset → no POST (no network call)
  * Critical findings present + webhook set → POST with structured payload
  * Only Warning + threshold=critical → no POST
  * Only Warning + threshold=warning → POST
  * Freshness warning alone → POST even with no Critical findings
  * Webhook failure (HTTP error, timeout) → swallowed, audit not broken
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_RR_PATH = Path(
    str(Path(__file__).resolve().parents[2] / "olav-netops/.olav/workspace/audit/audit-runner/scripts/render_report.py"
)


@pytest.fixture(scope="module")
def render_report():
    spec = importlib.util.spec_from_file_location("_test_rr_alert", _RR_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_rr_alert"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolate_dedup_state(monkeypatch):
    """Default dedup OFF for tests that don't explicitly test dedup —
    otherwise shared `/tmp/.audit_alert_state.json` causes cross-test
    contamination (one test's POST is dedup'd against another's
    fingerprint). Dedup tests override this fixture by re-setting the
    env var inside the test body."""
    monkeypatch.setenv("OLAV_ALERT_DEDUP_WINDOW_SECONDS", "0")


def _make_audit_json(*, critical: int = 0, warning: int = 0, freshness: dict | None = None) -> dict:
    findings = []
    for i in range(critical):
        findings.append({
            "device": f"R{i}", "metric_value": 0, "severity_hint": "Critical",
        })
    for i in range(warning):
        findings.append({
            "device": f"SW{i}", "metric_value": 1, "severity_hint": "Warning",
        })
    return {
        "profile": "test_profile",
        "generated_at": "2026-05-12T00:00:00Z",
        "freshness_warning": freshness,
        "jobs": {
            "test_job": {
                "severity": "Critical" if critical else "Warning",
                "count": len(findings),
                "findings": findings,
            },
        },
    }


# ── webhook URL unset → no POST ──────────────────────────────────────────


def test_no_webhook_url_no_post(render_report, monkeypatch):
    monkeypatch.delenv("OLAV_ALERT_WEBHOOK_URL", raising=False)
    with patch("urllib.request.urlopen") as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(critical=2),
            profile_name="test_profile",
            report_path="/tmp/r.md",
            executive_summary="2 critical",
        )
    assert mock_open.call_count == 0, "must not attempt POST when URL unset"


# ── Critical findings → POST ─────────────────────────────────────────────


def test_critical_findings_trigger_post(render_report, monkeypatch):
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(critical=3, warning=1),
            profile_name="bgp_health",
            report_path="/tmp/r.md",
            executive_summary="3 critical, 1 warning",
        )
    assert mock_open.call_count == 1
    req = mock_open.call_args.args[0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["profile"] == "bgp_health"
    assert payload["critical_count"] == 3
    assert payload["warning_count"] == 1
    assert len(payload["critical_findings"]) == 3


# ── Warning-only + critical-threshold → no POST ──────────────────────────


def test_warning_only_with_critical_threshold_no_post(render_report, monkeypatch):
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    monkeypatch.setenv("OLAV_ALERT_SEVERITY", "critical")
    with patch("urllib.request.urlopen") as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(warning=2),
            profile_name="p",
            report_path="/tmp/r.md",
            executive_summary="only warnings",
        )
    assert mock_open.call_count == 0


def test_warning_only_with_warning_threshold_triggers_post(render_report, monkeypatch):
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    monkeypatch.setenv("OLAV_ALERT_SEVERITY", "warning")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(warning=2),
            profile_name="p",
            report_path="/tmp/r.md",
            executive_summary="warnings only",
        )
    assert mock_open.call_count == 1


# ── Freshness warning alone (no Critical findings) → POST ────────────────


def test_freshness_warning_alone_triggers_post(render_report, monkeypatch):
    """Stale data is itself a critical condition for audit trustworthiness
    — even if no per-finding Critical was emitted, the freshness gate
    fires the alert."""
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(
                critical=0, warning=0,
                freshness={"type": "stale_data", "max_hours_since_last_seen": 273.0},
            ),
            profile_name="p",
            report_path="/tmp/r.md",
            executive_summary="stale only",
        )
    assert mock_open.call_count == 1
    req = mock_open.call_args.args[0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["freshness_warning"] is not None
    assert payload["freshness_warning"]["max_hours_since_last_seen"] == 273.0


# ── No findings + no freshness → no POST ─────────────────────────────────


def test_clean_run_no_post(render_report, monkeypatch):
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    with patch("urllib.request.urlopen") as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(critical=0, warning=0, freshness=None),
            profile_name="p",
            report_path="/tmp/r.md",
            executive_summary="all green",
        )
    assert mock_open.call_count == 0


# ── Webhook failure must not raise ───────────────────────────────────────


def test_webhook_failure_swallowed(render_report, monkeypatch):
    """Audit must always produce a report even when the alert receiver
    is unreachable. Webhook exceptions are logged + swallowed."""
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:1/dead")
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("nope")):
        # Should NOT raise.
        render_report._post_critical_alert(
            audit_json=_make_audit_json(critical=1),
            profile_name="p",
            report_path="/tmp/r.md",
            executive_summary="x",
        )
    # If we got here without exception, the swallow worked.


# ── Payload caps unbounded inputs ────────────────────────────────────────


def test_payload_caps_critical_findings_list(render_report, monkeypatch):
    """A 1000-finding audit shouldn't ship a 1000-element payload —
    cap at a reasonable number so the webhook receiver isn't DDoS'd."""
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        render_report._post_critical_alert(
            audit_json=_make_audit_json(critical=500),
            profile_name="p",
            report_path="/tmp/r.md",
            executive_summary="x" * 10000,
        )
    payload = json.loads(mock_open.call_args.args[0].data.decode("utf-8"))
    assert payload["critical_count"] == 500, "counter reports TRUE total"
    assert len(payload["critical_findings"]) <= 20, "list capped to keep payload small"
    assert len(payload["executive_summary"]) <= 4000, "summary truncated"


# ── Dedup (2026-05-12 follow-up) ─────────────────────────────────────────


def test_dedup_swallows_duplicate_in_window(render_report, monkeypatch, tmp_path):
    """Same Critical condition fired twice within dedup window → second
    POST is swallowed. Prevents alert fatigue on long-running incidents."""
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    monkeypatch.setenv("OLAV_ALERT_DEDUP_WINDOW_SECONDS", "3600")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    report = tmp_path / "report.md"
    report.write_text("body")
    audit = _make_audit_json(critical=3)
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        # First call → POST
        render_report._post_critical_alert(
            audit_json=audit, profile_name="p", report_path=str(report),
            executive_summary="x",
        )
        # Second call with identical signal → swallowed
        render_report._post_critical_alert(
            audit_json=audit, profile_name="p", report_path=str(report),
            executive_summary="x",
        )
    assert mock_open.call_count == 1, (
        "duplicate critical condition in dedup window must not re-POST"
    )
    # State file should exist next to report
    state_path = report.parent / ".audit_alert_state.json"
    assert state_path.exists()
    import json as _json
    state = _json.loads(state_path.read_text())
    assert len(state) == 1
    fingerprint = next(iter(state))
    assert state[fingerprint]["sent_count"] >= 1
    assert state[fingerprint]["profile"] == "p"


def test_dedup_different_critical_set_posts(render_report, monkeypatch, tmp_path):
    """Different Critical findings → fingerprint differs → POST sent."""
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    monkeypatch.setenv("OLAV_ALERT_DEDUP_WINDOW_SECONDS", "3600")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    report = tmp_path / "report.md"
    report.write_text("body")
    audit_a = _make_audit_json(critical=3)
    # Re-shape critical findings so they have a different device set
    audit_b = {
        **audit_a,
        "jobs": {
            "test_job": {
                "severity": "Critical", "count": 2, "findings": [
                    {"device": "DIFFERENT_DEVICE_A", "metric_value": 0, "severity_hint": "Critical"},
                    {"device": "DIFFERENT_DEVICE_B", "metric_value": 0, "severity_hint": "Critical"},
                ],
            },
        },
    }
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        render_report._post_critical_alert(
            audit_json=audit_a, profile_name="p", report_path=str(report),
            executive_summary="x",
        )
        render_report._post_critical_alert(
            audit_json=audit_b, profile_name="p", report_path=str(report),
            executive_summary="x",
        )
    assert mock_open.call_count == 2, (
        "different critical-device sets should each trigger a POST"
    )


def test_dedup_disabled_when_window_zero(render_report, monkeypatch, tmp_path):
    """OLAV_ALERT_DEDUP_WINDOW_SECONDS=0 → no dedup, every alert posts."""
    monkeypatch.setenv("OLAV_ALERT_WEBHOOK_URL", "http://localhost:9999/hook")
    monkeypatch.setenv("OLAV_ALERT_DEDUP_WINDOW_SECONDS", "0")
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    report = tmp_path / "report.md"
    report.write_text("body")
    audit = _make_audit_json(critical=3)
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        render_report._post_critical_alert(
            audit_json=audit, profile_name="p", report_path=str(report),
            executive_summary="x",
        )
        render_report._post_critical_alert(
            audit_json=audit, profile_name="p", report_path=str(report),
            executive_summary="x",
        )
    assert mock_open.call_count == 2


def test_dedup_fingerprint_excludes_timestamps_and_counts(render_report):
    """Fingerprint must be stable across runs even when timestamps /
    exact metric values change — only device + metric_name + freshness
    presence drive it."""
    fp1 = render_report._alert_fingerprint(
        profile_name="bgp_health",
        critical_findings=[
            {"device": "SW1", "metric_name": "BGP Neighbor Count", "metric_value": 0},
            {"device": "SW2", "metric_name": "BGP Neighbor Count", "metric_value": 0},
        ],
        freshness_present=True,
    )
    fp2 = render_report._alert_fingerprint(
        profile_name="bgp_health",
        critical_findings=[
            # Same device + metric, different metric_value (counter ticked)
            {"device": "SW1", "metric_name": "BGP Neighbor Count", "metric_value": 1},
            {"device": "SW2", "metric_name": "BGP Neighbor Count", "metric_value": 1},
        ],
        freshness_present=True,
    )
    assert fp1 == fp2, "fingerprint should NOT depend on metric_value (counter noise)"
    fp3 = render_report._alert_fingerprint(
        profile_name="bgp_health",
        critical_findings=[
            {"device": "SW1", "metric_name": "BGP Neighbor Count", "metric_value": 0},
        ],
        freshness_present=True,
    )
    assert fp1 != fp3, (
        "different set of critical devices → different fingerprint"
    )
