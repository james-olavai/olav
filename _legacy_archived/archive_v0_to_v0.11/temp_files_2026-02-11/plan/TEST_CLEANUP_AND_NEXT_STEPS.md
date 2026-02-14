# Test Database Cleanup & Next Steps

**Status**: 🟢 Production Migration Complete  
**Next Phase**: Verification & Production Readiness

---

## 当前状态

### ✅ 已完成
- **主数据库填充**: olav.duckdb 现有 107MB 数据 (80 devices, 1200 interfaces, 106K stats)
- **Agent 验证**: 成功查询生产数据库
- **路径配置**: 使用 config/paths.py 的 UNIFIED_DB
- **数据导入工具**: 创建可复用的导入脚本

### 📋 需要清理的代码

#### 1. verify_agent_capability.py 
**当前状态**: 使用 test_network.duckdb
```python
# Line 12
DB_PATH = OLAV_ROOT / ".olav" / "db" / "test_network.duckdb"  # ❌ Old
```

**需要更新为**:
```python
# Line 12  
from config.paths import UNIFIED_DB
DB_PATH = UNIFIED_DB  # ✅ Production DB
```

#### 2. generate_e2e_test_data.py
**状态**: 已弃用，仅保留作参考
**建议**: 
- [x] 改为只用 scripts/import_network_data.py
- [ ] 或完全删除此脚本
- [ ] 或转换为数据验证工具

#### 3. 待修改的测试脚本
查找所有引用 test_network.duckdb 的脚本:
```bash
grep -r "test_network\.duckdb" /home/yhvh/Olav --include="*.py" --include="*.md"
```

**可能的引用**:
- tests/e2e/test_*.py (如有)
- scripts/verify_*.py (如有)
- examples/ 中的示例脚本

---

## 数据库配置说明

### 🔒 UNIFIED_DB 架构 (v0.10.1)
```
config/paths.py (Line 45-52):
├── UNIFIED_DB = olav.duckdb  ← 单一生产数据库
├── MAIN_DB_PATH = UNIFIED_DB
├── SNAPSHOTS_DB = UNIFIED_DB  
├── AUDIT_LOGS_DB = UNIFIED_DB
└── OLAV_DB_PATH = UNIFIED_DB

效果:
├── query_main() → UNIFIED_DB  ✅
├── query_snapshots() → UNIFIED_DB  ✅
├── data_gateway.query_database() → UNIFIED_DB  ✅
└── Agent 查询 → UNIFIED_DB  ✅
```

### ✅ test_network.duckdb 现状
- **大小**: 11MB (test data)
- **用途**: 参考和离线备份
- **状态**: 保留但不再使用
- **何时删除**: Phase 5 (生产确认后)

---

## 下一阶段工作 (Phase 4 Continuation)

### 立即执行 (今)

#### Task 1: 运行完整测试套件 (估计: 30 分钟)
```bash
# L1 测试 (20 个, 应该 100% 通过)
uv run pytest tests/e2e/test_real_scenarios.py::test_list_devices -v
uv run pytest tests/e2e/test_real_scenarios.py::test_device_count -v
# ... 其他 L1 测试

# L2 测试 (15 个, 应该 100% 通过)
uv run pytest tests/e2e/test_real_scenarios.py -v --tb=short

# L3 测试 (45 个, 目标 80%+)
uv run pytest tests/ -v -k "l3 or L3" --tb=short
```

**期待结果**:
- L1: 9/9 (100%) ✅
- L2: 15/15 (100%) ✅
- L3: 36+/45 (80%+) ✅

#### Task 2: 更新验证脚本 (估计: 15 分钟)
```bash
# 更新这些脚本
verify_agent_capability.py        # 改用 UNIFIED_DB
verify_phase3.py                  # 检查是否引用测试 DB
verify_*.py (任何)                 # 全部检查

# 命令
find . -name "verify*.py" -exec grep -l "test_network" {} \;
```

#### Task 3: 版本更新 (估计: 5 分钟)
```bash
# 更新文档版本号
docs/DEVELOPER_INDEX.md
docs/reference/ARCHITECTURE.md
.olav/OLAV.md  # 如有版本字段

# 添加迁移笔记
MIGRATION_NOTES.md (新建)
```

### 本周执行 (Phase 4A)

#### Task 4: 测试报告生成 (估计: 20 分钟)
```bash
# 生成完整测试报告
uv run pytest tests/e2e/ -v --html=htmlcov/test_report.html
# 保存报告
cp htmlcov/test_report.html docs/

# 更新 AUDIT_REPORT
echo "Date: $(date)" >> docs/AUDIT_REPORT.md
echo "Production DB Migration: SUCCESS" >> docs/AUDIT_REPORT.md
```

