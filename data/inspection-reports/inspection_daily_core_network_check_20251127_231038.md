# 🔍 Network Inspection Report

**Profile**: daily_core_network_check
**Description**: Daily health check for core routers and switches
**Run Time**: 2025-11-27 23:10:38 → 23:10:39 (1.5s)

## 📊 Executive Summary

- **Devices**: 6
- **Checks**: 6
- **Total Results**: 36
- ✅ **Passed**: 18 (50.0%)
- ❌ **Failed**: 18 (50.0%)

### 🔴 Overall Status: Critical Issues

## 🚨 Critical Issues (12)

- **R2** / bgp_peer_health: Device R2 has 1 established BGP peers (expected >= 2)
- **SW1** / bgp_peer_health: Device SW1 has 1 established BGP peers (expected >= 2)
- **R1** / bgp_peer_health: Device R1 has 1 established BGP peers (expected >= 2)
- **SW2** / bgp_peer_health: Device SW2 has 1 established BGP peers (expected >= 2)
- **R3** / bgp_peer_health: Device R3 has 1 established BGP peers (expected >= 2)
- **R4** / bgp_peer_health: Device R4 has 1 established BGP peers (expected >= 2)
- **R2** / ospf_neighbor_check: Device R2 has 0 OSPF neighbors in Full state (expected >= 1)
- **SW1** / ospf_neighbor_check: Device SW1 has 0 OSPF neighbors in Full state (expected >= 1)
- **R1** / ospf_neighbor_check: Device R1 has 0 OSPF neighbors in Full state (expected >= 1)
- **SW2** / ospf_neighbor_check: Device SW2 has 0 OSPF neighbors in Full state (expected >= 1)
- **R3** / ospf_neighbor_check: Device R3 has 0 OSPF neighbors in Full state (expected >= 1)
- **R4** / ospf_neighbor_check: Device R4 has 0 OSPF neighbors in Full state (expected >= 1)

## ⚠️ Warnings (6)

- **R2** / route_table_check: Device R2 has 1 routes (expected >= 10)
- **SW1** / route_table_check: Device SW1 has 1 routes (expected >= 10)
- **R1** / route_table_check: Device R1 has 1 routes (expected >= 10)
- **SW2** / route_table_check: Device SW2 has 1 routes (expected >= 10)
- **R3** / route_table_check: Device R3 has 1 routes (expected >= 10)
- **R4** / route_table_check: Device R4 has 1 routes (expected >= 10)

## 📋 Device Results

| Device | Check | Status | Message |
|---|---|---|---|
| R2 | bgp_peer_health | 🔴 | Device R2 has 1 established BGP peers (expected >= 2) |
| SW1 | bgp_peer_health | 🔴 | Device SW1 has 1 established BGP peers (expected >= 2) |
| R1 | bgp_peer_health | 🔴 | Device R1 has 1 established BGP peers (expected >= 2) |
| SW2 | bgp_peer_health | 🔴 | Device SW2 has 1 established BGP peers (expected >= 2) |
| R3 | bgp_peer_health | 🔴 | Device R3 has 1 established BGP peers (expected >= 2) |
| R4 | bgp_peer_health | 🔴 | Device R4 has 1 established BGP peers (expected >= 2) |
| R2 | ospf_neighbor_check | 🔴 | Device R2 has 0 OSPF neighbors in Full state (expected >= 1) |
| SW1 | ospf_neighbor_check | 🔴 | Device SW1 has 0 OSPF neighbors in Full state (expected >= 1... |
| R1 | ospf_neighbor_check | 🔴 | Device R1 has 0 OSPF neighbors in Full state (expected >= 1) |
| SW2 | ospf_neighbor_check | 🔴 | Device SW2 has 0 OSPF neighbors in Full state (expected >= 1... |
| R3 | ospf_neighbor_check | 🔴 | Device R3 has 0 OSPF neighbors in Full state (expected >= 1) |
| R4 | ospf_neighbor_check | 🔴 | Device R4 has 0 OSPF neighbors in Full state (expected >= 1) |
| R2 | interface_up_check | ✅ | Device R2 has 1 interfaces UP |
| SW1 | interface_up_check | ✅ | Device SW1 has 1 interfaces UP |
| R1 | interface_up_check | ✅ | Device R1 has 1 interfaces UP |
| SW2 | interface_up_check | ✅ | Device SW2 has 1 interfaces UP |
| R3 | interface_up_check | ✅ | Device R3 has 1 interfaces UP |
| R4 | interface_up_check | ✅ | Device R4 has 1 interfaces UP |
| R2 | mac_table_size | ✅ | Device R2 has 1 MAC entries |
| SW1 | mac_table_size | ✅ | Device SW1 has 1 MAC entries |
| R1 | mac_table_size | ✅ | Device R1 has 1 MAC entries |
| SW2 | mac_table_size | ✅ | Device SW2 has 1 MAC entries |
| R3 | mac_table_size | ✅ | Device R3 has 1 MAC entries |
| R4 | mac_table_size | ✅ | Device R4 has 1 MAC entries |
| R2 | route_table_check | ⚠️ | Device R2 has 1 routes (expected >= 10) |
| SW1 | route_table_check | ⚠️ | Device SW1 has 1 routes (expected >= 10) |
| R1 | route_table_check | ⚠️ | Device R1 has 1 routes (expected >= 10) |
| SW2 | route_table_check | ⚠️ | Device SW2 has 1 routes (expected >= 10) |
| R3 | route_table_check | ⚠️ | Device R3 has 1 routes (expected >= 10) |
| R4 | route_table_check | ⚠️ | Device R4 has 1 routes (expected >= 10) |
| R2 | device_inventory | ✅ | Device R2 inventory status: 1 (expected: alive) |
| SW1 | device_inventory | ✅ | Device SW1 inventory status: 1 (expected: alive) |
| R1 | device_inventory | ✅ | Device R1 inventory status: 1 (expected: alive) |
| SW2 | device_inventory | ✅ | Device SW2 inventory status: 1 (expected: alive) |
| R3 | device_inventory | ✅ | Device R3 inventory status: 1 (expected: alive) |
| R4 | device_inventory | ✅ | Device R4 inventory status: 1 (expected: alive) |

---
*Report generated: 2025-11-27 23:10:39*
*OLAV Automated Inspection System*