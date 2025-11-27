# 🔍 网络巡检报告

**巡检配置**: bgp_peer_audit
**描述**: Verify BGP peer counts and states across edge routers
**执行时间**: 2025-11-27 23:10:51 → 23:10:51 (0.2秒)

## 📊 执行摘要

- **设备数**: 3
- **检查项**: 2
- **总检查数**: 6
- ✅ **通过**: 3 (50.0%)
- ❌ **失败**: 3 (50.0%)

### 🟡 整体状态: 需要关注

## ⚠️ 警告 (3)

- **R1** / bgp_no_idle_peers: Device R1 has 4 BGP peers in Idle state
- **R2** / bgp_no_idle_peers: Device R2 has 4 BGP peers in Idle state
- **R3** / bgp_no_idle_peers: Device R3 has 2 BGP peers in Idle state

## 📋 设备巡检结果

| 设备 | 检查项 | 状态 | 说明 |
|---|---|---|---|
| R1 | bgp_established_count | ✅ | Device R1 has only 4 established BGP peers (expected >= 2) |
| R2 | bgp_established_count | ✅ | Device R2 has only 4 established BGP peers (expected >= 2) |
| R3 | bgp_established_count | ✅ | Device R3 has only 2 established BGP peers (expected >= 2) |
| R1 | bgp_no_idle_peers | ⚠️ | Device R1 has 4 BGP peers in Idle state |
| R2 | bgp_no_idle_peers | ⚠️ | Device R2 has 4 BGP peers in Idle state |
| R3 | bgp_no_idle_peers | ⚠️ | Device R3 has 2 BGP peers in Idle state |

---
*报告生成时间: 2025-11-27 23:10:51*
*OLAV 自动化巡检系统*