# Core Agent 工具集

Core Agent 是 OLAV 的"全能工程师"——它可以执行 Python 代码、SQL 查询、Shell 命令和 Web 搜索。当其他 Agent 能力不足时，Core Agent 是你的后盾。

```bash
olav --agent core "你的请求"
```

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-31 | Core Agent 执行 Python 代码并返回输出 | ✅ v0.10.0 |
    | C-L2-32 | Core Agent 执行 SQL 查询业务数据库 | ✅ v0.10.0 |
    | C-L2-33 | Core Agent Web 搜索并总结结果 | ✅ v0.10.0 |
    | C-L2-34 | Core Agent 执行 Shell 命令 | ✅ v0.10.0 |
    | C-L2-35 | Config Agent 检测工作空间健康问题 | ✅ v0.10.0 |

---

## 执行 Python 代码

让 Agent 直接运行 Python，适合数据分析、计算和快速脚本：

```bash
olav --agent core "run this python: import sys; print(sys.version)"
```

```
🔧 run_python_code(...)
Python 3.12.3 (main, Mar 3 2026, ...)
```

更多示例：

```bash
olav --agent core "计算这组数据的 P95 延迟: [12, 45, 23, 89, 34]"
olav --agent core "解析这个 CSV 并统计 A 列的唯一值数量"
olav --agent core "画一个柱状图: red=10, blue=25, green=15 并保存到 /tmp/chart.png"
```

Python 在 OLAV 平台的 Python 环境中运行，输出会被捕获并显示在回复中。

---

## 执行 SQL 查询

直接查询业务数据库中的网络数据：

```bash
olav --agent core "数据库里有哪些表？"
```

```
Main Tables (use netops. prefix):
 • netops.devices (hostname, platform, ip_address, role)
 • netops.parsed_outputs (device_name, command, parsed_data, snapshot_id)
 • netops.topology_links (source_device, source_interface, ...)

Views (no prefix needed):
 • v_interfaces_auto, v_bgp_neighbors_auto, v_ospf_neighbors_auto, ...
```

你可以用自然语言描述，也可以直接写 SQL：

```bash
olav --agent core "数据库里有多少台设备？"
olav --agent core "SELECT hostname, platform FROM netops.devices"
olav --agent core "显示最近 5 条拓扑链路"
```

!!! note "SQL 查询的是业务数据库"
    Core Agent 的 `execute_sql` 连接的是 `.olav/databases/domain.duckdb`（网络设备数据）。如果要查**审计日志**，请使用 `olav log` 命令或直接连接 `.olav/databases/audit.duckdb`。

---

## Web 搜索

当你需要查找外部文档或技术资料时：

```bash
olav --agent core "search: Cisco IOS BGP maximum-paths 配置方法"
olav --agent core "search: DuckDB 窗口函数教程"
```

Agent 会搜索网络、提取相关内容、总结后返回给你。

---

## Shell 命令

执行系统命令，查看服务器状态或文件：

```bash
olav --agent core "run: df -h"
olav --agent core "run: ls -la exports/"
olav --agent core "检查 2280 端口是否开放"
```

!!! warning "注意执行路径"
    Shell 命令以当前用户身份在 OLAV 项目根目录下执行。路径请使用绝对路径或明确的相对路径。

---

## 跳过确认

自动化场景下，跳过每次工具调用的确认提示：

```bash
olav --agent core --auto-approve "run: df -h"
```

---

## 工作空间健康检查（Config Agent）

Config Agent 可以诊断工作空间的常见问题：

```bash
olav --agent config "执行健康检查"
olav --agent config "审计工作空间是否有错误"
```

能检测到的问题：

- `@tool` 函数名冲突（多个技能定义了同名工具）
- `MANIFEST.yaml` 缺少必要字段
- `AGENT.md` 中引用了不存在的文件

---

## Core Agent vs Config Agent：该用哪个？

| 任务 | 用哪个 Agent |
|------|-------------|
| 执行 Python / SQL / Shell | `core` |
| Web 搜索 | `core` |
| 数据分析和计算 | `core` |
| 注册外部服务 | `config` |
| 工作空间健康检查 | `config` |
| 安装 / 生成技能 | `config` |
