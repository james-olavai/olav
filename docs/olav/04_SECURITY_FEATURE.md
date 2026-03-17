# Security Features & Governance

OLAV implements a **multi-layer security architecture** designed to prevent high-risk operations, ensure access control, and maintain comprehensive audit trails. This framework integrates intent recognition, role-based access control, credential management, and real-time monitoring.

## 🎯 Security Architecture Overview

```
┌─────────────────────────────────────────────────┐
│ User Query / CLI Command                        │
├─────────────────────────────────────────────────┤
│ Layer 1: Identity & Authentication              │
│ • User identification, API key validation       │
├─────────────────────────────────────────────────┤
│ Layer 2: Role-Based Access Control (RBAC)       │
│ • User role validation, agent permission check  │
├─────────────────────────────────────────────────┤
│ Layer 3: Semantic Firewall (Risk Detection)     │
│ • Intent analysis, risk classification          │
├─────────────────────────────────────────────────┤
│ Layer 4: Command Blacklist (Deterministic)      │
│ • Hard-coded forbidden command blocking         │
├─────────────────────────────────────────────────┤
│ Layer 5: Audit & Logging                        │
│ • Request logging, result tracking, compliance  │
└─────────────────────────────────────────────────┘
```

## 🔐 Core Security Components

### Layer 1: Identity & Authentication
- API key / SSH key validation
- Multi-user isolation (USER_ID tracking)
- Token expiration and renewal policies

### Layer 2: Role-Based Access Control (RBAC)
- User roles: `admin`, `user`, `readonly`
- Agent-level permissions (which agents can users invoke)
- Data access scoping (which devices/networks can be queried)

### Layer 3: Semantic Firewall (Proactive Protection)
Identifies the *intent* of a user query using AI embeddings. Even if a user rephrases a dangerous command (e.g., "wipe the box" instead of "delete config"), the semantic layer can detect the risk.

### Layer 4: Command Blacklist (Reactive Protection)
A hard-coded list of forbidden commands. This layer blocks specific, predefined commands from being sent to any network device, providing a deterministic safety net.

### Layer 5: Audit & Logging
Complete audit trail of all operations, user actions, and system events for compliance and forensics.

---

## 1️⃣ Identity & Authentication

Ensures only authorized users can access OLAV systems.

### User Identification
```bash
# Users are identified by:
# - Username + API key (HTTP API)
# - Username (interactive CLI)
# - SSH key + username (SSH access)

# View current user
olav config "Show current user and their role"

# List all authorized users
olav --agent config "Show all users and their roles"
```

### API Key Management
```bash
# Create API key for a user
olav --agent config "Generate API key for user john.doe, valid for 90 days"

# Revoke API key
olav --agent config "Revoke API key for user john.doe"

# Check API key expiration
olav --agent config "Show API key expiration dates for all users"

# Auto-rotate expired keys
olav --agent config "Auto-rotate API keys older than 90 days"
```

### SSH Key Management
```bash
# Update SSH keys for device credentials
olav --agent config "Update SSH private key for device R1"

# Validate key access
olav --agent config "Test SSH connectivity with current keys for all devices"
```

---

## 2️⃣ Role-Based Access Control (RBAC)

Defines what each user can do in OLAV.

### User Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| **admin** | Full control-plane access | User management, platform administration, future workspace lifecycle actions |
| **user** | Standard operational access | Normal agent usage for day-to-day work |
| **readonly** | Read-only access | Read-only queries and audit observation |

### Agent-Level Permissions

```bash
# Check which agents a user can access
olav --agent config "Show permission matrix for user alice"

# Grant agent access to a user
olav --agent config "Allow user bob to access Ops Agent"

# Revoke agent access
olav --agent config "Revoke Bob's access to Config Agent"

# Scope data access (which devices/networks)
olav --agent config "User alice can only query devices with tag=production"
```

### Command-Level Permissions

