"""Generic intent → TCF handler driven by per-intent YAML schemas.

Phase F prototype (rev 271, 2026-05-12). Single Python module renders
TCF blocks for ANY intent declared as
``src/olav/data/intent_schemas/<intent>.intent.yaml``. Adding a new
intent type does not touch this file — only the schema YAML.

Design discussion: dev_docs/73 § Phase F. The original Phase F design
called for `handlers/<intent>.py` per-intent. This module is the
alternative ("user-favoured" rev 271) where intent-specific logic
lives entirely in YAML (Jinja-templated CLI + SQL fact lookups +
Python-expression computed facts), and ONE handler walks it.

NOTE: this is an experimental parallel to ``tcf_writer.py`` —
it does not replace the existing per-intent renderers yet. The
hand-coded ebgp_direct / freeform_cli renderers in tcf_writer
remain canonical for the in-production CAB flow; this module
proves out the config-driven approach so we can compare for
the next sim refactor.
"""
from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined, Template

logger = logging.getLogger(__name__)


# ── Schema discovery ────────────────────────────────────────────────


def _schemas_dir() -> Path:
    """Locate the bundled intent schemas directory."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "intent_schemas"


def list_intents() -> list[str]:
    """Return intent names with available schemas."""
    d = _schemas_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem.replace(".intent", "") for p in d.glob("*.intent.yaml"))


def load_intent_schema(intent_name: str) -> dict[str, Any]:
    """Read ``<intent>.intent.yaml`` and return the parsed dict."""
    p = _schemas_dir() / f"{intent_name}.intent.yaml"
    if not p.exists():
        raise FileNotFoundError(
            f"intent schema not found: {p}. "
            f"Available: {list_intents()}"
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"intent schema {p} is not a YAML mapping")
    return data


# ── Jinja rendering helpers ─────────────────────────────────────────


def _render(template_str: str, ctx: dict[str, Any]) -> str:
    """Render a Jinja2 template with strict-undefined to catch typos.

    Strict-undefined means missing variables raise immediately rather
    than rendering as empty string — that's the right default for a
    config-driven CLI generator where silently dropping a variable
    means we ship broken commands.
    """
    return Template(template_str, undefined=StrictUndefined).render(**ctx)


def _render_list(items: list[str], ctx: dict[str, Any]) -> list[str]:
    return [_render(s, ctx) for s in items]


# ── Args validation ─────────────────────────────────────────────────


def _validate_and_default_args(spec: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Merge user args with declared defaults; raise on missing required."""
    merged: dict[str, Any] = {}
    decls = spec.get("args", {})
    for name, decl in decls.items():
        if name in args:
            merged[name] = args[name]
        elif "default" in decl:
            merged[name] = decl["default"]
        elif decl.get("required", False):
            raise ValueError(
                f"intent {spec.get('intent')!r}: missing required arg {name!r}"
            )
        else:
            merged[name] = None
    # Accept extra args silently (handlers may want device/peer context
    # not declared in args:) — they just propagate into the template ctx.
    for name, val in args.items():
        if name not in merged:
            merged[name] = val
    return merged


# ── Fact lookups (SQL) ──────────────────────────────────────────────


def _run_fact_lookups(spec: dict[str, Any], ctx: dict[str, Any], db_conn: Any) -> dict[str, Any]:
    """Execute each declared fact_lookups[].sql against ``db_conn``.

    db_conn is duck-typed: anything with `.execute(sql, args).fetchone()`
    works. Tests pass a stub; production passes a duckdb connection.
    """
    facts: dict[str, Any] = {}
    for lookup in spec.get("fact_lookups", []):
        sql = lookup["sql"]
        args_template = lookup.get("args_template", [])
        sql_args = [_render(a, {**ctx, **facts}) for a in args_template]
        var = lookup["var"]
        ret_type = lookup.get("return", "scalar")
        on_missing = lookup.get("on_missing", "error")

        try:
            cursor = db_conn.execute(sql, sql_args)
            row = cursor.fetchone()
        except Exception as exc:
            raise RuntimeError(
                f"fact_lookups[{var}]: SQL execution failed: {type(exc).__name__}: {exc}"
            ) from exc

        if row is None:
            if on_missing == "error":
                raise RuntimeError(
                    f"fact_lookups[{var}]: no row returned (sql={sql!r}, args={sql_args!r})"
                )
            facts[var] = None
            continue

        if ret_type == "scalar":
            facts[var] = row[0]
        elif ret_type == "row":
            # Best-effort column names from cursor.description; falls
            # back to positional dict-like.
            desc = getattr(cursor, "description", None)
            if desc:
                facts[var] = {d[0]: v for d, v in zip(desc, row, strict=False)}
            else:
                facts[var] = list(row)
        else:
            raise ValueError(
                f"fact_lookups[{var}]: unknown return type {ret_type!r} (expected 'scalar' or 'row')"
            )
    return facts


# ── Fact computed (Python expr) ─────────────────────────────────────


# Restricted globals for fact_computed eval — only what's needed for
# common netops computations.  No __builtins__ access.
_COMPUTED_GLOBALS: dict[str, Any] = {
    "ipaddress": ipaddress,
    "int": int,
    "str": str,
    "len": len,
    "min": min,
    "max": max,
    "abs": abs,
}


