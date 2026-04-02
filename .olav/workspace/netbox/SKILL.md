---
description: 'NetBox DCIM/IPAM read-only agent: query devices, racks, sites, cables,
  IPs, prefixes, VLANs, circuits, VMs, tenants'
name: netbox
static_context:
- path: .olav/workspace/netbox/schema_reference.json
tools:
- path: .olav/workspace/ops/tools/_generated/netbox_dcim.py
- path: .olav/workspace/ops/tools/_generated/netbox_ipam.py
- path: .olav/workspace/ops/tools/_generated/netbox_tenancy.py
- path: .olav/workspace/ops/tools/_generated/netbox_circuits.py
- path: .olav/workspace/ops/tools/_generated/netbox_virtualization.py
---

# Netbox

NetBox DCIM/IPAM read-only agent: query devices, racks, sites, cables, IPs, prefixes, VLANs, circuits, VMs, tenants

## Tools

- `netbox_dcim` — from `.olav/workspace/ops/tools/_generated/netbox_dcim.py`
- `netbox_ipam` — from `.olav/workspace/ops/tools/_generated/netbox_ipam.py`
- `netbox_tenancy` — from `.olav/workspace/ops/tools/_generated/netbox_tenancy.py`
- `netbox_circuits` — from `.olav/workspace/ops/tools/_generated/netbox_circuits.py`
- `netbox_virtualization` — from `.olav/workspace/ops/tools/_generated/netbox_virtualization.py`
