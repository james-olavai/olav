#!/usr/bin/env python3
"""list_recipes — inventory of view_recipes DB + source YAML file mapping.

ARCH-29: lets the agent (or `olav recipes list`) see which recipes are
active, which are built-in vs user, and where each came from.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _resolve_source(command: str, vendor: str) -> str:
    """Return 'builtin' / 'user' / 'unknown' based on file existence."""
    from olav_netops.core.recipe_seeds import (
        _builtin_recipes_dir,
        _user_recipes_dir,
    )
    builtin = _builtin_recipes_dir()
    user = _user_recipes_dir()
    # Simple filename heuristic: <protocol>_<vendor>.yaml
    for root, label in [(builtin, "builtin"), (user, "user")]:
        if not root.exists():
            continue
        for f in root.glob("*.yaml"):
            import yaml
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
                entries = data if isinstance(data, list) else [data]
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    if e.get("command") == command and (
                        e.get("vendor_hint") or "universal"
                    ) == vendor:
                        return label
            except Exception:
                continue
    return "unknown"


def list_recipes(concept: str | None = None) -> list[dict[str, Any]]:
    """Return active recipes from ``view_recipes`` DB, annotated with source.

    Args:
        concept: Optional filter (``bgp_neighbors``, ``ospf_neighbors``, etc.).

    Returns:
        List of ``{command, concept, vendor_hint, source, field_count}``
        dicts sorted by (concept, vendor_hint, command). ``source`` is
        ``'builtin'`` / ``'user'`` / ``'unknown'`` based on which YAML
        file contains the matching entry.
    """
    import duckdb
    import json as _json
    from olav.core.config import MAIN_DB_PATH

    con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    try:
        sql = (
            "SELECT command, concept, vendor_hint, field_mappings, filter_expr, "
            "discovered_at FROM view_recipes"
        )
        params: list = []
        if concept:
            sql += " WHERE concept = ?"
            params.append(concept)
        sql += " ORDER BY concept, vendor_hint, command"
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        cmd, c, vendor, fm_json, flt, discovered = r
        try:
            fm = _json.loads(fm_json) if isinstance(fm_json, str) else (fm_json or {})
        except Exception:
            fm = {}
        out.append({
            "command": cmd,
            "concept": c,
            "vendor_hint": vendor or "universal",
            "source": _resolve_source(cmd, vendor or "universal"),
            "field_count": len(fm),
            "has_filter": bool(flt),
            "discovered_at": str(discovered) if discovered else None,
        })
    return out


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = list_recipes(**_args)
    print(_json.dumps(result, default=str))
