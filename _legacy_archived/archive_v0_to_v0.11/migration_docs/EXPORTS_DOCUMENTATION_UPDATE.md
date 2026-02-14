# exports 目录结构更新说明 (v0.9.8)

## 📝 文档补充 - 添加到 docs/00_development_guide.md

### 项目结构补充 - exports 输出目录

在"项目结构"章节后添加以下内容：

---

#### 📁 输出目录结构 (exports/)

```
exports/
├── reports/                          # 各类分析报告
│   ├── inspection/                  # Inspection 诊断报告
│   │   ├── latest.md                # 最新报告（符号链接）
│   │   ├── report_20260201_170504.md  # 时间戳命名的历史报告
│   │   └── ...
│   └── snapshots/                   # 快照汇总报告
│       └── 20260201.md              # 日期维度的汇总
│
└── snapshots/                        # 原始网络快照数据
    └── 2026-02-01/
        ├── raw/                     # 原始命令输出（文本）
        │   ├── R1/
        │   ├── R2/
        │   ├── R3/
        │   ├── R4/
        │   ├── SW1/
        │   └── SW2/
        └── parsed/                  # 解析后的结构化数据（JSON）
            ├── R1/
            ├── R2/
            ├── R3/
            ├── R4/
            ├── SW1/
            └── SW2/
                ├── show-version.json
                ├── show-ip-interface-brief.json
                ├── show-interfaces.json
                ├── show-bgp-neighbor.json
                ├── show-ospf-database-router.json
                ├── show-arp.json
                ├── show-cdp-neighbors.json
                └── ... (约 30+ 个命令输出)
```

**说明**:
- `reports/inspection/`: 由 `olav inspect` 命令生成
- `reports/snapshots/`: 由快照采集汇总生成
- `snapshots/raw/`: 原始 show 命令输出（用于调试）
- `snapshots/parsed/`: TextFSM 解析后的 JSON 数据（用于查询）

**大小参考**:
- 单日快照：约 4-5 MB (6 设备 × 30+ 命令)
- Inspection 报告：平均 1-2 KB / 报告
- 建议保留：最近 7 天快照 + 最新 30 个报告

---

### 文件大小统计 (2026-02-01)

```
exports/ (4.5 MB 总计)
├── reports/              68 KB   # 共 14 个报告
│   ├── inspection/       52 KB   # 13 个诊断报告
│   └── snapshots/        16 KB   # 1 个汇总报告
└── snapshots/           4.4 MB   # 1 日快照（6 设备）
    └── 2026-02-01/
        ├── raw/         1.2 MB   # 原始文本
        └── parsed/      3.2 MB   # JSON 数据
```

---

### 清理与维护

#### 📋 清理历史

```bash
# 保留最新 30 个 inspection 报告，其余进行压缩
# (实现中，待补充脚本)

# 保留最近 7 天快照
# (建议政策)
```

#### 🔄 自动化建议

在 Orchestrator 中实现生命周期管理：
```python
class SnapshotRetentionPolicy:
    """快照数据生命周期管理"""
    
    max_snapshot_age_days = 7      # 快照保留 7 天
    max_inspection_reports = 30    # 保留最新 30 个报告
    
    async def cleanup(self):
        # 定期执行清理任务
        pass
```

---

## 执行的清理操作

### ✅ 已完成

| 项 | 操作 | 结果 |
|----|------|------|
| exports/path/ | 删除空目录 | ✅ 已删除 |
| exports/topology/ | 删除空目录 | ✅ 已删除 |
| exports/reports/inspection/ | 保留 | ✅ 13 个报告 |
| exports/reports/snapshots/ | 保留 | ✅ 汇总报告 |
| exports/snapshots/ | 保留 | ✅ 4.4 MB 快照数据 |

### 📊 清理效果

```
Before:  4.5 MB (4 个目录）
After:   4.5 MB (2 个目录）
Cleanup: 2 个空目录已删除
```

---

## 下次改进方向

1. **自动压缩**: 月度快照压缩归档
2. **清理脚本**: 实现生命周期管理
3. **监控告警**: 当快照大小超过阈值时告警
4. **分层存储**: 考虑分离热数据和冷数据

