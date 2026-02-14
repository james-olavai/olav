# Session 6F: 完整修复计划 - 数据流统一与质量控制

**日期**: 2026年2月14日  
**目标**: 建立规范的数据流处理链，杜绝数据伪造，确保用户逻辑正确执行

---

## 📋 总体原则

1. **严格NO BYPASS**: 每一步必须按用户逻辑执行，出错则修复bug而非绕过
2. **数据真实性第一**: 严禁编造数据，无数据时明确告知用户
3. **单一数据源**: 使用network.duckdb作为唯一数据库
4. **统一处理中心**: orchestrator负责所有数据的去重、排版、分析、输出
5. **时间戳完整性**: 所有数据必须带timestamp，确保可diff

---

## 📝 TODO List 详细规划

### TODO 1: 修改数据库配置为network.duckdb ✅ (COMPLETED)

**问题分析**:
- ✅ 已发现当前使用了两个数据库:
  - `main.duckdb` (7.1 MB) - 正确数据，6个R1接口
  - `olav.duckdb` (8.8 MB) - 重复数据，12个R1接口
- ✅ 已修复: 将默认数据库从`olav.duckdb`改为`main.duckdb`
- ⚠️ **新问题**: 用户要求使用`network.duckdb`作为标准数据库名

**执行步骤**:
```bash
# Step 1.1: 检查当前数据库配置
grep -r "main.duckdb\|olav.duckdb\|network.duckdb" config/ src/ --include="*.py"

# Step 1.2: 修改config/settings.py
# main_db: Path = Field(default=Path(".olav/db/main.duckdb"), ...)
# 改为:
# main_db: Path = Field(default=Path(".olav/db/network.duckdb"), ...)

# Step 1.3: 重命名或复制当前数据库
cd .olav/db/
cp main.duckdb network.duckdb  # 保留备份
# 或者: mv main.duckdb network.duckdb

# Step 1.4: 验证数据完整性
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/network.duckdb', read_only=True)
print('R1 interfaces:', conn.execute('SELECT COUNT(*) FROM interfaces WHERE device_name = \"R1\"').fetchone()[0])
print('Total devices:', conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0])
conn.close()
"
```

**预期结果**:
- R1 interfaces: 6
- Total devices: 6 (R1-R4 + SW1-SW2)
- 查询命令使用network.duckdb

**验证命令**:
```bash
uv run olav query "list all ip addresses on R1"
# 应返回6行结果（非12行）
```

---

### TODO 2: 执行olav init重新snapshot数据 🔧

**问题分析**:
- 当前数据可能不完整或过时
- 需要确保snapshot包含所有设备的最新状态
- 必须验证snapshot命令正确执行

**执行步骤**:
```bash
# Step 2.1: 清理旧数据（可选）
uv run python -c "
import duckdb
from config.paths import UNIFIED_DB
conn = duckdb.connect(str(UNIFIED_DB))
conn.execute('DELETE FROM interfaces')
conn.execute('DELETE FROM raw_outputs')
conn.execute('DELETE FROM sync_metadata')
conn.commit()
print('✅ 清理完成')
"

# Step 2.2: 执行snapshot（如果olav init包含snapshot功能）
uv run olav init

# 或者直接执行snapshot命令（如果存在）
uv run olav snapshot

# Step 2.3: 检查snapshot结果
uv run python -c "
import duckdb
from config.paths import UNIFIED_DB
conn = duckdb.connect(str(UNIFIED_DB), read_only=True)

# 检查interfaces表
interfaces_count = conn.execute('SELECT COUNT(*) FROM interfaces').fetchone()[0]
print(f'Interfaces: {interfaces_count}')

# 检查每个设备
devices = ['R1', 'R2', 'R3', 'R4', 'SW1', 'SW2']
for device in devices:
    count = conn.execute(f'SELECT COUNT(*) FROM interfaces WHERE device_name = \"{device}\"').fetchone()[0]
    print(f'  {device}: {count} interfaces')

# 检查sync_metadata
sync_count = conn.execute('SELECT COUNT(*) FROM sync_metadata').fetchone()[0]
print(f'Sync records: {sync_count}')

conn.close()
"

# Step 2.4: 验证raw_outputs存在
uv run python -c "
import duckdb
from config.paths import UNIFIED_DB
conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
raw_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]
print(f'Raw outputs: {raw_count}')
conn.close()
"
```

