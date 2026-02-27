# OLAV Skill Naming Convention

## Overview

This document defines the naming convention for OLAV skills following the **One Agent One Skill** principle. Each skill corresponds to exactly one SubAgent in the federated agents architecture.

## Naming Format

```
{agent}-{specialty}
```

Where:
- `{agent}` = Main agent name (quick, ops, config, audit)
- `{specialty}` = SubAgent expertise area (camelCase)

## Agent → Skill Mapping

| Main Agent | Agent Code | Skills (SubAgents) |
|------------|------------|-------------------|
| **quick** | `quick` | quick-Query |
| **ops** | `ops` | ops-L2Expert, ops-L3Expert, ops-Probe, ops-DiffExpert |
| **config** | `config` | config-Infrastructure, config-Knowledge, config-CommandLearner, config-SkillBuilder, config-Doctor |
| **audit** | `audit` | audit-Compliance |

## Skill Definitions

### quick-Query
- **Purpose**: Fast SQL/CLI lookup, zero-shot queries
- **Tools**: execute_sql, execute_cli, search_commands, search_knowledge, format_and_export
- **Formerly**: olav-ops

### ops-L2Expert
- **Purpose**: L2 topology, MAC tables, ARP, STP, CDP/LLDP
- **Tools**: analyze_network_topology, execute_sql (topology tables)
- **Formerly**: olav-topology

### ops-L3Expert
- **Purpose**: L3 routing, BGP, OSPF, static routes
- **Tools**: execute_sql (routing tables), execute_cli
- **Formerly**: olav-routing

### ops-Probe
- **Purpose**: Active probing, liveness detection, latency testing
- **Tools**: ping_device, traceroute, port_scan, execute_cli_parallel
- **NEW**: Missing, needs implementation

### ops-DiffExpert
- **Purpose**: Time-series drift detection, state comparison
- **Tools**: diff_sql_state, diff_topology_drift, diff_routing_drift, diff_configs
- **Formerly**: olav-diff

### config-Infrastructure
- **Purpose**: DB init, device sync, SSH snapshot, template sync
- **Tools**: sync_schemas, sync_inventory, take_snapshot, sync_commands, sync_all
- **Formerly**: olav-config

### config-Knowledge
- **Purpose**: Knowledge base management, vector indexing
- **Tools**: index_knowledge_files, search_knowledge, manage_cache, get_knowledge_status

### config-CommandLearner
- **Purpose**: Teaching OLAV new CLI commands via TextFSM
- **Tools**: search_ntc_templates, generate_template, save_template
- **Formerly**: command_learner

### config-SkillBuilder
- **Purpose**: External system integration (NetBox, ServiceNow)
- **Tools**: read_api_schema, write_skill_code
- **NEW**: Missing, needs implementation

### config-Doctor
- **Purpose**: System self-diagnosis, health checks
- **Tools**: check_health, analyze_logs

### audit-Compliance
- **Purpose**: Rule generation and compliance checking
- **Tools**: list_audits, validate_audit_config, create_audit_config, run_audit
- **Formerly**: olav-audit

## Migration Checklist

- [ ] Rename `olav-ops` → `quick-Query`
- [ ] Rename `olav-topology` → `ops-L2Expert`
- [ ] Rename `olav-routing` → `ops-L3Expert`
- [ ] Create `ops-Probe` (NEW)
- [ ] Rename `olav-diff` → `ops-DiffExpert`
- [ ] Rename `olav-config` → `config-Infrastructure`
- [ ] Create `config-Knowledge` (extract from config-Infrastructure)
- [ ] Rename `command_learner` → `config-CommandLearner`
- [ ] Create `config-SkillBuilder` (NEW)
- [ ] Rename `olav-audit` → `audit-Compliance`
- [ ] Update `.olav/OLAV.md` with new agent/subagent structure

## File Structure After Migration

```
.olav/skills/
├── quick-Query/
│   ├── SKILL.md
│   ├── prompts/
│   │   └── system.md
│   └── tools/
│       ├── execute_sql.py
│       ├── execute_cli.py
│       └── ...
├── ops-L2Expert/
│   ├── SKILL.md
│   ├── prompts/
│   │   └── system.md
│   └── tools/
│       ├── analyze_network_topology.py
│       └── ...
├── ops-L3Expert/
├── ops-Probe/          # NEW
├── ops-DiffExpert/
├── config-Infrastructure/
├── config-Knowledge/   # NEW (extracted)
├── config-CommandLearner/
├── config-SkillBuilder/ # NEW
├── config-Doctor/
└── audit-Compliance/
```

## Notes

1. **One Agent One Skill**: Each skill maps to exactly one SubAgent
2. **Consistent Naming**: Use camelCase for specialty, lowercase agent code
3. **Backward Compatibility**: Keep old skill names as aliases until v2.1
4. **Tool Ownership**: Tools belong to the skill that owns their functionality
