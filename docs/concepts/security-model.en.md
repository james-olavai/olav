# Security Model

OLAV was designed from the ground up with security requirements for multi-user, team collaboration scenarios. This page covers how authentication, authorization, and data isolation work.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-23 | `olav admin "add-user/list-users/revoke-token"` user management | ✅ v0.10.0 |
    | C-L2-28 | Supports none/token/ldap/ad/oidc authentication modes | ✅ v0.10.0 |
    | C-L2-12 | Multi-user concurrent audit with no write conflicts | ✅ v0.10.0 |

---

## Authentication: Verifying Who You Are

Each user has a unique token stored at `~/.olav/token`. OLAV validates this token on every request.

### Adding a New User

An administrator creates the user and assigns a role:

```bash
olav admin "add-user alice --role user"
```

After execution, a one-time token is printed -- share it with the user immediately, as it cannot be retrieved again.

### User Configures Token

After receiving the token, the user saves it locally:

```bash
mkdir -p ~/.olav
echo "TOKEN_HERE" > ~/.olav/token
chmod 600 ~/.olav/token
```

Tokens are stored as SHA256 hashes (salted) in `.olav/databases/users.duckdb`. The plaintext token is never saved.

---

## Authorization: What You Can Do

OLAV uses a fixed three-tier role model (RBAC), simple and intuitive:

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| `admin` | Everything -- manage users, view all logs, modify configuration, install skills | -- |
| `user` | Run queries, call tools, view own audit logs | Install/uninstall skills, manage users |
| `readonly` | Read-only queries | Any write operation (modify data, execute commands) |

The permission system matches on `(agent_id, skill_name, action)` triples, supporting fine-grained access control down to specific Agents and Skills. Four operation types:

- **use**: Run queries, call tools
- **mutate**: Modify data, execute write operations
- **install**: Install/uninstall skills
- **admin**: User management, configuration changes

---

## Multi-User Concurrency Safety

OLAV supports multiple users working simultaneously in the same project directory, with clear security boundaries for each resource:

| Resource | Storage Location | Concurrency Safe | Notes |
|----------|-----------------|-----------------|-------|
| Audit logs | `.olav/databases/audit.duckdb` | ✅ | DuckDB atomic writes, each record tagged with user_id |
| LLM cache | `~/.olav/cache/` | ✅ | User-isolated, no interference |
| Session records | `~/.olav/sessions/` | ✅ | User-isolated, auto-expires after 24h |
| Auth tokens | `~/.olav/token` | ✅ | Only readable by current user (chmod 600) |

---

## Authentication Modes

Choose the appropriate authentication method based on your team size and security requirements. Configure in `auth.mode` within `.olav/config/api.json`:

| Mode | Use Case | Description |
|------|----------|-------------|
| `none` | Personal use, local development | Default mode, uses OS username for identity, no token required |
| `token` | Small teams | OLAV built-in token authentication, simplest multi-user option |
| `ldap` | Enterprise environments | Integrates with LDAP directory services |
| `ad` | Enterprise environments | Integrates with Active Directory |
| `oidc` | SSO scenarios | Integrates with OpenID Connect single sign-on |

---

## Credential Security: What to Commit and What Not To

| Content | Commit to Git? | Reason |
|---------|---------------|--------|
| `.olav/workspace/` | ✅ Commit | Agent and Skill definitions, no sensitive information |
| `.olav/config/` | ❌ Add to .gitignore | Contains API keys and authentication configuration |
| `.olav/databases/` | ❌ Add to .gitignore | Contains audit logs and business data |

!!! tip "Audit Log Tamper Protection"
    OLAV's audit system generates a SHA256 digest for each log entry and writes it to an Audit Manifest file, meeting NIST AU-9 tamper protection requirements. You can use the built-in integrity verification feature to detect whether logs have been modified.

See [Users and Roles Reference ->](../reference/users-and-roles.md) for details.

---

!!! info "Sandbox and Execution Security"
    Authentication/authorization is only the first layer of defense. OLAV also provides a three-layer code execution sandbox, Prompt injection scanning, and dangerous command HITL approval mechanisms. See [Agent Harness ->](agent-harness.md) for details.
