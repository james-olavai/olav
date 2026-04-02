#!/usr/bin/env python3
"""
register_service — Import an external service API schema and generate interaction tools.

Flow:
  1. Fetch OpenAPI schema from the service endpoint
  2. Load operations into api_registry DuckDB
  3. Generate Python @tool files per tag group in _generated/
  4. Return summary of generated files

Prerequisites:
  - Service must be running and schema_url reachable
  - Service must be configured in .olav/config/services.yaml

Workflow:
  1. run_shell("docker compose ps") → verify service is healthy
  2. register_service("netbox") → pull schema, generate tools
  3. Inspect returned files_written to confirm tool generation
"""

import json
import sys
from pathlib import Path

from langchain_core.tools import tool


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _list_workspaces() -> list[dict]:
    """Return all available agents and subagents the user can register tools into."""
    workspace_root = PROJECT_ROOT / ".olav" / "workspace"
    results = []
    for agent_file in sorted(workspace_root.rglob("AGENT.md")):
        rel = agent_file.relative_to(workspace_root)
        name = agent_file.read_text().split("name:", 1)[1].split("\n", 1)[0].strip() if "name:" in agent_file.read_text() else rel.parts[0]
        # Also find subagents listed in this AGENT.md
        subagents = []
        for skill_file in sorted(agent_file.parent.rglob("SKILL.md")):
            skill_rel = skill_file.relative_to(workspace_root)
            skill_name = skill_file.read_text().split("name:", 1)[1].split("\n", 1)[0].strip() if "name:" in skill_file.read_text() else str(skill_rel)
            subagents.append({"path": str(skill_rel), "name": skill_name})
        results.append({
            "agent": name,
            "path": str(rel),
            "subagents": subagents,
        })
    return results


@tool
def register_service(
    service_name: str,
    force: bool = False,
    max_retries: int = 3,
) -> dict:
    """Import a registered service's OpenAPI schema and generate interaction tools.

    Fetches the OpenAPI spec from the running service, stores operations in the
    api_registry, and writes Python @tool files to _generated/ for each configured
    tag group. Call this after the service container is healthy.

    After generation, ALWAYS present the user with the available_workspaces list
    and ask: "Which agent should the new tools be registered under?" before
    modifying any AGENT.md or SKILL.md files.

    Args:
        service_name: Key in .olav/config/services.yaml (e.g. "netbox", "containerlab")
        force:        Re-fetch and regenerate even if already registered (default False)
        max_retries:  Schema fetch attempts (default 3, with 5s between retries)

    Returns:
        {
          "service": "netbox",
          "status": "ok",
          "ops_loaded": 1166,
          "files_written": [...],
          "available_workspaces": [
            {"agent": "ops-orchestrator", "path": "ops/AGENT.md",
             "subagents": [{"path": "ops/netbox/SKILL.md", "name": "ops-netbox"}, ...]},
            ...
          ],
          "next_step": "Ask user which agent to register tools under, then update SKILL.md"
        }
    """
    try:
        from olav.platform.services.tool_generator import register_service as _register
        result = _register(service_name, force=force, max_retries=max_retries, retry_delay=5.0)
        result["available_workspaces"] = _list_workspaces()
        result["next_step"] = (
            f"Tools generated. Ask the user: 'Which agent should {service_name} tools be "
            f"registered under? Options: (1) existing agent from available_workspaces, "
            f"(2) create new standalone workspace.' Then update SKILL.md accordingly."
        )
        return result
    except Exception as exc:
        return {"service": service_name, "status": "error", "error": str(exc)}


if __name__ == "__main__":
    try:
        params = json.loads(sys.stdin.read()) if sys.stdin.read().strip() else {}
        print(json.dumps(register_service.func(**params), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        sys.exit(1)
