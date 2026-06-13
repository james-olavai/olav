# Slash Command 自动注册设计

**状态**: 设计草案 v0.1  
**日期**: 2026-03-16  
**关联文档**: `olav_platform.md`, `plugin_rector.md`, `tracking.md`

---

## 1. 背景

当前 OLAV 已完成三类自动发现能力：

1. Agent / Skill 通过 `.olav/workspace/**/MANIFEST.yaml` 自动发现
2. Tool 通过 `tools/` 目录自动发现
3. 外部插件通过 Python entry points 自动发现

但 `/` 命令仍主要依赖 `src/olav/cli/commands/builtin.py` 中的函数注册表：

```python
SLASH_COMMANDS: dict[str, Callable] = {}

@register_command("help")
async def cmd_help(args: str) -> str:
    ...
```

这带来两个问题：

1. 域包命令虽然可以通过 best-effort import 挂进平台，但机制不统一
2. 之前迁移出去的 netops 脚本无法以声明式方式重新接回 `/` 命令体系

因此需要把 slash command 也纳入“声明式自动注册”体系，与 Agent / Skill / Tool 保持一致。

---

## 2. 设计目标

### 2.1 目标

1. `/` 命令支持自动注册，不再要求平台硬编码域命令
2. 支持注册 Python callable
3. 支持注册 shell 脚本，作为历史脚本兼容层
4. 支持把 `olav-netops` 的 init / snapshot / migrate / learn 类命令重新接回 `/` 命令体系
5. 不破坏平台与 netops 的解耦方向

### 2.2 非目标

1. 不把所有域 CLI 生命周期命令都改成 slash command
2. 不扫描任意脚本文件并自动暴露给用户
3. 不允许未声明元数据的 shell 脚本直接进入命令面
4. 不让 slash command 替代 `workspace status/diff/upgrade/remove/rollback`

---

## 3. 核心原则

### 3.1 声明式优先，不做裸扫描

不采用“扫描所有 `.py` / `.sh` 文件并注册”的方案。

原因：

1. 命令名冲突不可控
2. 帮助文本缺失
3. 危险脚本无法区分
4. 无法做权限、审批、超时控制

正确做法是：

- Python 包级发现使用 entry points
- workspace 控制面发现使用 `MANIFEST.yaml`
- `/` 命令本身从声明加载，而不是从文件名猜测

### 3.2 Python callable 是一等公民

优先支持：

- `package.module:function`
- async 或 sync callable
- 返回 `str` / `dict` / 可序列化结果

Shell 脚本只作为兼容层，用于接回历史脚本或外部工具包装层。

### 3.3 shell script 默认高审慎

Shell 类型命令默认要求：

1. 显式声明 `approval: required`
2. 明确 `timeout`
3. 明确 `cwd_policy`
4. 使用 argv 方式执行，不允许拼接字符串后走 `shell=True`

---

## 4. 注册模型

slash command 采用三层来源合并：

| 来源 | 用途 | 优先级建议 |
|---|---|---|
| platform builtin | 平台核心命令：`/help` `/clear` `/history` `/quit` | 最高 |
| workspace manifest | 项目本地启用的域命令 | 中 |
| Python entry point | 包安装后可用的外部命令 | 低 |

说明：

1. 平台核心命令不能被覆盖
2. workspace manifest 允许项目级覆盖已安装包的默认命令配置
3. entry point 只声明“包提供了什么”，不代表当前项目一定启用

---

## 5. MANIFEST.yaml 扩展

在现有 `MANIFEST.yaml` 中新增 `slash_commands` 字段：

```yaml
kind: Agent
name: netops
version: "0.11.0"
route_keywords:
  - troubleshoot
  - collect snapshot

slash_commands:
  - name: learn_cmd
    aliases: [learn, lc]
    kind: python
    entrypoint: olav_netops.cli.builtin:cmd_learn
    help: Learn a network command and generate a TextFSM template
    approval: none
    timeout: 300

  - name: netops_init
    kind: python
    entrypoint: olav_netops.scripts.netops_init:main
    help: Initialize netops workspace and bootstrap inventory
    approval: required
    timeout: 1800

  - name: netops_snapshot
    kind: shell
    script: olav-netops/scripts/netops_snapshot.sh
    help: Run network snapshot collection workflow
    approval: required
    timeout: 3600
    cwd_policy: project_root
```

