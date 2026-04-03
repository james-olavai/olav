# 审计与日志

OLAV 自动记录每一次 Agent 操作——每个查询、每次工具调用、每个错误，全部写入审计日志。无需额外配置，开箱即用。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-08 | `olav log list/errors` 查询审计日志 | ✅ v0.10.0 |
    | C-L2-12 | 多用户并发 Audit 无写冲突 | ✅ v0.10.0 |
    | C-L2-22 | `olav log export trajectory/sft/atif` 导出训练数据 | ✅ v0.10.0 |
    | C-L2-40 | `olav log show <run-id>` 显示完整事件序列 | ✅ v0.10.0 |
    | C-L2-45 | 审计数据库可直接通过 DuckDB 查询 | ✅ v0.10.0 |

---

## 为什么重要？

- **可追溯**：出了问题可以回溯到具体的操作和时间点
- **合规**：满足 SOC2、ISO 27001 等审计要求（审计日志带 SHA256 防篡改校验）
- **改进**：分析失败模式，让 Agent 越用越好
- **训练**：导出操作轨迹，用于微调你自己的 LLM

---

## 查看最近操作

```bash
olav log list
```

```
Recent Audit Runs (last 24h):

  [2026-04-03 15:35:52] 7f2693b8  completed     agent=core
  [2026-04-03 15:35:25] 2e31144b  completed     agent=config
  [2026-04-03 15:34:20] 4e314755  completed     agent=quick
  [2026-04-03 02:33:26] 37d3dc7f  running       agent=config
```

每条记录包含：时间戳、运行 ID（8 位）、状态（`completed` / `running` / `error`）、执行的 Agent。

## 查看某次操作的详情

```bash
olav log show 7f2693b8
```

使用 `olav log list` 中显示的 8 位运行 ID，可以查看该次操作的完整信息：调用了哪些工具、LLM 的推理过程、输入输出、错误信息等。

## 只看错误

```bash
olav log errors              # 最近 24 小时的错误
olav log errors --hours 168  # 最近 7 天的错误
```

---

## 导出训练数据

OLAV 的审计日志不仅用于回溯，还可以导出为 LLM 训练数据——让你的操作经验变成 AI 的知识。

```bash
olav log export trajectory --output ./exports/train/ --no-encrypt
```

```
✓ Trajectory export complete
  Runs scanned: 19
  Samples exported: 17
  Runs rejected: 0
  Runs deduped: 0
```

导出产出：
```
exports/train/
├── trajectory.jsonl      ← 工具调用轨迹（每个运行一条 JSON）
├── manifest.json         ← 导出元数据
├── stats.json            ← 统计摘要
└── rejected_runs.json    ← 被排除的运行及原因
```

### 三种导出格式

| 格式 | 命令 | 用途 |
|------|------|------|
| Tool-use trajectory | `olav log export trajectory` | 微调工具调用模型（推荐） |
| SFT chat | `olav log export sft` | 有监督微调（对话格式） |
| ATIF trace | `olav log export atif` | 结构化指令格式 |

常用参数：`--hours N`（导出最近 N 小时，默认全部）、`--output DIR`（输出目录）、`--min-score N`（0.0–1.0 质量过滤）。

---

## 审计数据库结构

所有审计数据存储在 `.olav/databases/audit.duckdb`（DuckDB 格式，支持并发写入），包含四张表：

| 表名 | 记录内容 | 用途 |
|------|---------|------|
| `audit_runs` | 每次运行的摘要：运行 ID、开始/结束时间、状态、Agent、用户 | 查看操作总览 |
| `audit_tool_calls` | 每次工具调用的详情：工具名、输入参数、输出结果、耗时（ms） | 分析哪些工具最常用、最慢 |
| `audit_events` | 原始事件流：LLM 消息、工具返回、错误详情 | 深度排查问题 |
| `audit_messages` | 对话消息：用户输入、Agent 回复 | 回顾交互历史 |

!!! tip "敏感信息自动脱敏"
    审计日志会自动识别并脱敏密码、API Key、PSK 等敏感凭证，你不需要担心密钥被明文记录。

---

## 直接用 SQL 查询审计数据

如果你需要更灵活的分析，可以直接用 DuckDB 查询审计数据库：

```python
import duckdb
con = duckdb.connect(".olav/databases/audit.duckdb")

# 哪些工具被调用得最多？
con.execute("""
  SELECT tool_name, COUNT(*) as calls
  FROM audit_tool_calls
  GROUP BY tool_name
  ORDER BY calls DESC
""").fetchall()
# [('execute_sql', 617), ('run_python_code', 187), ('search_knowledge', 165), ...]

# 最近失败的运行
con.execute("""
  SELECT run_id, agent_id, start_time
  FROM audit_runs
  WHERE status = 'error'
  ORDER BY start_time DESC
  LIMIT 10
""").fetchall()
```

---

## 多用户场景

团队共享同一个项目目录时，所有人的操作都写入同一个审计数据库。每条记录都标记了 `user_id`，方便区分谁做了什么操作。

```
.olav/databases/audit.duckdb   ← 项目级共享，DuckDB 保证并发安全
```
