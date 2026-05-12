"""Tests for tcf_writer — prose Change Summary → grounded TCF YAML.

Phase C of R-AGENT-HIERARCHY (dev_docs/73): the LLM never authors
TCF args; the writer parses a Markdown change plan and grounds all
facts from the DB before composing the TCF.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from olav.core.cab.tcf_writer import (
    _extract_summary,
    render_tcf_from_change_plan,
)


# ────────────────────────────────────────────────────────────────────
# Summary extraction
# ────────────────────────────────────────────────────────────────────


def test_extract_summary_fenced_yaml():
    plan = """
# Some prose

## Change Summary

```yaml
change_id: x1
intent_type: ebgp_direct
devices: [A, B]
```
"""
    s = _extract_summary(plan)
    assert s["change_id"] == "x1"
    assert s["devices"] == ["A", "B"]


def test_extract_summary_bare_body():
    plan = """
## Change Summary
change_id: x2
title: Bare YAML
intent_type: ibgp_direct
devices:
  - C
  - D

## Other section
"""
    s = _extract_summary(plan)
    assert s["change_id"] == "x2"
    assert s["devices"] == ["C", "D"]


def test_extract_summary_missing():
    assert _extract_summary("# No summary block here") == {}


def test_extract_summary_malformed_yaml():
    plan = """## Change Summary
```yaml
this is: not: valid: yaml: sequence
```
"""
    assert _extract_summary(plan) == {}


# ────────────────────────────────────────────────────────────────────
# render — error envelopes (no DB needed)
# ────────────────────────────────────────────────────────────────────


def test_render_no_summary():
    r = render_tcf_from_change_plan("# Just prose, no summary")
    assert r["status"] == "error"
    assert "no `## Change Summary`" in r["error"]


def test_render_missing_required_fields(tmp_path):
    plan = """
## Change Summary
```yaml
change_id: x1
intent_type: ebgp_direct
```
"""
    r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    assert "missing required fields" in r["error"]
    assert "title" in r["error"] and "devices" in r["error"]


def test_render_unknown_intent(tmp_path):
    # Use an intent that's neither in _INTENT_RENDERERS nor has a YAML
    # schema under src/olav/data/intent_schemas/. (vlan_add was used here
    # before rev 271; now that vlan_add.intent.yaml exists it's a valid
    # routed intent.)
    plan = """
## Change Summary
```yaml
change_id: x1
title: T
intent_type: completely_nonexistent_intent_xyz
devices: [A, B]
```
"""
    r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    assert "intent_type" in r["error"]


def test_render_empty_devices(tmp_path):
    plan = """
## Change Summary
```yaml
change_id: x1
title: T
intent_type: ebgp_direct
devices: []
```
"""
    r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    assert "devices" in r["error"]


def test_render_explicit_feasibility_blocked(tmp_path):
    plan = """
## Change Summary
```yaml
change_id: x1
title: Plan with explicit blocker
intent_type: ebgp_direct
devices: [A, B]
feasibility: BLOCKED
feasibility_reason: "no IGP between peers"
```
"""
    r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    assert "feasibility=BLOCKED" in r["error"]
    assert "no IGP between peers" in r["blockers"]


# ────────────────────────────────────────────────────────────────────
# render — DB-grounded scenarios (mock _db_facts)
# ────────────────────────────────────────────────────────────────────


def test_render_blocks_when_same_asn(tmp_path):
    """Both devices in same AS → eBGP impossible → BLOCK with grounded reason."""
    fake_facts = {
        "R1": {"platform": "juniper_junos", "loopback": "1.1.1.1", "local_as": 65000},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    plan = """
## Change Summary
```yaml
change_id: r1-r3-test
title: Add eBGP between R1 and R3
intent_type: ebgp_direct
devices: [R1, R3]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    assert "eBGP feasibility BLOCKED" in r["error"]
    assert "AS 65000" in r["error"]
    assert r["facts"] == fake_facts


def test_render_blocks_when_devices_count_wrong(tmp_path):
    """ebgp_direct requires exactly 2 devices."""
    fake_facts = {
        "R1": {"platform": "juniper_junos", "loopback": "1.1.1.1", "local_as": 65001},
        "R2": {"platform": "cisco_ios", "loopback": "2.2.2.2", "local_as": 65001},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    plan = """
## Change Summary
```yaml
change_id: r1-r2-r3-bogus
title: Add eBGP across 3 routers
intent_type: ebgp_direct
devices: [R1, R2, R3]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    # ISSUE-ARCH-40 (2026-05-12): error string now comes from the
    # shared intent_registry.require_two_devices helper.
    assert "ebgp_direct" in r["error"] and "exactly 2 devices" in r["error"]