### 5.1 字段定义

| 字段 | 必填 | 含义 |
|---|---|---|
| `name` | 是 | slash command 名称，不含 `/` |
| `aliases` | 否 | 别名数组 |
| `kind` | 是 | `python` 或 `shell` |
| `entrypoint` | Python 必填 | `pkg.mod:callable` |
| `script` | Shell 必填 | 可执行脚本路径 |
| `help` | 是 | `/help` 输出文案 |
| `approval` | 否 | `none` / `required` |
| `timeout` | 否 | 超时时间，秒 |
| `cwd_policy` | 否 | `project_root` / `workspace_dir` / `script_dir` |
| `env_allowlist` | 否 | 允许注入的环境变量列表 |

### 5.2 校验规则

1. `name` 不能与平台保留命令冲突
2. `aliases` 不能与已有命令或别名冲突
3. `kind=python` 时必须存在 `entrypoint`
4. `kind=shell` 时必须存在 `script`
5. `approval=none` 的 shell 命令仅允许显式白名单场景，默认拒绝

---

## 6. Python entry point 扩展

在现有插件发现之外，新增一个专用组：

```toml
[project.entry-points."olav.slash_commands"]
learn_cmd = "olav_netops.cli.builtin:cmd_learn"
netops_init = "olav_netops.scripts.netops_init:main"
```

### 6.1 与 MANIFEST 的关系

| 机制 | 作用 |
|---|---|
| `olav.slash_commands` | 声明包安装后“可以提供哪些 callable” |
| `MANIFEST.yaml` `slash_commands` | 声明当前项目“启用哪些 slash command、用什么元数据运行” |

两者的分工与 `olav.agents` / `MANIFEST.yaml` 的关系保持一致：

- entry point 负责包级可发现性
- manifest 负责项目级启用与配置

---

## 7. 运行时加载流程

```text
启动 CLI
  ↓
加载 platform builtin slash commands
  ↓
扫描已安装包的 olav.slash_commands entry points
  ↓
扫描 .olav/workspace/**/MANIFEST.yaml 中的 slash_commands
  ↓
执行校验、冲突处理、生成最终注册表
  ↓
/ help 与 execute_command 使用统一 registry
```

建议新增模块：

```text
src/olav/cli/commands/
├── builtin.py                # 平台核心命令
├── registry.py               # 新增：统一加载 slash command
└── shell_runner.py           # 新增：安全执行 shell 类型命令
```

### 7.1 建议 API

```python
def load_builtin_slash_commands() -> dict[str, SlashCommandSpec]:
    ...

def load_entrypoint_slash_commands() -> dict[str, SlashCommandSpec]:
    ...

def load_workspace_slash_commands(workspace_root: Path) -> dict[str, SlashCommandSpec]:
    ...

def build_slash_command_registry(workspace_root: Path) -> dict[str, SlashCommandSpec]:
    ...
```

---

## 8. 执行模型

### 8.1 Python 类型

执行逻辑：

1. import `entrypoint`
2. 若为 async callable，则 await
3. 若为 sync callable，则直接调用
4. 统一包装异常并返回可读错误信息

建议签名：

```python
async def cmd(args: str, context: SlashCommandContext) -> str:
    ...
```

其中 `SlashCommandContext` 可包含：

- `project_root`
- `workspace_root`
- `user_id`
- `approval_callback`
- `audit_recorder`
- `get_or_create_agent`

### 8.2 Shell 类型

执行逻辑：

