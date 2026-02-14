# OLAV 问题诊断与修复方案

## 问题列表

### 1. ❌ OLAV启动花费很长时间

**症状**：启动时间超过预期

**根本原因分析**：
```python
# cli_main.py line 941-977
def main() -> None:
    # 1. setup_logging() - 日志初始化
    # 2. ensure_schema() - 3个数据库的schema检查
    # 3. SkillConfig.initialize() - 技能配置初始化
    # 4. app() - Typer应用启动
```

**瓶颈识别**：
1. **SkillConfig.initialize()** - 扫描 `.olav/skills/` 目录
2. **ensure_schema()** - 3个数据库文件的版本检查
3. **Import cascade** - 导入大量依赖模块（deepagents, langchain等）

**修复方案**：
```python
# 方案A: 延迟初始化（Lazy Loading）
# 将SkillConfig.initialize()移到首次使用时

# 方案B: 缓存初始化结果
# 将schema版本检查结果缓存到内存

# 方案C: 并行初始化
import asyncio
async def parallel_init():
    await asyncio.gather(
        ensure_schema_async(db1),
        ensure_schema_async(db2),
        SkillConfig.initialize_async()
    )
```

**预期改进**：启动时间从 5-10s → 1-2s

---

### 2. ❌ TAB补全功能无法使用

**症状**：历史记录可以显示，但按TAB键没有补全提示

**根本原因分析**：
检查 `src/olav/cli/cli_main.py` 中的 prompt_toolkit 配置

**可能原因**：
1. `WordCompleter` 没有正确绑定到 `PromptSession`
2. 补全词典为空
3. `enable_history_search=False` 禁用了搜索

**修复方案**：
```python
# 检查 cli_main.py 中的 completer 配置
from prompt_toolkit.completion import WordCompleter

# 确保补全器包含关键词
OLAV_COMMANDS = [
    'list', 'show', 'describe', 'query', 'help',
    'devices', 'interfaces', 'bgp', 'ospf', 'vlans',
    'R1', 'R2', 'R3', 'R4', 'SW1', 'SW2',
]

completer = WordCompleter(
    OLAV_COMMANDS, 
    ignore_case=True,
    sentence=True,  # 允许多词补全
)

# 确保session正确使用completer
session = PromptSession(
    completer=completer,
    complete_while_typing=True,  # 关键！
    enable_history_search=True,
)
```

**验证方法**：
```bash
OLAV> lis<TAB>  # 应该补全为 "list"
OLAV> show int<TAB>  # 应该补全为 "show interfaces"
```

---

### 3. ❌ 无法查询设备数据（返回空结果）

**症状**：
```
OLAV> list ip addresses on R2
**No IP addresses found for device R2.**
Database views (e.g., v_interfaces) queried via filesystem search returned no data.
```

**根本原因分析**：

#### 问题A: 数据未导入
```bash
# 检查数据库
$ ls -lh .olav/db/main.duckdb
# 如果文件很小（<1MB）→ 数据未导入

# 检查表和行数
$ duckdb .olav/db/main.duckdb
D SHOW TABLES;
D SELECT COUNT(*) FROM devices;
D SELECT COUNT(*) FROM v_interfaces;
```

#### 问题B: 视图不存在
```python
# orchestrator.py 提到的表/视图
"v_interfaces"  # ← 可能不存在
"v_lldp"
"v_bgp_neighbors" 
"v_ospf_neighbors"
```

#### 问题C: 查询逻辑错误
```python
# query_network 工具可能使用了错误的表名
# 应该检查 tools/react_query.py 或 lib/data_gateway.py
```

**修复方案**：

**Step 1: 验证数据是否存在**
```bash
uv run python diagnose_olav.py
```

**Step 2: 如果数据缺失，运行导入**
```bash
# 方案A: 使用现有的snapshot导入
uv run olav sync

# 方案B: 手动导入devices表
uv run python setup_devices_in_main_db.py
```

**Step 3: 修复视图名称**
```python
# 如果v_interfaces不存在，需要：
# 1. 创建视图
CREATE VIEW v_interfaces AS 
SELECT * FROM read_json_auto('exports/snapshots/*/parsed/*.json');

# 2. 或修改查询逻辑使用正确的表名
```

**Step 4: 更新 orchestrator.py 系统提示**
```python
# 移除不存在的视图引用
# 仅列出实际存在的表
system_prompt = """
Available Tables:
- devices (hostname, ip_address, vendor, model, ios_version, device_role, site)
- raw_outputs (device, command, output, timestamp)
"""
```

