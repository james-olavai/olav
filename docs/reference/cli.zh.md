# CLI 命令参考

OLAV 的所有功能都可以通过命令行访问。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-01 | `olav version` | ✅ v0.10.0 |
    | C-L2-02 | `olav list` | ✅ v0.10.0 |
    | C-L2-10 | `olav export claude-plugin` | ✅ v0.10.0 |
    | C-L2-13 | `olav init` | ✅ v0.10.0 |
    | C-L2-27 | `olav reset --agent` | ✅ v0.10.0 |
    | C-L2-14 | TUI 交互模式 | ✅ v0.10.0 |

---

## 基本用法

```
olav [选项] [命令] [查询]
```

### 全局选项

| 选项 | 简写 | 默认值 | 说明 |
|------|------|-------|------|
| `--agent NAME` | `-a` | `quick` | 指定使用哪个 Agent |
| `--auto-approve` | | 关闭 | 自动批准所有工具调用（跳过确认） |
| `--dangerously-skip-permissions` | | 关闭 | 跳过权限检查（仅限开发环境） |
| `--sandbox MODE` | | `none` | 沙箱模式：`none`（本地）/ `modal` / `daytona` / `runloop`（远程） |
| `--verbose` | `-v` | 关闭 | 显示详细输出（调试用） |
| `--no-splash` | | 关闭 | 跳过启动横幅 |
| `--session ID` | | | 恢复之前的会话 |
| `--version` | `-V` | | 显示版本号 |

---

## 命令列表

### 基础命令

| 命令 | 说明 |
|------|------|
| `olav "你的问题"` | 自然语言查询（使用默认 Agent） |
| `olav --agent config "..."` | 指定 Agent 查询 |
| `olav` | 启动交互式终端（TUI） |
| `olav version` | 显示平台版本 |
| `olav list` | 列出所有可用 Agent |
| `olav init` | 在当前目录初始化 OLAV 项目 |

### 工作空间管理

| 命令 | 说明 |
|------|------|
| `olav workspace list` | 列出所有工作空间（`*` 标记当前活跃） |
| `olav workspace use <name>` | 切换活跃工作空间 |
| `olav workspace status` | 显示工作空间状态 |

### 技能管理

| 命令 | 说明 |
|------|------|
| `olav skill install <路径\|URL>` | 从本地目录或 Git 仓库安装技能 |
| `olav skill install <路径> --merge-into <ws>` | 将工具追加到已有工作空间 |
| `olav skill list` | 列出已安装的技能 |
| `olav skill status <name>` | 查看技能详情（版本、来源、安装时间） |

### 服务注册

| 命令 | 说明 |
|------|------|
| `olav registry register <name>` | 注册外部服务（自动发现 OpenAPI schema 并生成工具） |
| `olav registry refresh <name>` | 强制重新获取已注册服务的 schema |
| `olav registry list` | 列出所有已注册的外部服务 |
| `olav registry status <name>` | 检查已注册服务的可达性 |

### 审计与日志

| 命令 | 说明 |
|------|------|
| `olav log list` | 最近 24h 的操作记录 |
| `olav log errors [--hours N]` | 只看错误事件 |
| `olav log show <run-id>` | 查看某次操作的完整详情 |
| `olav log export sft\|trajectory\|atif` | 导出审计数据为训练格式 |

### 后台服务

| 命令 | 说明 |
|------|------|
| `olav service web start [--port N]` | 启动 Web 服务（默认端口 2280） |
| `olav service daemon start` | 启动 Daemon 加速服务 |
| `olav service logs start [--port N]` | 启动 Syslog 接收服务（默认端口 5514） |
| `olav service start --all` | 启动所有后台服务 |
| `olav service stop --all` | 停止所有后台服务 |
| `olav service status` | 查看服务运行状态 |

### 管理员命令

| 命令 | 说明 |
|------|------|
| `olav admin "add-user <name> --role <role>"` | 添加用户 |
| `olav admin "list-users"` | 列出所有用户 |
| `olav admin "revoke-token <name>"` | 撤销用户令牌 |
| `olav admin "rotate-token <name>"` | 轮换用户令牌 |

### Schema 演进

| 命令 | 说明 |
|------|------|
| `olav config evolve --list` | 查看待审批的 schema 演进提案 |
| `olav config evolve --approve <id>` | 审批并应用 schema 演进 |

### 其他

| 命令 | 说明 |
|------|------|
| `olav export claude-plugin` | 导出 Claude 插件工件 |
| `olav reset --agent <name>` | 重置某个 Agent 的对话历史 |

---

## 交互模式（TUI）

不带查询参数运行 `olav` 启动交互式终端：

```bash
olav                      # 使用默认 Agent
olav --agent config       # 使用指定 Agent
olav --no-splash          # 跳过启动横幅
olav --session <id>       # 恢复之前的会话
```

### 交互模式中的斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示可用命令列表 |
| `/clear` | 重置对话并清屏 |
| `/tokens` | 显示本次会话的 Token 消耗 |
| `/model <name>` | 会话内临时切换 LLM 模型（不修改配置文件） |
| `/trace-review` | 分析最近 7 天失败记录，自动提取经验教训写入记忆 |
| `/quit` `/exit` `/q` | 退出交互模式 |

### 交互模式特殊语法

| 语法 | 说明 |
|------|------|
| `@file.txt` | 将文件内容注入到当前提问中 |
| `!command` | 直接执行 Shell 命令（不经过 Agent） |

---

## 三种使用接口对比

| 接口 | 启动方式 | 适用场景 |
|------|---------|---------|
| **CLI** | `olav "查询"` | 脚本集成、一次性查询、自动化流水线 |
| **TUI** | `olav`（不带参数） | 多轮对话、探索式分析、调试 |
| **Web UI** | `olav service web start` → `http://localhost:2280` | 浏览器访问、团队共享 |