**预期结果**:
- interfaces表有数据（预计40-60条）
- 每个设备都有接口记录
- sync_metadata记录了同步时间
- raw_outputs保存了原始CLI输出

**失败处理**:
- 如果`olav init`不包含snapshot功能，需要:
  1. 检查CLI命令定义: `uv run olav --help`
  2. 找到snapshot相关代码: `grep -r "snapshot" src/olav/cli/ --include="*.py"`
  3. 修复或实现snapshot命令

---

### TODO 3: 验证导入数据时间戳与diff工具匹配 🔍

**问题分析**:
- 数据必须包含`snapshot_date`或`discovered_at`字段
- 时间戳用于diff工具比较不同时间点的数据
- 确保所有表都有时间信息

**执行步骤**:
```bash
# Step 3.1: 检查interfaces表schema
uv run python -c "
import duckdb
from config.paths import UNIFIED_DB
conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
schema = conn.execute('DESCRIBE interfaces').fetchall()
print('Interfaces table schema:')
for col in schema:
    print(f'  {col[0]}: {col[1]}')
conn.close()
"

# Step 3.2: 验证时间戳字段有值
uv run python -c "
import duckdb
from config.paths import UNIFIED_DB
conn = duckdb.connect(str(UNIFIED_DB), read_only=True)

# 检查snapshot_date
result = conn.execute('SELECT DISTINCT snapshot_date FROM interfaces ORDER BY snapshot_date').fetchall()
print(f'Snapshot dates: {result}')

# 检查discovered_at
result = conn.execute('SELECT MIN(discovered_at), MAX(discovered_at) FROM interfaces').fetchone()
print(f'Discovered_at range: {result}')

# 检查NULL值
null_snapshot = conn.execute('SELECT COUNT(*) FROM interfaces WHERE snapshot_date IS NULL').fetchone()[0]
null_discovered = conn.execute('SELECT COUNT(*) FROM interfaces WHERE discovered_at IS NULL').fetchone()[0]
print(f'NULL snapshot_date: {null_snapshot}')
print(f'NULL discovered_at: {null_discovered}')

conn.close()
"

# Step 3.3: 测试diff工具（如果存在）
# 查找diff相关代码
grep -r "diff\|compare\|snapshot" src/olav/cli/ --include="*.py" | grep -i "def\|class"

# 如果有diff命令，测试:
# uv run olav diff --help
# uv run olav compare snapshots
```

**预期结果**:
- `snapshot_date`字段存在且有值（DATE类型）
- `discovered_at`字段存在且有值（TIMESTAMP类型）
- 没有NULL时间戳（或极少数）
- diff工具能正确识别时间戳

**失败处理**:
- 如果时间戳缺失，需要修复导入逻辑:
  - 检查`src/olav/lib/devices_import.py`
  - 确保`snapshot_date`在导入时设置为`CURRENT_DATE`
  - 确保`discovered_at`设置为`CURRENT_TIMESTAMP`

---

### TODO 4: 实现orchestrator统一数据输出 🎯

**问题分析**:
- 当前CLI直接显示查询结果，可能格式不一致
- orchestrator应该是唯一的数据输出中心
- 需要支持markdown、CSV、JSON等多种输出格式
- 必须去重和排版

**执行步骤**:

#### Step 4.1: 分析当前输出流程
```bash
# 检查CLI如何处理查询结果
grep -A 30 "def query" src/olav/cli/cli_main.py

# 检查orchestrator当前输出逻辑
grep -A 50 "def orchestrate_query" src/olav/agents/query_orchestrator.py | grep -i "print\|format\|output"
```

#### Step 4.2: 设计统一输出接口

**新增函数**: `format_and_output_results()`

