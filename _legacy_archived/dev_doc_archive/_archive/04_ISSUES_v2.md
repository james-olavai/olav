# OLAV v0.10.0 Issues - CLI 无法使用问题

> 日期: 2026-02-04
> 状态: 🔴 Critical - 阻塞用户使用

## 背景

E2E 测试全部通过，但实际用户使用 `uv run olav` 启动 CLI 时遇到多个问题，导致系统无法正常使用。

---

## Issue #1: SKILL.md 目录扫描问题

### 症状
```
2026-02-04 22:38:01 - olav.core.skill_config - WARNING - SKILL.md not found: /home/yhvh/Olav/.olav/skills/_archive/SKILL.md
2026-02-04 22:38:01 - olav.core.skill_config - WARNING - SKILL.md not found: /home/yhvh/Olav/.olav/skills/test/SKILL.md
```

### 根因
`src/olav/core/skill_config.py` 第 49-57 行的 `initialize()` 方法遍历 SKILLS_DIR 下的**所有子目录**，没有跳过特殊目录。

```python
# 问题代码
for skill_dir in skills_path.iterdir():
    if not skill_dir.is_dir():
        continue
    # ❌ 缺少: 跳过 _archive/, test/ 等非 skill 目录
```

### 影响
- 启动时产生警告日志污染
- 可能导致 skill 加载计数不准确

### 修复方案
在目录遍历时添加过滤条件：
```python
if skill_dir.name.startswith("_") or skill_dir.name in ("test", "__pycache__"):
    continue
```

---

## Issue #2: TAB 补全显示乱码

### 症状
TAB 补全显示中文正则表达式和奇怪符号，如 `显示.*接口.*状态`，而非用户友好的命令提示。

### 根因
1. `.olav/config/command_whitelist.yaml` 实际是 JSON 格式，内容是中文正则匹配模式：
```json
{
  "command_whitelist": {
    "显示.*接口.*状态": "SELECT...",
    "查看.*路由表": "SELECT..."
  }
}
```

2. `src/olav/cli/session.py` 第 83-88 行从 whitelist 的 **keys** 提取词汇用于补全：
```python
words = [cmd.strip() for cmd in self.whitelist.keys()]
# 结果: ["显示.*接口.*状态", "查看.*路由表", ...] ← 不是用户友好的命令
```

### 影响
- TAB 补全完全不可用
- 用户体验极差

### 修复方案
1. 将 `command_whitelist.yaml` 改为真正的 YAML 格式
2. 分离匹配模式和补全提示，例如：
```yaml
completions:
  - "show interfaces on R1"
  - "list BGP neighbors"
  - "check routing table"
patterns:
  - pattern: "显示.*接口"
    sql: "SELECT..."
```

---

## Issue #3: 设备名 R2 不被识别

### 症状
```
OLAV> list ip addresses on R2
🔍 Processing...
🎓 Learning: I don't know 'R2'. Which devices do you mean?
  Enter device names (comma-separated), or press Enter to skip:
```

### 根因
`src/olav/agents/query_agent.py` 第 141-148 行从 `v_system` 视图加载已知设备：
```python
def _load_known_devices(self) -> set[str]:
    devices = self.gw.query_snapshots("SELECT DISTINCT device FROM v_system")
    return {str(d["device"]).upper() for d in devices}
```

**问题**: `v_system` 视图不存在！

数据库验证：
```bash
# snapshots.duckdb 表: query_cache, schema_version  ← 没有 v_system!
# olav.duckdb 表: raw_outputs (包含 R1, R2, R3, R4, SW1, SW2)
```

`DataGateway.query_snapshots()` 连接的是 `snapshots.duckdb`，但设备数据在 `olav.duckdb` 的 `raw_outputs` 表中。

### 影响
- 所有设备名都被当作"未知"
- 触发不必要的学习流程
- 用户无法正常查询

### 修复方案
选项 A: 在 `snapshots.duckdb` 创建 `v_system` 视图
选项 B: 修改 `_load_known_devices()` 从正确的数据库/表加载
选项 C: 使用 `olav.duckdb` 的 `raw_outputs` 表

---

## Issue #4: 查询长时间无响应

### 症状
输入查询后系统长时间无响应，没有任何输出。

### 根因组合
1. `_known_devices` 加载失败返回空集
2. 所有设备名触发别名学习流程 (等待用户输入)
3. LLM API 调用可能无响应或超时设置不合理
4. 没有明确的进度指示器

### 影响
- 用户不知道系统在做什么
- 体验极差，感觉系统卡死

### 修复方案
1. 修复设备加载问题 (Issue #3)
2. 添加超时控制和进度反馈
3. 优化别名学习流程 (跳过明显是设备名的模式如 R1, SW1)

---

## Issue #5: E2E 测试与实际使用的差距

### 症状
`uv run pytest tests/e2e/test_acceptance.py -v` 全部通过，但 `uv run olav` 无法正常使用。

### 根因分析

| 方面 | E2E 测试 | 真实 CLI |
|:----|:--------|:--------|
| 数据库 | Mock 或测试数据 | 生产数据库 (缺少视图) |
| 设备连接 | 直接 NetworkExecutor | 通过 LLM Agent 间接调用 |
| 输入来源 | 硬编码字符串 | prompt-toolkit 交互 |
| Session | 测试隔离 | 持久化 DuckDB |
| 补全/历史 | 未测试 | FileHistory + WordCompleter |

### E2E 测试覆盖的内容
- ✅ NetworkExecutor 直接命令执行
- ✅ Ruff/Pyright 代码质量
- ✅ 基本 subprocess 管道调用

### E2E 测试未覆盖的内容
- ❌ 交互式 CLI 完整流程
- ❌ 数据库视图存在性验证
- ❌ QueryAgent 设备识别逻辑
- ❌ TAB 补全实际效果
- ❌ 真实 LLM 响应处理

### 修复方案
1. 添加真实交互式 CLI 端到端测试
2. 验证数据库结构完整性
3. 测试从用户输入到输出的完整链路

---

## 优先级排序

| 优先级 | Issue | 原因 |
|:------|:------|:----|
| P0 | #3 设备不识别 | 完全阻塞核心功能 |
| P0 | #4 无响应 | 用户无法使用 |
| P1 | #2 TAB 补全 | 严重影响体验 |
| P2 | #1 目录扫描 | 警告日志但不阻塞 |
| P2 | #5 测试差距 | 需要长期改进 |

---

## 相关文件

- `src/olav/core/skill_config.py` - Issue #1
- `src/olav/cli/session.py` - Issue #2
- `.olav/config/command_whitelist.yaml` - Issue #2
- `src/olav/agents/query_agent.py` - Issue #3, #4
- `src/olav/lib/data_gateway.py` - Issue #3
- `tests/e2e/test_acceptance.py` - Issue #5
