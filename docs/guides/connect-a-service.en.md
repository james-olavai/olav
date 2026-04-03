# Connect an External Service

OLAV can connect to any external service that provides a REST API. Once connected, you can query it forever using natural language.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-19 | `olav registry register <url>` registers an OpenAPI service with a single command | ✅ v0.10.0 |
    | C-L2-20 | Creator Agent auto-generates Skill code from OpenAPI | ✅ v0.10.0 |

---

## Use Cases

Your team likely uses multiple operations tools: NetBox (IPAM), Zabbix (monitoring), ServiceNow (ticketing), in-house platforms, and more. Each tool has its own API and query methods. OLAV lets you query across systems with a single sentence:

```bash
olav "How many devices are in rack A1?"        # queries NetBox
olav "What active alerts are there in Zabbix?"  # queries Zabbix
olav "List all sites in Europe"                 # queries NetBox
```

---

## Quick Registration: One Command

If the target service provides an OpenAPI (Swagger) specification, registration takes just one command:

```bash
olav registry register http://netbox.example.com/api/schema/
```

OLAV automatically reads the OpenAPI schema, generates calling tools, and then you can query it directly using natural language.

### Services That Require Authentication

Most services require an API Token or other authentication method:

```bash
olav registry register http://netbox.example.com/api/schema/ \
  --header "Authorization: Token YOUR_TOKEN"
```

OLAV's service registration supports multiple authentication methods (Bearer Token, API Key, Basic Auth, JWT), configured in `.olav/config/services.yaml`.

### Managing Registered Services

```bash
olav registry list                        # list all registered services
olav registry status netbox               # check reachability of a service
olav registry refresh netbox              # force re-fetch the schema
olav --agent config "unregister netbox"   # disconnect via Agent
```

---

## Deep Integration: Creator Agent

`registry register` is great for quick onboarding, but it produces a generic API proxy. If you need **more precise tools** — for example, exposing only key operations, customizing parameter names, or adding business logic — use the Creator Agent.

Creator Agent reads the OpenAPI schema and auto-generates a set of customized Python tool functions that you can edit and refine:

```bash
olav --agent config "create a skill for http://zabbix.internal/api_jsonrpc.php"
```

See [Creator Agent →](creator-agent.md) for details.

---

## Comparison of the Two Approaches

| | `registry register` | Creator Agent |
|-|---------------------|---------------|
| Speed | Completes in seconds | Takes a few minutes to generate code |
| Output | Generic API proxy | Customized Python tool functions |
| Editable | No | Yes — edit `tools.py` directly |
| Best for | Quick trials, simple queries | Deep integration, complex business logic |
