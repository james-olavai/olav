#!/usr/bin/env python3
"""check_health.py - OLAV System Health Checker.

Validates configuration, architecture, and performance against best practices.
"""

import json
import os
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


def _check_env() -> dict:
    """Check environment configuration."""
    results = {"status": "ok", "checks": []}

    env_file = _PROJECT_ROOT / ".env"
    if env_file.exists():
        results["checks"].append({"name": ".env exists", "status": "ok"})
    else:
        results["checks"].append(
            {"name": ".env exists", "status": "warning", "message": "No .env file"}
        )

    api_key = os.getenv("LLM_API_KEY")
    if api_key:
        results["checks"].append({"name": "LLM_API_KEY set", "status": "ok"})
    else:
        results["checks"].append(
            {"name": "LLM_API_KEY set", "status": "error", "message": "Missing LLM_API_KEY"}
        )
        results["status"] = "error"

    provider = os.getenv("LLM_PROVIDER", "openai")
    valid_providers = [
        "openai",
        "anthropic",
        "openrouter",
        "xai",
        "groq",
        "mistral",
        "ollama",
        "azure",
    ]
    if provider in valid_providers:
        results["checks"].append({"name": f"LLM_PROVIDER={provider}", "status": "ok"})
    else:
        results["checks"].append(
            {
                "name": f"LLM_PROVIDER={provider}",
                "status": "warning",
                "message": "Unknown provider",
            }
        )

    return results


def _check_olav_md() -> dict:
    """Check OLAV.md configuration."""
    results = {"status": "ok", "checks": []}

    olav_md = _OLAV_DIR / "OLAV.md"
    if not olav_md.exists():
        results["checks"].append(
            {"name": "OLAV.md exists", "status": "error", "message": "Missing .olav/OLAV.md"}
        )
        results["status"] = "error"
        return results

    results["checks"].append({"name": "OLAV.md exists", "status": "ok"})

    try:
        import yaml

        content = olav_md.read_text()
        if content.startswith("---"):
            yaml_end = content.index("---", 3) + 3
            yaml_content = content[3 : yaml_end - 3]
            config = yaml.safe_load(yaml_content)

            if "subagents" in config:
                results["checks"].append(
                    {"name": "SubAgents defined", "status": "ok", "count": len(config["subagents"])}
                )
            else:
                results["checks"].append(
                    {
                        "name": "SubAgents defined",
                        "status": "error",
                        "message": "No subagents section",
                    }
                )
                results["status"] = "error"

            if "orchestrator" in config:
                results["checks"].append({"name": "Orchestrator defined", "status": "ok"})
            else:
                results["checks"].append({"name": "Orchestrator defined", "status": "warning"})

        else:
            results["checks"].append(
                {"name": "OLAV.md format", "status": "error", "message": "No YAML frontmatter"}
            )
            results["status"] = "error"

    except Exception as e:
        results["checks"].append({"name": "OLAV.md parse", "status": "error", "message": str(e)})
        results["status"] = "error"

    return results


def _check_skills() -> dict:
    """Check skills configuration."""
    results = {"status": "ok", "checks": [], "skills": []}

    required_skills = ["olav-ops", "olav-config", "olav-audit"]
    skills_dir = _OLAV_DIR / "skills"

    if not skills_dir.exists():
        results["checks"].append(
            {"name": "skills directory", "status": "error", "message": "Missing .olav/skills/"}
        )
        results["status"] = "error"
        return results

    for skill_name in required_skills:
        skill_path = skills_dir / skill_name
        skill_md = skill_path / "SKILL.md"
        prompt_md = skill_path / "prompts" / "system.md"

        skill_result = {"name": skill_name, "checks": []}

        if skill_md.exists():
            skill_result["checks"].append({"name": "SKILL.md", "status": "ok"})
        else:
            skill_result["checks"].append(
                {"name": "SKILL.md", "status": "error", "message": "Missing"}
            )
            results["status"] = "error"

        if prompt_md.exists():
            skill_result["checks"].append({"name": "prompts/system.md", "status": "ok"})
        else:
            skill_result["checks"].append(
                {"name": "prompts/system.md", "status": "error", "message": "Missing"}
            )
            results["status"] = "error"

        tools_dir = skill_path / "tools"
        if tools_dir.exists():
            py_files = list(tools_dir.glob("*.py"))
            skill_result["checks"].append(
                {"name": "tools directory", "status": "ok", "count": len(py_files)}
            )
        else:
            skill_result["checks"].append(
                {"name": "tools directory", "status": "warning", "message": "No tools dir"}
            )

        results["skills"].append(skill_result)

    return results