def _run_fact_computed(spec: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Evaluate fact_computed[].expr Python expressions (restricted)."""
    facts: dict[str, Any] = {}
    for c in spec.get("fact_computed", []):
        # Render the expression itself with Jinja so it can reference
        # args/facts. Then eval against the restricted globals.
        expr = _render(c["expr"], {**ctx, **facts})
        try:
            facts[c["var"]] = eval(expr, {"__builtins__": {}}, _COMPUTED_GLOBALS)
        except Exception as exc:
            raise RuntimeError(
                f"fact_computed[{c['var']}] failed: {type(exc).__name__}: {exc} "
                f"(expr after Jinja: {expr!r})"
            ) from exc
    return facts


# ── Platform key resolution ─────────────────────────────────────────


def _resolve_platform_key(spec: dict[str, Any], platform_value: str | None) -> str:
    """Pick the cli_templates key that best matches the device platform.

    Accepts loose matching — ``cisco_ios``, ``cisco-ios``, ``CISCO IOS``
    all match the ``cisco_ios`` key. Raises if no match.
    """
    cli_templates = spec.get("cli_templates", {})
    if not cli_templates:
        raise ValueError(f"intent {spec.get('intent')!r}: no cli_templates defined")

    if not platform_value:
        raise ValueError(
            f"intent {spec.get('intent')!r}: no platform value to match against "
            f"cli_templates keys: {sorted(cli_templates.keys())}"
        )

    def _norm(s: str) -> str:
        return s.replace("_", "").replace("-", "").replace(" ", "").lower()

    norm = _norm(platform_value)
    for key in cli_templates:
        norm_key = _norm(key)
        if norm_key in norm or norm in norm_key:
            return key

    raise ValueError(
        f"intent {spec.get('intent')!r}: platform {platform_value!r} did not match any "
        f"cli_templates key. Available: {sorted(cli_templates.keys())}"
    )


# ── Top-level entry ─────────────────────────────────────────────────


def render_intent_to_tcf_blocks(
    intent: str,
    args: dict[str, Any],
    db_conn: Any,
) -> dict[str, Any]:
    """Load intent schema, gather facts, render CLI — return TCF blocks.

    Returns:
        {
          "intent": <name>,
          "implementation": [{device, phase, action, cli: [str, ...]}, ...],
          "rollback":       [{device, phase, action, cli: [str, ...]}, ...],
          "post_check":     [{device, check_id, command, expected_pattern,
                              must_match, description}, ...],
          "facts_used":     {var_name: value, ...},
          "platform":       <resolved cli_templates key>,
        }

    Shape is compatible with ``tcf_writer._render_freeform_cli`` return
    so a future commit can wire this in as one more option in the
    ``_INTENT_RENDERERS`` dispatch table.
    """
    spec = load_intent_schema(intent)

    # 1. Validate + default args
    ctx = _validate_and_default_args(spec, args)

    # 2. Fact lookups (SQL)
    facts_sql = _run_fact_lookups(spec, ctx, db_conn)
    ctx.update(facts_sql)

    # 3. Computed facts (Python expr)
    facts_computed = _run_fact_computed(spec, ctx)
    ctx.update(facts_computed)
    all_facts = {**facts_sql, **facts_computed}

    # 4. Resolve platform key
    # By convention, the lookup that holds platform is named
    # ``<something>_platform`` or just ``platform``. We try in order.
    platform_value = (
        all_facts.get("src_platform")
        or all_facts.get("platform")
        or ctx.get("platform")
    )
    platform_key = _resolve_platform_key(spec, str(platform_value) if platform_value else None)

    # 5. Render CLI
    tmpl_block = spec["cli_templates"][platform_key]
    setup_cli = _render_list(tmpl_block.get("setup", []), ctx)
    rollback_cli = _render_list(tmpl_block.get("rollback", []), ctx)

    # The "device" for impl/rollback is the src_device by convention.
    # Multi-device intents (eBGP between two devices) will need
    # ``setup_per_device`` mappings — out of scope for this prototype.
    src_device = ctx.get("src_device") or ctx.get("device")
    if not src_device:
        raise ValueError(
            f"intent {intent!r}: cannot identify src_device for impl/rollback blocks"
        )

    implementation = [{
        "device": src_device,
        "phase": 1,
        "action": "configure",
        "cli": setup_cli,
    }]
    rollback = [{
        "device": src_device,
        "phase": 1,
        "action": "configure",
        "cli": rollback_cli,
    }]

    # 6. Post-checks
    post_check: list[dict[str, Any]] = []
    for i, pc in enumerate(spec.get("post_checks", []), start=1):
        device_var = pc.get("device_var", "src_device")
        check_device = ctx.get(device_var)
        if not check_device:
            continue
        cmd_templates = pc.get("command_templates", {})
        cmd_template = cmd_templates.get(platform_key)
        if not cmd_template:
            # No per-platform command for this check on this platform — skip.
            continue
        command = _render(cmd_template, ctx)
        expected = _render(pc.get("expected_pattern", ""), ctx)
        desc = _render(pc.get("description", ""), ctx)
        post_check.append({
            "device": check_device,
            "check_id": f"PC-{check_device}-{i:02d}",
            "command": command,
            "expected_pattern": expected,
            "must_match": bool(pc.get("must_match", True)),
            "description": desc,
        })

    return {
        "intent": intent,
        "implementation": implementation,
        "rollback": rollback,
        "post_check": post_check,
        "facts_used": all_facts,
        "platform": platform_key,
    }
