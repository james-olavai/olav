# network-cli Skill Configuration

## Overview

This directory contains configuration files for the **network-cli** skill, which handles CLI command execution and device management.

## Configuration Files

### blacklist.txt

**Purpose**: Define dangerous commands that should never be executed automatically by agents.

**Location**: `.olav/skills/network-cli/config/blacklist.txt`

**Format**: One command pattern per line (case-insensitive)

**Examples of Blacklisted Commands**:
- `erase`, `reload`, `shutdown` - System destruction
- `delete`, `clear config` - Configuration deletion  
- `enable password`, `crypto key` - Security-sensitive
- `debug all` - Resource intensive commands
- `no vlan`, `no interface` - Critical network changes

**How It Works**:
1. When `nornir_execute(device, command)` is called
2. The NetworkExecutor loads this blacklist file
3. It checks if the command matches any pattern (case-insensitive)
4. If matched, execution is blocked with an error
5. If not matched, execution proceeds (with additional safety checks)

## Usage

### Standard Read-Only Commands (Safe)

These commands are typically allowed:
- `show version`
- `show interfaces`
- `show ip route`
- `show bgp summary`
- `show running-config`

### Adding New Blacklist Entries

Edit `blacklist.txt` to add dangerous patterns:

```
# Example: Block a specific command family
configure
config terminal
(config)#
```

## Integration with Agent Code

The blacklist is automatically loaded by network_executor.py:

```python
from olav.tools.network import nornir_execute

# This will check against blacklist.txt
result = nornir_execute("device_name", "show version")  # ✅ Allowed
result = nornir_execute("device_name", "reload")         # ❌ Blocked by blacklist
```

## Future Enhancements

- [ ] Whitelist mode (default-deny, explicit allow)
- [ ] Per-device ACLs (allow different commands on different devices)
- [ ] Time-based restrictions (allow dangerous commands only during maintenance windows)
- [ ] Approval workflow (requires human confirmation for dangerous commands)
- [ ] Audit logging of blocked command attempts
- [ ] Command validation before execution (syntax check, variable validation)