def _check_database() -> dict:
    """Check database health."""
    results = {"status": "ok", "checks": [], "stats": {}}

    db_dir = _OLAV_DIR / "databases"
    main_db = db_dir / "main.duckdb"
    llm_cache = db_dir / "llm_cache.sqlite"
    checkpoints = db_dir / "checkpoints.sqlite"

    if not main_db.exists():
        results["checks"].append(
            {
                "name": "main.duckdb exists",
                "status": "error",
                "message": "Run 'sync_schemas' to create",
            }
        )
        results["status"] = "error"
        return results

    results["checks"].append(
        {
            "name": "main.duckdb exists",
            "status": "ok",
            "size_mb": round(main_db.stat().st_size / 1024 / 1024, 2),
        }
    )

    try:
        import duckdb

        conn = duckdb.connect(str(main_db), read_only=True)

        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        results["stats"]["tables"] = table_names

        if "devices" in table_names:
            device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            results["stats"]["devices"] = device_count
            results["checks"].append(
                {"name": "devices table", "status": "ok", "count": device_count}
            )
        else:
            results["checks"].append(
                {"name": "devices table", "status": "warning", "message": "Run 'sync_inventory'"}
            )

        if "parsed_outputs" in table_names:
            output_count = conn.execute("SELECT COUNT(*) FROM parsed_outputs").fetchone()[0]
            results["stats"]["parsed_outputs"] = output_count
            results["checks"].append(
                {"name": "parsed_outputs table", "status": "ok", "count": output_count}
            )
        else:
            results["checks"].append(
                {
                    "name": "parsed_outputs table",
                    "status": "warning",
                    "message": "Run 'take_snapshot'",
                }
            )

        conn.close()

    except Exception as e:
        results["checks"].append({"name": "Database read", "status": "error", "message": str(e)})
        results["status"] = "error"

    if llm_cache.exists():
        try:
            conn = sqlite3.connect(str(llm_cache))
            count = conn.execute("SELECT COUNT(*) FROM full_llm_cache").fetchone()[0]
            results["stats"]["llm_cache_entries"] = count
            results["checks"].append({"name": "llm_cache.sqlite", "status": "ok", "entries": count})
            conn.close()
        except:
            results["checks"].append(
                {"name": "llm_cache.sqlite", "status": "ok", "message": "Empty or new"}
            )

    if checkpoints.exists() and checkpoints.stat().st_size > 0:
        results["checks"].append(
            {"name": "checkpoints.sqlite", "status": "ok", "message": "Checkpointer enabled"}
        )
    else:
        results["checks"].append(
            {"name": "checkpoints.sqlite", "status": "warning", "message": "Not enabled"}
        )

    return results


def _check_nornir() -> dict:
    """Check Nornir inventory."""
    results = {"status": "ok", "checks": []}

    hosts_yaml = _OLAV_DIR / "config" / "nornir" / "hosts.yaml"

    if hosts_yaml.exists():
        results["checks"].append({"name": "hosts.yaml exists", "status": "ok"})
        try:
            import yaml

            with open(hosts_yaml) as f:
                inventory = yaml.safe_load(f)
            if inventory:
                host_count = len(inventory.get("hosts", {}))
                results["checks"].append(
                    {"name": "Device inventory", "status": "ok", "devices": host_count}
                )
            else:
                results["checks"].append(
                    {"name": "Device inventory", "status": "warning", "message": "Empty inventory"}
                )
        except Exception as e:
            results["checks"].append(
                {"name": "hosts.yaml parse", "status": "error", "message": str(e)}
            )
            results["status"] = "error"
    else:
        results["checks"].append(
            {"name": "hosts.yaml exists", "status": "warning", "message": "No Nornir inventory"}
        )

    return results


