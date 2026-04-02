#!/usr/bin/env python3
"""check_health.py - OLAV System Health Checker.

Validates workspace agent/skill/tool registrations, database health,
environment config, and network connectivity.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

from langchain_core.tools import tool


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
_OLAV_DIR = _PROJECT_ROOT / ".olav"
_WORKSPACE = _OLAV_DIR / "workspace"


# ── Frontmatter parser ────────────────────────────────────────────────────────

def _parse_frontmatter(path: Path) -> dict | None:
    """Return YAML frontmatter dict from a Markdown file, or None if missing/invalid."""
    try:
        import yaml
        txt = path.read_text()
        m = re.match(r"^---\n(.*?)\n---", txt, re.DOTALL)
        if not m:
            return None
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        return None


# ── Workspace / Agent / Skill / Tool checks ───────────────────────────────────

def _check_skill_tools(skill_md: Path, skill_dir: Path) -> list[dict]:
    """Verify every tool declared in a SKILL.md actually has a file on disk."""
    checks = []
    fm = _parse_frontmatter(skill_md)
    if fm is None:
        return [{"name": "SKILL.md frontmatter", "status": "error",
                 "message": f"Missing or invalid in {skill_md.relative_to(_PROJECT_ROOT)}"}]

    raw_tools = fm.get("tools", [])
    declared_names: set[str] = set()

    for entry in raw_tools:
        if isinstance(entry, dict):
            tool_rel = entry.get("path", "")
            tool_path = skill_dir / tool_rel
            name = tool_path.name
            declared_names.add(name)
            if tool_path.exists():
                checks.append({"name": f"tool:{name}", "status": "ok"})
            else:
                checks.append({"name": f"tool:{name}", "status": "error",
                                "message": f"File missing: {tool_rel}"})
        elif isinstance(entry, str) and not entry.startswith("#"):
            tool_file = skill_dir / "tools" / f"{entry}.py"
            declared_names.add(f"{entry}.py")
            if tool_file.exists():
                checks.append({"name": f"tool:{entry}", "status": "ok"})
            else:
                checks.append({"name": f"tool:{entry}", "status": "warning",
                                "message": "Not found as tools/{name}.py — may resolve at runtime"})

    # Detect orphaned tool files (on disk but not declared)
    tools_dir = skill_dir / "tools"
    if tools_dir.exists():
        for py in tools_dir.glob("*.py"):
            if py.name.startswith("_") or py.name == "__init__.py":
                continue
            if py.name not in declared_names:
                checks.append({"name": f"orphan:{py.name}", "status": "warning",
                                "message": "Tool file exists but not declared in SKILL.md"})

    return checks


def _check_agent(agent_name: str) -> dict:
    """Full registration check for one agent directory."""
    agent_dir = _WORKSPACE / agent_name
    result: dict = {"name": agent_name, "status": "ok", "checks": [], "subagents": []}

    # ── AGENT.md ──────────────────────────────────────────────────────────────
    agent_md = agent_dir / "AGENT.md"
    if not agent_md.exists():
        result["checks"].append({"name": "AGENT.md", "status": "error", "message": "Missing"})
        result["status"] = "error"
        return result

    fm = _parse_frontmatter(agent_md)
    if fm is None:
        result["checks"].append({"name": "AGENT.md frontmatter", "status": "error",
                                  "message": "Missing or malformed YAML"})
        result["status"] = "error"
    else:
        result["checks"].append({"name": "AGENT.md", "status": "ok",
                                  "agent_name": fm.get("name", "?"),
                                  "description": (fm.get("description") or "")[:80]})

        # system_prompt_file
        spf = fm.get("system_prompt_file")
        if spf:
            spf_path = agent_dir / spf
            if spf_path.exists():
                result["checks"].append({"name": "system_prompt_file", "status": "ok",
                                          "path": spf})
            else:
                result["checks"].append({"name": "system_prompt_file", "status": "error",
                                          "message": f"Missing: {spf}"})
                result["status"] = "error"

        # subagents
        for sa in fm.get("subagents", []):
            sa_path_rel = sa.get("path", "") if isinstance(sa, dict) else str(sa)
            sa_skill_path = agent_dir / sa_path_rel
            sa_dir = sa_skill_path.parent
            sa_entry: dict = {"path": sa_path_rel, "status": "ok", "tool_checks": []}

            if not sa_skill_path.exists():
                sa_entry["status"] = "error"
                sa_entry["message"] = "SKILL.md missing"
                result["status"] = "error"
            else:
                sa_fm = _parse_frontmatter(sa_skill_path)
                sa_entry["skill_name"] = sa_fm.get("name", "?") if sa_fm else "?"
                sa_entry["description"] = ((sa_fm.get("description") or "") if sa_fm else "")[:80]
                tool_checks = _check_skill_tools(sa_skill_path, sa_dir)
                sa_entry["tool_checks"] = tool_checks
                errors = [c for c in tool_checks if c["status"] == "error"]
                warnings = [c for c in tool_checks if c["status"] == "warning"]
                if errors:
                    sa_entry["status"] = "error"
                    result["status"] = "error"
                elif warnings:
                    sa_entry["status"] = "warning"
                    if result["status"] == "ok":
                        result["status"] = "warning"

            result["subagents"].append(sa_entry)

    # ── MANIFEST.yaml ─────────────────────────────────────────────────────────
    manifest = agent_dir / "MANIFEST.yaml"
    if not manifest.exists():
        result["checks"].append({"name": "MANIFEST.yaml", "status": "warning",
                                  "message": "Missing — agent is unmanaged"})
        if result["status"] == "ok":
            result["status"] = "warning"
    else:
        try:
            import yaml
            mf = yaml.safe_load(manifest.read_text()) or {}
            issues = []
            if not mf.get("description"):
                issues.append("no description")
            if not mf.get("route_keywords"):
                issues.append("no route_keywords")
            if issues:
                result["checks"].append({"name": "MANIFEST.yaml", "status": "warning",
                                          "message": f"Incomplete: {', '.join(issues)}"})
                if result["status"] == "ok":
                    result["status"] = "warning"
            else:
                result["checks"].append({"name": "MANIFEST.yaml", "status": "ok",
                                          "manifest_name": mf.get("name", "?")})
        except Exception as e:
            result["checks"].append({"name": "MANIFEST.yaml", "status": "error",
                                      "message": str(e)})
            result["status"] = "error"

    # ── Direct SKILL.md tool check (top-level orchestrator skill) ─────────────
    top_skill = agent_dir / "SKILL.md"
    if top_skill.exists():
        tool_checks = _check_skill_tools(top_skill, agent_dir)
        errors = [c for c in tool_checks if c["status"] == "error"]
        orphans = [c for c in tool_checks if c["status"] == "warning"]
        if errors:
            result["checks"].append({"name": "SKILL.md tools", "status": "error",
                                      "details": errors})
            result["status"] = "error"
        elif orphans:
            result["checks"].append({"name": "SKILL.md tools", "status": "warning",
                                      "orphaned": [o["name"] for o in orphans]})
            if result["status"] == "ok":
                result["status"] = "warning"

    return result


def _check_workspace() -> dict:
    """Check PLATFORM.md registration and all agent/skill/tool validity."""
    results: dict = {"status": "ok", "checks": [], "agents": []}

    platform_md = _WORKSPACE / "PLATFORM.md"
    if not platform_md.exists():
        results["checks"].append({"name": "PLATFORM.md", "status": "error",
                                   "message": "Missing .olav/workspace/PLATFORM.md"})
        results["status"] = "error"
        return results

    try:
        import yaml
        txt = platform_md.read_text()
        m = re.match(r"^---\n(.*?)\n---", txt, re.DOTALL)
        if not m:
            raise ValueError("No frontmatter")
        fm = yaml.safe_load(m.group(1)) or {}
        registered = fm.get("agents", [])
    except Exception as e:
        results["checks"].append({"name": "PLATFORM.md parse", "status": "error",
                                   "message": str(e)})
        results["status"] = "error"
        return results

    results["checks"].append({"name": "PLATFORM.md", "status": "ok",
                               "registered_agents": registered})

    # Detect workspace dirs not in PLATFORM.md
    workspace_dirs = {
        d.name for d in _WORKSPACE.iterdir()
        if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")
    }
    unregistered = workspace_dirs - set(registered)
    if unregistered:
        results["checks"].append({"name": "Unregistered agent dirs", "status": "warning",
                                   "agents": sorted(unregistered)})
        if results["status"] == "ok":
            results["status"] = "warning"

    # Check each registered agent
    error_agents, warning_agents = [], []
    for agent_name in registered:
        agent_dir = _WORKSPACE / agent_name
        if not agent_dir.exists():
            results["agents"].append({"name": agent_name, "status": "error",
                                       "checks": [{"name": "directory", "status": "error",
                                                    "message": "Workspace dir missing"}],
                                       "subagents": []})
            error_agents.append(agent_name)
            continue
        agent_result = _check_agent(agent_name)
        results["agents"].append(agent_result)
        if agent_result["status"] == "error":
            error_agents.append(agent_name)
        elif agent_result["status"] == "warning":
            warning_agents.append(agent_name)

    if error_agents:
        results["checks"].append({"name": "Agent errors", "status": "error",
                                   "agents": error_agents})
        results["status"] = "error"
    elif warning_agents:
        results["checks"].append({"name": "Agent warnings", "status": "warning",
                                   "agents": warning_agents})
        results["status"] = "warning"
    else:
        total_subagents = sum(len(a.get("subagents", [])) for a in results["agents"])
        results["checks"].append({"name": "All agents valid", "status": "ok",
                                   "agents": len(registered),
                                   "subagents": total_subagents})

    return results


# ── Environment / Config check ────────────────────────────────────────────────

def _check_env() -> dict:
    """Check environment and LLM configuration (env vars + api.json)."""
    results: dict = {"status": "ok", "checks": []}

    # ── LLM API key ───────────────────────────────────────────────────────────
    env_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
               or os.getenv("OPENROUTER_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
    api_json_path = _OLAV_DIR / "config" / "api.json"
    cfg: dict = {}
    if api_json_path.exists():
        try:
            cfg = json.loads(api_json_path.read_text())
        except Exception:
            pass

    # Key can be in env, cfg.llm.api_key, or cfg.shared.api_key
    json_key = cfg.get("llm", {}).get("api_key") or cfg.get("shared", {}).get("api_key")
    if env_key:
        results["checks"].append({"name": "LLM API key", "status": "ok", "source": "env"})
    elif json_key:
        results["checks"].append({"name": "LLM API key", "status": "ok", "source": "api.json"})
    else:
        results["checks"].append({"name": "LLM API key", "status": "warning",
                                   "message": "Not found in env or api.json"})
        results["status"] = "warning"

    # ── api.json model / provider ─────────────────────────────────────────────
    if not cfg:
        results["checks"].append({"name": "api.json", "status": "warning",
                                   "message": "Not found or invalid JSON"})
        results["status"] = "warning"
    else:
        llm = cfg.get("llm", {})
        model = llm.get("model", "")
        provider = llm.get("provider", "")
        base_url = llm.get("base_url", "")
        issues = []
        if not model:
            issues.append("llm.model not set")
        if not provider:
            issues.append("llm.provider not set")
        if provider == "custom" and not base_url:
            issues.append("llm.base_url required for custom provider")
        if issues:
            results["checks"].append({"name": "api.json LLM config", "status": "warning",
                                       "message": "; ".join(issues)})
            results["status"] = "warning"
        else:
            results["checks"].append({"name": "api.json LLM config", "status": "ok",
                                       "provider": provider, "model": model})

    # ── settings.json: active_workspace + syslog ─────────────────────────────
    settings_path = _OLAV_DIR / "config" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())

            # active_workspace must be a registered agent
            active_ws = settings.get("active_workspace", "")
            if active_ws:
                platform_md = _WORKSPACE / "PLATFORM.md"
                registered: list = []
                if platform_md.exists():
                    try:
                        import yaml
                        m = re.match(r"^---\n(.*?)\n---",
                                     platform_md.read_text(), re.DOTALL)
                        if m:
                            registered = yaml.safe_load(m.group(1)).get("agents", [])
                    except Exception:
                        pass
                if active_ws in registered:
                    results["checks"].append({"name": "Active workspace", "status": "ok",
                                               "workspace": active_ws})
                else:
                    results["checks"].append({"name": "Active workspace", "status": "warning",
                                               "message": f"'{active_ws}' not in PLATFORM.md agents"})
                    if results["status"] == "ok":
                        results["status"] = "warning"

            # syslog receiver — if enabled, check if port is actually listening
            sr = settings.get("syslog_receiver", {})
            if sr.get("enabled"):
                import socket
                port = sr.get("port", 5514)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(0.2)
                    sock.sendto(b"", ("127.0.0.1", port))
                    # For UDP we can only check if the port is bound (bind attempt)
                    sock.close()
                    # Try to bind — if it succeeds, nothing is listening
                    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        probe.bind(("127.0.0.1", port))
                        probe.close()
                        # Bind succeeded → port is free → syslog NOT running
                        results["checks"].append({"name": "Syslog receiver", "status": "warning",
                                                   "message": f"enabled but not listening on UDP:{port}"})
                        if results["status"] == "ok":
                            results["status"] = "warning"
                    except OSError:
                        # Bind failed → something is already bound → syslog IS running
                        probe.close()
                        results["checks"].append({"name": "Syslog receiver", "status": "ok",
                                                   "port": port, "protocol": "UDP"})
                except Exception as e:
                    results["checks"].append({"name": "Syslog receiver", "status": "warning",
                                               "message": str(e)})
        except Exception:
            pass

    return results


# ── Database check ────────────────────────────────────────────────────────────

def _check_database() -> dict:
    """Check database health: DuckDB network state, audit schema, LanceDB memory."""
    results: dict = {"status": "ok", "checks": [], "stats": {}}

    db_dir = _OLAV_DIR / "databases"

    # ── DuckDB files ──────────────────────────────────────────────────────────
    for db_name, label in [("main.duckdb", "Network state DB"),
                            ("audit.duckdb", "Audit event store")]:
        db_path = db_dir / db_name
        if db_path.exists():
            size_mb = round(db_path.stat().st_size / 1024 / 1024, 2)
            results["checks"].append({"name": label, "status": "ok",
                                       "file": db_name, "size_mb": size_mb})
        else:
            results["checks"].append({"name": label, "status": "warning",
                                       "message": f"Missing {db_name}"})
            if results["status"] == "ok":
                results["status"] = "warning"

    # ── main.duckdb: current network state tables ─────────────────────────────
    main_db = db_dir / "main.duckdb"
    if main_db.exists():
        try:
            import duckdb
            conn = duckdb.connect(str(main_db), read_only=True)

            # Core registry tables — must have rows if system is configured
            for tbl, label in [("commands", "Command registry"),
                                ("schema_catalog", "Schema catalog"),
                                ("sync_metadata", "Sync metadata")]:
                try:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    results["stats"][tbl] = count
                    s = "ok" if count > 0 else "warning"
                    results["checks"].append({"name": label, "status": s, "rows": count})
                    if count == 0 and results["status"] == "ok":
                        results["status"] = "warning"
                except Exception:
                    pass

            # Auto-generated network state views — at least one should have data
            auto_views = [
                t for (t,) in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='main' AND table_name LIKE 'v_%_auto'"
                ).fetchall()
            ]
            populated = {}
            for v in auto_views:
                try:
                    c = conn.execute(f'SELECT COUNT(*) FROM "{v}"').fetchone()[0]
                    if c > 0:
                        populated[v] = c
                except Exception:
                    pass
            if populated:
                results["checks"].append({"name": "Network state views", "status": "ok",
                                           "populated": len(populated),
                                           "total": len(auto_views),
                                           "sample": dict(list(populated.items())[:4])})
                results["stats"]["network_views"] = populated
            else:
                results["checks"].append({"name": "Network state views", "status": "warning",
                                           "message": f"0/{len(auto_views)} auto-views have data"
                                                       " — run take_snapshot"})
                if results["status"] == "ok":
                    results["status"] = "warning"

            # Snapshot freshness — warn if last completed snapshot > 24h old
            try:
                from datetime import datetime as _dt
                row = conn.execute(
                    "SELECT end_time, status, device_count, success_count "
                    "FROM sync_metadata ORDER BY end_time DESC LIMIT 1"
                ).fetchone()
                if row:
                    end_time, snap_status, total, success = row
                    age_h = (_dt.now() - end_time.replace(tzinfo=None)).total_seconds() / 3600
                    snap_info: dict = {"snap_status": snap_status,
                                       "devices": f"{success}/{total}",
                                       "age_hours": round(age_h, 1)}
                    if snap_status != "completed":
                        results["checks"].append({"name": "Snapshot freshness",
                                                   "status": "warning",
                                                   "message": f"Last snapshot status={snap_status}",
                                                   **snap_info})
                        if results["status"] == "ok":
                            results["status"] = "warning"
                    elif age_h > 24:
                        results["checks"].append({"name": "Snapshot freshness",
                                                   "status": "warning",
                                                   "message": f"{round(age_h,1)}h since last snapshot",
                                                   **snap_info})
                        if results["status"] == "ok":
                            results["status"] = "warning"
                    else:
                        results["checks"].append({"name": "Snapshot freshness",
                                                   "status": "ok", **snap_info})
                else:
                    results["checks"].append({"name": "Snapshot freshness", "status": "warning",
                                               "message": "No snapshot recorded yet"})
                    if results["status"] == "ok":
                        results["status"] = "warning"
            except Exception:
                pass

            conn.close()
        except Exception as e:
            results["checks"].append({"name": "main.duckdb read", "status": "error",
                                       "message": str(e)})
            results["status"] = "error"

    # ── audit.duckdb: schema + row counts ────────────────────────────────────
    audit_db = db_dir / "audit.duckdb"
    if audit_db.exists():
        try:
            import duckdb
            conn = duckdb.connect(str(audit_db), read_only=True)
            audit_stats: dict = {}
            for tbl in ["audit_events", "audit_runs", "audit_tool_calls", "audit_messages"]:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    audit_stats[tbl] = count
                except Exception as e:
                    audit_stats[tbl] = f"ERR: {e}"
            conn.close()
            missing = [t for t, v in audit_stats.items() if isinstance(v, str)]
            if missing:
                results["checks"].append({"name": "Audit schema", "status": "error",
                                           "missing_tables": missing})
                results["status"] = "error"
            else:
                results["checks"].append({"name": "Audit schema", "status": "ok",
                                           "stats": audit_stats})
                results["stats"]["audit"] = audit_stats
        except Exception as e:
            results["checks"].append({"name": "audit.duckdb read", "status": "error",
                                       "message": str(e)})
            results["status"] = "error"

    # ── LanceDB memory store ──────────────────────────────────────────────────
    lancedb_path = db_dir / "memory.lancedb"
    if lancedb_path.exists():
        try:
            import lancedb
            db = lancedb.connect(str(lancedb_path))
            response = db.list_tables()
            # list_tables() returns a ListTablesResponse with .tables attribute in newer lancedb
            table_names = (response.tables if hasattr(response, "tables") else list(response))
            lance_stats = {}
            for t in table_names:
                try:
                    lance_stats[str(t)] = db.open_table(str(t)).count_rows()
                except Exception:
                    lance_stats[str(t)] = "?"
            results["checks"].append({"name": "LanceDB memory store", "status": "ok",
                                       "tables": lance_stats})
            results["stats"]["lancedb"] = lance_stats
        except Exception as e:
            results["checks"].append({"name": "LanceDB memory store", "status": "warning",
                                       "message": str(e)})
            if results["status"] == "ok":
                results["status"] = "warning"
    else:
        results["checks"].append({"name": "LanceDB memory store", "status": "warning",
                                   "message": "Not initialized (.olav/databases/memory.lancedb missing)"})
        if results["status"] == "ok":
            results["status"] = "warning"

    # ── User session checkpoints ──────────────────────────────────────────────
    session_dir = Path.home() / ".olav" / "checkpoints"
    cp_files = list(session_dir.glob("*.duckdb")) if session_dir.exists() else []
    results["checks"].append({"name": "User checkpoints", "status": "ok",
                               "files": len(cp_files)})

    return results


# ── Nornir check ──────────────────────────────────────────────────────────────

def _check_nornir(connectivity_sample: int = 3) -> dict:
    """Check Nornir inventory and optional SSH connectivity sample."""
    import random

    results: dict = {"status": "ok", "checks": []}
    nornir_config = _OLAV_DIR / "config" / "nornir" / "config.yaml"

    if not nornir_config.exists():
        results["checks"].append({"name": "nornir config.yaml", "status": "warning",
                                   "message": "Not found"})
        results["status"] = "warning"
        return results

    results["checks"].append({"name": "nornir config.yaml", "status": "ok"})
    nr = None
    host_count = 0

    try:
        from nornir import InitNornir
        _orig = os.getcwd()
        os.chdir(_PROJECT_ROOT)  # config.yaml paths are relative to project root
        nr = InitNornir(config_file=str(nornir_config))
        os.chdir(_orig)
        host_count = len(nr.inventory.hosts)
        s = "ok" if host_count > 0 else "warning"
        results["checks"].append({"name": "Nornir inventory", "status": s,
                                   "devices": host_count})
        if host_count == 0:
            results["status"] = "warning"
    except Exception as e:
        results["checks"].append({"name": "Nornir inventory", "status": "error",
                                   "message": str(e)})
        results["status"] = "error"
        return results

    if connectivity_sample > 0 and nr is not None and host_count > 0:
        try:
            from nornir_netmiko.tasks import netmiko_send_command
            sample_names = random.sample(list(nr.inventory.hosts),
                                         k=min(connectivity_sample, host_count))
            nr_sample = nr.filter(filter_func=lambda h: h.name in sample_names)
            res = nr_sample.run(task=netmiko_send_command, command="show clock")
            reachable = [n for n, r in res.items() if not r.failed]
            failed = [n for n, r in res.items() if r.failed]
            check: dict = {
                "name": "SSH connectivity (sample)",
                "status": "ok" if not failed else ("warning" if reachable else "error"),
                "sample_size": len(sample_names),
                "reachable": len(reachable), "failed": len(failed),
            }
            if failed:
                check["failed_hosts"] = failed
                results["status"] = "error" if not reachable else "warning"
            results["checks"].append(check)
        except Exception as e:
            results["checks"].append({"name": "SSH connectivity (sample)", "status": "warning",
                                       "message": str(e)})
            if results["status"] == "ok":
                results["status"] = "warning"

    return results


# ── AAA check ─────────────────────────────────────────────────────────────────

def _check_aaa() -> dict:
    """Check Authentication, Authorization, and Accounting configuration.

    Authentication tiers:
      none   → OS identity ($USER) — no real auth, warn in non-dev
      token  → ~/.olav/token + users.duckdb hash verification
      server → .olav/run/server.token (service-to-service)
      ldap / ad / oidc → enterprise SSO (config fields must be non-empty)

    Authorization:
      - security_policies.yaml  — BLOCK/CONFIRM/WARN pattern rules
      - approval_rules.yaml     — dangerous command approval patterns
      - HITL settings (require_hitl_for_write, require_hitl_for_delete)

    Accounting:
      - audit.duckdb tables are checked in the database section
    """
    import yaml
    results: dict = {"status": "ok", "checks": []}
    config_dir = _OLAV_DIR / "config"

    # ── Authentication ────────────────────────────────────────────────────────
    api_json_path = config_dir / "api.json"
    auth_cfg: dict = {}
    if api_json_path.exists():
        try:
            auth_cfg = json.loads(api_json_path.read_text()).get("auth", {})
        except Exception:
            pass

    mode = auth_cfg.get("mode", "none")

    if mode == "none":
        results["checks"].append({
            "name": "Auth mode", "status": "warning", "mode": mode,
            "message": "auth.mode=none — OS identity only, no real authentication"
        })
        if results["status"] == "ok":
            results["status"] = "warning"

    elif mode == "token":
        results["checks"].append({"name": "Auth mode", "status": "ok", "mode": mode})
        # users.duckdb must exist and have at least one admin
        users_db = _OLAV_DIR / "databases" / "users.duckdb"
        if not users_db.exists():
            results["checks"].append({
                "name": "users.duckdb", "status": "error",
                "message": "Missing — run 'olav onboard' to initialise"
            })
            results["status"] = "error"
        else:
            try:
                import duckdb
                conn = duckdb.connect(str(users_db), read_only=True)
                count = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin'"
                ).fetchone()[0]
                conn.close()
                if count == 0:
                    results["checks"].append({
                        "name": "users.duckdb", "status": "error",
                        "message": "No admin users — run 'olav admin add-user'"
                    })
                    results["status"] = "error"
                else:
                    results["checks"].append({
                        "name": "users.duckdb", "status": "ok", "admin_count": count
                    })
            except Exception as e:
                results["checks"].append({
                    "name": "users.duckdb", "status": "error", "message": str(e)
                })
                results["status"] = "error"
        # Current user token file
        token_file = Path(auth_cfg.get("token_file", "~/.olav/token")).expanduser()
        if token_file.exists():
            results["checks"].append({
                "name": "User token file", "status": "ok", "path": str(token_file)
            })
        else:
            results["checks"].append({
                "name": "User token file", "status": "warning",
                "message": f"~/.olav/token missing for current user"
            })
            if results["status"] == "ok":
                results["status"] = "warning"

    elif mode == "server":
        results["checks"].append({"name": "Auth mode", "status": "ok", "mode": mode})
        server_token = _OLAV_DIR / "run" / "server.token"
        if server_token.exists():
            results["checks"].append({
                "name": "Server token", "status": "ok", "path": str(server_token)
            })
        else:
            results["checks"].append({
                "name": "Server token", "status": "error",
                "message": ".olav/run/server.token missing"
            })
            results["status"] = "error"

    else:
        # ldap / ad / oidc — check required fields are non-empty
        required_fields = {
            "ldap":  ["host", "base_dn"],
            "ad":    ["domain", "dc_host"],
            "oidc":  ["issuer_url", "client_id"],
        }
        results["checks"].append({"name": "Auth mode", "status": "ok", "mode": mode})
        fields = auth_cfg.get(mode, {})
        missing = [f for f in required_fields.get(mode, []) if not fields.get(f)]
        if missing:
            results["checks"].append({
                "name": f"{mode} config", "status": "warning",
                "message": f"Required fields empty: {', '.join(missing)}"
            })
            if results["status"] == "ok":
                results["status"] = "warning"
        else:
            results["checks"].append({"name": f"{mode} config", "status": "ok"})

    # ── Authorization ─────────────────────────────────────────────────────────
    for filename in ["security_policies.yaml", "approval_rules.yaml"]:
        fpath = config_dir / filename
        if not fpath.exists():
            results["checks"].append({
                "name": filename, "status": "warning", "message": "File missing"
            })
            if results["status"] == "ok":
                results["status"] = "warning"
        else:
            try:
                yaml.safe_load(fpath.read_text())
                results["checks"].append({"name": filename, "status": "ok"})
            except Exception as e:
                results["checks"].append({
                    "name": filename, "status": "error",
                    "message": f"Parse error: {e}"
                })
                results["status"] = "error"

    # ── HITL / write-guard settings ───────────────────────────────────────────
    settings_path = config_dir / "settings.json"
    if settings_path.exists():
        try:
            perms = json.loads(settings_path.read_text()).get("permissions", {})
            hitl_write = perms.get("require_hitl_for_write", False)
            hitl_delete = perms.get("require_hitl_for_delete", False)
            audit_on = perms.get("audit_log_enabled", False)
            issues = []
            if not hitl_write:
                issues.append("require_hitl_for_write=false")
            if not hitl_delete:
                issues.append("require_hitl_for_delete=false")
            if not audit_on:
                issues.append("audit_log_enabled=false")
            if issues:
                results["checks"].append({
                    "name": "HITL / audit settings", "status": "warning",
                    "message": "; ".join(issues)
                })
                if results["status"] == "ok":
                    results["status"] = "warning"
            else:
                results["checks"].append({
                    "name": "HITL / audit settings", "status": "ok",
                    "hitl_write": hitl_write, "hitl_delete": hitl_delete,
                    "audit": audit_on
                })
        except Exception:
            pass

    # ── Accounting note ───────────────────────────────────────────────────────
    results["checks"].append({
        "name": "Accounting (audit.duckdb)", "status": "ok",
        "note": "See database section for audit event counts"
    })

    return results


# ── Services check ────────────────────────────────────────────────────────────

def _pid_alive(pid_file: Path) -> tuple[bool, int | None]:
    """Return (is_alive, pid). Detects stale/mock PID files."""
    if not pid_file.exists():
        return False, None
    try:
        raw = pid_file.read_text().strip()
        pid = int(raw)
        os.kill(pid, 0)
        return True, pid
    except (ValueError, TypeError):
        return False, None  # non-integer content (e.g. MagicMock)
    except ProcessLookupError:
        return False, None  # stale PID
    except PermissionError:
        return True, None   # process exists but we can't signal it


def _check_services() -> dict:
    """Check OLAV-managed services and external service dependencies."""
    import socket
    import urllib.request
    results: dict = {"status": "ok", "checks": []}

    run_dir = _OLAV_DIR / "run"

    # ── OLAV Web API (uvicorn/FastAPI on DEFAULT_WEB_PORT) ────────────────────
    web_pid_file = run_dir / "web.pid"
    alive, pid = _pid_alive(web_pid_file)
    if alive:
        # Try HTTP health probe
        try:
            from olav.core.defaults import DEFAULT_WEB_PORT
            port = DEFAULT_WEB_PORT
        except Exception:
            port = 2280
        try:
            req = urllib.request.urlopen(
                f"http://localhost:{port}/health", timeout=2)
            results["checks"].append({"name": "OLAV Web API", "status": "ok",
                                       "pid": pid, "port": port,
                                       "http_status": req.status})
        except Exception:
            # Running but /health returned error or not available — still up
            results["checks"].append({"name": "OLAV Web API", "status": "ok",
                                       "pid": pid, "port": port,
                                       "note": "process alive, /health unreachable"})
    else:
        stale = web_pid_file.exists()
        results["checks"].append({"name": "OLAV Web API", "status": "warning",
                                   "message": "Not running"
                                               + (" (stale PID file)" if stale else "")})
        if stale:
            # Clean up stale PID file
            try:
                web_pid_file.unlink()
            except Exception:
                pass
        if results["status"] == "ok":
            results["status"] = "warning"

    # ── OLAV CLI Daemon ───────────────────────────────────────────────────────
    daemon_pid_file = run_dir / "daemon.pid"
    alive, pid = _pid_alive(daemon_pid_file)
    if alive:
        results["checks"].append({"name": "OLAV CLI daemon", "status": "ok", "pid": pid})
    else:
        stale = daemon_pid_file.exists()
        results["checks"].append({"name": "OLAV CLI daemon", "status": "warning",
                                   "message": "Not running"
                                               + (" (stale PID file)" if stale else "")})
        if results["status"] == "ok":
            results["status"] = "warning"

    # ── External services from services.yaml ──────────────────────────────────
    services_yaml = _OLAV_DIR / "config" / "services.yaml"
    if services_yaml.exists():
        try:
            import yaml
            cfg = yaml.safe_load(services_yaml.read_text()) or {}
            services = cfg.get("services", {})
            for svc_name, svc in services.items():
                endpoint = svc.get("endpoint", "")
                if not endpoint:
                    continue
                try:
                    resp = urllib.request.urlopen(endpoint, timeout=2)
                    results["checks"].append({"name": f"Service: {svc_name}", "status": "ok",
                                               "endpoint": endpoint,
                                               "http_status": resp.status})
                except Exception as e:
                    msg = str(e)
                    # HTTP errors (401, 403) mean the service IS running
                    is_up = any(code in msg for code in ["401", "403", "404", "302"])
                    status_str = "ok" if is_up else "warning"
                    results["checks"].append({"name": f"Service: {svc_name}",
                                               "status": status_str,
                                               "endpoint": endpoint,
                                               "message": msg[:80]})
                    if not is_up and results["status"] == "ok":
                        results["status"] = "warning"
        except Exception:
            pass

    return results


# ── Package sanity check ──────────────────────────────────────────────────────

def _check_packages() -> dict:
    """Verify critical Python packages are importable."""
    results: dict = {"status": "ok", "checks": []}
    required = [
        ("duckdb", "DuckDB"),
        ("lancedb", "LanceDB"),
        ("langchain_core", "LangChain core"),
        ("langchain_openai", "LangChain OpenAI"),
        ("deepagents", "deepagents (skills middleware)"),
        ("nornir", "Nornir"),
        ("yaml", "PyYAML"),
    ]
    for module, label in required:
        try:
            mod = __import__(module)
            ver = getattr(mod, "__version__", "?")
            results["checks"].append({"name": label, "status": "ok", "version": ver})
        except ImportError:
            results["checks"].append({"name": label, "status": "warning",
                                       "message": f"'{module}' not importable"})
            if results["status"] == "ok":
                results["status"] = "warning"
    return results


# ── Recommendations ───────────────────────────────────────────────────────────

def _generate_recommendations(health: dict) -> list[str]:
    recs = []

    for agent in health.get("workspace", {}).get("agents", []):
        if agent["status"] == "error":
            msgs = [c["message"] for c in agent.get("checks", [])
                    if c.get("status") == "error" and c.get("message")]
            recs.append(f"Fix agent '{agent['name']}': " + "; ".join(msgs))
        for sa in agent.get("subagents", []):
            if sa["status"] == "error":
                msgs = [c["message"] for c in sa.get("tool_checks", [])
                        if c.get("status") == "error" and c.get("message")]
                skill = sa.get("skill_name", sa["path"])
                recs.append(f"Fix subagent '{skill}' in '{agent['name']}': " + "; ".join(msgs))

    for check in health.get("workspace", {}).get("checks", []):
        if check.get("status") == "warning" and "Unregistered" in check.get("name", ""):
            recs.append(f"Register agents in PLATFORM.md: {check.get('agents', [])}")

    for check in health.get("aaa", {}).get("checks", []):
        if check.get("status") in ("error", "warning"):
            name = check.get("name", "")
            msg = check.get("message", "")
            if "Auth mode" in name and "none" in msg:
                recs.append("Auth is disabled (mode=none) — set auth.mode=token in api.json for real auth")
            elif "users.duckdb" in name and "Missing" in msg:
                recs.append("Run 'olav onboard' to create users.duckdb and admin token")
            elif "users.duckdb" in name and "admin" in msg:
                recs.append("Run 'olav admin add-user --role admin' to create first admin")

    for check in health.get("services", {}).get("checks", []):
        if check.get("status") == "warning":
            name = check.get("name", "")
            if "Web API" in name:
                recs.append("OLAV Web API not running — start with 'olav service web start'")
            elif "daemon" in name:
                recs.append("OLAV daemon not running — start with 'olav service daemon start'")
            elif "Service:" in name:
                recs.append(f"{name} unreachable at {check.get('endpoint','?')}")

    for check in health.get("database", {}).get("checks", []):
        if check.get("status") == "warning":
            name = check.get("name", "")
            if "Command registry" in name:
                recs.append("No commands — run 'olav workspace sync' to register commands")
            elif "Schema catalog" in name:
                recs.append("No schema catalog — run schema discovery pipeline")
            elif "Network state views" in name:
                recs.append("No network data — run 'take_snapshot' to collect device state")
            elif "Snapshot freshness" in name:
                recs.append(f"Snapshot stale ({check.get('age_hours','?')}h) — run 'take_snapshot'")

    if not recs:
        recs.append("System is healthy — no immediate improvements needed")
    return recs


# ── Main tool ─────────────────────────────────────────────────────────────────

@tool
def check_health(
    detailed: bool = False,
    connectivity_sample: int = 3,
    workspace_only: bool = False,
) -> dict:
    """Check OLAV system health: workspace registrations, database, environment, and network.

    Validates:
    - PLATFORM.md agent registry completeness
    - Every registered agent's AGENT.md frontmatter and MANIFEST.yaml
    - All subagent SKILL.md files declared in each AGENT.md
    - All tools declared in each SKILL.md exist on disk
    - Orphaned tool files (exist on disk but not declared in SKILL.md)
    - system_prompt_file references exist
    - LLM API key + api.json model/provider configuration
    - Active workspace validation + syslog receiver status
    - AAA: auth mode (none/token/server/ldap/oidc), users.duckdb, security policies,
      approval rules, HITL write-guard settings
    - OLAV Web API + CLI daemon process health (PID files + HTTP probe)
    - External services in services.yaml (HTTP reachability)
    - Database health: main.duckdb (network state + snapshot freshness),
      audit.duckdb schema + row counts, LanceDB memory store
    - Critical Python package imports (duckdb, lancedb, langchain, deepagents, nornir)
    - Nornir inventory reachability + optional SSH connectivity sample

    Args:
        detailed: Include full per-tool breakdown in output (default: slim summary)
        connectivity_sample: Random hosts to SSH-test (0 = skip for speed)
        workspace_only: Only run workspace/agent checks (skip DB and Nornir)

    Returns:
        Health report dict with status, per-section checks, and recommendations
    """
    health: dict = {"status": "ok"}

    health["workspace"] = _check_workspace()
    health["env"] = _check_env()
    health["packages"] = _check_packages()

    if not workspace_only:
        health["aaa"] = _check_aaa()
        health["services"] = _check_services()
        health["database"] = _check_database()
        health["nornir"] = _check_nornir(connectivity_sample=connectivity_sample)

    for section in health.values():
        if isinstance(section, dict):
            s = section.get("status")
            if s == "error":
                health["status"] = "error"
            elif s == "warning" and health["status"] == "ok":
                health["status"] = "warning"

    error_count = sum(1 for s in health.values()
                      if isinstance(s, dict) and s.get("status") == "error")
    warning_count = sum(1 for s in health.values()
                        if isinstance(s, dict) and s.get("status") == "warning")

    health["summary"] = f"{error_count} errors, {warning_count} warnings"
    health["recommendations"] = _generate_recommendations(health)

    if not detailed:
        for agent in health.get("workspace", {}).get("agents", []):
            for sa in agent.get("subagents", []):
                sa.pop("tool_checks", None)

    return health


if __name__ == "__main__":
    import sys
    detailed = "--detailed" in sys.argv or "-d" in sys.argv
    ws_only = "--workspace" in sys.argv or "-w" in sys.argv
    result = check_health.invoke({"detailed": detailed, "workspace_only": ws_only,
                                  "connectivity_sample": 0})
    print(json.dumps(result, indent=2))
