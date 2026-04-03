# 运行你的第一个查询

安装完成后，你有三种方式与 OLAV 交互。让我们从最简单的开始。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-02 | `olav list` 列出所有可用 Agent | ✅ v0.10.0 |
    | C-L2-14 | `olav` 无参数启动 TUI 交互模式 | ✅ v0.10.0 |
    | C-L2-15 | `olav --session <id>` 恢复会话 | ✅ v0.10.0 |
    | C-L2-16 | `olav service web start` 启动 Web 界面 | ✅ v0.10.0 |
    | C-L2-08 | `olav log list` 查看操作历史 | ✅ v0.10.0 |

---

## 命令行模式：一句话提问

最快的方式是直接在命令行输入自然语言问题：

```bash
olav "有多少台设备？"
olav "哪些接口是 down 的？"
olav "列出所有运行 IOS XE 的设备"
```

OLAV 会自动将你的问题路由到最合适的 Agent。默认的 `quick` Agent 针对网络运维场景优化，适合快速查询。

如果你想查询 **OLAV 平台本身**的信息，使用内置命令：

```bash
olav version                          # 查看平台版本
olav list                             # 查看所有可用 Agent
olav --agent config "列出已注册的服务"   # 查看已连接的外部服务
```

你也可以用 `--agent`（或 `-a`）直接指定某个 Agent：

```bash
olav --agent core "run df -h"                              # 执行系统命令
olav --agent core "run this python: import sys; print(sys.version)"  # 执行 Python 代码
```

---

## 交互模式：多轮对话

不带参数运行 `olav` 即可进入交互式终端（TUI），支持多轮对话：

```bash
olav                      # 默认 Agent 启动
olav --agent config       # 指定 Agent 启动
olav --no-splash          # 跳过启动横幅
```

在交互模式中，你可以像聊天一样自然提问，Agent 会保持上下文：

```
> 有多少个 Agent 可用？
> 最近一小时我做了什么？
> 显示最近的错误
```

### 交互模式中的斜杠命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/clear` | 重置当前对话、清屏 |
| `/tokens` | 查看本次会话的 Token 消耗统计 |
| `/model <name>` | 会话内临时切换 LLM 模型（不修改配置文件） |
| `/trace-review` | 分析最近 7 天的 Agent 失败记录，自动提取经验教训并写入记忆 |
| `/quit` `/exit` `/q` | 退出交互模式 |

### 交互模式中的特殊语法

| 语法 | 功能 | 示例 |
|------|------|------|
| `@file.txt` | 将文件内容注入到提问中 | `@config.yaml 这个配置有什么问题？` |
| `!command` | 直接执行 Shell 命令（不经过 Agent） | `!ls -la exports/` |

!!! tip "从错误中学习"
    `/trace-review` 是 OLAV 自我改进的核心功能。它会分析审计日志中的失败记录，自动总结"下次应该避免什么"，并存入向量记忆库。之后的查询会自动参考这些经验，避免重复犯错。

### 恢复之前的会话

```bash
olav --session <session-id>
```

会话存储在 `~/.olav/sessions/`，默认 24 小时后过期。

---

## Web 界面：浏览器访问

如果你更习惯图形界面，或需要在团队内共享：

```bash
olav service web start
```

然后浏览器访问 `http://localhost:2280`，即可使用与 CLI 相同的 Agent 能力，支持实时流式响应。

详见 [后台服务 →](../guides/services.md)

---

## 了解你的 Agent

运行以下命令查看当前工作空间中有哪些 Agent 可用：

```bash
olav list
```

```
Available Agents:

  • config
    Config & System Agent — 服务注册、数据导入、工作空间健康检查
    Location: .olav/workspace/config/

  • core
    Core OLAV platform agent — 代码执行、SQL 查询、Shell 命令
    Location: .olav/workspace/core/

  • quick  (active)
    Quick Agent — 快速数据查询、CLI 执行、知识库搜索
    Location: .olav/workspace/quick/
```

每个 Agent 擅长不同的事情：

| Agent | 擅长做什么 | 使用场景 |
|-------|-----------|---------|
| `quick` *(默认)* | 快速查询，一步到位 | "有多少台设备？""哪些接口 down 了？" |
| `config` | 管理服务注册、工作空间健康检查 | 连接新 API、诊断工作空间问题 |
| `core` | 执行 Python/SQL/Shell、Web 搜索 | 数据分析、自动化脚本、复杂查询 |

---

## 查看操作历史

OLAV 自动记录每一次操作。查看最近的活动：

```bash
olav log list
```

```
Recent Audit Runs (last 24h):

  [2026-04-03 15:35:52] 7f2693b8  completed     agent=core
  [2026-04-03 15:35:25] 2e31144b  completed     agent=config
  [2026-04-03 15:34:20] 4e314755  completed     agent=quick
```

详见 [审计与日志 →](../guides/audit-and-logs.md)

**下一步：** [了解工作原理 →](how-it-works.md)
