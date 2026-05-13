"""Staged-ReAct fill of DraftChangePlan — section-by-section, lint-after-each.

Pattern mirrors audit `render_report` reduce stage:
  * Section template = focused LLM prompt + just the context that section needs
  * LLM fills ONE section per call (not the whole envelope at once)
  * Lint runs immediately after each section
  * Retry that section (max 3) on lint fail
  * Final whole-draft lint before disk write

Designed so a 30B model can produce facts-complete, field-precise
drafts without hitting its short-context degradation. Each call has
a tiny working set.

This is an EXPERIMENT prototype (2026-05-13). For freeform_cli only.
Other intents added when proven valuable.

The `llm_callable` parameter is a thin abstraction:
    llm_callable(prompt: str) → str
Caller provides any chat model — local Ollama, OpenRouter, hand-mock.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from olav.core.cab.schemas import DraftChangePlan

from .lint import lint_draft, LintError


LLMCallable = Callable[[str], str]


# ────────────────────────────────────────────────────────────────────
# Section templates
# ────────────────────────────────────────────────────────────────────

SCOPE_PROMPT = """\
You are filling section S1 (scope) of a DraftChangePlan.

USER PROMPT:
{user_prompt}

Return ONLY a JSON object with these exact keys:
  - "user_prompt":      string (echo the user prompt verbatim)
  - "devices_in_scope": list of device hostnames (e.g. ["R1", "R3"])

NOTHING ELSE. Do not include explanation, just the JSON object.

Example output:
{{"user_prompt": "Add OSPF between R1 and R3", "devices_in_scope": ["R1", "R3"]}}
"""

FACTS_PROMPT = """\
You are filling section S2 (facts_collected) of a DraftChangePlan.

SCOPE: devices_in_scope = {devices_in_scope}

INSPECTOR OUTPUTS (raw JSON from inspect_devices + inspect_topology):

inspect_devices result:
{inspect_devices_json}

inspect_topology result:
{inspect_topology_json}

Return ONLY a JSON object with EXACTLY these keys:
{{
  "devices": [
    {{"name": "...", "platform": "...", "local_as": <int or null>, "loopback": "...", "interfaces": [...]}},
    ...
  ],
  "topology_edges": [
    {{"source_device": "...", "source_interface": "...", "destination_device": "...", "destination_interface": "...", "discovery_protocol": "..."}},
    ...
  ],
  "routing_state": {{}},
  "blast_radius": {{}}
}}

Rules (HARD):
  - Every device in {devices_in_scope} MUST appear in "devices".
  - For multi-device drafts (>=2 devices), "topology_edges" MUST be populated
    from inspect_topology output. Empty topology_edges for a multi-device draft
    is a lint failure.
  - Just COPY the inspector outputs verbatim — don't summarize or omit.

NOTHING ELSE. JSON only.
"""

INTENT_PROMPT = """\
You are filling section S3 (intent + rationale) of a DraftChangePlan.

USER PROMPT: {user_prompt}
SCOPE: {devices_in_scope}
FACTS SUMMARY: {facts_summary}

Choose ONE intent from: ebgp_direct, ibgp_direct, static_route_add, vlan_add, freeform_cli.