```bash
# Restricted commands require admin-only control-plane access
olav --agent config "Enable command filtering: require admin role for destructive control-plane operations"

# User scope filtering
olav --agent config "User john.doe can only access devices in region=US"
```

### Permission Verification

```bash
# Before execution, OLAV checks:
olav "Show device R1 config"  # ✅ readonly can execute read-only queries
olav --agent config "Modify management IP"  # ❌ readonly cannot execute control actions
```

---

## 3️⃣ Semantic Firewall (Guardrails)

The Semantic Firewall categorizes user queries into risk levels and takes actions (BLOCK, CONFIRM, or WARN) based on similarity matching with defined policy patterns.

### Configuration
Managed via: `.olav/config/security_policies.yaml` and the **Config Agent**

```bash
# View current security policies
olav --agent config "Show all semantic firewall rules"

# Adjust risk threshold
olav --agent config "Lower semantic firewall threshold to 0.7 (more sensitive)"
```

### Key Policy Levels:
- **Destructive**: Actions that permanently delete or modify data (e.g., `rm -rf`, `drop database`). 
  - **Action**: `BLOCK` (Immediately terminates the request).
- **High Risk**: Actions that significantly affect system or network state (e.g., `reboot`, `modify ospf`).
  - **Action**: `CONFIRM` (Requires explicit user confirmation).
- **Medium Risk**: Actions that require caution (e.g., `execute command`, `export data`).
  - **Action**: `WARN` (Allows execution but logs a warning).
- **Low Risk**: Safe queries (e.g., `show config`, `ping`).
  - **Action**: `ALLOW` (Executes immediately, logged).

### Examples

```bash
# Destructive operation → BLOCKED
olav "Delete all snapshots"
# Output: ❌ BLOCKED - Destructive operation detected

# High-risk operation → CONFIRM required
olav "Reboot router R1"
# Output: ⚠️ CONFIRM REQUIRED - This action will cause service disruption
# Do you want to proceed? [yes/no]

# Medium-risk operation → WARN logged
olav "Export all network snapshot data"
# Output: ✓ ALLOWED (WARNING logged) - Large data export
```

---

## 4️⃣ Command Blacklist

The Command Blacklist provides an immutable wall against specific command strings. It is particularly useful for preventing CPU-intensive debug commands or unauthorized configuration saving.

### Configuration
Managed via: `.olav/config/blacklisted_commands.yaml` and the **Config Agent**

```bash
# View blacklisted commands
olav --agent config "Show all blacklisted commands and their reasons"

# Add a command to the blacklist
olav --agent config "Blacklist command 'debug ip ospf' - reason: CPU intensive"

# Remove a command from the blacklist
olav --agent config "Remove 'debug ip ospf' from blacklist (emergency override)"

# Test if a command is blocked
olav --agent config "Is 'write memory' blacklisted?"
```

### Examples of Blacklisted Commands:
- `debug ip ospf` (Prevents device CPU spikes)
- `write memory` (Prevents accidental saves without approval)
- `copy running-config startup-config` (Hardened operations require explicit request)
- `reload <interface>` (Interface reloads should go through change management)

---

## 5️⃣ Audit Logging & Compliance

OLAV maintains comprehensive audit logs of all user actions for compliance, forensics, and security monitoring.

### Audit Log Locations

```
~/.olav/logs/
  ├── users/
  │   ├── {user}.log          # All operations by this user
  │   └── {user}-failed.log   # Failed operations (access denied, etc.)
  ├── security/
  │   ├── auth.log            # Authentication events (login/logout)
  │   ├── blocked.log         # Blocked/denied operations
  │   └── sensitive.log       # High-risk operations (changes, deletes)
  └── audit/
      ├── config-changes.log  # Configuration modifications
      ├── device-access.log   # Device SSH access logs
      └── data-exports.log    # Data export events
```

### Querying Audit Logs

