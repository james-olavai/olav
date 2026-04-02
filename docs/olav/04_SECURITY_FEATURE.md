# Security Features

OLAV is an **internal, trusted intranet platform**. The security model is designed to prevent accidental or erroneous destructive operations, not to defend against adversarial external attackers.

---

## Security Architecture

```
Request Path                   Security Mechanism              Constraint Type
────────────────────────────   ─────────────────────────────   ───────────────
execute_cli                    check_approval() — pattern      Hard
execute_sql                    DuckDB read_only=True           Hard
API tool generation            readonly_only=True (GET only)   Hard
service_call (write methods)   requires_approval gate          Hard
sandbox HTTP mutations         sandbox_guard pre-scan          Soft (regex)
sandbox DB mutations (direct)  sandbox_guard pre-scan          Soft (regex)
sandbox DB mutations (indirect)DuckDB monkey-patch             Hard
sandbox network (opt-in)       unshare --net namespace         Hard (opt-in)
memory / KB writes             injection_scanner               Soft (regex)
```

**Hard constraint** — enforced at the execution layer, cannot be bypassed by user code.
**Soft constraint** — regex/pattern-based scan, covers common cases; known bypasses exist (see §5).

---

## 1. Identity & Authentication

Users are identified by OS username (`$USER`) at Tier 0. The platform supports token-based authentication for multi-user deployments.

```bash
# Add a user
olav admin add-user alice --role user

# Revoke access
olav admin revoke-token alice

# Rotate token (90-day policy)
olav admin rotate-token alice
```

**Roles:**

| Role | Permissions |
|------|-------------|
| `admin` | Full access — workspace lifecycle, user management, all agents |
| `user` | Standard access — all agents, `use` + `mutate` skill actions |
| `readonly` | Read-only queries only — no `mutate`, `install`, or `admin` actions |

---

## 2. Role-Based Access Control (RBAC)

Authorization is checked at the workspace command level.

```bash
# workspace lifecycle is admin-only
olav workspace install <path>    # requires admin role
olav workspace remove <name>     # requires admin role

# skill install / upgrade is admin-only
olav skill install <path>        # requires admin role
```

Non-admin users receive a `denied:` response for lifecycle operations. Read queries and agent invocations are available to all roles.

---

## 3. Dangerous CLI Command Approval

**File:** `src/olav/platform/safety/approval.py`

All `execute_cli` calls pass through `check_approval()` before reaching the network device. Dangerous commands return `{"status": "requires_approval"}` — the agent must obtain explicit confirmation before proceeding.

**Blocked categories (severity: high):**

| Category | Examples |
|----------|---------|
| Device reload | `reload`, `reload in 5` |
| Config wipe | `write erase`, `erase startup-config` |
| Routing protocol removal | `no router bgp`, `no router ospf` |
| Interface shutdown | `interface X` + `shutdown` |
| AAA disable | `no aaa new-model` |
| Filesystem format | `format flash:` |

Read-only commands (`show`, `ping`, `traceroute`, `display`, etc.) are whitelisted and never trigger approval.

```python
# Response when approval is required:
{
    "status": "requires_approval",
    "severity": "high",
    "reason": "Remove routing protocol — may cause network-wide reachability loss on R1",
    "suggested_action": "Use record_hitl_requested() to escalate to a human operator..."
}
```

---

## 4. Read-Only Constraints

### 4.1 Database (`execute_sql`)

All SQL queries are executed on a `read_only=True` DuckDB connection. `DELETE`, `DROP`, `UPDATE`, `INSERT` are rejected at the driver level — no approval flow, just a hard error.

### 4.2 API Tool Generation (`readonly_only`)

Services are configured with `readonly_only: true` by default. The tool generator only emits `GET` operations; write-method tools (`POST`, `PUT`, `DELETE`) are never created.

```yaml
# .olav/config/services.yaml
netbox:
  readonly_only: true      # only GET tools generated (default)

containerlab:
  readonly_only: false     # lab system — deploy/destroy tools needed
```

### 4.3 `service_call` Write Gate

Any call to `service_call()` with a write method (`DELETE`, `POST`, `PUT`, `PATCH`) returns `requires_approval` before any HTTP request is made.

```python
service_call("containerlab", "DELETE", "/api/v1/labs/prod")
# → {"status": "requires_approval", "method": "DELETE", "path": "/api/v1/labs/prod", ...}
```