1. 根据 `cwd_policy` 计算 cwd
2. 将 `args` 解析成 argv 数组
3. 使用 `subprocess` / `asyncio.create_subprocess_exec` 执行
4. 采集 stdout / stderr
5. 记录审计事件

禁止：

- `shell=True`
- 隐式读取未声明环境变量
- 无 timeout 的长时间阻塞执行

---

## 9. 冲突处理策略

### 9.1 保留命令

以下命令为平台保留，不允许覆盖：

- `help`
- `?`
- `clear`
- `history`
- `quit`
- `exit`

### 9.2 非保留命令冲突

建议策略：

1. 同名命令冲突时，workspace manifest 优先于 entry point
2. builtin 高于一切
3. 冲突时打印 warning，并把被覆盖项写入审计日志或启动日志

### 9.3 别名冲突

别名冲突直接拒绝注册，避免 `/help` 输出不确定。

---

## 10. 与 netops 脚本回接的关系

这个机制允许把之前迁移出去的 netops 脚本接回 slash command 体系，但不把它们重新硬编码进平台。

推荐映射：

| 旧能力 | 新 slash command |
|---|---|
| onboard / init | `/netops_init` |
| snapshot | `/netops_snapshot` |
| migrate | `/netops_migrate` |
| learn command | `/learn_cmd` |

### 10.1 为什么不建议恢复 `/onboard`

`/onboard` 过于通用，未来 K8s/ITSM/Cloud 域都会需要类似初始化动作。

因此应使用域命名空间化命名：

- `/netops_init`
- `/k8s_init`
- `/itsm_init`

如果后续要支持二级命令，可再演进为：

- `/netops init`
- `/netops snapshot`

但当前 `execute_command()` 的 parser 只支持单 token 命令名，因此 Phase 1 应优先采用单命令名方案。

---

## 11. 安全与审计要求

### 11.1 审批

- Python `kind=python` 命令可声明 `approval: none`
- Shell `kind=shell` 默认必须 `approval: required`
- 高风险命令必须走 HITL 审批

### 11.2 审计

每次 slash command 执行都应记录：

- command name
- aliases resolved
- source: builtin / entry_point / workspace_manifest
- execution kind: python / shell
- entrypoint or script path
- user_id
- args
- result status
- duration_ms

### 11.3 最小权限

manifest 中不直接写明文凭据。

shell / python 命令如需凭据，统一从：

- `.olav/config/api.json`
- `.olav/config/domains/<domain>/...`
- 环境变量引用

中解析。

---

## 12. Phase 切分

### Phase 1

1. 新增 `SlashCommandSpec` 数据结构
2. 实现 `load_workspace_slash_commands()`
3. 支持 `kind=python`
4. 把 `learn_cmd` 改成 manifest 驱动注册

### Phase 2

1. 新增 `olav.slash_commands` entry point 支持
2. 新增 `kind=shell`
3. 接回 `netops_init` / `netops_snapshot` / `netops_migrate`

### Phase 3

1. 支持 `/domain subcommand` 二级命令
2. 支持 richer help 输出
3. 支持 command-specific permission policy

---

## 13. 推荐结论

**建议采用。**

原因：

1. 与现有 Agent / Skill / Tool 自动发现机制一致
2. 可以把域命令从平台硬编码中抽出去
3. 可以把历史 netops 脚本接回用户交互层而不重新耦合平台
4. MANIFEST + entry point 双层模型可同时满足“包可发现”和“项目可启用”

**但必须避免两种错误实现：**

1. 扫描任意脚本文件后直接注册
2. 把 netops 命令重新写死回 `builtin.py`

---

## 14. 最小实现建议

若立即实施，建议最小范围如下：

1. 新增 `dev_docs` 中对应 tracking 任务
2. 在 `MANIFEST.yaml` 中引入 `slash_commands`
3. 在 `src/olav/cli/commands/registry.py` 中实现 workspace manifest 加载
4. 先接回两个命令验证机制：
   - `learn_cmd`
   - `netops_init`

只要这两项跑通，后续其它域脚本都可以复用同一机制。
