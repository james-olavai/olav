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

    for check in health.get("database", {}).get("checks", []):
        if check.get("status") == "warning":
            name = check.get("name", "")
            if "Command registry" in name:
                recs.append("No commands — run 'olav workspace sync' to register commands")
            elif "Schema catalog" in name:
                recs.append("No schema catalog — run schema discovery pipeline")
            elif "Network state views" in name:
                recs.append("No network data — run 'take_snapshot' to collect device state")

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
    - Database health: main.duckdb (network state), audit.duckdb schema + row counts,
      LanceDB memory store, user checkpoint files
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
