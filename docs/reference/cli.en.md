# CLI Command Reference

All OLAV features are accessible via the command line.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-01 | `olav version` | ✅ v0.10.0 |
    | C-L2-02 | `olav list` | ✅ v0.10.0 |
    | C-L2-10 | `olav export claude-plugin` | ✅ v0.10.0 |
    | C-L2-13 | `olav init` | ✅ v0.10.0 |
    | C-L2-27 | `olav reset --agent` | ✅ v0.10.0 |
    | C-L2-14 | TUI interactive mode | ✅ v0.10.0 |

---

## Basic Usage

```
olav [options] [command] [query]
```

### Global Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--agent NAME` | `-a` | `quick` | Specify which Agent to use |
| `--auto-approve` | | off | Automatically approve all tool calls (skip confirmation) |
| `--dangerously-skip-permissions` | | off | Skip permission checks (development only) |
| `--sandbox MODE` | | `none` | Sandbox mode: `none` (local) / `modal` / `daytona` / `runloop` (remote) |
| `--verbose` | `-v` | off | Show verbose output (for debugging) |
| `--no-splash` | | off | Skip startup banner |
| `--session ID` | | | Resume a previous session |
| `--version` | `-V` | | Show version number |

---

## Command List

### Basic Commands

| Command | Description |
|---------|-------------|
| `olav "your question"` | Natural language query (using the default Agent) |
| `olav --agent config "..."` | Query with a specific Agent |
| `olav` | Launch the interactive terminal (TUI) |
| `olav version` | Show the platform version |
| `olav list` | List all available Agents |
| `olav init` | Initialize an OLAV project in the current directory |

### Workspace Management

| Command | Description |
|---------|-------------|
| `olav workspace list` | List all workspaces (`*` marks the active one) |
| `olav workspace use <name>` | Switch the active workspace |
| `olav workspace status` | Show workspace status |

### Skill Management

| Command | Description |
|---------|-------------|
| `olav skill install <path\|URL>` | Install a skill from a local directory or Git repository |
| `olav skill install <path> --merge-into <ws>` | Append tools to an existing workspace |
| `olav skill list` | List installed skills |
| `olav skill status <name>` | View skill details (version, source, install time) |

### Service Registry

| Command | Description |
|---------|-------------|
| `olav registry register <name>` | Register an external service (auto-discovers OpenAPI schema and generates tools) |
| `olav registry refresh <name>` | Force re-fetch the schema of a registered service |
| `olav registry list` | List all registered external services |
| `olav registry status <name>` | Check the reachability of a registered service |

### Audit and Logs

| Command | Description |
|---------|-------------|
| `olav log list` | Operations from the last 24 hours |
| `olav log errors [--hours N]` | Show only error events |
| `olav log show <run-id>` | View full details of a specific operation |
| `olav log export sft\|trajectory\|atif` | Export audit data in training formats |

### Background Services

| Command | Description |
|---------|-------------|
| `olav service web start [--port N]` | Start the Web service (default port 2280) |
| `olav service daemon start` | Start the Daemon accelerator service |
| `olav service logs start [--port N]` | Start the Syslog receiver service (default port 5514) |
| `olav service start --all` | Start all background services |
| `olav service stop --all` | Stop all background services |
| `olav service status` | View service status |

### Admin Commands

| Command | Description |
|---------|-------------|
| `olav admin "add-user <name> --role <role>"` | Add a user |
| `olav admin "list-users"` | List all users |
| `olav admin "revoke-token <name>"` | Revoke a user's token |
| `olav admin "rotate-token <name>"` | Rotate a user's token |

### Schema Evolution

| Command | Description |
|---------|-------------|
| `olav config evolve --list` | View pending schema evolution proposals |
| `olav config evolve --approve <id>` | Approve and apply a schema evolution |

### Other

| Command | Description |
|---------|-------------|
| `olav export claude-plugin` | Export Claude plugin artifacts |
| `olav reset --agent <name>` | Reset an Agent's conversation history |

---

## Interactive Mode (TUI)

Run `olav` without a query argument to launch the interactive terminal:

```bash
olav                      # Use the default Agent
olav --agent config       # Use a specific Agent
olav --no-splash          # Skip the startup banner
olav --session <id>       # Resume a previous session
```

### Slash Commands in Interactive Mode

| Command | Description |
|---------|-------------|
| `/help` | Show the list of available commands |
| `/clear` | Reset the conversation and clear the screen |
| `/tokens` | Show token consumption for the current session |
| `/model <name>` | Temporarily switch the LLM model within the session (does not modify config files) |
| `/trace-review` | Analyze failures from the last 7 days and automatically extract lessons learned into memory |
| `/quit` `/exit` `/q` | Exit interactive mode |

### Special Syntax in Interactive Mode

| Syntax | Description |
|--------|-------------|
| `@file.txt` | Inject file contents into the current prompt |
| `!command` | Execute a shell command directly (bypassing the Agent) |

---

## Comparison of the Three Interfaces

| Interface | How to Start | Best For |
|-----------|-------------|----------|
| **CLI** | `olav "query"` | Script integration, one-off queries, automation pipelines |
| **TUI** | `olav` (no arguments) | Multi-turn conversations, exploratory analysis, debugging |
| **Web UI** | `olav service web start` → `http://localhost:2280` | Browser access, team sharing |