Rules:
  - If user wants OSPF / iBGP / static route etc. and there's no dedicated intent
    type, use freeform_cli (you'll provide CLI in S4).
  - If user wants eBGP between same-AS devices → BLOCKED (let sim reject).

Return ONLY a JSON object:
{{
  "proposed_intent": "<one of the 5>",
  "rationale": "<≥30 chars explaining WHY based on facts observed>"
}}

Example: {{"proposed_intent": "freeform_cli", "rationale": "Both R1 and R3 are AS 65000 directly connected; OSPF Area 0 will form IGP for R2 decommission."}}
"""

FREEFORM_CLI_ARGS_PROMPT = """\
You are filling section S4 (intent_args) for intent=freeform_cli.

CONTEXT:
  user_prompt: {user_prompt}
  devices_in_scope: {devices_in_scope}
  facts (per-device): {facts_summary}

==== VENDOR CLI AUTHORING GUIDE (FROM KB) ====
{cli_authoring_guide}
==== END GUIDE ====

Apply the rules above when composing CLI. In particular:
  - Junos: wrap with `configure` and `commit and-quit`
  - Cisco IOS: wrap with `configure terminal` and `end` + `write memory`
  - rollback symmetry: every `set` has a `delete`/`no`
  - post_check expected_pattern from the catalog, NEVER empty

You must compose intent_args with this EXACT schema. Field names are CASE-SENSITIVE
and must match verbatim — using synonyms ("expected" instead of "expected_pattern") is REJECTED.

{{
  "cli_per_device": {{
    "<DEVICE_NAME>": [
      "<cli line 1>",
      "<cli line 2>",
      ...
    ]
  }},
  "rollback_per_device": {{
    "<DEVICE_NAME>": ["<undo cli lines>"]
  }},
  "post_checks": [
    {{
      "device": "<one of devices_in_scope>",
      "command": "<show command, e.g. 'show ip ospf neighbor'>",
      "expected_pattern": "<substring/regex that must appear in command output>",
      "description": "<what this verifies>"
    }}
  ]
}}

HARD constraints (lint will reject any violation):
  1. Every device in {devices_in_scope} MUST have an entry in cli_per_device AND rollback_per_device.
  2. post_checks list MUST be non-empty.
  3. Each post_check MUST have FOUR keys: device, command, expected_pattern, description.
     - NOT "expected" — the canonical name is "expected_pattern".
     - NOT empty string — expected_pattern must be a real substring/regex that proves the change worked.
       e.g. "FULL" for OSPF adjacency, "192.0.2.0/24" for static route, "Description: uplink" for desc change.
  4. post_check.device MUST be in {devices_in_scope}.
  5. Use REAL prod CLI for the device platform — per the VENDOR CLI AUTHORING GUIDE above.
     Junos must include `configure` AND `commit and-quit` wrappers.
     Cisco IOS must include `configure terminal` AND `end` + `write memory` wrappers.

Return ONLY the JSON object. NOTHING else.
"""


# ────────────────────────────────────────────────────────────────────
# S5 — self-review pass (re-read assembled draft, propose fixes)
# ────────────────────────────────────────────────────────────────────

REVIEW_PROMPT = """\
You just composed this DraftChangePlan section by section. Now do a
final SELF-REVIEW of the assembled draft and identify any issues.

ASSEMBLED DRAFT:
{draft_json}

==== VENDOR CLI AUTHORING GUIDE (FROM KB) ====
{cli_authoring_guide}
==== END GUIDE ====

CHECKLIST — review each item against the guide:

1. **Per-device CLI completeness**
   - Junos devices: does `cli_per_device[<device>]` START with `configure`
     and END with `commit and-quit` (or `commit`)?
   - Cisco IOS devices: does it START with `configure terminal` and END
     with `end` then `write memory`?
   - Naked `set ...` (Junos) or `router ospf` (Cisco) without the wrapper
     is INCOMPLETE — operators executing this verbatim get a no-op.

2. **Rollback symmetry + wrapping**
   - Every impl `set X` has matching rollback `delete X` (Junos) or `no X` (Cisco)?
   - Rollback also wrapped with configure / commit / write memory?

3. **post_checks**
   - Every entry has device + command + expected_pattern (NON-EMPTY real
     substring) + description?
   - Field names are CANONICAL (NOT `expected`, NOT `cmd`, NOT `desc`)?

4. **facts_collected completeness**
   - Every device in scope has platform + local_as + loopback filled
     (no nulls where the DB would have a value)?

5. **Cross-field consistency**
   - Does facts.devices[].platform match the platform implied by the CLI
     (e.g. if cli_per_device has `set protocols`, that device should be junos;
     if `router ospf 1`, should be cisco_ios)?

Return ONLY JSON, NOTHING else:
{{
  "review_pass": <true|false>,
  "findings": ["<one-line per issue>"],
  "fixed_draft": <FULL corrected DraftChangePlan JSON if review_pass=false; omit if review_pass=true>
}}

If review_pass=true, "findings" can be empty list.

When emitting fixed_draft, return the COMPLETE draft (all top-level fields:
user_prompt, devices_in_scope, proposed_intent, intent_args, rationale,
facts_collected, revision_round, previous_blockers), not just the changed parts.
"""


def _validate_review(parsed: Any) -> list["LintError"]:
    from .lint import LintError
    errors: list[LintError] = []
    if not isinstance(parsed, dict):
        return [LintError(code="not_dict", message="review must be a JSON object", field="(root)")]
    if "review_pass" not in parsed:
        errors.append(LintError(code="review_pass_missing", message="must include 'review_pass' boolean", field="review_pass"))
    if not parsed.get("review_pass", True) and not parsed.get("fixed_draft"):
        errors.append(LintError(
            code="fixed_draft_missing",
            message="review_pass=false but 'fixed_draft' is missing",
            field="fixed_draft",
            hint="When review_pass=false, you MUST include the corrected draft as 'fixed_draft' (full DraftChangePlan).",
        ))
    return errors


# ────────────────────────────────────────────────────────────────────
# Memory / KB loader
# ────────────────────────────────────────────────────────────────────

def _load_cli_authoring_guide() -> str:
    """Read the change_plan_cli_authoring.guide.yaml body.

    Searches workspace guides dirs (cwd-relative) then a fallback empty
    string. NOT going through lancedb — staged-fill knows it always
    needs this guide, no semantic search required.
    """
    from pathlib import Path
    candidates = [
        Path.cwd() / ".olav/workspace/netops/guides/change_plan_cli_authoring.guide.yaml",
        Path.cwd() / "olav-netops/.olav/workspace/netops/guides/change_plan_cli_authoring.guide.yaml",
    ]
    for p in candidates:
        if p.exists():
            try:
                import yaml as _yaml
                data = _yaml.safe_load(p.read_text(encoding="utf-8"))
                body = (data or {}).get("body", "")
                if body:
                    return body
            except Exception:
                pass
    return ""


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction from LLM response (strips markdown fences,
    leading prose, trailing prose)."""
    s = text.strip()
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    # First { to matching last }
    if s.startswith("{") or s.startswith("["):
        return json.loads(s)
    # Find first JSON-looking block
    m = re.search(r"(\{.*\}|\[.*\])", s, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"no JSON object in response: {s[:200]}")


def _summarize_facts(devices: list[dict], edges: list[dict]) -> str:
    """Compact human-readable summary for prompts (keep token count low)."""
    parts = []
    for d in devices:
        parts.append(
            f"  - {d.get('name')}: platform={d.get('platform')} "
            f"AS={d.get('local_as')} loopback={d.get('loopback')}"
        )
    if edges:
        for e in edges:
            parts.append(
                f"  - link: {e.get('source_device')}.{e.get('source_interface')} "
                f"↔ {e.get('destination_device')}.{e.get('destination_interface')}"
            )
    return "\n".join(parts)


# ────────────────────────────────────────────────────────────────────
# Journal
# ────────────────────────────────────────────────────────────────────

@dataclass
class SectionAttempt:
    section: str
    attempt: int
    prompt_chars: int
    response_chars: int
    elapsed_s: float
    accepted: bool
    lint_errors: list[dict] = field(default_factory=list)
    parse_error: str = ""


@dataclass
class FillJournal:
    user_prompt: str
    attempts: list[SectionAttempt] = field(default_factory=list)
    final_lint_errors: list[dict] = field(default_factory=list)
    total_elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "user_prompt": self.user_prompt,
            "attempts": [a.__dict__ for a in self.attempts],
            "final_lint_errors": self.final_lint_errors,
            "total_elapsed_s": round(self.total_elapsed_s, 2),
            "per_section_stats": self.per_section_stats(),
        }

    def per_section_stats(self) -> dict:
        d: dict = {}
        for a in self.attempts:
            s = d.setdefault(a.section, {"attempts": 0, "accepted_on": None, "total_elapsed_s": 0.0})
            s["attempts"] += 1
            s["total_elapsed_s"] += a.elapsed_s
            if a.accepted and s["accepted_on"] is None:
                s["accepted_on"] = a.attempt
        return d


