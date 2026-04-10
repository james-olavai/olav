# Olav Skill Development Reference

## What is a Skill?

In Olav, a **skill** is a workspace directory that packages:
- An agent identity (`AGENT.md`) — who this agent is and how to configure it
- A router manifest (`MANIFEST.yaml`) — keywords so the router can route queries here
- Tools (`SKILL.md` + `tools/`) — `@tool` functions the agent can call
- A system prompt (`prompts/system.md`) — what the agent knows and how it behaves
- References (`references/`) — static context injected into the system prompt

Skills are installed into `.olav/workspace/<name>/`. The platform auto-discovers
them. No code changes needed — drop files, the platform picks them up.

---

## Workspace Directory Structure

```
.olav/workspace/
└── <skill-name>/
    ├── AGENT.md            ← Required: agent config (YAML frontmatter + description)
    ├── MANIFEST.yaml       ← Required: router metadata
    ├── SKILL.md            ← Required: tool list + static_context
    ├── prompts/
    │   └── system.md       ← Agent system prompt (Markdown, plain text)
    ├── tools/
    │   ├── mytool.py       ← Each @tool decorated function in its own file
    │   └── ...
    └── references/
        └── API_GUIDE.md    ← Injected into system prompt via static_context
```

---

## File Formats

### AGENT.md

```yaml
---
name: netbox
description: "NetBox DCIM/IPAM — device inventory and IP management queries"
system_prompt_file: prompts/system.md
---

# NetBox Agent

Handles queries against the NetBox DCIM and IPAM API.
```

### MANIFEST.yaml

```yaml
kind: Agent
name: netbox
version: "1.0.0"
description: "NetBox DCIM/IPAM — device inventory and IP management queries"
route_keywords:
  - netbox
  - dcim
  - ipam
  - device inventory
  - ip address management
  - prefix
  - vlan
```

### SKILL.md

```yaml
---
name: netbox
description: "NetBox API tools — DCIM and IPAM"
tools:
  - netbox_dcim          # tools/netbox_dcim.py
  - netbox_ipam          # tools/netbox_ipam.py
static_context:
  - path: ./references/API_GUIDE.md
---

# NetBox Skill

Tools for querying NetBox via its REST API.
```

### tools/example_tool.py

```python
from langchain_core.tools import tool

@tool
def get_devices(site: str = "") -> list[dict]:
    """Query NetBox for all devices, optionally filtered by site."""
    from olav.platform.services.client import service_call
    params = {"site": site} if site else {}
    return service_call("netbox", "GET", "/api/dcim/devices/", params=params)
```

---

## Workflow: Create a New Skill from Scratch

### Step 1 — Check if the target service is running

```python
# Use run_python_code:
import requests
resp = requests.get("http://192.168.1.200:8000/api/", headers={"Authorization": "Token abc123"})
_result = {"status": resp.status_code, "ok": resp.ok}
```

### Step 2 — Register the service schema

```bash
# Via CLI (agent can call this via execute or run_python_code):
olav registry register <name>

# Or update .olav/config/services.yaml first, then register:
# services.yaml entry needed: endpoint, schema_url, auth.type, auth.token_env
```

After registration, the API reference markdown appears in:
`.olav/workspace/infra/references/<name>_<tag>_api.md`

Use `api_request(service="<name>", path="...", ...)` to call the service.

### Step 3 — Create the skill workspace directory

```python
# Use run_python_code to create the files:
import os
from pathlib import Path

ws = Path(".olav/workspace/netbox")
(ws / "prompts").mkdir(parents=True, exist_ok=True)
(ws / "tools").mkdir(exist_ok=True)
(ws / "references").mkdir(exist_ok=True)

# Write AGENT.md
(ws / "AGENT.md").write_text("""---
name: netbox
description: "NetBox DCIM/IPAM queries"
system_prompt_file: prompts/system.md
---
""")

# Write MANIFEST.yaml
(ws / "MANIFEST.yaml").write_text("""kind: Agent
name: netbox
version: "1.0.0"
description: "NetBox DCIM/IPAM queries"
route_keywords:
  - netbox
  - dcim
  - device inventory
  - ip address
  - vlan
  - prefix
""")

# Write SKILL.md (reference generated tools)
(ws / "SKILL.md").write_text("""---
name: netbox
description: "NetBox API tools"
tools:
  - netbox_dcim
  - netbox_ipam
---
""")

_result = {"created": str(ws)}
```

### Step 4 — Install and activate

```bash
olav skill install .olav/workspace/netbox
olav workspace use netbox
```

### Step 5 — Verify

```bash
olav workspace validate netbox
olav workspace status
```

---

## How API Schema Awareness Works

When you run `olav registry register <name>`:

1. Platform fetches the OpenAPI schema from `schema_url`
2. Operations are stored in `~/.olav/olav_registry.duckdb`
3. A markdown reference file is generated in `.olav/workspace/infra/references/`
4. Use `api_request(service=name, ...)` to call any endpoint (auth automatic)

The agent is "schema-aware" because:
- The reference markdown lists each endpoint with parameters
- `api_request` automatically handles auth and HITL for writes
- The infra agent prompt directs it to consult the reference docs

To check what was registered:
```bash
# Check registered services
olav registry list

# Find a specific operation
# (no direct CLI; query the DuckDB directly)
```

---

## Key CLI Commands for Skill Management

```bash
# List installed workspaces
olav workspace list

# Check workspace + agent status
olav workspace status

# Switch active workspace
olav workspace use <name>

# Validate workspace integrity
olav workspace validate <name>

# Install from local directory
olav skill install <path>

# Register external service schema
olav registry register <name>

# Check registry
olav registry list
olav registry status <name>
```

---

## services.yaml Reference

To register a new service, add an entry to `.olav/config/services.yaml`:

```yaml
services:
  myservice:
    display_name: "My Service"
    description: "Description of what this service does"
    endpoint: "http://hostname:port"
    schema_url: "http://hostname:port/api/schema/?format=json"
    auth:
      type: bearer        # bearer | jwt | basic | none
      token_env: MY_SERVICE_TOKEN   # env var holding the token
    reference_generation:
      output_dir: ".olav/workspace/infra/references"
      groups:
        - tag: "devices"
          description: "Device management endpoints"
    permissions:
      admin:
        actions: [use, mutate, install, admin]
      user:
        actions: [use]
```

Then run: `olav registry register myservice`

---

## What NOT to Do

- **Do not** hardcode API calls — use `service_call()` from the platform client
- **Do not** put domain-specific tools in `core/tools/` — those are platform primitives only
- **Do not** edit `workspace.lock.yaml` by hand — it is written by `olav skill install`
- **Do not** put Python package logic in tools — tools call platform functions, not implement them
