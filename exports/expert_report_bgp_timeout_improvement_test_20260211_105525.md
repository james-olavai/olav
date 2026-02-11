# Expert 诊断报告

**场景ID**: bgp_timeout_improvement_test  
**生成时间**: 2026-02-11T10:55:25.785891  

## 诊断决策

| 项目 | 值 |
|------|-----|
| **决策** | ACCEPT |
| **路由** | direct_user |
| **理由** | Constraint score 90.80% >= 85.00% |

## 诊断分数

| 指标 | 分数 | 说明 |
|------|------|------|
| 约束验证 (Task 4) | 90.8% | 幻觉检测、完整性检查 |
| 准确性验证 (Task 5) | N/A | 未提供Ground Truth |
| Expert置信度 | 94.0% | Expert Agent的置信度 |

## Expert诊断信息

### 根本原因 (Root Cause)
```
BGP TCP keepalive timeout on R1 due to network latency
```

### 解决方案 (Solution)
```
Increase TCP keepalive timer and restart BGP daemon
```

### 恢复命令 (Recovery Commands)

- `show running-config | include bgp`
- `systemctl restart bgp`
- `show ip bgp neighbor`

### 验证步骤 (Verification Steps)

- Check BGP neighbor status
- Verify route convergence

### 证据 (Evidence)
```
BGP neighbor state changed from ESTABLISHED to IDLE
```

## 执行信息

- **执行时间**: 2.4ms
- **生成时间**: 2026-02-11T10:55:25.786070

---
*此报告由Expert Orchestrator自动生成*