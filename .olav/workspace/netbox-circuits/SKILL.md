---
name: netbox-circuits
description: "NetBox circuits API: providers, circuits, terminations, circuit groups, and virtual circuits management"
tools:
  # Circuit group assignments
  - netbox_circuits_get_api_circuits_circuit_group_assignments
  - netbox_circuits_get_api_circuits_circuit_group_assignments_by_id
  # Circuit groups
  - netbox_circuits_get_api_circuits_circuit_groups
  - netbox_circuits_get_api_circuits_circuit_groups_by_id
  # Circuit terminations
  - netbox_circuits_get_api_circuits_circuit_terminations
  - netbox_circuits_get_api_circuits_circuit_terminations_by_id
  - netbox_circuits_get_api_circuits_circuit_terminations_by_id_paths
  # Circuit types
  - netbox_circuits_get_api_circuits_circuit_types
  - netbox_circuits_get_api_circuits_circuit_types_by_id
  # Circuits
  - netbox_circuits_get_api_circuits_circuits
  - netbox_circuits_get_api_circuits_circuits_by_id
  # Provider accounts
  - netbox_circuits_get_api_circuits_provider_accounts
  - netbox_circuits_get_api_circuits_provider_accounts_by_id
  # Provider networks
  - netbox_circuits_get_api_circuits_provider_networks
  - netbox_circuits_get_api_circuits_provider_networks_by_id
  # Providers
  - netbox_circuits_get_api_circuits_providers
  - netbox_circuits_get_api_circuits_providers_by_id
  # Virtual circuit terminations
  - netbox_circuits_get_api_circuits_virtual_circuit_terminations
  - netbox_circuits_get_api_circuits_virtual_circuit_terminations_by_id
  - netbox_circuits_get_api_circuits_virtual_circuit_terminations_by_id_paths
  # Virtual circuit types
  - netbox_circuits_get_api_circuits_virtual_circuit_types
  - netbox_circuits_get_api_circuits_virtual_circuit_types_by_id
  # Virtual circuits
  - netbox_circuits_get_api_circuits_virtual_circuits
  - netbox_circuits_get_api_circuits_virtual_circuits_by_id
metadata:
  version: 1.1.0
  generated_by: config-creator
  service: netbox
  readonly_only: true
  tag: circuits
  tool_count: 24
---

# Netbox Circuits

NetBox circuits API: providers, circuits, terminations, circuit groups, and virtual circuits management

## Tools

- `netbox_circuits` — from `.olav/workspace/ops/tools/_generated/netbox_circuits.py`
