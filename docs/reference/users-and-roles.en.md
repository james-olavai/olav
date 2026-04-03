# Users and Roles

OLAV supports multi-user collaboration, with roles controlling what each person can do.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-23 | `olav admin "add-user/list-users/revoke-token/rotate-token"` | ✅ v0.10.0 |
    | C-L2-28 | Supports none/token/ldap/ad/oidc authentication modes | ✅ v0.10.0 |
    | C-L2-44 | `rotate-token` and `add-user --expires` | ✅ v0.10.0 |

---

## Role Permissions

| Role | Capabilities | Typical Personnel |
|------|-------------|-------------------|
| `admin` | Everything: manage users, view everyone's logs, modify configuration, install skills | Platform administrators |
| `user` | Run queries, invoke tools, view own audit logs | Day-to-day users (default role) |
| `readonly` | Read-only queries — cannot perform any write operations | Auditors, observers |

---

## User Management (Admin Operations)

### Adding Users

```bash
olav admin "add-user alice --role user"
olav admin "add-user bob --role admin"
```

This prints a one-time token — share it with the user **immediately**, as it cannot be retrieved again.

You can also set a token expiration date:

```bash
olav admin "add-user contractor --role user --expires 2026-06-01"
```

### Listing All Users

```bash
olav admin "list-users"
```

### Token Management

```bash
olav admin "revoke-token alice"    # Revoke immediately (user can no longer log in)
olav admin "rotate-token alice"    # Generate a new token, invalidating the old one
```

---

## User Initial Setup

After receiving a token from the administrator, save it locally:

```bash
mkdir -p ~/.olav
echo "TOKEN_HERE" > ~/.olav/token
chmod 600 ~/.olav/token
```

`chmod 600` ensures only you can read the token file.

---

## Session Management

Conversations in interactive mode are automatically saved as sessions:

```bash
olav --session <id> "Continue the previous conversation"
```

Sessions expire after 24 hours by default. This can be adjusted in the configuration: `auth.session_ttl_hours`.

---

## Data Isolation

| Resource | Scope | Storage Location |
|----------|-------|-----------------|
| Workspaces (Agent definitions) | Shared across project | `.olav/workspace/` |
| Audit logs | Shared across project (tagged with user_id) | `.olav/databases/audit.duckdb` |
| Authentication tokens | Per-user private | `~/.olav/token` |
| Session records | Per-user private | `~/.olav/sessions/` |
| LLM cache | Per-user private | `~/.olav/cache/` |

---

## Admin: Viewing All Activity

Administrators can query the audit database directly to view all users' operation records:

```bash
# Query via OLAV
olav log list

# Or query DuckDB directly (more flexible)
duckdb .olav/databases/audit.duckdb \
  "SELECT user_id, agent_id, status, started_at
   FROM audit_runs
   ORDER BY started_at DESC
   LIMIT 20"
```

---

## Authentication Mode Configuration

Configured in `.olav/config/api.json` — see [Configuration Reference → Authentication Mode](configuration.md#authentication-mode) for details.