# ────────────────────────────────────────────────────────────────────
# Section runners — each ONE LLM call + lint
# ────────────────────────────────────────────────────────────────────

def _fill_section(
    section_name: str,
    prompt: str,
    llm: LLMCallable,
    journal: FillJournal,
    section_validator: Callable[[Any], list[LintError]],
    max_attempts: int = 3,
) -> Any:
    """Generic single-section fill loop. Returns parsed JSON on success.
    Raises RuntimeError if max_attempts exhausted."""

    last_errors: list[LintError] = []
    parse_err = ""
    current_prompt = prompt

    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        try:
            response = llm(current_prompt)
            parsed = _extract_json(response)
            parse_err = ""
            errors = section_validator(parsed)
        except (ValueError, json.JSONDecodeError) as e:
            response = ""
            parsed = None
            parse_err = str(e)[:300]
            errors = [LintError(code="json_parse_error", message=parse_err, field=section_name)]
        elapsed = time.time() - t0

        accepted = not errors and not parse_err
        journal.attempts.append(SectionAttempt(
            section=section_name, attempt=attempt,
            prompt_chars=len(current_prompt),
            response_chars=len(response or ""),
            elapsed_s=round(elapsed, 2),
            accepted=accepted,
            lint_errors=[e.to_dict() for e in errors],
            parse_error=parse_err,
        ))
        if accepted:
            return parsed

        last_errors = errors
        # Build retry prompt: original + lint feedback
        err_lines = "\n".join(
            f"  - [{e.code}] {e.message}" + (f"\n      HINT: {e.hint}" if e.hint else "")
            for e in errors
        )
        retry_note = (
            f"\n\nPrevious attempt #{attempt} REJECTED with these lint errors:\n"
            f"{err_lines}\n\n"
            f"Fix the issues above and return a corrected JSON object. "
            f"Do NOT include the errors in your response — just the fixed JSON."
        )
        current_prompt = prompt + retry_note

    raise RuntimeError(
        f"section '{section_name}' failed after {max_attempts} attempts. "
        f"Last lint errors: {[e.code for e in last_errors]}; parse_err: {parse_err}"
    )


