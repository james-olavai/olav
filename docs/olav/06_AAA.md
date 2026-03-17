# OLAV AAA

This document describes the current Authentication, Authorization, and Audit model exposed to users and operators.

It is intentionally conservative: it distinguishes what is implemented today from what is still architectural direction.

## 1. Current State

As of the current v0.11 codebase:

1. Authentication is centered on per-user tokens stored locally in `~/.olav/token`.
2. User records live in `.olav/databases/users.duckdb`.
3. The implemented roles are `admin`, `user`, and `readonly`.
4. Admin user creation is available through the admin user management command.
5. If no valid token or users database is available, token auth can fall back to OS identity.

This means OLAV already has a usable local multi-user model, but not every planned RBAC feature is enforced everywhere yet.

## 2. Authentication

### Token Storage

- Local token file: `~/.olav/token`
- Shared users database: `.olav/databases/users.duckdb`

The token file is user-local. The database is project-scoped shared state.

Recommended file permissions:

```bash
chmod 600 ~/.olav/token
```

### Admin User Lifecycle

Create an admin user:

```bash
uv run olav admin "add-user admin --role admin"
```

List users:

```bash
uv run olav admin "list-users"
```

Rotate a token:

```bash
uv run olav admin "rotate-token alice"
```

Revoke a token:

```bash
uv run olav admin "revoke-token alice"
```

The token is shown once when created or rotated. OLAV stores only the salted hash in the users database.

### Current First-Use Reality

Older design notes describe an `olav onboard` bootstrap admin token flow. That is not the primary implemented user bootstrap in the current code path.

The implemented path is:

1. `olav init`
2. `olav admin "add-user admin --role admin"`
3. store token in `~/.olav/token`

## 3. Authorization

### Baseline Roles

| Role | Intended use | Current meaning |
|---|---|---|
| `admin` | Platform control plane | User management, full platform administration, future workspace lifecycle control |
| `user` | Normal operator/engineer | Day-to-day agent usage |
| `readonly` | Audit and observation | Read-only access model |

### Current Boundary

The project design has converged on a simple baseline:

1. Fixed roles, not arbitrary user-defined role graphs.
2. Skill-granular authorization as the long-term model.
3. Admin-only control-plane actions such as install, upgrade, disable, remove, and rollback of workspace capabilities.

Some of those enforcement points are still planned or partial. The role model is stable; the full enforcement surface is not yet complete.

## 4. Audit

The project architecture requires central auditing of user actions.

Current principles:

1. CLI commands should be attributable to a user identity.
2. Shared audit state belongs under `.olav/databases/` and `.olav/logs/`.
3. User-local secrets and sessions belong under `~/.olav/`.

From the platform design perspective, audit is not optional. It is part of the core shared control plane.

## 5. Storage Boundaries

Use this split when reasoning about AAA-related files:

| Location | Scope | Purpose |
|---|---|---|
| `~/.olav/token` | per-user | local authentication token |
| `~/.olav/sessions/` | per-user | local session/checkpoint state |
| `.olav/databases/users.duckdb` | project-shared | user table and token hashes |
| `.olav/databases/audit.duckdb` | project-shared | audit events |
| `.olav/workspace/` | project-shared | declared agent and skill control plane |
| `.olav/config/` | project-shared | runtime configuration |

## 6. What Is Not Fully Implemented Yet

These areas are still design-led or partial:

1. Full workspace lifecycle authorization enforcement.
2. Complete skill-level permission matrix enforcement.
3. Rich policy editing, groups, approvals, and policy versioning.
4. A polished WebUI or enterprise policy management surface.

Those are valid roadmap items, but they should not be described as already complete.

## 7. Open-Source Baseline Vs Enterprise Layer

The current architectural position is:

1. Basic AAA is part of the platform baseline.
2. Fixed-role RBAC should not be enterprise-only.
3. Editable policy management, groups, approvals, and governance UX can be enterprise features.

In other words, the platform must ship with a credible default AAA model. Enterprise builds may add management depth, not invent AAA from scratch.

## 8. Operational Recommendations

For a small team, the practical operating model is:

1. Keep `admin` users to a very small set.
2. Use `user` as the default role for engineers.
3. Use `readonly` for audit-only access.
4. Rotate tokens when ownership changes or a workstation is lost.
5. Treat workspace installation and upgrade as admin-only actions.

## 9. Related Docs

- [docs/02_QUICK_START.md](./02_QUICK_START.md)
- [docs/04_SECURITY_FEATURE.md](./04_SECURITY_FEATURE.md)
- [docs/03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [docs/07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [docs/08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)