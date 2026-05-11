"""Prose-mode LLM translator for freeform_cli intent.

When TCF intent.type == "freeform_cli", the per-intent Python
renderer (R89 / generate_srl_lab_config) cannot synthesize SRL
config — sim emits prod CLI (IOS / Junos / EOS), and there is no
deterministic template that maps "arbitrary prod CLI" → SRL.

Empirically validated (rev 247 prototype, 2026-05-11):

- Tool-calling LLM (lab agent with skill scripts): 0 SRL output
  across 90+ tool calls; model defaults to "find a tool" rather
  than emit raw CLI text.
- Prose-mode LLM (this module): single-turn call with SRL rules
  in system prompt produces 3/3 valid SRL on DeepSeek V4 Flash
  in 5–19s per translation. Output uses correct slug, prefix-
  length conversion, ``set / network-instance`` hierarchy, and
  ``enter candidate`` / ``commit save`` wrap.

This module is called *internally* by ``validate_tcf_in_lab`` —
the lab agent sees a single skill script entry point. The LLM
call has NO tool schema attached, which is critical: the
tool-calling channel has no "emit raw text" output mode, so
the model can only produce SRL when tools are absent.

Per ADR-0011 §4, this path requires a ≥200B-class cloud model
(DeepSeek V3/V4, Claude Sonnet, GPT-4-class). gemma4:31b nothink
returns empty strings on this task.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# System prompt — loaded from data/cab_srl_rules/*.yaml at import time
#
# Plan C (rev 254, 2026-05-11): the per-intent translation rules used
# to live in this file as a 60-line string. They now live as separate
# YAML files under ``src/olav/data/cab_srl_rules/``. Each file has:
#
#     name: <intent_name>
#     priority: <int — sort key, lower first>
#     description: "<one-liner>"
#     body: |
#       <markdown fragment that goes verbatim into the system prompt>
#
# Reasons (compared to the previous hardcoded string):
#  * Each translation case is one editable file — easier to extend
#    without redeploying the python module (rebuild wheel only).
#  * Aligned with OLAV's memory/guide file pattern, but kept out of
#    the AutoRecall index because they are tooling content, not
#    agent-facing memory (intentionally NOT named *.guide.yaml).
#  * Build-time eager concat means the LLM still sees all rules every
#    call (same prose behaviour we proved works in rev 252) — no
#    runtime retrieval miss risk.
# ────────────────────────────────────────────────────────────────────


_HEADER = """\
/no_think You are an SR Linux configuration translator.

The OLAV CAB lab digital twin uses Nokia SR Linux containers
(image: ghcr.io/nokia/srlinux:24.10.1). Your job: translate
production CLI (Cisco IOS or Juniper Junos) into the equivalent
SR Linux CLI.
"""


def _rules_dir() -> Path:
    """Locate the bundled SRL translation rule directory."""
    here = Path(__file__).resolve().parent
    # src/olav/core/cab/freeform_translator.py → src/olav/data/cab_srl_rules
    return here.parent.parent / "data" / "cab_srl_rules"


def _load_system_prompt() -> str:
    """Concatenate _HEADER + all loaded rule bodies (sorted by priority).

    Returns the hardcoded fallback header alone if the rules directory
    is missing or unreadable — should not happen in a normal install
    but keeps the translator functional with degraded coverage.
    """
    parts: list[str] = [_HEADER]
    try:
        rules_dir = _rules_dir()
        if not rules_dir.is_dir():
            logger.warning(
                "freeform_translator: rules dir not found at %s; "
                "using header-only prompt (translation coverage limited)",
                rules_dir,
            )
            return _HEADER

        loaded: list[tuple[int, str, str]] = []
        for path in sorted(rules_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "freeform_translator: skip %s (parse error: %s)",
                    path.name, exc,
                )
                continue
            if not isinstance(data, dict):
                continue
            body = data.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            priority = int(data.get("priority", 99))
            name = str(data.get("name") or path.stem)
            loaded.append((priority, name, body.rstrip()))

        loaded.sort(key=lambda t: (t[0], t[1]))
        if loaded:
            # The base rule (priority 0) provides format / hard rules;
            # everything else is a per-intent example block.
            parts.append("# Translation rules\n")
            for _, _, body in loaded:
                parts.append(body)
        logger.info(
            "freeform_translator: loaded %d SRL translation rule files",
            len(loaded),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "freeform_translator: rule load failed (%s); "
            "using header-only prompt", exc,
        )
        return _HEADER

    return "\n\n".join(parts)


_SYSTEM_PROMPT = _load_system_prompt()


# ────────────────────────────────────────────────────────────────────
# LLM client construction (reads .olav/config/api.json)
# ────────────────────────────────────────────────────────────────────


def _resolve_config_path() -> Path:
    """Find the active OLAV LLM config file."""
    env_path = os.environ.get("OLAV_DEV_CONFIG")
    if env_path:
        p = Path(env_path).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            return p
    # Fall back to cwd's .olav/config/api.json
    p = Path.cwd() / ".olav" / "config" / "api.json"
    if p.exists():
        return p
    raise FileNotFoundError(
        "OLAV LLM config not found; set OLAV_DEV_CONFIG or "
        "run from a directory with .olav/config/api.json"
    )


def _build_client_and_model() -> tuple[Any, str, int]:
    """Return (OpenAI client, model, timeout_s) using OLAV's LLM config."""
    cfg_path = _resolve_config_path()
    cfg = json.loads(cfg_path.read_text())
    llm = cfg.get("llm", {})
    base_url = llm.get("base_url")
    model = llm.get("model")
    api_key = llm.get("api_key") or "local"
    timeout_s = int(cfg.get("shared", {}).get("timeout", 60))
    if not base_url or not model:
        raise RuntimeError(
            f"llm.base_url + llm.model required in {cfg_path}"
        )
    # Append /v1 for ollama endpoints if missing
    if "ollama" in (llm.get("model_provider") or "") and not base_url.endswith("/v1"):
        if not base_url.endswith("/"):
            base_url = base_url + "/"
        base_url = base_url + "v1"
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
    return client, model, timeout_s


