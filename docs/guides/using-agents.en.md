# Using Agents

At the core of OLAV are multiple AI Agents working together — each Agent focuses on a different domain. You can let OLAV choose automatically, or specify one manually.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-02 | `olav list` lists all available Agents | ✅ v0.10.0 |
    | C-L2-03 | `olav workspace list/use` switches the active workspace | ✅ v0.10.0 |
    | C-L2-26 | `olav --auto-approve` skips tool call confirmation | ✅ v0.10.0 |

---

## View Available Agents

```bash
olav list
```

Example output:
```
Available Agents:

  • config
    Config & System Agent — service registration, data import, workspace health checks
    Location: .olav/workspace/config/

  • core
    Core OLAV platform agent — code execution, SQL queries, platform operations
    Location: .olav/workspace/core/

  • quick  (active)
    Quick Agent — fast data queries, CLI execution, knowledge base search
    Location: .olav/workspace/quick/
```

Compact view:

```bash
olav workspace list
```

```
* quick                 -       (user)    ← * indicates currently active
  config                -       (user)
  core                  -       (user)
  venv-test             v1.0.0  (managed) ← managed = installed via olav skill install
```

---

## Built-in Agents at a Glance

| Agent | Role | Use Cases |
|-------|------|-----------|
| `quick` *(default)* | Fast query assistant | "How many devices are there?" "Which interfaces are down?" — one-step queries |
| `config` | System administrator | Register external services, generate skills, workspace health checks |
| `core` | Full-stack engineer | Execute Python/SQL/Shell, web search, complex data analysis |

---

## Automatic Routing (Default Behavior)

When `--agent` is not specified, OLAV automatically selects the most suitable Agent based on the content of your question:

```bash
olav "Show all devices"              # → auto-routes to quick Agent
olav "Which interfaces are down?"    # → auto-routes to quick Agent
olav "List BGP neighbors"            # → auto-routes to quick Agent
```

Routing is based on the `route_keywords` defined in each Agent's `MANIFEST.yaml`. The default active `quick` Agent is optimized for network operations scenarios.

!!! note "Platform commands bypass routing"
    Built-in commands like `olav version`, `olav list`, and `olav log list` execute directly and do not go through Agent routing.

---

## Manually Specifying an Agent

When you know exactly which Agent you want to use:

```bash
olav --agent config "list registered services"
olav --agent core "what tables are in the database?"
olav --agent core "search: BGP convergence tuning"
```

Shorthand:

```bash
olav -a config "list registered services"
```

---

## Interactive Mode

Launch an interactive terminal with multi-turn conversation support, where the Agent maintains context:

```bash
olav               # start with the default Agent
olav --agent config # start with a specific Agent
```

In interactive mode, the Agent remembers previous conversation content, so you can naturally ask follow-up questions:

```
> Show all devices
> Which of these are routers?
> What are their IOS versions?
```

---

## Switching the Active Agent

The active Agent is the one used by default when you don't specify `--agent`:

```bash
olav workspace list           # view all Agents, * marks the currently active one
olav workspace use config     # switch to the config Agent
olav workspace use quick      # switch back to the quick Agent
```

---

## Skipping Tool Confirmation

By default, the Agent asks for your confirmation before calling a tool. If you trust the operation (e.g., read-only queries), you can skip it:

```bash
olav --auto-approve "run health check"
```

!!! warning "Use with caution"
    `--auto-approve` automatically approves all tool calls, including write operations. It is recommended to use this only when you are certain the query is read-only.