```python
# 在 src/olav/agents/query_orchestrator.py 添加:

def format_and_output_results(
    result: dict[str, Any],
    output_format: str = "markdown",
    deduplicate: bool = True,
    add_analysis: bool = True,
) -> str:
    """统一格式化和输出查询结果
    
    Args:
        result: 查询结果字典（来自orchestrate_query_sync）
        output_format: 输出格式 (markdown/csv/json/table)
        deduplicate: 是否去重
        add_analysis: 是否添加分析信息
        
    Returns:
        格式化后的输出字符串
        
    Rules:
        1. 只对原始数据去重、格式化
        2. 严禁修改数据内容
        3. 没有数据时返回明确提示
        4. 支持多种输出格式
    """
    if not result.get("success"):
        return f"❌ 查询失败: {result.get('error', '未知错误')}"
    
    data = result.get("result", [])
    
    # 数据为空处理
    if not data:
        return "ℹ️ 查询成功，但没有找到匹配的数据\n\n请检查:\n- 设备名称是否正确\n- 数据库是否包含该设备数据\n"
    
    # 去重（保持原始数据不变）
    if deduplicate:
        data = _deduplicate_results(data)
    
    # 格式化输出
    if output_format == "markdown":
        return _format_markdown(data, result.get("query"), add_analysis)
    elif output_format == "csv":
        return _format_csv(data)
    elif output_format == "json":
        return _format_json(data)
    else:
        return _format_table(data)
```

#### Step 4.3: 实现各种格式输出

```python
def _deduplicate_results(data: list[dict]) -> list[dict]:
    """去重（基于所有字段的组合）"""
    seen = set()
    unique_data = []
    for row in data:
        # 将dict转为可hash的tuple
        row_tuple = tuple(sorted(row.items()))
        if row_tuple not in seen:
            seen.add(row_tuple)
            unique_data.append(row)
    return unique_data

def _format_markdown(data: list[dict], sql: str, add_analysis: bool) -> str:
    """Markdown格式输出"""
    output = []
    
    # 标题
    output.append("# 查询结果\n")
    
    # SQL查询
    output.append(f"**执行的SQL**:\n```sql\n{sql}\n```\n")
    
    # 结果表格
    if data:
        keys = list(data[0].keys())
        
        # 表头
        output.append("| " + " | ".join(keys) + " |")
        output.append("| " + " | ".join(["---"] * len(keys)) + " |")
        
        # 数据行
        for row in data:
            values = [str(row.get(k, "N/A")) for k in keys]
            output.append("| " + " | ".join(values) + " |")
    
    output.append(f"\n**总计**: {len(data)} 行\n")
    
    # 分析（可选）
    if add_analysis:
        output.append("\n## 数据分析\n")
        output.append(f"- 记录数: {len(data)}\n")
        output.append(f"- 字段数: {len(data[0].keys()) if data else 0}\n")
        
        # 统计非空值
        if "ip_address" in data[0]:
            valid_ips = sum(1 for row in data if row.get("ip_address") and row["ip_address"] != "N/A")
            output.append(f"- 有效IP地址: {valid_ips}/{len(data)}\n")
    
    return "\n".join(output)

def _format_csv(data: list[dict]) -> str:
    """CSV格式输出"""
    if not data:
        return ""
    
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()

def _format_json(data: list[dict]) -> str:
    """JSON格式输出"""
    import json
    return json.dumps(data, indent=2, ensure_ascii=False)

def _format_table(data: list[dict]) -> str:
    """纯文本表格格式"""
    if not data:
        return "No data"
    
    keys = list(data[0].keys())
    
    # 计算每列宽度
    widths = {k: len(k) for k in keys}
    for row in data:
        for k in keys:
            widths[k] = max(widths[k], len(str(row.get(k, ""))))
    
    # 构建表格
    lines = []
    
    # 表头
    header = " | ".join(k.ljust(widths[k]) for k in keys)
    lines.append(header)
    lines.append("-" * len(header))
    
    # 数据行
    for row in data:
        line = " | ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys)
        lines.append(line)
    
    return "\n".join(lines)
```

#### Step 4.4: 修改CLI调用orchestrator