def _validate_scope(parsed: Any) -> list[LintError]:
    errors: list[LintError] = []
    if not isinstance(parsed, dict):
        return [LintError(code="not_dict", message="scope must be a JSON object", field="(root)")]
    if not parsed.get("user_prompt"):
        errors.append(LintError(code="user_prompt_missing", message="missing 'user_prompt'", field="user_prompt"))
    devs = parsed.get("devices_in_scope")
    if not isinstance(devs, list) or not devs:
        errors.append(LintError(
            code="devices_in_scope_missing",
            message="'devices_in_scope' must be a non-empty list of strings",
            field="devices_in_scope",
            hint='Example: "devices_in_scope": ["R1", "R3"]',
        ))
    return errors


def _validate_facts(parsed: Any, scope: list[str], intent_hint: str = "") -> list[LintError]:
    errors: list[LintError] = []
    if not isinstance(parsed, dict):
        return [LintError(code="not_dict", message="facts must be a JSON object", field="(root)")]
    devs = parsed.get("devices")
    if not isinstance(devs, list) or not devs:
        errors.append(LintError(
            code="facts_devices_missing",
            message="'devices' must be a non-empty list",
            field="devices",
        ))
    else:
        names = {d.get("name") for d in devs if isinstance(d, dict)}
        missing = [d for d in scope if d not in names]
        if missing:
            errors.append(LintError(
                code="facts_devices_missing_scope",
                message=f"devices in scope but not in facts.devices: {missing}",
                field="devices",
            ))
        for i, d in enumerate(devs):
            if not isinstance(d, dict):
                errors.append(LintError(code="device_not_dict", message=f"devices[{i}] not a dict", field=f"devices[{i}]"))
                continue
            if not d.get("platform"):
                errors.append(LintError(
                    code="device_platform_missing",
                    message=f"devices[{i}] ({d.get('name')!r}) missing 'platform'",
                    field=f"devices[{i}].platform",
                ))
    edges = parsed.get("topology_edges")
    if len(scope) >= 2 and (not isinstance(edges, list) or not edges):
        errors.append(LintError(
            code="topology_edges_missing",
            message=f"multi-device draft ({len(scope)} devices) but topology_edges is empty",
            field="topology_edges",
            hint="Copy inspect_topology output into topology_edges as a list of "
                 "{source_device, source_interface, destination_device, destination_interface, discovery_protocol}",
        ))
    return errors


