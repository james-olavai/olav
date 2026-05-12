"""``olav audit`` — operator entry points for the audit subsystem.

Current subcommands:
  * ``selftest <profile>`` — validate a Profile's SQL against the live
    DB schema (ISSUE-AUDIT-SCHEMA-DRIFT-NO-SELFTEST). Two-pass check:
    EXPLAIN (binder validation) + LIMIT 0 (column-name probe). Catches
    schema drift BEFORE the next audit run silently reports
    "✅ Healthy" off renamed/removed columns.

Resolves ``map_engine.selftest_profile`` via the same plugin
entry-point pattern used by ``olav diff`` (``olav.cli_tools`` group)
so the platform never reaches into a domain workspace directly.

Exit codes:
  0 — all jobs pass schema validation
  1 — bad CLI args / profile not found
  2 — one or more jobs failed (schema_error / runtime_error)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_selftest_profile():
    """Resolve ``selftest_profile`` via the ``olav.cli_tools`` entry-point
    group. Falls back to a relative path walk if the entry-point isn't
    registered (development setup before wheel install)."""
    from importlib.metadata import entry_points

    # 1. Preferred path: entry-point registered by olav-netops package
    try:
        eps = list(entry_points(group="olav.cli_tools"))
    except Exception:
        eps = []
    for ep in eps:
        if ep.name != "selftest_profile":
            continue
        try:
            loader = ep.load()
            fn = loader() if callable(loader) else None
            if fn is not None:
                return fn
        except Exception:
            continue

    # 2. Fallback: walk likely workspace locations for map_engine.py.
    #    Useful during development before the entry-point is wired.
    candidates = [
        Path.cwd() / ".olav" / "workspace" / "audit" / "runner" / "tools" / "map_engine.py",
        Path.cwd() / "olav-netops" / ".olav" / "workspace" / "audit" / "runner" / "tools" / "map_engine.py",
    ]
    for p in candidates:
        if not p.exists():
            continue
        import importlib.util
        spec = importlib.util.spec_from_file_location("_olav_audit_selftest_me", p)
        if spec is None or spec.loader is None:
            continue
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, "selftest_profile", None)
        except Exception:
            continue
    return None


def _resolve_profile_path(arg: str) -> str:
    """Accept either a bare profile name (`bgp_health`) or an explicit path.

    Bare names get resolved against
    ``.olav/workspace/audit/profiles/<name>.md``. Explicit paths pass
    through unchanged."""
    p = Path(arg)
    if p.suffix == ".md" or "/" in arg or "\\" in arg:
        return arg
    cand = Path.cwd() / ".olav" / "workspace" / "audit" / "profiles" / f"{arg}.md"
    if cand.exists():
        return str(cand)
    return arg


def _print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return
    ok = result.get("ok")
    profile = result.get("profile", "?")
    print(f"profile : {profile}")
    print(f"path    : {result.get('profile_path', '?')}")
    jobs = result.get("jobs", [])
    print(f"jobs    : {len(jobs)}")
    if ok:
        print("status  : ✅ all jobs pass schema validation")
    else:
        n_failed = sum(1 for j in jobs if j.get("status") != "ok")
        print(f"status  : 🔴 {n_failed} of {len(jobs)} job(s) failed")
    for j in jobs:
        status = j.get("status", "?")
        icon = {"ok": "✅", "schema_error": "🔴", "runtime_error": "🔴"}.get(status, "·")
        line = f"  {icon} {j.get('name', '?')}: {status}"
        if j.get("table"):
            line += f"  (table: {j['table']})"
        print(line)
        if j.get("error"):
            # Indent the error and crop to 4 lines
            for ln in str(j["error"]).splitlines()[:4]:
                print(f"      {ln}")


def handle_audit_command(args: argparse.Namespace) -> int:
    """Entry point invoked by main.py's command dispatcher."""
    sub = getattr(args, "audit_command", None)
    if sub is None:
        print("usage: olav audit <subcommand>", file=sys.stderr)
        print("subcommands: selftest", file=sys.stderr)
        return 1

    if sub == "selftest":
        return _handle_selftest(args)

    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return 1


def _handle_selftest(args: argparse.Namespace) -> int:
    fn = _load_selftest_profile()
    if fn is None:
        print(
            "error: could not load map_engine.selftest_profile — "
            "is `olav-netops` installed in the active venv?",
            file=sys.stderr,
        )
        return 2

    profile_arg = getattr(args, "profile", None)
    if not profile_arg:
        print("error: missing required argument: profile", file=sys.stderr)
        print("usage: olav audit selftest <profile_name_or_path>", file=sys.stderr)
        return 1

    profile_path = _resolve_profile_path(profile_arg)
    if not Path(profile_path).exists():
        print(f"error: profile not found: {profile_path}", file=sys.stderr)
        return 1

    try:
        result = fn(profile_path)
    except Exception as exc:
        print(f"error: selftest raised: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    _print_result(result, as_json=bool(getattr(args, "json", False)))
    return 0 if result.get("ok") else 2