```bash
# View all operations by a user in past 24 hours
olav --agent config "Show audit logs for user alice from last 24 hours"

# View all failed access attempts
olav --agent config "Show all failed authentication attempts"

# View all configuration changes
olav --agent config "Who modified the management IP? When? What was changed?"

# View high-risk operations
olav --agent config "Show all HIGH RISK operations in the last 7 days"

# Export audit logs for compliance
olav --agent config "Export all audit logs from March 2026 to CSV"

# Real-time audit monitoring
olav --agent config "Alert on all 'BLOCK' or 'CONFIRM' operations in real-time"
```

### Example Audit Log Entry
```
2026-03-06 14:23:15 | USER: john.doe | ROLE: user | ACTION: query
AGENT: ops | QUERY: "Show BGP neighbors for R1"
RISK_LEVEL: LOW | STATUS: ALLOWED | RESULT: Success | DURATION: 250ms
LOG_FILE: /home/john/.olav/logs/users/john.doe.log
```

### Compliance & Retention

```bash
# Set audit log retention policy
olav --agent config "Keep audit logs for 2 years, archive older logs"

# Generate compliance report
olav --agent config "Generate SOC2 / ISO 27001 compliance report for Q1 2026"

# Check if logs are immutable
olav --agent config "Verify audit logs are write-protected and immutable"
```

---

## 6️⃣ Credential Lifecycle Management

Manage API keys, SSH keys, device credentials with automatic rotation and expiration.

### API Key Lifecycle

```bash
# Generate API key
olav --agent config "Create API key for user alice, valid for 90 days, scope: production devices"

# Track key expiration
olav --agent config "Show: which API keys expire in next 30 days"

# Auto-rotate keys
olav --agent config "Enable auto-rotation: refresh API keys every 90 days"

# Revoke key immediately
olav --agent config "Revoke API key {key_id} immediately - compromised"

# Rotate all keys for a user
olav --agent config "Force rotate all API keys for user bob"
```

### SSH Key Lifecycle

```bash
# Update device SSH keys
olav --agent config "Update SSH private key for device group 'production-routers'"

# Validate key access
olav --agent config "Test SSH connectivity for all devices with current keys"

# Check key age
olav --agent config "Show SSH keys older than 180 days, mark for rotation"

# Emergency key revocation
olav --agent config "Revoke SSH key for device R1 due to compromise"
```

### Password Policy

```bash
# Set password requirements
olav --agent config "Enforce: minimum 12 chars, must include number+special char"

# Force password change
olav --agent config "Require all users to change password within 7 days"

# Check credential strength
olav --agent config "Audit all device credentials - show weakness"
```

---

## 7️⃣ Integration with Config Agent

The **Config Agent** is the centralized way to manage all security policies and credentials.

### Security Management via Config Agent

```bash
# View all security settings
olav --agent config "Show all security policies and settings"

# Modify security policies
olav --agent config "Update semantic firewall threshold to 0.8"
olav --agent config "Add new rule: Block 'debug all' on all devices"

# Manage users
olav admin "add-user john.doe --role user"
olav admin "rotate-token alice"
olav admin "revoke-token bob"

# Manage credentials
olav --agent config "Rotate all API keys for 90-day policy"
olav --agent config "Verify all SSH keys are accessible"

# Generate security reports
olav --agent config "Generate security audit report - active users, recent changes, failed logins"
```

### Config Agent Security Workflows

**Workflow 1: Add New User**
```bash
olav admin "add-user sarah.chen --role user"
# Save the returned token to ~/.olav/token on Sarah's workstation
```

**Workflow 2: Emergency Access Revocation**
```bash
olav --agent config "Emergency: Revoke all access for user david
- Revoke API keys immediately
- Revoke SSH credentials
- Kill all active sessions
- Archive audit logs for this user"
```

**Workflow 3: Security Compliance Audit**
```bash
olav --agent config "Monthly security audit
- List all active users and their roles
- Check for expired/expiring credentials
- Review high-risk operations from last month
- Generate compliance report (SOC2)"
```

---

## 8️⃣ Best Practices & Security Recommendations

### 🛡️ Operational Security

