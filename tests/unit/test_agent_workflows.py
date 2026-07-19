"""Declarative cross-subagent workflows (src/olav/agents/workflows.py).

The change-plan orchestration moved from hand-written SKILL.md prose to
``workflows/*.workflow.yaml`` data rendered deterministically into the
orchestrator prompt. Covers: schema parsing, validation fallbacks (bad yaml
/ unknown step agent / header mismatch must skip, never break boot),
rendering fidelity to the live-proven prompt shape, and the real netops
declaration.
"""
from __future__ import annotations

from pathlib import Path

from olav.agents.workflows import (
    load_workflows,
    render_workflow_prompt,
    render_workflows_section,
)

REPO = Path(__file__).resolve().parents[2]
NETOPS_DIR = REPO / "olav-netops" / ".olav" / "workspace" / "netops"

_VALID = """\
name: demo_flow
title: Demo workflow
trigger: demo intent
artifact: the file path from step 1
steps:
  - agent: alpha
    prompt: <original request>
    returns: extract the path
  - agent: beta
    prompt: '"verify <path>"'
assembly:
  headers: [Draft, Check]
"""


def _write(tmp_path: Path, content: str, name: str = "demo.workflow.yaml") -> Path:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir(exist_ok=True)
    (wf_dir / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_loads_valid_workflow(tmp_path):
    wfs = load_workflows(_write(tmp_path, _VALID))
    assert len(wfs) == 1
    wf = wfs[0]
    assert [s.agent for s in wf.steps] == ["alpha", "beta"]
    assert wf.headers == ("Draft", "Check")


def test_render_matches_proven_prompt_shape(tmp_path):
    wf = load_workflows(_write(tmp_path, _VALID))[0]
    text = render_workflow_prompt(wf)
    assert "## Demo workflow" in text
    assert '1. `task("alpha", <original request>)`' in text
    assert '2. `task("beta", "verify <path>")`' in text
    assert "stacked verbatim" in text
    assert "## Draft" in text and "## Check" in text
    assert "Never retry a step more than once" in text  # default on_failure


def test_bad_yaml_skipped_not_raised(tmp_path):
    _write(tmp_path, "steps: [only_one_entry_and_not_even_a_mapping")
    assert load_workflows(tmp_path) == []


def test_single_step_rejected(tmp_path):
    single = "name: x\nsteps:\n  - agent: a\n    prompt: p\n"
    _write(tmp_path, single)
    assert load_workflows(tmp_path) == []


def test_undeclared_step_agent_skips_workflow(tmp_path):
    _write(tmp_path, _VALID)
    assert load_workflows(tmp_path, declared_subagents={"alpha"}) == []
    assert len(load_workflows(tmp_path, declared_subagents={"alpha", "beta"})) == 1


def test_header_count_mismatch_skipped(tmp_path):
    bad = _VALID.replace("headers: [Draft, Check]", "headers: [OnlyOne]")
    _write(tmp_path, bad)
    assert load_workflows(tmp_path) == []


def test_no_workflows_dir_renders_empty(tmp_path):
    assert render_workflows_section(tmp_path) == ""


# ── the real netops declaration ───────────────────────────────────────────


_NETOPS_SUBAGENTS = {"analyzer", "reporter", "simulator", "collector",
                     "importer", "topology", "learner", "writer"}


def test_netops_change_plan_workflow_valid():
    wfs = load_workflows(NETOPS_DIR, declared_subagents=_NETOPS_SUBAGENTS)
    names = {w.name for w in wfs}
    assert "change_plan" in names
    wf = next(w for w in wfs if w.name == "change_plan")
    assert [s.agent for s in wf.steps] == ["analyzer", "reporter", "simulator"]
    text = render_workflow_prompt(wf)
    assert "Pre-check the change plan at <path>" in text
    assert "Batfish" in text


def test_netops_decommission_workflow_valid():
    """Phase 1 (dev_docs/102): decommission_impact — same trio, tailored
    prompts (independent blast-radius recomputation + removal-focused
    Batfish check)."""
    wfs = load_workflows(NETOPS_DIR, declared_subagents=_NETOPS_SUBAGENTS)
    wf = next(w for w in wfs if w.name == "decommission_impact")
    assert [s.agent for s in wf.steps] == ["analyzer", "reporter", "simulator"]
    text = render_workflow_prompt(wf)
    assert "recompute the blast radius" in text
    assert "reachability is lost" in text


def test_netops_workflow_triggers_are_disjoint_on_removal_intent():
    """change_plan and decommission_impact must not both claim
    remove/decommission — an ambiguous trigger makes the orchestrator's
    workflow choice a coin flip."""
    wfs = {w.name: w for w in load_workflows(NETOPS_DIR)}
    cp, dc = wfs["change_plan"], wfs["decommission_impact"]
    for kw in ("decommission", "remove"):
        assert kw in dc.trigger.lower()
        # change_plan may MENTION the redirect, but must not claim the intent
        assert f'"{kw}' not in cp.trigger.split("Removal")[0].lower().replace("/ ", '"'), (
            f"change_plan trigger must not claim {kw!r}"
        )
    assert "add" in cp.trigger.lower() and "modify" in cp.trigger.lower()


def test_audit_domain_ships_no_workflows():
    """Phase 2 (dev_docs/102) resolution: the audit lifecycle workflow was
    validated for platform-generality, then WITHDRAWN — 0/3 behavioral (the
    orchestrator's mature passthrough hard-rule wins over injected
    workflows) and low operational value (author/run are naturally separate
    in real usage). The PROFILE_PATH output contract and the deterministic
    grader stay. If someone re-adds an audit workflow, they must re-read
    dev_docs/102 §Phase 2 first."""
    audit_dir = REPO / "src" / "olav" / "data" / "workspace" / "audit"
    assert load_workflows(audit_dir) == []


def test_netops_skill_md_no_longer_carries_the_prose_workflow():
    """The orchestration must live in YAML only — a re-added prose copy in
    SKILL.md would drift from the declaration."""
    body = (NETOPS_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert 'task("reporter", "Pre-check the change plan' not in body
    assert "workflows/*.workflow.yaml" in body  # pointer note stays


def test_wired_into_orchestrator_prompt_builder():
    """Wiring proof: _get_orchestrator_prompt must call the renderer."""
    src = (REPO / "src/olav/agents/agent.py").read_text(encoding="utf-8")
    assert "render_workflows_section" in src
    idx_fn = src.index("def _get_orchestrator_prompt")
    idx_call = src.index("render_workflows_section")
    assert idx_call > idx_fn, "workflow injection must live inside _get_orchestrator_prompt"
