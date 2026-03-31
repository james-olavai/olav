# SR Linux CLI Syntax Reference — `set /` Commands

> **Purpose**: This document is the authoritative syntax reference for generating
> SR Linux configuration from OpenConfig field data. Given an OC path, value, and
> context (interface name, neighbor IP, etc.), use these patterns to produce the
> correct `set /...` command.

---

## General Rules

- All commands start with `set /`
- Paths follow the YANG tree exactly (same structure as OpenConfig but SRL-specific leaf names)
- Interface names use SRL format: `ethernet-1/1`, `ethernet-1/2`, etc. (never vendor names like GigabitEthernet)
- Network instance for L3 unicast: `default` (unless explicitly VRF-specific)
- Boolean config uses `true`/`false` (not `TRUE`/`FALSE`)
- Admin-state uses `enable`/`disable` (not `up`/`down`)

---

## Interface

```
# Admin state
set / interface <name> admin-state enable|disable

# Description
set / interface <name> description "<text>"

# MTU (bytes)
set / interface <name> mtu <1500-9232>

# Subinterface (L3 unit)
set / interface <name> subinterface <index> admin-state enable|disable
set / interface <name> subinterface <index> description "<text>"

# IPv4 address (CIDR required: x.x.x.x/N)
set / interface <name> subinterface <index> ipv4 admin-state enable
set / interface <name> subinterface <index> ipv4 address <ip/prefix> primary

# IPv6 address
set / interface <name> subinterface <index> ipv6 admin-state enable
set / interface <name> subinterface <index> ipv6 address <ip/prefix> primary

# Attach subinterface to network-instance
set / network-instance <vrf> interface <name>.<index>
```

---

## BGP

```
# Global
set / network-instance <vrf> protocols bgp admin-state enable
set / network-instance <vrf> protocols bgp autonomous-system <asn>
set / network-instance <vrf> protocols bgp router-id <ip>

# Address families
set / network-instance <vrf> protocols bgp group <group> ipv4-unicast admin-state enable
set / network-instance <vrf> protocols bgp group <group> evpn admin-state enable

# Peer group
set / network-instance <vrf> protocols bgp group <group> peer-as <asn>
set / network-instance <vrf> protocols bgp group <group> admin-state enable
set / network-instance <vrf> protocols bgp group <group> export-policy [ <policy> ]
set / network-instance <vrf> protocols bgp group <group> import-policy [ <policy> ]

# Neighbor
set / network-instance <vrf> protocols bgp neighbor <peer-ip> admin-state enable|disable
set / network-instance <vrf> protocols bgp neighbor <peer-ip> peer-as <asn>
set / network-instance <vrf> protocols bgp neighbor <peer-ip> peer-group <group>
set / network-instance <vrf> protocols bgp neighbor <peer-ip> transport local-address <ip>
set / network-instance <vrf> protocols bgp neighbor <peer-ip> ipv4-unicast admin-state enable
set / network-instance <vrf> protocols bgp neighbor <peer-ip> evpn admin-state enable
```

---

## OSPF

```
set / network-instance <vrf> protocols ospf instance <name> admin-state enable
set / network-instance <vrf> protocols ospf instance <name> router-id <ip>
set / network-instance <vrf> protocols ospf instance <name> version ospf-v2|ospf-v3

# Area
set / network-instance <vrf> protocols ospf instance <name> area <area-id> interface <iface>.<sub> admin-state enable
set / network-instance <vrf> protocols ospf instance <name> area <area-id> interface <iface>.<sub> interface-type point-to-point|broadcast
set / network-instance <vrf> protocols ospf instance <name> area <area-id> interface <iface>.<sub> metric <1-65535>
set / network-instance <vrf> protocols ospf instance <name> area <area-id> interface <iface>.<sub> passive true|false
```

---

## IS-IS

```
set / network-instance <vrf> protocols isis instance <name> admin-state enable
set / network-instance <vrf> protocols isis instance <name> level-capability L1|L2|L1L2
set / network-instance <vrf> protocols isis instance <name> net [ <net-address> ]

# Interface
set / network-instance <vrf> protocols isis instance <name> interface <iface>.<sub> admin-state enable
set / network-instance <vrf> protocols isis instance <name> interface <iface>.<sub> circuit-type point-to-point|broadcast
set / network-instance <vrf> protocols isis instance <name> interface <iface>.<sub> level 2 metric <1-16777215>
set / network-instance <vrf> protocols isis instance <name> interface <iface>.<sub> passive true
```

---

## EVPN / VXLAN

```
# VXLAN tunnel interface
set / tunnel-interface vxlan1 vxlan-interface <vxlan-index> type l2|l3
set / tunnel-interface vxlan1 vxlan-interface <vxlan-index> ingress vni <vni>

# Attach to network-instance
set / network-instance <vrf> vxlan-interface vxlan1.<vxlan-index>

# BGP-EVPN
set / network-instance <vrf> protocols bgp-evpn bgp-instance 1 admin-state enable
set / network-instance <vrf> protocols bgp-evpn bgp-instance 1 vxlan-interface vxlan1.<vxlan-index>
set / network-instance <vrf> protocols bgp-evpn bgp-instance 1 evi <evi>
set / network-instance <vrf> protocols bgp-evpn bgp-instance 1 ecmp 2
```

---

## Routing Policy

```
# Prefix set
set / routing-policy prefix-set <name> prefix <ip/prefix> mask-length-range exact|<min>..<max>

# Policy
set / routing-policy policy <name> default-action policy-result accept|reject
set / routing-policy policy <name> statement <seq> match prefix-set <name>
set / routing-policy policy <name> statement <seq> action policy-result accept|reject

# Community set
set / routing-policy community-set <name> member [ <community> ]
```

---

## LAG / LACP

```
set / interface lag<n> admin-state enable
set / interface lag<n> lag lag-type lacp|static
set / interface lag<n> lag lacp-rate fast|slow
set / interface <port> ethernet lag-member-link lag<n>
```

---

## OC Path → SRL Command Mapping Notes

| OC concept | SRL CLI key difference |
|---|---|
| `admin-status: UP/DOWN` | `admin-state enable/disable` |
| `state/` prefix (read-only) | Replace with `config/` semantics → use SRL set directly |
| `network-instance: default` | Nearly all L3 config lives under `network-instance default` |
| `subinterface index` | Usually index `0` for L3 (point-to-point links) |
| Interface names | Always resolve to `ethernet-1/N` format before generating commands |
| BGP `as` field | Maps to `autonomous-system` in SRL |
| BGP `enabled` field | Maps to `admin-state enable/disable` |
| OSPF `adjacency-state` | Read-only state — skip, do not generate set command |
| BGP `session-state` | Read-only state — skip, do not generate set command |