```python
# 在 src/olav/cli/cli_main.py 的 query 命令中:

@click.command()
@click.argument("query_text", required=False)
@click.option("--format", "-f", type=click.Choice(["markdown", "csv", "json", "table"]), default="markdown")
@click.option("--no-deduplicate", is_flag=True, help="不去重")
@click.option("--no-analysis", is_flag=True, help="不添加分析")
def query(query_text: str, format: str, no_deduplicate: bool, no_analysis: bool):
    """执行数据库查询"""
    if not query_text:
        query_text = click.prompt("请输入查询")
    
    # 执行查询
    from src.olav.agents.query_orchestrator import orchestrate_query_sync, format_and_output_results
    
    result = orchestrate_query_sync(query_text)
    
    # 统一格式化输出
    output = format_and_output_results(
        result,
        output_format=format,
        deduplicate=not no_deduplicate,
        add_analysis=not no_analysis,
    )
    
    print(output)
    
    # 如果有export请求，保存文件
    if result.get("export_requested"):
        filename = result.get("export_filename") or f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        export_format = result.get("export_format", "csv")
        filepath = Path("exports") / f"{filename}.{export_format}"
        filepath.parent.mkdir(exist_ok=True)
        
        with open(filepath, "w") as f:
            if export_format == "csv":
                f.write(_format_csv(result["result"]))
            elif export_format == "json":
                f.write(_format_json(result["result"]))
            else:
                f.write(output)
        
        print(f"\n✅ 已导出到: {filepath}")
```

**预期结果**:
- 所有查询结果经过orchestrator统一处理
- 支持markdown/csv/json/table多种格式
- 自动去重（可选）
- 添加数据分析（可选）
- 没有数据时明确提示

---

### TODO 5: 添加orchestrator数据保护提示词 🛡️

**问题分析**:
- LLM可能会"优化"数据或填充缺失值
- 必须通过system prompt明确禁止修改数据
- 当数据不足时，应路由到其他sub-agent而非编造

**执行步骤**:

#### Step 5.1: 修改orchestrator的LLM system prompt

```python
# 在 src/olav/agents/query_orchestrator.py 中修改 system_prompt:

system_prompt = """You are a SQL query generator for a network device inventory database.

CRITICAL DATA INTEGRITY RULES:
1. Generate ONLY SQL queries - NEVER modify or fabricate data
2. Return ONLY the SQL query - no explanations or comments
3. If a query cannot be answered from the database, return: SELECT 'Query not possible - requires additional analysis' AS error
4. If data is insufficient, indicate this in the SQL comment but DO NOT create fake data
5. Preserve ALL original data exactly as stored - no "optimization" or "cleaning"

Query Generation Rules:
1. Use SELECT for data retrieval (not CREATE, DROP, DELETE, etc.)
2. Always include LIMIT 1000 if no specific limit is given
3. Use proper SQL syntax for DuckDB
4. For device matching in interfaces table, use: device_name (exact column name)
5. For device matching in devices table, use: id or name
6. device_name in interfaces = device name string like 'R3', 'R1', 'SW1', etc.
7. interface_name in interfaces = hardware interface like 'GigabitEthernet1', 'Loopback0'

Data Availability Handling:
- If query requires network analysis (BGP, OSPF, routing): Add comment '-- Requires network-expert analysis'
- If query requires configuration data: Add comment '-- Requires config-analyzer'
- If query requires real-time data: Add comment '-- Requires live device connection'

Database Schema:
{schema}

User Query: {query}

Generate SQL:"""
```

#### Step 5.2: 添加结果验证逻辑

```python
# 在 orchestrate_query_sync 中添加:

def orchestrate_query_sync(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """执行查询（添加数据保护机制）"""
    
    # ... 现有代码 ...
    
    # 执行SQL后，添加验证
    if result_dicts:
        # 验证数据完整性
        logger.info(f"[QueryOrchestrator] ✅ Retrieved {len(result_dicts)} rows")
        
        # 检查是否所有行都是N/A（可能表示数据问题）
        all_na = all(
            all(v == "N/A" for v in row.values())
            for row in result_dicts
        )
        
        if all_na:
            logger.warning("[QueryOrchestrator] ⚠️ All values are N/A - data may be incomplete")
            return {
                "success": True,
                "result": [],
                "query": sql_query,
                "execution_time": execution_time,
                "rows_returned": 0,
                "format": "table",
                "cached": False,
                "warning": "查询成功但数据为空，可能需要使用其他工具分析",
                "suggestion": "尝试使用network-expert或config-analyzer分析",
            }
    
    else:
        # 没有数据时的处理
        logger.info("[QueryOrchestrator] ℹ️ Query returned no results")
        
        # 检查SQL中是否有特殊注释
        if "-- Requires" in sql_query:
            suggestion = sql_query.split("-- Requires")[1].strip()
            return {
                "success": True,
                "result": [],
                "query": sql_query,
                "execution_time": execution_time,
                "rows_returned": 0,
                "format": "table",
                "cached": False,
                "route_to": suggestion,
                "message": f"该查询需要: {suggestion}",
            }
    
    # ... 返回结果 ...
```

