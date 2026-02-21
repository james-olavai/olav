---
name: olav-audit
description: "Evolution of network-inspection — SSH collection (Map), config-driven rule engine (Reduce), LLM root-cause analysis, and structured reporting."
metadata:
  version: 2.0.0
  author: OLAV Team
  type: agent
  category: network-audit
  intent: audit
  tools:
    - list_audits               # audit_designer.py — list available audit configs
    - validate_audit_config     # audit_designer.py — validate YAML with Pydantic
    - create_audit_config       # audit_designer.py — LLM writes audit YAML from intent
    - run_audit                 # audit_runner.py — reduce → analyze → report (reads parsed_outputs from DB)
    - get_current_datetime      # get_current_datetime.py — accurate timestamps
    - diff_snapshot             # diff_snapshot.py — compare raw snapshots between dates during LLM analyze phase
  prompts:
    system: $ref:./prompts/system.md
  audit_types:
    - name: health_check
      description: CPU, memory, interface health monitoring
      suggested_intents: [system, interfaces, routing]
    - name: consistency
      description: Cross-device consistency (VLANs, routing, neighbors)
      suggested_intents: [switching, routing, neighbors]
    - name: compliance
      description: "Configuration compliance (descriptions, naming, security)"
      suggested_intents: [configs, interfaces]
    - name: custom
      description: User-defined audit with any supported targets
      suggested_intents: []
  tags:
    - network-audit
    - compliance
    - intent-driven
    - config-driven
    - ssh-collection
---

## Audit Agent Workflow

### Design Mode

When user expresses an audit intent:

1. `list_audits()` — check if a matching audit config already exists.
2. If not: `create_audit_config(name, intent, audit_type)` — LLM writes the YAML.
3. `validate_audit_config(audit_name)` — verify the generated config.
4. Ask user whether to run immediately.

### Execute Mode

When user asks to run an audit:

1. `list_audits()` — match user description to audit name.
2. `run_audit(audit_name, devices, output_dir)` — full pipeline:
   - **Map** — `take_snapshot` : SSH collect → raw files + DuckDB parsed_outputs
   - **Reduce** — config-driven rule engine → findings
   - **Analyze** — LLM per-device root-cause + global correlation
   - **Report** — Markdown with findings table, per-device analysis, cascade chain
3. Report path → summary to user.

### Advanced: Snapshot Only

When user wants fresh data without a full audit:

```python
take_snapshot(devices=["R1", "R2"], categories=["system", "routing"])
```

### Raw Text Rules (no NTC template needed)

For commands that lack a TextFSM template (e.g. `show logging`, `show running-config`):

```yaml
- name: ntp_server_configured
  target: ntp_server
  condition: raw_contains
  command: show running-config
  pattern: "^ntp server "
  severity: warning
  threshold: "NTP server must be configured"
```

The raw `.txt` file from today’s snapshot is read directly from
`exports/snapshots/{today}/raw/{device}/{cmd-slug}.txt`.
Add an empty `.olav/templates/cisco_ios_show_running_config.textfsm` to ensure
`show running-config` is always collected.

## Built-in Audits

| Audit Name | Type | Description |
|------------|------|-------------|
| `AUDIT_HEALTH` | health_check | CPU, memory, interfaces, BGP/OSPF state, NTP/logging compliance |

## Config Directory Layout

```
config/
├── AUDIT_HEALTH.yaml       # Built-in health check (flat file)
├── vlan_consistency.yaml   # Example user-created audit
└── ntp_compliance.yaml     # Example user-created audit
```

Audit names are file stems — no prefix convention required.