1. **Principle of Least Privilege**
   - Assign users the minimum role required for their job
   - Use device/network scoping to limit data access
   - Regular audit of permission over-grants

2. **Key Rotation**
   - Rotate API keys every 90 days automatically
   - Rotate SSH keys every 180 days
   - Emergency rotation if key is suspected compromised

3. **Multi-User Isolation**
   - Each user has isolated session/cache in `~/.olav/`
   - Global audit logs centralized in `.olav/logs/`
   - No cross-user data leakage

4. **Semantic Firewall Tuning**
   - Lower threshold (0.7) = more protective but may block legitimate requests
   - Higher threshold (0.9) = less false positives but may miss risks
   - Regularly review blocked requests to find false positives

5. **Audit Log Monitoring**
   - Review high-risk operations daily
   - Set up real-time alerts for BLOCK/CONFIRM events
   - Archive logs regularly for compliance

### ⚠️ Security Anti-Patterns

- ❌ **Never hardcode credentials** in scripts - use Config Agent to manage
- ❌ **Never log sensitive data** (passwords, API keys, SSH keys)
- ❌ **Never skip confirmation** for CONFIRM-level operations
- ❌ **Never disable semantic firewall** entirely, even for "trusted" users
- ❌ **Never share API keys** - one key per user
- ❌ **Never override blacklist** without audit trail and approval

### 🔍 Monitoring & Alerting

```bash
# Set up real-time security alerts
olav --agent config "Alert on:
  - Any BLOCK operation (may indicate attack attempt)
  - All CONFIRM operations (high-risk changes)
  - Failed authentication (wrong API key)
  - Unusual data export (large access patterns)
  - Off-hours access (after business hours)"
```

---

## 9️⃣ Configuration & Management

### Edit Security Policies (via Config Agent - Recommended)
```bash
# All security changes should go through Config Agent
olav --agent config "Modify security policy: ..."
olav --agent config "Blacklist new command: ..."
olav --agent config "Update user permissions: ..."
```

### Manual Configuration (Advanced)
```bash
# Direct file editing (requires system admin access)
vi .olav/config/security_policies.yaml
vi .olav/config/blacklisted_commands.yaml
vi .olav/config/rbac_matrix.yaml

# Sync changes after manual edits
uv run python -m olav.tools.sync_security_rules
```

### Verify Configuration
```bash
# Test a security rule
olav --agent config "Is this operation allowed? [operation description]"

# Validate configuration syntax
uv run python -m olav.tools.validate_security_config

# Test the security check logic directly
uv run python -m olav.core.security "delete all configs"
```

---

## 🔟 Incident Response

### Security Incident Procedures

**If API Key is Compromised:**
```bash
olav --agent config "Emergency: Revoke API key {key_id} immediately"
olav --agent config "Audit: Show all operations with the compromised key"
# Kill existing sessions, regenerate new key
```

**If Account is Compromised:**
```bash
olav --agent config "Emergency revocation for user john.doe:
- Revoke all API keys
- Revoke all SSH credentials
- Terminate all active sessions
- Mark account as locked (pending password reset)"
```

**If Blacklist is Updated (Emergency):**
```bash
olav --agent config "Override blacklist for command 'write memory' this time
- Reason: Emergency configuration must be saved
- Approval by: admin user
- Log to sensitive.log"
```

---

## 📋 Security Checklist

Before deploying OLAV to production:

- [ ] Configure RBAC roles and user matrix (admin, user, readonly)
- [ ] Generate initial API keys for all users (with 90-day rotation enabled)
- [ ] Configure semantic firewall policies (adjust threshold if needed)
- [ ] Populate command blacklist (add device-specific dangerous commands)
- [ ] Enable audit logging and set log retention policy (minimum 1 year)
- [ ] Set up real-time monitoring alerts for high-risk operations
- [ ] Test incident response procedures (key revocation, account lockout)
- [ ] Document security policy and share with all users
- [ ] Schedule regular security audits (monthly minimum)