def _validate_intent(parsed: Any) -> list[LintError]:
    errors: list[LintError] = []
    if not isinstance(parsed, dict):
        return [LintError(code="not_dict", message="intent must be a JSON object", field="(root)")]
    intent = parsed.get("proposed_intent")
    if intent not in ("ebgp_direct", "ibgp_direct", "static_route_add", "vlan_add", "freeform_cli"):
        errors.append(LintError(
            code="invalid_intent",
            message=f"proposed_intent={intent!r} not in supported set",
            field="proposed_intent",
            hint="Choose from: ebgp_direct, ibgp_direct, static_route_add, vlan_add, freeform_cli",
        ))
    rationale = (parsed.get("rationale") or "").strip()
    if len(rationale) < 30:
        errors.append(LintError(
            code="rationale_too_short",
            message=f"rationale is only {len(rationale)} chars; need ≥30",
            field="rationale",
        ))
    return errors


def _validate_freeform_args(parsed: Any, scope: list[str]) -> list[LintError]:
    """Reuses the heavy lint from lint.py by wrapping into a fake DraftChangePlan."""
    errors: list[LintError] = []
    if not isinstance(parsed, dict):
        return [LintError(code="not_dict", message="intent_args must be a JSON object", field="(root)")]
    # Hand off to the shared lint via a minimal draft
    try:
        d = DraftChangePlan(
            user_prompt="(validation only)",
            devices_in_scope=scope,
            proposed_intent="freeform_cli",
            intent_args=parsed,
            rationale="(validation only — 30 char minimum filler text here OK)",
            facts_collected={
                "devices": [{"name": n, "platform": "unknown"} for n in scope],
                "topology_edges": [{"source_device": scope[0], "source_interface": "x",
                                    "destination_device": scope[-1], "destination_interface": "y"}] if len(scope) > 1 else [],
            },
        )
        # Use only the freeform_cli-specific lint pieces, not the cross-cutting ones
        from .lint import _lint_freeform_cli  # type: ignore
        for e in _lint_freeform_cli(d):
            errors.append(e)
    except Exception as e:
        errors.append(LintError(code="pydantic_error", message=str(e)[:300], field="(unknown)"))
    return errors


# ────────────────────────────────────────────────────────────────────
# Public entry
# ────────────────────────────────────────────────────────────────────

