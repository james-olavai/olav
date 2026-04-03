# Creator Agent

Creator Agent is OLAV's "skill factory" — it can read any OpenAPI specification and auto-generate a set of ready-to-use Python tool functions.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-20 | Creator Agent auto-generates a Skill workspace from an OpenAPI schema | ✅ v0.10.0 |

---

## Why Do You Need It?

After quickly connecting a service via `registry register`, you may find that:

- The generic proxy generates too many tools or lacks precision
- Certain API operations require special parameter handling
- You want to customize tool descriptions to be more user-friendly for your team

Creator Agent solves these problems — it generates **editable Python code** that you can tailor to your actual needs.

---

## Usage

Tell the config Agent which service you want to integrate:

```bash
olav --agent config "create a skill for Zabbix API http://zabbix.internal/api_jsonrpc.php"
olav --agent config "create a skill for http://myservice/openapi.json"
```

Creator Agent will automatically:

1. Fetch the target service's OpenAPI schema
2. Analyze API endpoints and select key operations
3. Generate a `@tool` Python function for each operation
4. Create a complete Skill directory with metadata and route keywords

## Generated Output

```
.olav/workspace/<service>/
├── SKILL.md        ← Skill description and Agent binding
└── tools.py        ← Python tool functions (one function per key API operation)
```

You can edit `tools.py` directly: rename functions, adjust parameters, add error handling, or include business logic.

## Ready to Use Immediately After Generation

```bash
olav "Show all hosts with active problems in Zabbix"
olav "What new alerts have appeared in the last hour?"
```

OLAV's semantic router automatically invokes the newly generated tools based on the content of your question.

---

## Differences from `registry register`

| | `registry register` | Creator Agent |
|-|---------------------|---------------|
| Output | Generic API proxy (not editable) | Python tool function code (fully editable) |
| Precision | Treats all endpoints equally | Generates tools only for key operations |
| Customization | Cannot modify | Can modify function logic, parameters, descriptions |
| Best for | Quick onboarding, validating feasibility | Long-term use, deep customization |

!!! tip "Recommended Workflow"
    Start with `registry register` to quickly verify that the API works, then use Creator Agent to generate production-ready skill code.
