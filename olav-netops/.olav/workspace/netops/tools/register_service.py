#!/usr/bin/env python3
"""
register_service — Import an external service API schema and generate reference docs.

Flow:
  1. Fetch OpenAPI schema from the service endpoint
  2. Load operations into api_registry DuckDB
  3. Generate markdown reference file(s) in infra/references/
  4. Return summary of generated reference files

Prerequisites:
  - Service must be running and schema_url reachable
  - Service must be configured in .olav/config/services.yaml

Workflow:
  1. run_shell("docker compose ps") → verify service is healthy
  2. register_service("netbox") → pull schema, generate reference markdown
  3. Inspect returned reference_files to confirm generation
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
    """Import a registered service's OpenAPI schema and generate reference docs.

    Fetches the OpenAPI spec from the running service, stores operations in the
    api_registry, and writes a markdown reference file to infra/references/ for
    each configured tag group. Call this after the service container is healthy.

    Use `api_request(service=service_name, ...)` to query the service after registration.

    Args:
        service_name: Key in .olav/config/services.yaml (e.g. "netbox", "containerlab")
        force:        Re-fetch and regenerate even if already registered (default False)
        max_retries:  Schema fetch attempts (default 3, with 5s between retries)

    Returns:
        {
          "service": "netbox",
          "status": "ok",
          "ops_loaded": 1166,
          "reference_files": [".olav/workspace/infra/references/netbox_dcim_api.md", ...],
          "available_workspaces": [...]
        }
    """
    try:
        from olav.platform.services.tool_generator import register_service as _register
        result = _register(service_name, force=force, max_retries=max_retries, retry_delay=5.0)
        result["available_workspaces"] = _list_workspaces()
        result["next_step"] = (
            f"Service '{service_name}' registered. API reference markdown generated in "
            f"infra/references/. The infra agent can now query this service via api_request. "
            f"No tool code was generated — agents use the core api_request tool directly."
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