#### Task 5: 代码清理 (估计: 30 分钟)
```bash
# 选项 A: 删除测试脚本 (激进)
rm scripts/generate_e2e_test_data.py
rm scripts/quick_init_db.py
git rm generate_e2e_test_data.py

# 选项 B: 转移到归档 (保守)
mkdir -p archive/deprecated_tools
mv scripts/generate_e2e_test_data.py archive/deprecated_tools/
mv scripts/quick_init_db.py archive/deprecated_tools/
```

#### Task 6: Nornir 生产准备 (估计: 1 小时)
```bash
# 1. 备份当前配置
cp .olav/config/nornir/hosts.yaml .olav/config/nornir/hosts.yaml.dev-backup

# 2. 准备生产配置
cat > .olav/config/nornir/hosts.yaml.prod << 'EOF'
# 生产网络设备库存
# 用真实 IP 和凭证替换
R1:
  hostname: 10.0.1.1           # <- 更新为真实 IP
  username: admin              # <- 来自 .env
  password: "${DEVICE_PASSWORD}"  # <- 来自 .env
  # ...
EOF

# 3. 测试连接
uv run python -c "from olav.tools.network import get_nornir; nr = get_nornir(); print(nr.inventory.hosts.keys())"
```

---

## 文件索引 (清理相关)

### 导入/导出脚本
| 文件 | 用途 | 状态 |
|------|------|------|
| `scripts/import_network_data.py` | 完整导入工具 | ✅ 保留 |
| `scripts/copy_test_to_prod.py` | 快速数据迁移 | ✅ 保留 |
| `scripts/quick_init_db.py` | 快速初始化 | ⚠️ 可选 |
| `scripts/generate_e2e_test_data.py` | 生成测试数据 | ❌ 弃用 |

### 测试脚本
| 文件 | 使用数据库 | 需要更新 |
|------|-----------|---------|
| `verify_agent_capability.py` | test_network.duckdb | ✅ YES |
| `verify_phase3.py` | 无引用 | ❌ NO |
| `tests/e2e/*.py` | 应该用 UNIFIED_DB | ⚠️ 检查 |

### 配置文件 (已正确)
| 文件 | 配置 | 状态 |
|------|------|------|
| `config/paths.py` | UNIFIED_DB 定义 | ✅ 正确 |
| `config/settings.py` | 数据库设置 | ✅ 正确 |
| `.olav/config/nornir/hosts.yaml` | 设备库存 (dev) | ⚠️ 待更新(prod) |
| `.olav/config/nornir/config.yaml` | Nornir 配置 | ✅ 正确 |

---

## 快速检查清单

### 数据完整性
```bash
# 验证数据
uv run python << 'EOF'
import duckdb
conn = duckdb.connect('.olav/db/olav.duckdb')
print("✅ 设备:", conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0])
print("✅ 接口:", conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0])
print("✅ 统计:", conn.execute("SELECT COUNT(*) FROM interface_stats").fetchone()[0])
conn.close()
EOF
```

### Agent 功能
```bash
uv run olav query "有多少个设备?" | head -3
uv run olav query "有多少个接口?" | head -3
uv run olav query "列出所有设备" | head -10
```

### 路径配置
```bash
uv run python << 'EOF'
from config.paths import UNIFIED_DB
print(f"Production DB: {UNIFIED_DB}")
print(f"Expected: .olav/db/olav.duckdb")
EOF
```

---

## 故障恢复

### 如果需要恢复测试数据
```bash
# 方案 1: 从备份复制
uv run python scripts/copy_test_to_prod.py

# 方案 2: 重新生成 (slow)
uv run python scripts/import_network_data.py --clear

# 方案 3: 恢复旧数据库
cp .olav/db/test_network.duckdb.backup .olav/db/olav.duckdb
```

### 如果 Agent 仍查询旧数据库
```bash
# 检查 UNIFIED_DB 设置
grep "UNIFIED_DB" /home/yhvh/Olav/config/paths.py

# 验证 data_gateway 使用正确路径
grep -n "from config.paths import" /home/yhvh/Olav/src/olav/lib/data_gateway.py
```

---

## 成功指标

### Phase 4A 完成标准
- [x] `olav.duckdb` 已填充并验证数据 
- [x] 所有 Agent 查询使用生产数据库
- [ ] L1 测试通过 100% (9/9)
- [ ] L2 测试通过 100% (15/15)
- [ ] 文档已更新
- [ ] 弃用的脚本已清理

### 生产就绪 (Phase 4B 目标)
- [ ] L3 测试通过 80%+ (36+/45)
- [ ] Nornir 配置为真实设备
- [ ] Snapshot 成功收集数据
- [ ] 性能基线已建立 (平均响应 <30s)
- [ ] 文档已完成

---

**迁移完成**: 2026-02-09  
**清理开始**: 今日  
**完全就绪**: 2026-02-10 (预计)  
**生产部署**: 2026-02-11 (预计)