def test_render_success_writes_grounded_tcf(tmp_path):
    """Different ASNs → render full TCF YAML with DB-derived facts."""
    fake_facts = {
        "R1": {"platform": "juniper_junos", "loopback": "1.1.1.1", "local_as": 65001},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    plan = """
## Change Summary
```yaml
change_id: r1-r3-success
title: Add eBGP between R1 and R3
intent_type: ebgp_direct
devices: [R1, R3]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        # Pass lab_subnet explicitly to keep the assertion stable.
        # When omitted, ARCH-36 pool allocator picks 192.0.2.x — also valid.
        r = render_tcf_from_change_plan(
            plan, output_dir=tmp_path, lab_subnet="172.16.99.0/30",
        )

    assert r["status"] == "ok"
    spec_path = Path(r["spec_path"])
    assert spec_path.exists()
    yaml_text = spec_path.read_text()
    # DB-grounded values made it into the TCF
    assert "prod_asn: 65001" in yaml_text
    assert "prod_asn: 65000" in yaml_text
    assert "prod_loopback: 1.1.1.1" in yaml_text
    assert "prod_loopback: 3.3.3.3" in yaml_text
    # Junos render included for R1
    assert "set protocols bgp group EBGP-R3 type external" in yaml_text
    # IOS render included for R3
    assert "router bgp 65000" in yaml_text
    assert "neighbor 172.16.99.1 remote-as 65001" in yaml_text  # peer R1
    # Post_check + tvt populated
    assert "PC-R1-bgp" in yaml_text
    assert "TC-bgp-R1-R3" in yaml_text


def test_render_via_yaml_schema_static_route_add(tmp_path):
    """Rev 271 Phase F integration: when the intent has a matching
    ``src/olav/data/intent_schemas/<intent>.intent.yaml``, dispatch
    routes through generic_intent_handler (no hand-coded Python
    needed in _INTENT_RENDERERS).
    """
    fake_facts = {
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }

    # generic_intent_handler opens its own duckdb conn via MAIN_DB_PATH.
    # We patch duckdb.connect to return a stub that serves the
    # static_route_add fact_lookups query.
    class _StubCursor:
        def __init__(self, row): self._row = row
        def fetchone(self): return self._row
    class _StubDB:
        def execute(self, sql, args=()):
            if "FROM netops.devices" in sql and "platform" in sql:
                return _StubCursor(("cisco_ios",))
            return _StubCursor(None)
        def close(self): pass

    plan = """
## Change Summary
```yaml
change_id: r3-static-rt-01
title: Add static route 192.0.2.0/24 via 10.0.13.1 on R3
intent_type: static_route_add
devices: [R3]
intent_args:
  src_device: R3
  dst_prefix: 192.0.2.0/24
  next_hop_ip: 10.0.13.1
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts), \
         patch("duckdb.connect", return_value=_StubDB()):
        r = render_tcf_from_change_plan(
            plan, output_dir=tmp_path, lab_subnet="172.16.99.0/30",
        )

    assert r["status"] == "ok", f"render failed: {r}"
    spec_path = Path(r["spec_path"])
    assert spec_path.exists()
    yaml_text = spec_path.read_text()
    # Cisco IOS static-route CLI from the YAML schema's Jinja templates
    assert "ip route 192.0.2.0 255.255.255.0 10.0.13.1" in yaml_text
    assert "no ip route 192.0.2.0 255.255.255.0 10.0.13.1" in yaml_text
    # Post-check command + expected pattern
    assert "show ip route 192.0.2.0/24" in yaml_text
    assert "expected_pattern: 10.0.13.1" in yaml_text


def test_render_via_yaml_schema_missing_intent_args(tmp_path):
    """YAML-schema-routed intents need an `intent_args:` block."""
    fake_facts = {
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    plan = """
## Change Summary
```yaml
change_id: r3-static-rt-no-args
title: Missing intent_args
intent_type: static_route_add
devices: [R3]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "error"
    assert "intent_args" in r["error"]


def test_render_warns_on_db_gaps(tmp_path):
    """Partial DB facts → spec written with placeholders + warnings surfaced."""
    fake_facts = {
        "R1": {"platform": "juniper_junos", "loopback": None, "local_as": 65001},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    plan = """
## Change Summary
```yaml
change_id: r1-r3-partial
title: T
intent_type: ebgp_direct
devices: [R1, R3]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "ok"
    assert any("DB gap for R1" in w for w in r["warnings"])
    assert "loopback" in r["warnings"][0]


def test_render_facts_in_response_envelope(tmp_path):
    """The response always includes the grounded facts so the agent
    can show the user what the DB returned."""
    fake_facts = {
        "R2": {"platform": "cisco_ios", "loopback": "2.2.2.2", "local_as": 65001},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    plan = """
## Change Summary
```yaml
change_id: r2-r3-test
title: T
intent_type: ebgp_direct
devices: [R2, R3]
```
"""
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = render_tcf_from_change_plan(plan, output_dir=tmp_path)
    assert r["status"] == "ok"
    assert r["facts"]["R2"]["local_as"] == 65001
    assert r["facts"]["R3"]["local_as"] == 65000