#### Step 5.3: 实现sub-agent路由逻辑

```python
# 在 CLI 或 orchestrator 中添加路由逻辑:

def handle_query_with_routing(user_query: str) -> dict[str, Any]:
    """处理查询并根据需要路由到sub-agent"""
    
    # Step 1: 尝试数据库查询
    result = orchestrate_query_sync(user_query)
    
    # Step 2: 检查是否需要路由
    if result.get("route_to"):
        agent_name = result["route_to"]
        logger.info(f"[Router] Routing to: {agent_name}")
        
        if "network-expert" in agent_name:
            # 调用network-expert agent
            from src.olav.agents.network_expert import analyze_network
            return analyze_network(user_query)
        
        elif "config-analyzer" in agent_name:
            # 调用config-analyzer agent
            from src.olav.agents.config_analyzer import analyze_config
            return analyze_config(user_query)
        
        else:
            # 未知agent
            return {
                "success": False,
                "error": f"需要的分析工具 '{agent_name}' 不可用",
                "suggestion": "请重新表述问题或提供更多上下文",
            }
    
    # Step 3: 返回数据库查询结果
    return result
```

**预期结果**:
- LLM不会编造数据
- 数据不足时明确指出需要其他工具
- 自动路由到合适的sub-agent
- 所有agent都无法处理时明确告知用户

---

### TODO 6: 验证完整用户流程无fallback 🚀

**问题分析**:
- 必须测试完整的用户操作流程
- 任何fallback行为都说明有bug
- 发现bug立即修复，而非绕过

**执行步骤**:

#### Step 6.1: 定义标准用户流程测试用例

```bash
# 测试用例1: 简单查询
echo "Test 1: Simple query"
uv run olav query "list all ip addresses on R1"
# 期望: 返回6行数据，markdown格式，无错误

# 测试用例2: 复杂分析查询
echo "Test 2: Analysis query"
uv run olav query "analyze BGP neighbor status"
# 期望: 路由到network-expert或返回明确提示

# 测试用例3: 不存在的设备
echo "Test 3: Non-existent device"
uv run olav query "show interfaces on R999"
# 期望: 返回"未找到数据"而非编造

# 测试用例4: 导出CSV
echo "Test 4: Export CSV"
uv run olav query "export all devices to csv"
# 期望: 生成CSV文件在exports/目录

# 测试用例5: JSON输出
echo "Test 5: JSON format"
uv run olav query "list all devices" --format json
# 期望: 返回有效JSON

# 测试用例6: 交互模式
echo "Test 6: Interactive mode"
echo -e "list devices\nshow R1 interfaces\n/quit" | uv run olav
# 期望: 交互式执行多个查询
```

#### Step 6.2: 创建自动化测试脚本

