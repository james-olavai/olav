"""LLM-driven semantic verdict for paired (spec, lab) CLI blocks (R94.3).

The deterministic ``tcf_diff_spec_vs_lab`` only emits structural verdicts
(missing / extra / tvt / post_check). Per R94.2 policy, semantic
judgement of paired implementation / rollback blocks is the agent's job
— the agent reads both sides via sandbox file tools and renders a real
``approved`` / ``rejected`` / ``info`` verdict per pair.

This module is the deterministic Python *helper* the agent calls. It
takes a loaded ``CabTcf``, prompts the configured chat model once per
paired block, parses the JSON reply, and returns a ``list[StepVerdict]``
ready to feed into ``tcf_record_lab_run(step_verdicts=...)``.

Failure mode: any LLM/parse error becomes an ``info`` verdict with a
diagnostic reason — never silently swallowed and never crashes the
caller. CAB approver sees "LLM review failed: <reason>" and knows to
re-run or do manual review.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .tcf_schema import CabTcf, CliBlock, StepVerdict


_REVIEW_PROMPT = """You are a CAB change-control auditor.

Compare sim's prod-form CLI vs lab's SRL twin CLI for one device.

INTENT: {intent}

SPEC ({spec_kind}, device {device}, prod form — real {platform_hint} CLI ops will run in production):
{spec_cli}

LAB ({lab_kind}, container twin, SRL CLI pushed to digital twin):
{lab_cli}

Judge: does the lab SRL config faithfully validate the spec's intent? \
Compare AS numbers, neighbor IPs, BGP groups, policy intent.

Reply ONLY with JSON, no prose, no code fence:
{{"verdict": "approved"|"rejected"|"info", "reason": "<one short sentence, <120 chars>"}}

Rules:
- "approved" if AS numbers AND neighbor IPs match across vendors AND \
the BGP topology kind (eBGP / iBGP) is the same.
- "rejected" if any critical mismatch (different ASN, neighbor IP, \
or topology kind).
- "info" for non-blocking semantic notes (e.g. policy names differ \
by vendor convention but intent identical).
"""


def _format_cli(cli: list[str]) -> str:
    """Indent CLI lines for prompt readability."""
    return "\n".join(f"  {line}" for line in cli)


def _parse_verdict_response(raw: str) -> tuple[str, str]:
    """Extract ``(verdict, reason)`` from a model reply. Tolerates
    code fences, leading/trailing prose, embedded newlines.

    Returns ``(verdict, reason)`` with verdict in
    {approved, rejected, info}; on parse failure returns
    ``("info", "<failure description>")``.
    """
    if not raw or not raw.strip():
        return "info", "LLM returned empty response"
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if not match:
        return "info", f"LLM reply contained no JSON object: {raw[:120]!r}"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return "info", f"LLM reply JSON parse failed: {exc}"
    verdict = data.get("verdict", "info")
    reason = data.get("reason", "(no reason)")
    if verdict not in {"approved", "rejected", "info"}:
        return "info", (
            f"LLM returned unknown verdict {verdict!r}; "
            f"original reason: {reason}"
        )
    return verdict, str(reason)[:200]


def review_cli_pair(
    *,
    spec_block: CliBlock,
    lab_block: CliBlock,
    intent: dict[str, Any],
    spec_kind: str,
    spec_idx: int,
    lab_kind: str,
    lab_idx: int,
    platform_hint: str = "",
    chat_model: Any | None = None,
) -> StepVerdict:
    """Single LLM-driven semantic verdict for one (spec, lab) pair.

    ``chat_model`` is optional; if omitted, lazily creates one via
    ``olav.core.llm.get_chat_model(json_mode=True, temperature=0.1)``.
    Pass a mock for tests.

    Always returns a StepVerdict — never raises on LLM error.
    """
    if chat_model is None:
        # Lazy import — keeps the module loadable without LLM config
        from olav.core.llm import get_chat_model
        chat_model = get_chat_model(json_mode=True, temperature=0.1)

    prompt = _REVIEW_PROMPT.format(
        intent=json.dumps(intent),
        spec_kind=spec_kind,
        device=spec_block.device,
        platform_hint=platform_hint or "vendor",
        spec_cli=_format_cli(spec_block.cli),
        lab_kind=lab_kind,
        lab_cli=_format_cli(lab_block.cli),
    )

    try:
        # langchain BaseChatModel.invoke accepts str or message list
        response = chat_model.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        verdict, reason = _parse_verdict_response(raw)
    except Exception as exc:
        verdict = "info"
        reason = f"LLM review failed: {type(exc).__name__}: {exc}"[:200]

    return StepVerdict(
        spec_ref=f"{spec_kind}[{spec_idx}]",
        lab_ref=f"{lab_kind}[{lab_idx}]",
        verdict=verdict,
        reason=reason,
    )


def _index_blocks_by_device(blocks: list[CliBlock]) -> dict[str, tuple[int, CliBlock]]:
    """First block per device wins. Lower-cases device name to match
    sim's prod-form (R1) with lab's container name (r1)."""
    out: dict[str, tuple[int, CliBlock]] = {}
    for i, b in enumerate(blocks):
        key = b.device.lower()
        if key not in out:
            out[key] = (i, b)
    return out


def _platform_for_device(tcf: CabTcf, device_name: str) -> str:
    for d in tcf.devices:
        if d.name.lower() == device_name.lower():
            return d.platform
    return ""


def review_paired_blocks(
    tcf: CabTcf,
    *,
    chat_model: Any | None = None,
) -> list[StepVerdict]:
    """Run LLM semantic review across every structurally-paired
    implementation and rollback block in the TCF.

    Skips pairs missing on either side — those are already flagged by
    the deterministic layer as ``missing`` / ``extra``.

    Returns a list ready to pass as ``step_verdicts`` to
    ``tcf_record_lab_run``. Each verdict is independent — one LLM
    failure doesn't taint the rest (each pair gets its own ``info``
    fallback).
    """
    verdicts: list[StepVerdict] = []
    intent = tcf.intent.model_dump()

    pairs: list[tuple[str, str, list[CliBlock], list[CliBlock]]] = [
        ("implementation", "implementation_lab",
         list(tcf.implementation), list(tcf.lab.implementation_lab)),
        ("rollback", "rollback_lab",
         list(tcf.rollback), list(tcf.lab.rollback_lab)),
    ]

    for spec_kind, lab_kind, spec_blocks, lab_blocks in pairs:
        spec_by_dev = _index_blocks_by_device(spec_blocks)
        lab_by_dev = _index_blocks_by_device(lab_blocks)
        for dev_key, (spec_idx, spec_block) in spec_by_dev.items():
            if dev_key not in lab_by_dev:
                continue  # structural gap — already in deterministic verdicts
            lab_idx, lab_block = lab_by_dev[dev_key]
            verdicts.append(review_cli_pair(
                spec_block=spec_block,
                lab_block=lab_block,
                intent=intent,
                spec_kind=spec_kind,
                spec_idx=spec_idx,
                lab_kind=lab_kind,
                lab_idx=lab_idx,
                platform_hint=_platform_for_device(tcf, spec_block.device),
                chat_model=chat_model,
            ))

    return verdicts


__all__ = [
    "review_cli_pair",
    "review_paired_blocks",
]
