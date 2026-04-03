# 使用 Agent

OLAV 的核心是多个 AI Agent 协作——每个 Agent 专注不同领域，你可以让 OLAV 自动选择，也可以手动指定。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-02 | `olav list` 列出所有可用 Agent | ✅ v0.10.0 |
    | C-L2-03 | `olav workspace list/use` 切换活跃 workspace | ✅ v0.10.0 |
    | C-L2-26 | `olav --auto-approve` 跳过工具调用确认 | ✅ v0.10.0 |

---

## 查看可用的 Agent

```bash
olav list
```

输出示例：
```
Available Agents:

  • config
    Config & System Agent — 服务注册、数据导入、工作空间健康检查
    Location: .olav/workspace/config/

  • core
    Core OLAV platform agent — 代码执行、SQL 查询、平台操作
    Location: .olav/workspace/core/

  • quick  (active)
    Quick Agent — 快速数据查询、CLI 执行、知识库搜索
    Location: .olav/workspace/quick/
```

紧凑视图：

```bash
olav workspace list
```

```
* quick                 -       (user)    ← * 表示当前活跃
  config                -       (user)
  core                  -       (user)
  venv-test             v1.0.0  (managed) ← managed = 通过 olav skill install 安装
```

---

## 内置 Agent 一览

| Agent | 角色 | 适用场景 |
|-------|------|---------|
| `quick` *(默认)* | 快速查询助手 | "有多少台设备？""哪些接口 down 了？"——一步到位的查询 |
| `config` | 系统管理员 | 注册外部服务、生成技能、工作空间健康检查 |
| `core` | 全能工程师 | 执行 Python/SQL/Shell、Web 搜索、复杂数据分析 |

---

## 自动路由（默认行为）

不指定 `--agent` 时，OLAV 会根据你的问题内容自动选择最合适的 Agent：

```bash
olav "显示所有设备"              # → 自动路由到 quick Agent
olav "哪些接口是 down 的？"      # → 自动路由到 quick Agent
olav "列出 BGP 邻居"            # → 自动路由到 quick Agent
```

路由依据是每个 Agent 在 `MANIFEST.yaml` 中定义的 `route_keywords`。默认活跃的 `quick` Agent 针对网络运维场景优化。

!!! note "平台命令不经过路由"
    `olav version`、`olav list`、`olav log list` 等内置命令是直接执行的，不会经过 Agent 路由。

---

## 手动指定 Agent

当你明确知道要用哪个 Agent 时：

```bash
olav --agent config "列出已注册的服务"
olav --agent core "数据库里有哪些表？"
olav --agent core "search: BGP convergence tuning"
```

简写：

```bash
olav -a config "列出已注册的服务"
```

---

## 交互模式

启动交互式终端，支持多轮对话，Agent 会保持上下文：

```bash
olav               # 使用默认 Agent 启动
olav --agent config # 使用指定 Agent 启动
```

在交互模式中，Agent 记得之前的对话内容，你可以自然地追问：

```
> 显示所有设备
> 这些设备中哪些是路由器？
> 它们的 IOS 版本分别是什么？
```

---

## 切换活跃 Agent

活跃 Agent 是你不指定 `--agent` 时默认使用的那个：

```bash
olav workspace list           # 查看所有 Agent，* 标记表示当前活跃
olav workspace use config     # 切换到 config Agent
olav workspace use quick      # 切回 quick Agent
```

---

## 跳过工具确认

默认情况下，Agent 调用工具前会征求你的确认。如果你信任操作（比如只读查询），可以跳过：

```bash
olav --auto-approve "执行健康检查"
```

!!! warning "谨慎使用"
    `--auto-approve` 会自动批准所有工具调用，包括写入操作。建议只在你确定查询是只读的情况下使用。
