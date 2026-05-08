"""Tests for the submit_change_plan @tool — sim's structured-output deliverable.

R-AGENT-HIERARCHY Phase D: replaces the Markdown YAML block pattern
with LLM-tool-call structured output.  The Pydantic schema is enforced
at LangChain tool-call decode time; these tests cover the Python side
only (the LLM constraint is provider-side and tested in-vivo).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


def _load_submit_change_plan():
    """Load the tool from the sim sub-agent's tools/ dir.

    The skill workspace isn't on PYTHONPATH, so we load it explicitly.
    """
    here = Path(__file__).resolve().parents[2]
    tool_path = (
        here
        / "olav-netops"
        / ".olav"
        / "workspace"
        / "netops"
        / "sim"
        / "tools"
        / "submit_change_plan.py"
    )
    spec = importlib.util.spec_from_file_location(
        "submit_change_plan_module", tool_path
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["submit_change_plan_module"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_M = _load_submit_change_plan()


def test_slugify_basic():
    assert _M._slugify("R2-R3 eBGP!") == "r2-r3-ebgp"


def test_slugify_caps_at_60():
    s = _M._slugify("a" * 200)
    assert len(s) <= 60


def test_compose_plan_md_includes_required_sections():
    md = _M._compose_plan_md(
        intent="ebgp_direct",
        devices=["R2", "R3"],
        summary="Add eBGP between R2 and R3",
        rationale="Need redundant path.",
        steps="Phase 1: configure both devices.",
        feasibility="OK",
        feasibility_reason="",
        change_id="r2-r3-ebgp",
    )
    assert "# Change Plan: Add eBGP between R2 and R3" in md
    assert "**Intent**: `ebgp_direct`" in md
    assert "## Rationale" in md
    assert "Need redundant path." in md
    assert "## Steps" in md
    # Trailing summary block (for the deterministic renderer)
    assert "## Change Summary" in md
    assert "intent_type: ebgp_direct" in md
    assert "devices: ['R2', 'R3']" in md


def test_compose_plan_md_blocked_feasibility():
    md = _M._compose_plan_md(
        intent="ebgp_direct",
        devices=["R1", "R3"],
        summary="Add eBGP between R1 and R3",
        rationale="",
        steps="",
        feasibility="BLOCKED",
        feasibility_reason="same AS 65000",
        change_id="r1-r3-ebgp",
    )
    assert "Feasibility**: BLOCKED" in md
    assert "Feasibility reason**: same AS 65000" in md
    assert "feasibility: BLOCKED" in md
    assert 'feasibility_reason: "same AS 65000"' in md


def test_submit_rejects_too_many_devices(tmp_path):
    r = _M.submit_change_plan.invoke({
        "intent": "ebgp_direct",
        "devices": ["A", "B", "C", "D", "E"],
        "summary": "too many",
        "output_root": str(tmp_path),
    })
    assert r["status"] == "error"
    assert "1-4 entries" in r["error"]


def test_submit_rejects_zero_devices(tmp_path):
    r = _M.submit_change_plan.invoke({
        "intent": "ebgp_direct",
        "devices": [],
        "summary": "no devices",
        "output_root": str(tmp_path),
    })
    assert r["status"] == "error"
    assert "1-4 entries" in r["error"]


def test_submit_blocked_writes_md_but_no_tcf(tmp_path):
    """When sim flags feasibility=BLOCKED, render_tcf_from_change_plan
    returns error (no spec written), but the .md artifact still exists
    so the user can review the analysis."""
    r = _M.submit_change_plan.invoke({
        "intent": "ebgp_direct",
        "devices": ["R1", "R3"],
        "summary": "Add eBGP between R1 and R3",
        "rationale": "Same AS, eBGP impossible.",
        "feasibility": "BLOCKED",
        "feasibility_reason": "R1 and R3 both in AS 65000",
        "output_root": str(tmp_path),
    })
    assert r["status"] == "error"
    assert "feasibility=BLOCKED" in r["error"]
    plan_md_path = Path(r["plan_md_path"])
    assert plan_md_path.exists()
    assert "BLOCKED" in plan_md_path.read_text()


def test_submit_success_with_db_mocked(tmp_path):
    """Happy path: feasibility OK + DB returns different ASNs →
    .md saved, TCF spec.yaml written."""
    fake_facts = {
        "R2": {"platform": "cisco_ios", "loopback": "2.2.2.2", "local_as": 65001},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = _M.submit_change_plan.invoke({
            "intent": "ebgp_direct",
            "devices": ["R2", "R3"],
            "summary": "Add eBGP between R2 and R3",
            "rationale": "Redundant transit.",
            "steps": "Apply both phases atomically.",
            "feasibility": "OK",
            "output_root": str(tmp_path),
        })
    assert r["status"] == "ok"
    plan_md = Path(r["plan_md_path"])
    spec_yaml = Path(r["spec_path"])
    assert plan_md.exists()
    assert spec_yaml.exists()
    # The .md has both rationale and steps
    md_text = plan_md.read_text()
    assert "Redundant transit." in md_text
    assert "Apply both phases atomically." in md_text
    # The TCF YAML has DB-grounded facts
    yaml_text = spec_yaml.read_text()
    assert "prod_asn: 65001" in yaml_text
    assert "prod_asn: 65000" in yaml_text


def test_submit_auto_generates_change_id(tmp_path):
    """Empty change_id → auto-generated from devices + intent prefix."""
    fake_facts = {
        "R2": {"platform": "cisco_ios", "loopback": "2.2.2.2", "local_as": 65001},
        "R3": {"platform": "cisco_ios", "loopback": "3.3.3.3", "local_as": 65000},
    }
    with patch("olav.core.cab.tcf_writer._db_facts", return_value=fake_facts):
        r = _M.submit_change_plan.invoke({
            "intent": "ebgp_direct",
            "devices": ["R2", "R3"],
            "summary": "Some change",
            "output_root": str(tmp_path),
        })
    assert r["status"] == "ok"
    # Auto-generated change_id should include device names + intent
    assert "r2-r3-ebgp" in Path(r["plan_md_path"]).name


def test_submit_tool_args_schema_loaded():
    """The @tool decorator should expose a Pydantic args_schema with
    enum + list types — the LLM grammar constraint comes from this.
    """
    schema = _M.submit_change_plan.args_schema.model_json_schema()
    props = schema["properties"]
    # intent is a string with enum constraint
    assert "intent" in props
    assert props["intent"]["enum"] == ["ebgp_direct", "ibgp_direct", "vlan_add"]
    # devices is a typed list
    assert props["devices"]["type"] == "array"
    assert props["devices"]["items"]["type"] == "string"
    # feasibility is enum
    assert props["feasibility"]["enum"] == ["OK", "BLOCKED"]
    # required vs optional
    required = set(schema.get("required", []))
    assert "intent" in required
    assert "devices" in required
    assert "summary" in required
    # rationale, steps, feasibility_reason are optional
    assert "rationale" not in required
    assert "steps" not in required