# ────────────────────────────────────────────────────────────────────
# Output validation
# ────────────────────────────────────────────────────────────────────


_SRL_PATH_RE = re.compile(r"^\s*set\s+/\s+\S", re.M)
_IOS_LEAK_PHRASES = (
    "configure terminal",
    "write memory",
    "end\n",
    "no ip route",
    "no router bgp",
    "wr mem",
)


def _validate_srl_output(text: str) -> tuple[bool, str]:
    """Return (valid, reason). Cheap regex-only check."""
    if not text or not text.strip():
        return False, "empty output (model returned no SRL)"
    lower = text.lower()
    if "error_untranslatable" in lower:
        return False, "model declared output untranslatable"
    if "enter candidate" not in lower:
        return False, "missing 'enter candidate'"
    if "commit save" not in lower:
        return False, "missing 'commit save'"
    if not _SRL_PATH_RE.search(text):
        return False, "no 'set / ...' path hierarchy found"
    for bad in _IOS_LEAK_PHRASES:
        if bad in lower:
            return False, f"output contains IOS-only phrase: {bad!r}"
    return True, ""


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────


def translate_prod_cli_to_srl(
    prod_cli: list[str],
    platform: str,
    *,
    extra_context: str = "",
) -> dict[str, Any]:
    """Single-turn prose-mode LLM call to translate prod CLI → SRL.

    Args:
        prod_cli: list of CLI lines (as they appear in TCF
            implementation.cli — e.g. ``["configure terminal",
            "ip route 192.0.2.0 255.255.255.0 10.1.13.1", "end",
            "write memory"]``).
        platform: e.g. ``"cisco_ios"`` / ``"juniper_junos"``. Used
            in the user prompt so the model knows the source dialect.
        extra_context: optional extra prose appended to the user
            message (e.g. lab topology hints).

    Returns:
        ``{
            "status": "ok" / "error",
            "srl_lines": [str, ...],        # only on status=ok
            "raw_output": str,
            "model": str,
            "elapsed_s": float,
            "error": str,                   # only on status=error
            "validation_reason": str,       # only on status=error
        }``

    Empty / invalid model output → ``status=error`` so the caller
    can fall back to OK_HITL_ONLY.
    """
    import time

    try:
        client, model, _ = _build_client_and_model()
    except Exception as exc:
        return {
            "status": "error",
            "error": f"LLM client init failed: {exc}",
            "elapsed_s": 0.0,
        }

    user_prompt = (
        f"Source platform: {platform}\n\n"
        f"Source CLI:\n{chr(10).join(prod_cli)}\n\n"
        f"Translate to SR Linux CLI per the rules. Output ONLY the SRL lines."
    )
    if extra_context.strip():
        user_prompt += f"\n\nAdditional context:\n{extra_context.strip()}"

    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            # 2026-05-11: 500 was insufficient for thinking-mode models
            # (gemma4 fills reasoning tokens first, runs out of budget
            # before emitting content). 2000 leaves room for both
            # reasoning + content, AND the `/no_think` directive in the
            # system prompt usually short-circuits reasoning so most
            # responses are <500 anyway.
            max_tokens=2000,
            # CRITICAL: NO tools / tool_choice — pure prose channel.
        )
        text = resp.choices[0].message.content or ""
    except Exception as exc:
        return {
            "status": "error",
            "error": f"LLM call failed: {type(exc).__name__}: {exc}",
            "model": model,
            "elapsed_s": time.time() - t0,
        }

    elapsed = time.time() - t0
    valid, reason = _validate_srl_output(text)
    if not valid:
        return {
            "status": "error",
            "error": "SRL validation failed",
            "validation_reason": reason,
            "raw_output": text,
            "model": model,
            "elapsed_s": elapsed,
        }

    # Clean the output: strip empty lines, code fences if any sneaked in
    srl_lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("```")
    ]
    return {
        "status": "ok",
        "srl_lines": srl_lines,
        "raw_output": text,
        "model": model,
        "elapsed_s": elapsed,
    }