---

### 4. ❌ 为什么测试没有检查出问题？

**根本原因分析**：

#### 问题A: 测试覆盖不足
```python
# tests/unit/test_data_export.py
# ✅ 测试了 data_export 功能（23个测试）
# ❌ 没有测试 CLI 交互
# ❌ 没有测试数据库查询
# ❌ 没有测试 TAB 补全
```

#### 问题B: Mock数据掩盖了真实问题
```python
# 单元测试使用 mock 数据
@pytest.fixture
def mock_devices():
    return [{"hostname": "R1", "ip": "192.168.1.1"}]

# 真实环境中数据库可能为空
# → 测试无法发现此问题
```

#### 问题C: 缺少集成测试
```python
# 需要的测试类型：
# 1. E2E测试：启动CLI → 输入query → 验证输出
# 2. 数据库集成测试：验证表存在且有数据
# 3. 性能测试：验证启动时间 < 5s
# 4. UI测试：验证TAB补全工作
```

**修复方案 - 添加关键测试**：

```python
# tests/e2e/test_cli_functionality.py

import pytest
from olav.cli.cli_main import main
from olav.lib.data_gateway import query_database

class TestCLIStartup:
    """Test CLI startup performance"""
    
    def test_startup_time(self):
        """Verify startup time < 5 seconds"""
        import time
        start = time.time()
        import olav
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Startup too slow: {elapsed:.2f}s"

class TestDatabaseContent:
    """Test database has required data"""
    
    def test_devices_table_exists(self):
        """Verify devices table exists and has data"""
        result = query_database("SELECT COUNT(*) FROM devices")
        assert len(result) > 0
        assert result[0][0] > 0, "devices table is empty"
    
    def test_required_views_exist(self):
        """Verify required views exist"""
        views = query_database("SELECT table_name FROM information_schema.tables WHERE table_type='VIEW'")
        view_names = [v[0] for v in views]
        
        # Only check views that orchestrator actually uses
        required_views = ['v_lldp', 'v_bgp_neighbors', 'v_ospf_neighbors']
        for view in required_views:
            assert view in view_names, f"Missing view: {view}"

class TestCLICompletion:
    """Test TAB completion"""
    
    def test_completer_has_commands(self):
        """Verify completer is configured with commands"""
        from olav.cli.cli_main import OLAV_COMMANDS  # 需要添加此变量
        assert 'list' in OLAV_COMMANDS
        assert 'show' in OLAV_COMMANDS
        assert 'devices' in OLAV_COMMANDS

class TestQueryExecution:
    """Test actual query execution"""
    
    def test_query_device_ip(self):
        """Verify can query device IP addresses"""
        result = query_database("SELECT hostname, ip_address FROM devices WHERE hostname='R2'")
        assert len(result) > 0, "No data for R2"
        assert result[0][1] is not None, "R2 has no IP address"
```

---

## 立即行动计划

### Priority 1: 修复数据缺失问题
```bash
# 1. 诊断
uv run python diagnose_olav.py

# 2. 导入数据（如果缺失）
uv run python setup_devices_in_main_db.py

# 3. 验证
uv run duckdb .olav/db/main.duckdb "SELECT * FROM devices;"
```

### Priority 2: 修复TAB补全
```python
# 编辑 src/olav/cli/cli_main.py
# 添加 complete_while_typing=True
```

### Priority 3: 优化启动时间
```python
# 延迟初始化 SkillConfig
# 移到首次使用时再加载
```

### Priority 4: 添加关键测试
```python
# 创建 tests/e2e/test_cli_functionality.py
# 添加上述测试用例
```

---

## 验证清单

- [ ] 数据库有数据（devices表至少6行）
- [ ] 查询返回正确结果（`SELECT * FROM devices WHERE hostname='R2'`）
- [ ] TAB补全工作（`lis<TAB>` → `list`）
- [ ] 启动时间 < 5秒
- [ ] 所有E2E测试通过

---

## 根本原因总结

| 问题 | 根因 | 严重性 | 修复时间 |
|------|------|--------|---------|
| 启动慢 | 同步初始化多个组件 | Medium | 30min |
| TAB补全不工作 | `complete_while_typing=False` | High | 5min |
| 查询返回空 | 数据库无数据/视图不存在 | Critical | 10min |
| 测试未发现 | 测试覆盖不足 + Mock掩盖真实问题 | High | 2h |

**总修复时间预估**：3-4小时
