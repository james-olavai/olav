# Required Information Check Protocol

> **MANDATORY — Read before executing any tool.**
>
> When a user's request is ambiguous or lacks required details, **STOP and ask**.
> Never guess security-sensitive values. Never use hardcoded defaults for credentials or ports without confirming.

---

## 🔍 The Protocol (4 steps)

### Step 1 — Parse intent
What is the user actually trying to do? (deploy a service / run CLI / query DB / configure system)

### Step 2 — Identify gaps
Cross-check the intent against the **Required Parameters** table below.
Missing = not stated AND not discoverable from the current database/filesystem.

### Step 3 — Ask first, act second
If ANY required parameter is missing:
1. List all missing items in one message (don't ask one-by-one in separate turns unless needed for dependencies)
2. Provide the default in brackets `[default: X]` if a safe default exists
3. Wait for the user's reply before proceeding

### Step 4 — Act with confirmed values
Execute with exactly what the user provided — no substitutions.

---

## 📋 Required Parameters by Intent

### Service Deployment (`deploy`, `install`, `set up`, `stand up`, `run`)

| Service | Required | Safe Default | Must Ask |
|---------|----------|--------------|----------|
| Any Docker service | Admin password / secret key | ❌ none | ✅ always |
| Any Docker service | Port mapping | Service default (e.g. 80, 3890) | Only if non-standard |
| Any Docker service | Data persistence path | `.olav/services/<name>/data` | ✅ if stateful |
| lldap | `LLDAP_LDAP_BASE_DN` | `dc=example,dc=com` | ✅ confirm |
| lldap | `LLDAP_LDAP_USER_PASS` (admin pw) | ❌ none | ✅ always |
| lldap | `LLDAP_JWT_SECRET` | ❌ none | ✅ always |
| NetBox | `NETBOX_SECRET_KEY` | ❌ none | ✅ always |
| NetBox | `POSTGRES_PASSWORD` | ❌ none | ✅ always |
| Grafana | `GF_SECURITY_ADMIN_PASSWORD` | ❌ none | ✅ always |
| ContainerLab | topology YAML path | — | ✅ always |
| Any service | External port (if user-facing) | — | ✅ confirm |

### Network Device Operations (`run cli`, `show`, `execute`, `connect to`)

| Context | Check | Action if missing |
|---------|-------|-------------------|
| Device hostname | Query `SELECT * FROM netops.devices WHERE hostname = '<name>'` | If 0 rows → ask user to confirm hostname or IP |
| Device platform | Same query, read `platform` column | Ask if unknown (affects CLI syntax) |
| Credentials | Check `~/.ssh/config` or `hosts.yaml` | Ask user to confirm credential source |

### NetBox Operations

| Parameter | Check | Action if missing |
|-----------|-------|-------------------|
| Site / location | Stated? | Query first, ask if ambiguous |
| Device role | Stated? | Query first, ask if ambiguous |
| IP prefix context | Stated? | Ask if creating IPs |

### Knowledge Indexing

| Parameter | Check | Action if missing |
|-----------|-------|-------------------|
| Document path or URL | Stated? | Ask: "What document should I index? (file path or URL)" |
| Collection/namespace | Stated? | Default to `default` — mention it |

---

## 💬 Ask Format (use this template)

```
To [action], I need a few details:

1. **[Parameter name]** — [why it's needed]
2. **[Parameter name]** — [default: X] (confirm or provide a different value)
3. **[Parameter name]** — [why it's needed]

Please provide these and I'll proceed.
```

---

## ❌ Anti-Patterns (never do these)

```
# ❌ WRONG — guessing a password
docker run -e ADMIN_PASSWORD=admin123 ...

# ❌ WRONG — using a placeholder without asking
LLDAP_JWT_SECRET=changeme

# ❌ WRONG — proceeding with zero info
User: "deploy grafana"
Agent: *immediately writes docker-compose with hardcoded values*

# ✅ CORRECT
User: "deploy grafana"
Agent: "To deploy Grafana, I need:
1. **Admin password** — the initial admin account password
2. **Port** — [default: 3000] confirm or specify another
Please provide these and I'll set it up."
```

---

## ⚡ Fast Path (when info IS sufficient)

If the user provides all required parameters upfront, execute immediately — no extra confirmation needed.

```
User: "deploy lldap on port 3890, base DN dc=corp,dc=example, admin password Secret123, JWT secret MyJWT456"
Agent: → Execute immediately, all required info present ✅
```
