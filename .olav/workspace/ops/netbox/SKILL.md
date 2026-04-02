---
name: ops-netbox
description: "NetBox DCIM/IPAM agent — manage devices, IPs, VLANs, racks, and tenants via REST API"
system_prompt_file: prompts/system.md
tools:
  - path: ../tools/_generated/netbox_dcim.py
  - path: ../tools/_generated/netbox_ipam.py
  - path: ../tools/_generated/netbox_virtualization.py
  - path: ../tools/_generated/netbox_tenancy.py
---

## Overview

The NetBox agent manages the DCIM/IPAM data model via the NetBox REST API.
It can create, read, update, and delete devices, IP addresses, VLANs, racks,
sites, prefixes, VM clusters, and tenants.

## Prerequisites

NetBox must be running and registered:
```
olav service register netbox
```

Set token: `export NETBOX_TOKEN=<your-token>`

## Capabilities

- **DCIM**: Sites, racks, device types, devices, interfaces, cables, power
- **IPAM**: IP addresses, prefixes, VLANs, VRFs, route targets
- **Virtualization**: Clusters, VMs, VM interfaces
- **Tenancy**: Tenants, tenant groups, contacts

## Usage Patterns

```
# Inventory query
"Show all devices in site HQ"
"List all /24 prefixes in VRF default"

# Data creation
"Add device R1 as Cisco ASR1001-X in site HQ rack A1"
"Create IP 10.0.1.1/24 and assign to interface Gi0/0 on R1"

# Bulk operations
"Import all devices from this CSV: hostname,site,role,platform..."
```