def _check_performance() -> dict:
    """Check performance metrics from logs."""
    results = {"status": "ok", "checks": [], "metrics": {}}

    llm_cache = _OLAV_DIR / "databases" / "llm_cache.sqlite"
    if llm_cache.exists():
        try:
            conn = sqlite3.connect(str(llm_cache))

            total = conn.execute("SELECT COUNT(*) FROM full_llm_cache").fetchone()[0]
            results["metrics"]["total_llm_calls"] = total

            tool_calls = conn.execute(
                'SELECT COUNT(*) FROM full_llm_cache WHERE response LIKE \'%"name": "execute_sql"%\''
            ).fetchone()[0]
            results["metrics"]["sql_calls"] = tool_calls

            if total > 0:
                tool_rate = round(tool_calls / total * 100, 1)
                results["metrics"]["tool_call_rate"] = f"{tool_rate}%"

                if tool_rate > 30:
                    results["checks"].append(
                        {"name": "Tool usage", "status": "ok", "rate": f"{tool_rate}%"}
                    )
                elif tool_rate > 10:
                    results["checks"].append(
                        {"name": "Tool usage", "status": "warning", "rate": f"{tool_rate}%"}
                    )
                else:
                    results["checks"].append(
                        {"name": "Tool usage", "status": "warning", "message": "Low tool usage"}
                    )

            conn.close()
        except Exception as e:
            results["checks"].append(
                {"name": "Performance metrics", "status": "warning", "message": str(e)}
            )

    return results


def _generate_recommendations(health_data: dict) -> list[str]:
    """Generate improvement recommendations based on health check."""
    recommendations = []

    for check in health_data.get("env", {}).get("checks", []):
        if check["status"] == "error":
            if "LLM_API_KEY" in check["name"]:
                recommendations.append("Set LLM_API_KEY in .env file")

    for check in health_data.get("olav_md", {}).get("checks", []):
        if check["status"] == "error":
            if "OLAV.md" in check["name"]:
                recommendations.append("Create .olav/OLAV.md with SubAgent definitions")

    for check in health_data.get("database", {}).get("checks", []):
        if check["status"] == "error" and "main.duckdb" in check["name"]:
            recommendations.append("Run 'sync_schemas' to initialize database")
        if check.get("message") == "Run 'sync_inventory'":
            recommendations.append("Run 'sync_inventory' to load devices from hosts.yaml")
        if check.get("message") == "Run 'take_snapshot'":
            recommendations.append("Run 'take_snapshot' to collect device data")

    for check in health_data.get("nornir", {}).get("checks", []):
        if check["status"] == "warning" and "hosts.yaml" in check["name"]:
            recommendations.append("Create .olav/config/nornir/hosts.yaml with device inventory")

    stats = health_data.get("database", {}).get("stats", {})
    if stats.get("devices", 0) == 0:
        recommendations.append("No devices in database - run 'sync_all' to populate")
    if stats.get("parsed_outputs", 0) == 0:
        recommendations.append("No parsed outputs - run 'take_snapshot' to collect data")

    if not recommendations:
        recommendations.append("System is healthy - no immediate improvements needed")

    return recommendations


@tool
def check_health(detailed: bool = False) -> dict:
    """Check OLAV system health against best practices.

    Validates configuration, database, skills, and performance.
    Use this for system diagnostics and improvement recommendations.

    Args:
        detailed: If True, include detailed per-skill breakdown

    Returns:
        Health check results with status, checks, and recommendations

    Example:
        >>> check_health()
        {
            "status": "ok",
            "summary": "3 errors, 2 warnings",
            "recommendations": ["Run 'sync_schemas' to initialize database"]
        }
    """
    health = {
        "status": "ok",
        "env": _check_env(),
        "olav_md": _check_olav_md(),
        "skills": _check_skills() if detailed else {"status": "ok", "checks": []},
        "database": _check_database(),
        "nornir": _check_nornir(),
        "performance": _check_performance(),
    }

    error_count = sum(
        1
        for section in health.values()
        if isinstance(section, dict) and section.get("status") == "error"
    )
    warning_count = sum(
        1
        for section in health.values()
        if isinstance(section, dict) and section.get("status") == "warning"
    )

    if error_count > 0:
        health["status"] = "error"
    elif warning_count > 0:
        health["status"] = "warning"

    health["summary"] = f"{error_count} errors, {warning_count} warnings"
    health["recommendations"] = _generate_recommendations(health)

    return health


if __name__ == "__main__":
    import sys

    detailed = "--detailed" in sys.argv or "-d" in sys.argv
    result = check_health.invoke({"detailed": detailed})
    print(json.dumps(result, indent=2))
