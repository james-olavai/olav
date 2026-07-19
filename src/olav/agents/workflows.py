"""Declarative cross-subagent workflows — YAML data, not SKILL.md prose.

A domain orchestrator can ship known-shape multi-step workflows (e.g.
change-plan: draft → pre-check → formally verify) as
``<agent_dir>/workflows/*.workflow.yaml`` instead of hand-written prompt
sections. The platform renders each declaration into a deterministic prompt
block appended to the orchestrator's system prompt.

Why data-not-prose: the sequence is domain KNOWLEDGE, not agent voice —
keeping it in YAML makes workflows diffable, testable (schema-validated,
step agents checked against the declared subagents), and reusable by a
future Python-executed pipeline runner without re-parsing markdown.

Schema (``schema_version: 1``)::

    name: change_plan               # required, kebab/snake identifier
    title: Change-plan workflow     # heading shown to the model
    trigger: change-plan intent ... # one line: when to use this workflow
    artifact: the plan FILE PATH …  # what travels between steps (one line)
    steps:                          # ≥2 ordered delegations
      - agent: analyzer             # must be a declared sub-agent name
        prompt: <the original user request>
        returns: reply names the saved plan path — extract it   # optional
      - agent: reporter
        prompt: "Pre-check the change plan at <path>: …"
    assembly:                       # how to return the results
      headers: [Draft, Pre-check (reporter), …]  # one per step
    on_failure: include what you have and note the failed step …  # optional

Loader never raises — a malformed workflow file is logged and skipped
(an orchestrator must still boot if a domain ships a bad yaml).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_ON_FAILURE = (
    "If a step errors or the artifact cannot be found, include what you have "
    "and note the failed step. Never retry a step more than once; never reorder."
)


@dataclass(frozen=True)
class WorkflowStep:
    agent: str
    prompt: str
    returns: str = ""


@dataclass(frozen=True)
class Workflow:
    name: str
    title: str
    trigger: str
    artifact: str
    steps: tuple[WorkflowStep, ...]
    headers: tuple[str, ...]
    on_failure: str = _DEFAULT_ON_FAILURE
    source: str = ""


def _parse_workflow(path: Path) -> Workflow | None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("not a mapping")
    steps_raw = raw.get("steps") or []
    if len(steps_raw) < 2:
        raise ValueError("a workflow needs ≥2 steps (single-step = plain routing)")
    steps = tuple(
        WorkflowStep(
            agent=str(s["agent"]).strip(),
            prompt=str(s["prompt"]).strip(),
            returns=str(s.get("returns", "")).strip(),
        )
        for s in steps_raw
    )
    headers = tuple(str(h) for h in (raw.get("assembly", {}) or {}).get("headers", []))
    if headers and len(headers) != len(steps):
        raise ValueError(f"assembly.headers has {len(headers)} entries for {len(steps)} steps")
    if not headers:
        headers = tuple(s.agent for s in steps)
    return Workflow(
        name=str(raw.get("name") or path.stem),
        title=str(raw.get("title") or raw.get("name") or path.stem),
        trigger=str(raw.get("trigger", "")).strip(),
        artifact=str(raw.get("artifact", "")).strip(),
        steps=steps,
        headers=headers,
        on_failure=str(raw.get("on_failure") or _DEFAULT_ON_FAILURE).strip(),
        source=str(path),
    )


def load_workflows(
    agent_dir: Path, declared_subagents: set[str] | None = None
) -> list[Workflow]:
    """Load ``<agent_dir>/workflows/*.workflow.yaml``; skip invalid files.

    When *declared_subagents* is given, a workflow whose step references an
    undeclared agent is skipped (routing to a nonexistent sub-agent would
    fail at runtime — better to fall back to plain single-route dispatch).
    """
    wf_dir = Path(agent_dir) / "workflows"
    if not wf_dir.is_dir():
        return []
    out: list[Workflow] = []
    for path in sorted(wf_dir.glob("*.workflow.yaml")):
        try:
            wf = _parse_workflow(path)
        except Exception as exc:  # noqa: BLE001 — bad yaml must not block boot
            logger.warning("workflow %s skipped: %s", path.name, exc)
            continue
        if wf is None:
            continue
        if declared_subagents is not None:
            unknown = [s.agent for s in wf.steps if s.agent not in declared_subagents]
            if unknown:
                logger.warning(
                    "workflow %s skipped: steps reference undeclared sub-agent(s) %s",
                    path.name, unknown,
                )
                continue
        out.append(wf)
    return out


def render_workflow_prompt(wf: Workflow) -> str:
    """Render one workflow as the orchestrator prompt block.

    The output structure mirrors the hand-written section that was proven
    live (2026-07-19 change-plan run): numbered task() calls, artifact
    passed by reference, verbatim stacked assembly, bounded failure rule.
    """
    lines: list[str] = [f"## {wf.title}", ""]
    if wf.trigger:
        lines += [f"When to use: {wf.trigger}", ""]
    lines.append(
        f"Make {len(wf.steps)} `task` calls in this order"
        + (
            f", passing the artifact — {wf.artifact} — forward between steps"
            if wf.artifact
            else ""
        )
        + ":",
    )
    lines.append("")
    for i, step in enumerate(wf.steps, 1):
        lines.append(f'{i}. `task("{step.agent}", {step.prompt})`')
        if step.returns:
            lines.append(f"   → {step.returns}")
    lines += [
        "",
        "Then return the results stacked verbatim under these headers — "
        "no paraphrasing, no re-writing:",
        "",
        "```",
    ]
    for header in wf.headers:
        lines.append(f"## {header}")
        lines.append("<that step's reply>")
    lines += ["```", "", wf.on_failure]
    return "\n".join(lines)


def render_workflows_section(
    agent_dir: Path, declared_subagents: set[str] | None = None
) -> str:
    """All workflows for an agent as one prompt section ('' when none)."""
    workflows = load_workflows(agent_dir, declared_subagents)
    if not workflows:
        return ""
    return "\n\n".join(render_workflow_prompt(wf) for wf in workflows)
