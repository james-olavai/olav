# Managing Workspaces

The workspace (`.olav/workspace/`) is where all of OLAV's Agent and Skill definitions live. Think of it as OLAV's "capability library" — installing new skills, switching Agents, and managing versions all happen here.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-03 | `olav workspace list/use` lists and switches the active workspace | ✅ v0.10.0 |
    | C-L2-04 | `olav skill install <path>` installs a local Skill | ✅ v0.10.0 |
    | C-L2-36 | `olav skill list/status` shows installed skills | ✅ v0.10.0 |
    | C-L2-43 | `olav workspace status` displays Agent status | ✅ v0.10.0 |

---

## Viewing the Workspace

```bash
olav workspace list
```

```
  audit                 -       (user)
  config                -       (user)
  core                  -       (user)
* quick                 -       (user)    ← * = currently active Agent
  venv-test             v1.0.0  (managed) ← managed = installed via olav skill install
  verify-skill          v1.0.0  (managed)
```

Two sources:

- **(user)** — Agents created manually in `.olav/workspace/`, typically built-in or custom
- **(managed)** — Skill packages installed via `olav skill install`

View detailed information about a specific skill:

```bash
olav skill status venv-test
```

```
name:    venv-test
version: 1.0.0
source:  /tmp/venv-test-skill
installed: 2026-03-31T05:32:54
```

---

## Switching the Active Agent

The active Agent is the default Agent used when you run `olav` or `olav "question"`:

```bash
olav workspace use config     # Switch to config Agent
olav workspace use quick      # Switch back to quick Agent
```

After switching, all queries without `--agent` will be routed to the new active Agent.

---

## Installing Skills

```bash
# Install from a local directory (must contain MANIFEST.yaml or workspace.yaml)
olav skill install ./my-custom-tools/
# installed my-skill v0.1.0 → .olav/workspace/my-skill/

# Install from a Git repository
olav skill install https://github.com/your-org/my-skill

# Append tools to an existing Agent
olav skill install ./extra/ --merge-into existing-skill
```

Installed skills are available immediately — no restart required. See [Building a Custom Skill →](build-a-skill.md)

---

## Uninstalling Skills

Simply delete the workspace directory:

```bash
rm -rf .olav/workspace/my-skill/
```

There is currently no `olav skill remove` command — filesystem deletion is the uninstall method.

---

## Workspace Directory Structure

```
.olav/workspace/
├── quick/                          ← Built-in Agent
│   ├── AGENT.md                    ← Agent definition (name, description, system prompt, sub-agents)
│   └── MANIFEST.yaml               ← Routing keywords, version info
├── config/                         ← Built-in Agent (with multiple sub-skills)
│   ├── AGENT.md
│   ├── creator/SKILL.md            ← Sub-skill: Creator Agent (generates tool code)
│   ├── discovery/SKILL.md          ← Sub-skill: Service discovery
│   ├── knowledge/SKILL.md          ← Sub-skill: Knowledge base management
│   └── system/SKILL.md             ← Sub-skill: System health check
└── venv-test/                      ← Installed skill (managed)
    ├── MANIFEST.yaml
    ├── tools.py                    ← Tool functions
    └── .venv/                      ← Isolated Python virtual environment
```

### Key Files Explained

- **AGENT.md**: The Agent's "identity card" — defines the Agent's name, role description, system prompt, and which sub-agents/skills it can invoke
- **MANIFEST.yaml**: Skill metadata — name, version number, routing keywords, dependency declarations
- **SKILL.md**: Sub-skill binding file — binds a set of tool functions to a specific Agent
- **tools.py**: The actual Python tool functions — `@tool` functions that the Agent can call

---

## Version Control

Workspace definitions can be safely committed to Git and shared with the team:

```bash
git add .olav/workspace/
git commit -m "feat: add my-skill"
```

**Do not commit the following** (add to `.gitignore`):

```gitignore
.olav/databases/   # Database files
.olav/config/      # Contains API keys
.olav/run/         # Runtime PID files
```

This way, when team members pull the code, they have the same Agent definitions and skills — they just need to configure their own `api.json` to get started.