def run_staged_fill(
    *,
    user_prompt: str,
    llm: LLMCallable,
    inspect_devices: Callable[[list[str]], Any],
    inspect_topology: Callable[[list[str]], Any],
    max_attempts_per_section: int = 3,
) -> tuple[DraftChangePlan, FillJournal]:
    """Run the 4-section fill flow for freeform_cli.

    Args:
        user_prompt: original user request
        llm: callable that takes a prompt string, returns response string
        inspect_devices / inspect_topology: callables that take a device list,
                                            return dicts (mirroring the inspect_* tools)
        max_attempts_per_section: per-section retry budget (after this, raises)

    Returns:
        (draft, journal) — draft is a fully populated DraftChangePlan,
        journal records every LLM call + lint outcome for analysis.
    """
    journal = FillJournal(user_prompt=user_prompt)
    t_total = time.time()

    # S1 — scope
    scope_obj = _fill_section(
        "S1_scope",
        SCOPE_PROMPT.format(user_prompt=user_prompt),
        llm, journal, _validate_scope, max_attempts_per_section,
    )
    devices_in_scope = scope_obj["devices_in_scope"]

    # Run inspectors (deterministic Python, NOT LLM)
    insp_devices_out = inspect_devices(devices_in_scope)
    insp_topology_out = inspect_topology(devices_in_scope)

    # S2 — facts
    facts_obj = _fill_section(
        "S2_facts",
        FACTS_PROMPT.format(
            devices_in_scope=devices_in_scope,
            inspect_devices_json=json.dumps(insp_devices_out, default=str)[:2000],
            inspect_topology_json=json.dumps(insp_topology_out, default=str)[:2000],
        ),
        llm, journal,
        lambda p: _validate_facts(p, devices_in_scope),
        max_attempts_per_section,
    )

    # S3 — intent + rationale
    facts_summary = _summarize_facts(facts_obj.get("devices", []), facts_obj.get("topology_edges", []))
    intent_obj = _fill_section(
        "S3_intent",
        INTENT_PROMPT.format(
            user_prompt=user_prompt,
            devices_in_scope=devices_in_scope,
            facts_summary=facts_summary,
        ),
        llm, journal, _validate_intent, max_attempts_per_section,
    )

    # Load vendor CLI authoring guide once — injected into S4 + S5
    cli_authoring_guide = _load_cli_authoring_guide()

    # S4 — intent_args (only freeform_cli prototype here)
    intent_name = intent_obj["proposed_intent"]
    if intent_name == "freeform_cli":
        args_obj = _fill_section(
            "S4_intent_args",
            FREEFORM_CLI_ARGS_PROMPT.format(
                user_prompt=user_prompt,
                devices_in_scope=devices_in_scope,
                facts_summary=facts_summary,
                cli_authoring_guide=cli_authoring_guide or "(KB guide unavailable)",
            ),
            llm, journal,
            lambda p: _validate_freeform_args(p, devices_in_scope),
            max_attempts_per_section,
        )
    else:
        # Other intents: no intent_args needed for ebgp_direct etc. (renderer
        # synthesizes from facts). Future: add per-intent templates.
        args_obj = {}

    # Assemble initial draft
    draft = DraftChangePlan(
        user_prompt=user_prompt,
        devices_in_scope=devices_in_scope,
        proposed_intent=intent_name,
        intent_args=args_obj,
        rationale=intent_obj["rationale"],
        facts_collected=facts_obj,
        revision_round=0,
        previous_blockers=[],
    )

    # S5 — self-review pass. LLM reads the assembled draft, applies the
    # KB checklist, returns either review_pass=true OR a fixed_draft.
    # Only run for freeform_cli (where intent_args is non-trivial); other
    # intents have nothing to review until per-intent S4 templates land.
    # ALSO skip if S4's output is already lint-clean — memory guide
    # injection into S4 prompt usually nails it; running review when
    # there's nothing to fix wastes 500+s on 30B for no benefit.
    early_errors = lint_draft(draft)
    skip_review = (intent_name == "freeform_cli") and not early_errors
    if intent_name == "freeform_cli" and args_obj and not skip_review:
        try:
            review_obj = _fill_section(
                "S5_review",
                REVIEW_PROMPT.format(
                    draft_json=json.dumps(draft.model_dump(mode="json"),
                                            indent=2, default=str)[:8000],
                    cli_authoring_guide=cli_authoring_guide or "(KB guide unavailable)",
                ),
                llm, journal, _validate_review, max_attempts_per_section,
            )
            if not review_obj.get("review_pass") and review_obj.get("fixed_draft"):
                try:
                    fixed_draft = DraftChangePlan.model_validate(
                        review_obj["fixed_draft"]
                    )
                    # Re-lint the fixed draft; only adopt if it improves
                    # (≤ current lint errors) — never accept regressions.
                    orig_errors = lint_draft(draft)
                    fixed_errors = lint_draft(fixed_draft)
                    if len(fixed_errors) <= len(orig_errors):
                        draft = fixed_draft
                except Exception:
                    # fixed_draft doesn't validate → keep original
                    pass
        except RuntimeError:
            # Review section exhausted its retry budget — keep original
            # draft, let final lint be the gate.
            pass

    journal.total_elapsed_s = round(time.time() - t_total, 2)
    journal.final_lint_errors = [e.to_dict() for e in lint_draft(draft)]

    return draft, journal