---

## 5. Sandbox Security

The `run_python_code` / `execute_in_sandbox` sandbox applies three layers:

### 5.1 Pre-execution scan (`sandbox_guard`)

Detects external write operations in the code string before execution:

```python
httpx.delete(...)          # → requires_approval
httpx.post(...)            # → requires_approval
requests.put(...)          # → requires_approval
service_call("x","DELETE") # → requires_approval
.execute("DELETE FROM ...") # → requires_approval
.execute("DROP TABLE ...")  # → requires_approval
```

Local filesystem operations are always permitted:
```python
open('/tmp/out.csv', 'w')      # ✅ allowed
os.remove('/tmp/old.txt')      # ✅ allowed
shutil.rmtree('/tmp/work')     # ✅ allowed
httpx.get('http://...')        # ✅ allowed
```

### 5.2 DuckDB monkey-patch (hard constraint)

Every sandbox script begins with a prologue that overrides `duckdb.connect()` to force `read_only=True`, regardless of what user code passes:

```python
# Injected automatically — cannot be removed by user code
import duckdb as _olav_ddb
_olav_ddb_orig_connect = _olav_ddb.connect
def _olav_ddb_safe_connect(database=':memory:', read_only=False, **kw):
    return _olav_ddb_orig_connect(database, read_only=True, **kw)
_olav_ddb.connect = _olav_ddb_safe_connect
```

This covers bypasses that `sandbox_guard` cannot detect (variable interpolation, aliased imports).

### 5.3 Network namespace isolation (opt-in)

Set `OLAV_SANDBOX_NETNS=1` to run sandbox subprocesses inside a network namespace using `unshare --net`. All network access (`httpx`, `socket`, `urllib`, `aiohttp`, raw sockets) returns `Connection refused`.

```bash
export OLAV_SANDBOX_NETNS=1   # enable for high-security sessions
```

Falls back silently if `unshare` is not available. Disabled by default — in a trusted intranet deployment, legitimate `httpx.get()` calls in the sandbox are useful.

### 5.4 Known limitations

The `sandbox_guard` regex scan has bypasses that are acceptable for the trusted intranet threat model:

- Import aliasing: `import httpx as h; h.delete(...)`
- Dynamic method: `getattr(httpx, "delete")(...)`
- Subprocess re-execution: write to `/tmp/x.py`, then `subprocess.run(['python3', '/tmp/x.py'])`
- Uncovered HTTP libraries: `urllib`, `aiohttp`

The DuckDB monkey-patch (§5.2) and network namespace (§5.3) address the most critical of these.

---

## 6. Prompt Injection Scanning

**File:** `src/olav/platform/safety/injection_scanner.py`

Applied at write paths for memory and knowledge stores:

- `recall_memory` writes
- SKILL.md / AGENT.md loading
- KB document imports

Detects: role-hijacking patterns, instruction override, data-exfiltration payloads, invisible Unicode.

---

## 7. Audit Logging

All tool calls are recorded in `audit.duckdb`. This provides post-hoc accountability even when pre-emptive controls are bypassed.

```bash
# Query audit log
olav ask "Show all execute_cli calls from today"
olav ask "Show all requires_approval events in the last 7 days"
```

Network-significant events can be recorded explicitly:

```python
# Agent writes an explicit change event
record_network_event(
    event_type="config_push",
    device="R1",
    description="Pushed BGP neighbor config",
    before_state="...",
    after_state="...",
)
```

---

## 8. Deployment Checklist

```
[ ] Set OLAV_SANDBOX_NETNS=1 if stricter network isolation is needed
[ ] Confirm services.yaml — all production services have readonly_only: true
[ ] Confirm containerlab readonly_only: false is intentional
[ ] Add users with appropriate roles (admin / user / readonly)
[ ] Rotate admin token on first deployment
```

---

## 9. What Is Not In Scope

| Feature | Reason excluded |
|---------|----------------|
| External messaging gateways (Slack, Telegram, webhook) | Expands attack surface; conflicts with intranet-only deployment |
| Public API endpoint | Not part of deployment model |
| Guard LLM / semantic firewall | Ineffective against sandbox code obfuscation; execution-layer hard constraints are more reliable |
| SOC2 / ISO 27001 compliance reports | Out of scope for internal tool |
| Multi-tenant isolation | Single trusted-team deployment |
