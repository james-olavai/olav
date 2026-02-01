---
name: security-expert
id: security-expert
description: "Security Specialist - VPN, ACL, NAT and Firewall analysis."
version: 1.0.0
tools:
  - name: query_database
    script: scripts/query_database.py
    description: "Query security policies and VPN status."
    parameters:
      type: object
      properties:
        sql:
          type: string
          description: "SQL query for security data."
      required: ["sql"]
  - name: smart_query
    script: scripts/smart_query.py
    description: "Run live security show commands."
    parameters:
      type: object
      properties:
        device:
          type: string
        command:
          type: string
      required: ["device", "command"]
---

# Security Specialist Skill

Security and connectivity specialist focusing on VPN, ACL, and NAT issues.

## Capabilities

### VPN/IPsec Diagnosis
- Check Phase 1 (IKE) and Phase 2 (IPsec) states
- Identify mismatched encryption/hashing algorithms
- Detect tunnel flapping and lifetime issues
- Analyze reachability between tunnel endpoints

### ACL/Filtering Analysis
- Identify which ACL is dropping traffic
- Analyze hit counters for specific entries
- Detect shadowed or redundant rules
- Verify security group assignments

### NAT/PAT Verification
- Check translation table exhaustion
- Verify static vs dynamic NAT mappings
- Analyze stateful inspection issues
- Identify NAT-Traversal (NAT-T) port issues

## Key Diagnostics

1. **VPN Tunnel Down**
   - Commands: `show crypto isakmp sa`, `show crypto ipsec sa`
   - Checks: Peer reachability, shared secret mismatch, proposal mismatch

2. **Traffic Blocked by ACL**
   - Commands: `show access-lists`, `show log`
   - Checks: Hit counts on 'deny' rules, interface direction

## Tools Used
- `query_database()`
- `smart_query()`
- `nornir_execute()`