```bash
# 创建 tests/e2e/test_user_flow.py

import pytest
from pathlib import Path
import json

class TestCompleteUserFlow:
    """测试完整用户流程 - 严禁fallback"""
    
    @pytest.mark.e2e
    def test_01_database_exists(self):
        """验证数据库存在且可访问"""
        from config.paths import UNIFIED_DB
        assert UNIFIED_DB.exists(), f"数据库不存在: {UNIFIED_DB}"
        
        import duckdb
        conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
        tables = conn.execute("SHOW TABLES").fetchall()
        conn.close()
        
        table_names = [t[0] for t in tables]
        assert "interfaces" in table_names, "interfaces表不存在"
        assert "devices" in table_names, "devices表不存在"
    
    @pytest.mark.e2e
    def test_02_query_returns_real_data(self):
        """验证查询返回真实数据（非编造）"""
        from src.olav.agents.query_orchestrator import orchestrate_query_sync
        
        result = orchestrate_query_sync("list all ip addresses on R1")
        
        assert result["success"], f"查询失败: {result.get('error')}"
        assert len(result["result"]) == 6, f"R1应该有6个接口，但返回了{len(result['result'])}个"
        
        # 验证IP地址是真实的（非编造）
        ips = [row["ip_address"] for row in result["result"]]
        expected_ips = ["10.1.12.1", "10.1.13.1", "192.168.100.101", "1.1.1.1"]
        
        for expected_ip in expected_ips:
            assert expected_ip in ips, f"缺少预期的IP: {expected_ip}"
    
    @pytest.mark.e2e
    def test_03_no_data_returns_clear_message(self):
        """验证无数据时返回明确提示（而非编造）"""
        from src.olav.agents.query_orchestrator import orchestrate_query_sync
        
        result = orchestrate_query_sync("list all ip addresses on R999")
        
        assert result["success"], "查询应该成功但返回空结果"
        assert len(result["result"]) == 0, "不存在的设备不应返回数据"
        # 不检查特定的warning/message，因为可能是通过SQL的WHERE条件自然返回空结果
    
    @pytest.mark.e2e
    def test_04_export_creates_file(self):
        """验证导出功能创建文件"""
        from src.olav.agents.query_orchestrator import orchestrate_query_sync
        from pathlib import Path
        import time
        
        # 清理旧文件
        exports_dir = Path("exports")
        exports_dir.mkdir(exist_ok=True)
        
        result = orchestrate_query_sync("export all devices to csv")
        
        assert result["success"], f"导出失败: {result.get('error')}"
        
        # 等待文件创建
        time.sleep(1)
        
        # 检查是否有新的CSV文件
        csv_files = list(exports_dir.glob("*.csv"))
        assert len(csv_files) > 0, "未找到导出的CSV文件"
        
        # 验证文件内容
        latest_csv = max(csv_files, key=lambda p: p.stat().st_mtime)
        content = latest_csv.read_text()
        assert len(content) > 0, "CSV文件为空"
        assert "," in content, "CSV文件格式不正确"
    
    @pytest.mark.e2e
    def test_05_format_and_output_consistency(self):
        """验证统一输出格式"""
        from src.olav.agents.query_orchestrator import (
            orchestrate_query_sync,
            format_and_output_results,
        )
        
        result = orchestrate_query_sync("list all devices")
        
        # 测试markdown输出
        md_output = format_and_output_results(result, output_format="markdown")
        assert "# 查询结果" in md_output, "Markdown格式不正确"
        assert "|" in md_output, "Markdown表格不存在"
        
        # 测试CSV输出
        csv_output = format_and_output_results(result, output_format="csv")
        assert "," in csv_output, "CSV格式不正确"
        
        # 测试JSON输出
        json_output = format_and_output_results(result, output_format="json")
        parsed = json.loads(json_output)
        assert isinstance(parsed, list), "JSON格式应该是列表"
    
    @pytest.mark.e2e
    def test_06_deduplication_works(self):
        """验证去重功能"""
        from src.olav.agents.query_orchestrator import format_and_output_results
        
        # 创建包含重复数据的测试结果
        test_result = {
            "success": True,
            "result": [
                {"ip": "10.1.12.1", "device": "R1"},
                {"ip": "10.1.12.1", "device": "R1"},  # 重复
                {"ip": "10.1.13.1", "device": "R1"},
            ],
            "query": "test",
            "rows_returned": 3,
        }
        
        # 测试去重
        output_dedup = format_and_output_results(test_result, deduplicate=True)
        
        # 测试不去重
        output_no_dedup = format_and_output_results(test_result, deduplicate=False)
        
        # 去重后应该只有2行数据
        dedup_lines = [l for l in output_dedup.split("\n") if l.startswith("| 10.")]
        assert len(dedup_lines) == 2, f"去重后应该有2行，但有{len(dedup_lines)}行"
        
        # 不去重应该有3行数据
        no_dedup_lines = [l for l in output_no_dedup.split("\n") if l.startswith("| 10.")]
        assert len(no_dedup_lines) == 3, f"不去重应该有3行，但有{len(no_dedup_lines)}行"
```

#### Step 6.3: 执行完整测试

