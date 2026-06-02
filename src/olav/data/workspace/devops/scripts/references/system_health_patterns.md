# System Health Script Patterns

Reference patterns for the **devops agent** when writing health-check scripts.
These patterns use the same tools (`check_health`, `analyze_logs`, `audit_workspace`)
that the `config/system` subagent calls directly — here as code templates.

---

## Pattern 1: Service Health Check

```python
import subprocess, json

def check_service_health(service_name: str, health_url: str) -> dict:
    """Poll a service endpoint and check container state."""
    # Container state via docker compose
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=f".olav/services/{service_name}",
        capture_output=True, text=True,
    )
    containers = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    running = all(c.get("State") == "running" for c in containers)

    # HTTP probe
    import urllib.request
    try:
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            http_ok = resp.status < 500
    except Exception:
        http_ok = False

    return {"containers": containers, "running": running, "http_ok": http_ok}
```

---

## Pattern 2: Log Analysis

```python
import subprocess, re

def analyze_service_logs(service_name: str, tail: int = 100) -> dict:
    """Extract errors and warnings from service logs."""
    result = subprocess.run(
        ["docker", "compose", "logs", f"--tail={tail}", "--no-color"],
        cwd=f".olav/services/{service_name}",
        capture_output=True, text=True,
    )
    lines = result.stdout.splitlines()
    errors = [l for l in lines if re.search(r"error|exception|failed|critical", l, re.I)]
    warnings = [l for l in lines if re.search(r"warn|deprecated", l, re.I)]
    return {"total_lines": len(lines), "errors": errors[:20], "warnings": warnings[:10]}
```

---

## Pattern 3: Workspace Audit

```python
from pathlib import Path
import yaml

def audit_workspace(workspace_name: str) -> dict:
    """Check workspace structure and tool availability."""
    ws_dir = Path(".olav/workspace") / workspace_name
    skill_md = ws_dir / "SKILL.md"
    if not skill_md.exists():
        return {"status": "error", "message": "no SKILL.md"}

    text = skill_md.read_text()
    fm = yaml.safe_load(text.split("---")[1]) if "---" in text else {}
    tools = fm.get("tools", [])
    missing = [t if isinstance(t, str) else t.get("path", "?")
               for t in tools
               if not (ws_dir / "tools" / (t if isinstance(t, str) else t.get("path", ""))).exists()]
    return {"workspace": workspace_name, "tool_count": len(tools), "missing_tools": missing}
```

---

## When to use config/system tools vs. scripting

| Need | Use |
|------|-----|
| One-off health probe in an agentic run | `check_health` tool directly |
| Log analysis during investigation | `analyze_logs` tool directly |
| Generating a reusable health-check script | devops agent + this reference |
| CI/CD pipeline integration | devops agent generates standalone `.py` / `.sh` |
