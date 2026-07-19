"""simulator/read_change_plan — the change-plan ingestion gap (2026-07-18).

The simulator's designed purpose is validating change plans, but callers
reference plans by FILE PATH and sub-agents have no filesystem tools — the
demo prompt "validate this change plan: exports/change_plans/x.md" dead-ended
with the sub-agent reporting it had no read script. This script closes the gap.

Wiring is exercised through execute_skill_script (the real entry point,
CLAUDE.md DoD) against the authoritative olav-netops workspace copy.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NETOPS_WS = REPO / "olav-netops" / ".olav" / "workspace"


def _run(args: dict | None, tmp_cwd, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_cwd)
    from olav.core.skill_runner import execute_skill_script

    out = execute_skill_script(
        "simulator", "read_change_plan.py", args=args, workspace_root=NETOPS_WS
    )
    assert out["status"] == "ok", out
    return out["stdout"]


def test_reads_plan_by_relative_path(tmp_path, monkeypatch):
    plans = tmp_path / "exports" / "change_plans"
    plans.mkdir(parents=True)
    (plans / "alpha_redundant_ebgp_uplink.md").write_text(
        "# Change plan\nAdd eBGP uplink R1→R4", encoding="utf-8"
    )
    result = _run(
        {"path": "exports/change_plans/alpha_redundant_ebgp_uplink.md"},
        tmp_path, monkeypatch,
    )
    assert result["status"] == "ok"
    assert "eBGP uplink" in result["content"]


def test_bare_filename_resolves_under_change_plans_dir(tmp_path, monkeypatch):
    plans = tmp_path / "exports" / "change_plans"
    plans.mkdir(parents=True)
    (plans / "plan_x.md").write_text("content-x", encoding="utf-8")
    result = _run({"path": "plan_x.md"}, tmp_path, monkeypatch)
    assert result["status"] == "ok" and result["content"] == "content-x"


def test_no_path_lists_available_plans(tmp_path, monkeypatch):
    """Empty arg = discovery, not 'none' (ADR-0009 Tier-1 #5)."""
    plans = tmp_path / "exports" / "change_plans"
    plans.mkdir(parents=True)
    (plans / "a.md").write_text("a", encoding="utf-8")
    (plans / "b.md").write_text("b", encoding="utf-8")
    result = _run(None, tmp_path, monkeypatch)
    assert result["available_plans"] == ["a.md", "b.md"]


def test_missing_file_returns_error_with_alternatives(tmp_path, monkeypatch):
    plans = tmp_path / "exports" / "change_plans"
    plans.mkdir(parents=True)
    (plans / "real.md").write_text("r", encoding="utf-8")
    result = _run({"path": "nope.md"}, tmp_path, monkeypatch)
    assert result["status"] == "error"
    assert result["available_plans"] == ["real.md"]


def test_declared_in_skill_md_all_copies():
    """name-form scripts: entry present in the authoritative copy AND the
    wheel-shipped skillpack copy (two-workspace sync rule) — for BOTH
    consumers (simulator + reporter Mode V; deepagents read_file only sees
    the virtual FS, so real-disk plan reading must go through this script)."""
    import yaml

    skillpack = (REPO / "olav-netops" / "src" / "olav_netops" / "data" / "skillpack"
                 / ".olav" / "workspace" / "netops")
    for agent in ("simulator", "reporter"):
        for ws in (NETOPS_WS / "netops", skillpack):
            skill_md = ws / agent / "SKILL.md"
            fm = yaml.safe_load(skill_md.read_text(encoding="utf-8").split("---")[1])
            entries = {s["name"]: s for s in fm.get("scripts", [])}
            assert "read_change_plan" in entries, f"missing scripts: entry in {skill_md}"
            assert entries["read_change_plan"]["file"] == "read_change_plan.py"
            assert "execute_skill_script" in fm["tools"]


def test_script_copies_byte_identical_to_canonical():
    canonical = (NETOPS_WS / "netops" / "scripts" / "read_change_plan.py").read_bytes()
    for agent in ("simulator", "reporter"):
        dup = (NETOPS_WS / "netops" / agent / "scripts" / "read_change_plan.py").read_bytes()
        assert dup == canonical, f"{agent} copy drifted from canonical netops/scripts"