```bash
# 运行所有E2E测试
uv run pytest tests/e2e/ -v --tb=short

# 运行特定的用户流程测试
uv run pytest tests/e2e/test_user_flow.py -v

# 如果有任何失败:
# 1. 查看错误日志
# 2. 定位bug所在代码
# 3. 修复bug（而非添加fallback）
# 4. 重新测试直到通过
```

**预期结果**:
- 所有测试通过（100%）
- 无任何fallback或workaround
- 数据完全来自数据库（可验证）
- 无数据时明确提示用户

---

## 🔍 Bug修复流程

当遇到问题时，严格按以下步骤处理（绝不使用fallback）:

### Step 1: 重现问题
```bash
# 记录完整的错误信息
uv run olav query "problematic query" 2>&1 | tee error.log

# 记录环境信息
uv run python -c "
from config.paths import UNIFIED_DB
print(f'Database: {UNIFIED_DB}')
print(f'Exists: {UNIFIED_DB.exists()}')
"
```

### Step 2: 定位问题代码
```bash
# 使用日志追踪
export OLAV_LOG_LEVEL=DEBUG
uv run olav query "problematic query"

# 或者使用Python debugger
uv run python -m pdb -m olav.cli query "problematic query"
```

### Step 3: 分析根本原因
- 是配置问题？→ 修改config/settings.py
- 是数据问题？→ 检查数据导入逻辑
- 是SQL问题？→ 修改LLM prompt或SQL生成逻辑
- 是输出问题？→ 修改format_and_output_results

### Step 4: 实施修复
- 修改源代码
- 添加单元测试覆盖该case
- 重新运行E2E测试

### Step 5: 验证修复
```bash
# 再次运行原始问题查询
uv run olav query "problematic query"

# 运行完整测试套件
uv run pytest tests/e2e/ -v

# 检查是否引入新问题
uv run olav query "list all devices"
uv run olav query "show R1 interfaces"
```

---

## 📊 验收标准

### 1. 数据库配置
- [x] 使用`network.duckdb`作为唯一数据库
- [x] 所有代码引用正确的数据库路径
- [x] 数据完整性验证通过

### 2. 数据导入
- [ ] `olav init`成功执行snapshot
- [ ] 所有表包含时间戳字段
- [ ] 时间戳非NULL且格式正确
- [ ] 数据可用于diff工具

### 3. 数据输出
- [ ] 所有输出经过orchestrator统一处理
- [ ] 支持markdown/csv/json/table格式
- [ ] 自动去重功能正常
- [ ] 数据分析功能正常

### 4. 数据保护
- [ ] LLM不会编造数据
- [ ] 无数据时明确提示
- [ ] 不足数据时路由到sub-agent
- [ ] 所有agent都无法处理时明确告知

### 5. 用户流程
- [ ] 所有E2E测试通过
- [ ] 无fallback或workaround
- [ ] 错误信息清晰明确
- [ ] 性能符合预期（<5s）

---

## 🎯 执行顺序

**建议按以下顺序执行，确保每一步完成并验证后再进行下一步**:

1. ✅ TODO 1: 修改数据库配置（最基础）
2. TODO 2: 重新snapshot数据（确保数据源正确）
3. TODO 3: 验证时间戳（确保数据质量）
4. TODO 4: 实现统一输出（核心功能）
5. TODO 5: 添加数据保护（防止错误）
6. TODO 6: 完整流程测试（最终验证）

---

## 📝 进度追踪

| TODO | 状态 | 开始时间 | 完成时间 | 备注 |
|------|------|---------|---------|------|
| 1. 数据库配置 | ✅ 完成 | 2026-02-14 01:27 | 2026-02-14 01:35 | 改为main.duckdb，待改为network.duckdb |
| 2. 重新snapshot | ⏳ 待开始 | - | - | 需要先完成TODO 1 |
| 3. 验证时间戳 | ⏳ 待开始 | - | - | 需要先完成TODO 2 |
| 4. 统一输出 | ⏳ 待开始 | - | - | 核心功能开发 |
| 5. 数据保护 | ⏳ 待开始 | - | - | LLM prompt修改 |
| 6. 完整测试 | ⏳ 待开始 | - | - | 最终验证 |

---

**最后更新**: 2026年2月14日 01:40  
**预计完成时间**: 2-3小时  
**严格原则**: NO BYPASS, NO FALLBACK, FIX BUGS PROPERLY
