# OLAV 拆分方案：企业级 AIOps 平台 + 网络运维技能包

**状态**: 设计草案 v0.7（补充 Claude Skill 兼容层、完整生命周期、渐进式披露与控制面约束）  
**日期**: 2026-03-16

---

## 1. 愿景

将 OLAV 拆分为两个独立发布的包，实现"平台复用、领域扩展"的产品策略：

| 包 | 定位 | 典型用户 |
|:--|:--|:--|
| **`olav-platform`** | 企业级 AIOps 基础设施 | 任何需要多 Agent + 长期记忆 + 审计的团队 |
| **`olav-netops`** | 网络运维技能包 | 网络工程师，`pip install olav-netops` 即可 |

```
  olav-netops          olav-enterprise
  (BSL free, PyPI)     (BSL commercial, entry points)
        \                    /
         \                  /
          └── depends on ──┘
                    ↓
             olav-platform  (BSL free, PyPI)
               ├── LanceDB 长期记忆 + KB 引擎
               ├── DuckDB 审计 + 检查点
               ├── 语义路由 (SemanticRouter)
               ├── Agent 编排框架 (OLAVAgent)
               ├── schema_engine (字段分类引擎，标准库为空)
               ├── config-base Agent (creator/knowledge/system/discovery)
               └── audit / quick Agent
```

> **P2 三包关系**：`olav-enterprise` 与 `olav-netops` 均依赖 `olav-platform`，
> 互相不依赖。企业插件通过 `olav.plugins.*` entry points 注册，使用独立命名空间，
> 无 import 冲突。完整说明见 `ent_features.md`。

### 1.1 兼容性边界

本设计的目标是把 OLAV 重构成**自洽的平台扩展体系**，而不是把 `.olav/workspace/`
直接伪装成第三方生态标准。

**明确结论：**

- `.olav/workspace/` + `MANIFEST.yaml` 是 **OLAV 内部控制面标准**
- `.claude/skills/<name>/SKILL.md` 与 Claude plugin 目录结构是 **Claude Code / Agent Skills 生态标准**
- 两者**语义相近，但结构不直接兼容**

因此，平台层应提供**导出兼容层**，而不是声称运行时结构天然兼容。

### 1.2 设计原则补充

本轮拆分遵循以下额外原则：

1. **控制面与执行面分离**：安装、启停、升级、回滚是平台 CLI 责任，不交给 agent。
2. **平台内部标准与外部生态标准分离**：`MANIFEST.yaml` 用于 OLAV 自发现；导出器用于对接 Claude Code。
3. **渐进式披露**：常驻上下文只保留 descriptor；详细 playbook 与 reference 按需加载。
4. **共享状态只由平台拥有**：agent 不直接写共享 DuckDB/LanceDB，必须经平台控制面收口。

---

## 2. 代码归属映射

### 2.1 `src/olav/core/` — 核心层

| 模块 | 归属 | 理由 |
|:--|:--|:--|
| `config.py` | **PLATFORM** | 纯配置，需移除 TextFSM 相关属性 |
| `llm.py` | **PLATFORM** | LLM 工厂，零领域耦合 |
| `embedder.py` | **PLATFORM** | 向量化单例 |
| `database.py` | **PLATFORM** | DuckDB 连接管理 |
| `ingest_manager.py` | **PLATFORM** | Staging-First 写入，通用 |
| `memory/` | **PLATFORM** | LanceDB 长期记忆，完全通用 |
| `knowledge/` | **PLATFORM** | KB 引擎，完全通用 |
| `router.py` | **PLATFORM** | 语义路由，完全通用 |
| `audit_recorder.py` | **PLATFORM** | 审计事件记录 |
| `audit_logger.py` | **PLATFORM** | 日志写入 |
| `checkpointer.py` | **PLATFORM** | LangGraph 检查点 |
| `tool_discovery.py` | **PLATFORM** | 通用工具发现 |
| `version.py` / `watermark.py` | **PLATFORM** | 版本与水印 |
| `utils.py` / `defaults.py` | **PLATFORM** | 目录创建等通用工具 |
| `security.py` | **OVERLAP** | 通用策略检查 → PLATFORM；网络 ACL 细节 → NETOPS |
| `command_registry.py` | **NETOPS** | TextFSM 模板注册，317行，完全网络专用 |
| `calculate_diffs.py` | **NETOPS** | 网络配置 diff |
| `simulation/` | **NETOPS** | 网络仿真沙箱 |

### 2.2 `src/olav/` 其他层

| 模块 | 归属 | 理由 |
|:--|:--|:--|
| `agents/agent.py` | **PLATFORM** | `OLAVAgent` 通用编排器，无领域耦合 |
| `api/server.py` | **PLATFORM** | FastAPI HTTP 接口 |
| `plugins/` | **PLATFORM** | 插件注册机制 |
| `services/syslog_receiver.py` | **NETOPS** | UDP Syslog，偏网络基础设施 |
| `cli/main.py` | **OVERLAP** | 需参数化系统提示（移除硬编码网络描述） |
| `cli/display.py` / `banner.py` | **PLATFORM** | 通用输出 |
| `cli/admin.py` / `log_cmd.py` | **PLATFORM** | 管理与日志命令 |
| `cli/daemon.py` | **PLATFORM** | Daemon 管理 |
| `cli/commands/base.py` | **PLATFORM** | 命令基类 |
| `cli/commands/service.py` | **PLATFORM** | 服务管理 |
| `cli/commands/trace_review.py` | **PLATFORM** | Agent trace 分析 |
| `cli/commands/onboard.py` | **NETOPS** | 深度耦合网络工具，需重构 |
| `cli/commands/builtin.py` | **OVERLAP** | 网络相关命令需拆出 |

### 2.3 `.olav/workspace/` — Agent 技能包

| 目录 | 归属 | 说明 |
|:--|:--|:--|
| `olav/` | **PLATFORM** | 基础编排 Agent |
| `quick/` | **PLATFORM** | 快速查询 Agent |
| `audit/` | **PLATFORM** | 审计 Agent，行业通用 |
| `config/creator/` | **PLATFORM** | Skill 创建，通用 |
| `config/knowledge/` | **PLATFORM** | KB 管理，通用 |
| `config/system/` | **PLATFORM** | Doctor/自愈，通用 |
| `config/discovery/` | **PLATFORM（引擎代码）** / **NETOPS（标准库 bootstrap）** | 引擎代码（`schema_engine.py`）归 PLATFORM；网络字段标准向量库（bgp/ospf/interface）由 `olav-netops init` 注入 LanceDB，引擎启动时库为空则降级到 LLM-only |
| `config/sync/` | **NETOPS** | SSH 采集 + TextFSM 解析 |
| `config/learner/` | **NETOPS** | TextFSM 模板学习 |
| `ops/` | **NETOPS** | 全部：diff/probe/simulator/topology |

---

## 3. 重叠区域详细处理方案

### 3.1 `onboard.py` — 迁移为 `olav-netops` 独立二进制（设计决策）

> **决策**：域包的初始化逻辑与平台 CLI (`olav`) 无关。
> `olav onboard` / `olav netops init` 这类子命令形式要求平台在启动时发现并加载域插件，
> 制造了不必要的耦合与复杂度。正确模式是：**域包通过 `[project.scripts]` 注册自己的独立可执行文件**，
> `onboard.py` 的逻辑原封不动迁入，**无需任何过渡期别名，代码量零增加**。

**命令职责重划分：**

| 命令 | 来源 | 职责 |
|:--|:--|:--|
| `olav init` | `olav-platform` 安装后自带 | 验证 LLM 连通、创建目录结构、写入默认 `api.json`，输出 "platform ready" |
| `olav-netops init` | `olav-netops` 安装后自带 | 导入设备清单、触发 Stage1 SSH 采集、TextFSM bootstrap、生成初始拓扑 |
| `olav-<domain> init` | 第三方域包安装后自带 | 任意域包提供自己的独立 CLI 二进制（`[project.scripts]`） |

**平台层 `olav init` 实现（极简，不含网络逻辑）：**

```python
# olav-platform: cli/commands/init.py
class InitCommand(BaseCommand):
    """Platform-level init: infra check only, no domain logic."""
    async def execute(self, args: str = "") -> str:
        checks = [
            self._check_dirs(),      # 创建 .olav/ 目录结构
            self._check_llm(),       # LLM API 连通测试
            self._check_db(),        # DuckDB 初始化 + migration
            self._check_workspace(), # olav workspace status
        ]
        results = await asyncio.gather(*checks)
        return "\n".join(results)
```

**`olav-netops` 注册独立 CLI 二进制（标准 Python scripts）：**

```toml
# olav-netops/pyproject.toml
[project.scripts]
olav-netops = "olav_netops.cli:main"
```

```bash
pip install olav-netops
olav-netops init    # 完整保留原有 onboard.py 全部逻辑，Stage 1-5 不变
```

> **淘汰物**：不存在 `olav onboard` 别名；不存在 `_register_domain_commands()`；
> 平台 CLI 启动时零动态插件发现开销；平台代码永远不需要知道 `netops` 这个词。

### 3.2 `config.py` — 移除网络专用属性

将以下属性从 `PathsConfig` 移出，在 `olav-netops` 中用继承扩展：

```python
# 从 olav-platform PathsConfig 移除：
#   textfsm_templates_dir
#   backup_only_commands_file
#   blacklist_commands_file (网络黑名单)

# olav-netops: core/config_ext.py
class NetopsPathsConfig(PathsConfig):
    @property
    def textfsm_templates_dir(self) -> str:
        return self._data.get("templates_dir", ".olav/templates")

    @property
    def backup_only_commands_file(self) -> str:
        files = self._data.get("files", {})
        return files.get("backup_only_commands", ".olav/config/backup_only_commands.yaml")
```

### 3.3 `cli/main.py` — 参数化系统提示

```python
# 当前硬编码（需改为可注入）
# main.py:355
"""### Network Operations Domain
You are OLAV, a Network Operations AI Assistant..."""

# 改为：
def get_domain_prompt() -> str:
    """Extension point for domain packages."""
    try:
        from olav_netops.cli.prompt import DOMAIN_PROMPT
        return DOMAIN_PROMPT
    except ImportError:
        return "You are an AI Operations Assistant."
```

> **Reality Check (2026-03-16)**：`get_domain_prompt()` 注入点已经落地，但
> `get_system_prompt()` 后半段仍保留 `### Network Operations Domain` 的硬编码段落。
> 这意味着平台当前是“支持域覆盖”，而不是“真正无默认域假设”。要完成拆耦，必须：
>
> 1. 将网络专用能力列表完全移入 `olav-netops` 的 `DOMAIN_PROMPT`
> 2. 平台默认提示仅保留文件系统、审批、workspace 生命周期等通用能力
> 3. 不在 platform 包内保留 `Nornir`、设备快照、网络巡检等默认叙述

### 3.4 `config agent` — 一分为二

**`olav-platform` 提供 `config-base` Agent**：

```
.olav/workspace/config/
├── AGENT.md          (重写：只引用 creator/knowledge/system/discovery)
├── creator/          ✅ 通用 Skill 创建
├── knowledge/        ✅ 通用 KB 管理
├── system/           ✅ 通用 Doctor/自愈
└── discovery/        ✅ 薄工具层（→ schema_engine.py）；标准字段库为空
                         需执行 `olav-netops init` 注入网络字段向量库
```

> **P1 说明**：`discovery/` 引擎代码属于 PLATFORM。但 `field_classifications`
> LanceDB 表初始为空库（无任何标准字段向量）。网络专用字段（`bgp_peer_ip`、
> `ospf_router_id`、`interface_name` 等）由 `olav-netops init` 的 bootstrap
> 脚本生成并写入，与 PLATFORM 代码解耦。非网络域可提供自己的 bootstrap 脚本。

**`olav-netops` 追加 `config-netops` 子 Agent**：

```
.olav/workspace/config/
├── sync/             ❌ SSH + TextFSM 采集（网络专用）
└── learner/          ❌ TextFSM 模板学习（网络专用）
```

安装 `olav-netops` 时，自动将 `sync/` 和 `learner/` 注入到已有的 `config` Agent，并更新 `AGENT.md` 的 `subagents` 列表。

### 3.5 目录职责边界（新增，针对 pure skill-set 方案）

如果 `netdevops` / `olav-netops` 被收敛为**纯 skill 集**，目录边界应当明确区分
“静态控制面”与“项目运行态”：

| 目录 | 归属 | 是否可随包升级覆盖 | 应放内容 |
|:--|:--|:--|:--|
| `.olav/workspace/<domain>/` | 控制面 / 包内容 | **可以**（受 `workspace upgrade` 管理） | `MANIFEST.yaml`、`AGENT.md`、`SKILL.md`、`tools/`、`references/` |
| `.olav/config/` | 项目运行态 | **不应整体覆盖** | 平台公共配置、当前项目启用的 provider / auth / path / policy |
| `.olav/config/domains/<domain>/` | 域运行态配置 | **不应随 skill 升级静默覆盖** | Nornir、TextFSM、自定义命令白名单、域 API endpoint、凭据引用 |
| `.olav/databases/` | 平台共享运行态 | **否** | `domain.duckdb`、`audit.duckdb`、LanceDB、cache 索引 |
| `.olav/logs/` | 平台共享运行态 | **否** | 审计日志、服务日志、trace |
| `.olav/run/` | 平台共享运行态 | **否** | pid / lock / socket / ephemeral state |
| `.olav/knowledge/` | 平台共享运行态 | **否** | 已导入知识库与向量化产物 |

**结论**：不应把 `.olav/config` 整体下沉到各个 skill 目录。原因是它属于当前项目的
运行态配置，而不是 skill 包的静态定义。正确做法是把**域专用配置**下沉到
`.olav/config/domains/<domain>/`，而不是下沉到 `.olav/workspace/<domain>/`。

**直接后果：**

- `workspace` 目录可以安全地做 `status/diff/upgrade/remove/rollback`
- 用户本地修改过的运行配置不会在 skill 升级时被覆盖
- `databases/logs/run/knowledge` 继续作为平台根级共享状态，不与某个 skill 绑定

---

## 4. `pyproject.toml` 依赖拆分

### `olav-platform` 依赖

```toml
[project]
name = "olav-platform"
dependencies = [
    # LLM & Agents
    "langchain>=0.1.0", "langchain-openai", "langchain-ollama",
    "langchain-core", "langchain-community",
    "langgraph>=1.0.8", "langgraph-checkpoint-duckdb",
    "deepagents", "deepagents-cli",
    # Database
    "duckdb>=0.8.0", "duckdb-engine", "sqlalchemy",
    "lancedb>=0.29.2",
    # Embedding & Search
    "sentence-transformers>=5.2.3",
    "scipy", "scikit-learn", "numpy", "pandas",
    # API & Storage
    "fastapi", "uvicorn[standard]", "httpx", "requests",
    # CLI
    "rich", "prompt-toolkit", "typer",
    # Utilities
    "pydantic>=2.0", "pyyaml", "python-frontmatter",
    "python-dateutil", "tenacity", "nest-asyncio",
]
```

### `olav-netops` 依赖

```toml
[project]
name = "olav-netops"
dependencies = [
    "olav-platform>=0.11",
    # Network Tools
    "nornir>=3.3.0", "nornir-netmiko",
    "netutils>=1.17.1",
    "networkx>=3.6.1",
    # Document Processing (network KB)
    "PyPDF2>=3.0.0", "pdfplumber",
    # Syslog
    # (syslog_receiver.py 移入此包)
]
```

---

## 5. Workspace 分发机制设计

`.olav/workspace/` 的 Markdown + Python 工具不走 pip 标准路径，需要安装后钩子：

### 方案 A：`hatch` 自定义钩子（推荐）

```python
# olav-platform/hatch_hooks.py
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

class AgentwokInstallHook(BuildHookInterface):
    def install(self):
        """安装后将 workspace/ 复制到用户项目目录。"""
        import shutil
        src = Path(__file__).parent / "workspace_data"
        dst = Path.cwd() / ".olav" / "workspace"
        # 幂等：仅复制不存在的子目录
        for subdir in src.iterdir():
            target = dst / subdir.name
            if not target.exists():
                shutil.copytree(subdir, target)
```

### 方案 B：`olav init` CLI 命令（更显式）

```bash
# 安装后手动初始化
pip install olav-platform
olav init                    # 将 workspace 数据复制到当前项目 .olav/

pip install olav-netops
olav-netops init             # 追加网络专用 workspace
```

**推荐方案 B**：用户对 workspace 的修改是有意识的，不应被包更新覆盖，显式命令更安全。

### 5.1 Workspace 版本冲突策略（P3）

`olav init` / `olav-netops init` 执行时，每个 workspace 子目录写入 `.version` 文件，
后续升级通过版本比对 + 显式确认，**永远不静默覆盖**：

```
安装时：  复制 workspace，写入 .version = "0.11.0"
升级时：  检查 .version
           ├─ 版本一致 → 跳过
           ├─ 版本不一致 → 提示 diff，不自动覆盖
           └─ 版本文件不存在 → 视为用户完全自定义，跳过
```

**配套命令集：**
```bash
olav workspace status    # 列出每个子目录的包版本 vs 本地版本
olav workspace diff      # 显示新版本 vs 本地修改的 unified diff
olav workspace upgrade   # 选择性升级（逐目录确认，保留用户自定义子目录）
```

**规则**：`olav workspace upgrade` 只操作 `.version` 标记为「包管理」的子目录，
用户在 onboard 后手动创建的目录永远不触碰。

### 5.2 生命周期闭环（补齐 install-only 缺口）

当前 `init/status/diff/upgrade` 只能覆盖“安装与升级”，还不足以支撑平台化运维。
平台层必须补齐完整生命周期：

```bash
olav workspace status     # 查看当前已安装域、版本、来源、覆盖状态
olav workspace diff       # 比较包版本与本地版本差异
olav workspace upgrade    # 升级包管理子目录
olav workspace disable    # 禁用某个域或某个 agent/skill，不删除文件
olav workspace remove     # 移除某个包管理子目录及其 MANIFEST 注册
olav workspace prune      # 清理失效 MANIFEST / 孤儿目录 / 已卸载域残留
olav workspace rollback   # 回滚到指定已归档版本
```

**约束：**

- `disable` 是逻辑下线，保留文件，适合灰度与排障
- `remove` 只删除带 `.version` 且来源可追踪的包管理目录
- `prune` 只清理已失效注册，不碰用户自建目录
- `rollback` 必须基于显式归档快照，不做“猜测性恢复”

### 5.3 安装职责归属

**不引入 `install-skill` agent。**

理由很直接：skill / agent / workspace 的安装是确定性的文件分发、注册与校验动作，
属于平台控制面，不应交给带语言模型不确定性的 agent。正确分工是：

- agent 负责生成或建议改动
- CLI 负责 `init/enable/disable/remove/rollback`
- `workspace status` 负责验证注册状态

### 5.4 残余耦合清单（2026-03-16 Reality Check）

以下问题说明“平台与 netops 尚未完全解耦”，只能视为 Phase 0 已完成：

1. `src/olav/cli/main.py` 仍含 `Network Operations Domain` 默认系统提示。
2. `src/olav/cli/commands/builtin.py` 仍内置 `/learn_cmd` 与 TextFSM 工作流。
3. `src/olav/core/defaults.py` 仍保留 `DEFAULT_NETWORK_CONFIG`。
4. `src/olav/core/config.py` 仍暴露 `templates_dir` 这类网络模板路径默认值。
5. `src/olav/core/database.py` 仍使用 `NETWORK_DB_PATH` legacy alias。
6. `src/olav/core/ingest_manager.py` 默认 staging 目录仍指向 `exports/snapshots/json/`。
7. `.olav/config/` 当前仍混放平台公共配置与 netops 运行态配置（如 `nornir/`、黑白名单）。

因此后续评估应区分：

- **已完成**：包依赖、workspace 注册、MANIFEST 发现、CLI 生命周期骨架
- **未完成**：平台默认语义净化、内置命令拆分、配置命名空间化、运行目录净化

---

## 6. 声明式 Agent / Subagent 注册机制

> **动机**：当前每次添加新 Agent 或 Skill 都需要手动编辑 `AGENT.md` 的 `subagents:` 列表，
> 且没有机器可读的注册表，平台无法在运行时动态发现新域包带来的能力。

### 6.1 现有痛点

```yaml
# 当前 AGENT.md 中的 subagents（手动维护，脆弱）
subagents:
  - name: sync
    path: config/sync
  - name: learner
    path: config/learner
  # 安装 olav-netops 后需要手动追加 ↑
```

### 6.2 设计：MANIFEST.yaml 声明 + 运行时发现

每个域包在 workspace 子目录写入 `MANIFEST.yaml`，平台在 `OLAVAgent` 初始化时自动合并：

```yaml
# .olav/workspace/config/sync/MANIFEST.yaml  (olav-netops 安装时写入)
kind: Skill
name: sync
version: "0.11.0"
agent: config          # 注册到哪个 agent
route_keywords:        # SemanticRouter 自动注入
  - collect devices
  - take snapshot
  - sync network
requires:
  - olav-netops>=0.11
```

```yaml
# .olav/workspace/ops/MANIFEST.yaml  (olav-netops 安装时写入)
kind: Agent
name: ops
version: "0.11.0"
route_keywords:
  - troubleshoot
  - probe
  - diff config
tools_dir: tools/
requires:
  - olav-netops>=0.11
```

### 6.3 平台发现逻辑（`src/olav/core/agent_registry.py`）

```python
def discover_agents(workspace_root: Path) -> dict[str, AgentManifest]:
    """扫描所有 MANIFEST.yaml，返回 {name: manifest} 字典。"""
    manifests = {}
    for manifest_path in workspace_root.rglob("MANIFEST.yaml"):
        m = AgentManifest.from_yaml(manifest_path)
        manifests[m.name] = m
    return manifests

def build_router(manifests: dict) -> SemanticRouter:
    """从所有 manifest 的 route_keywords 自动构建 SemanticRouter。"""
    routes = [
        Route(name=name, utterances=m.route_keywords)
        for name, m in manifests.items()
    ]
    return SemanticRouter(routes=routes, encoder=get_embedder())
```

### 6.4 Entry Points 与 MANIFEST.yaml 的关系

| 机制 | 用途 | 触发时机 |
|:--|:--|:--|
| `olav.agents` entry points | Python 包级别声明（无 workspace） | `pip install` 后代码可 import |
| `MANIFEST.yaml` | Workspace 文件级别声明（AI 可读） | `olav-<domain> init` 后 |

两者互补：entry points 控制 Python 代码加载，MANIFEST.yaml 控制 Agent 路由注册。
域包安装时 `<domain> init` 同时写 MANIFEST.yaml，两者保持同步。

### 6.6 Claude Code / Agent Skills 兼容层

> **结论先行**：新平台**不能直接兼容** Claude Code skill 标准，
> 但可以通过显式导出层做到**一键导出兼容**。

Claude Code skill 标准以以下结构为核心：

```text
.claude/skills/<skill-name>/SKILL.md
.claude/agents/<agent-name>.md
<plugin-root>/skills/<skill-name>/SKILL.md
<plugin-root>/agents/<agent-name>.md
```

而 OLAV 的内部结构是：

```text
.olav/workspace/<domain>/
    MANIFEST.yaml
    AGENT.md
    SKILL.md
    tools/
```

因此需要一个**导出器**：

```bash
olav export claude-skills --domain itsm
olav export claude-plugin --domain itsm --output ./dist/olav-itsm-plugin
```

**导出映射规则：**

- `MANIFEST.yaml` → Claude 不消费；仅作为导出器输入
- `SKILL.md` → `.claude/skills/<name>/SKILL.md` 或 plugin `skills/<name>/SKILL.md`
- `AGENT.md` → `.claude/agents/<name>.md` 或 plugin `agents/<name>.md`
- `tools/` 中可执行脚本 → 导出为 skill supporting files / plugin scripts
- 路由关键词、权限级别、只读/写入标签 → 映射到 Claude frontmatter

**平台承诺：**

- 对内：继续使用 `.olav/workspace/` + `MANIFEST.yaml`
- 对外：通过 export 层兼容 Agent Skills / Claude plugin 目录标准
- 不把内部注册机制泄漏为外部标准

### 6.5 新 Agent / Skill 插入流程（最终态）

```bash
# 安装第三方域包
pip install olav-k8sops

# 初始化（写 MANIFEST.yaml + workspace 文件）
olav-k8sops init

# 验证注册
olav workspace status
# 输出：
# config/sync      ✅ v0.11.0  (olav-netops)
# ops              ✅ v0.11.0  (olav-netops)
# k8s/inspect      ✅ v1.0.0   (olav-k8sops)   ← 自动发现
```

---

## 7. Config Agent 升格：自动发现 OpenAPI → 生成 Domain Agent

> **动机**：`config/discovery/` 目前仅做字段分类（api_discovery.md）。
> 将其升格为**域 Onboarding Agent**：给定一个 OpenAPI 规范，自动产出可运行的 Domain Agent、
> 其注册元数据，以及可选的 Claude skill / plugin 导出物。

### 7.1 新能力：`scaffold_domain_agent` 工具

```
用户输入
  "接入我们的 ITSM 系统，URL: https://internal/api/openapi.json"
       ↓
config-orchestrator → discovery 子 Agent
       ↓
① register_api_schema(url)          — 拉取 OpenAPI spec，字段分类
② scaffold_domain_agent(spec, name) — 生成 workspace 文件 (NEW)
②b export_claude_plugin(name)       — 可选：导出 Claude Code 兼容插件
③ olav workspace status             — 验证注册
```

### 7.2 `scaffold_domain_agent` 生成物

给定 OpenAPI spec + 域名（如 `itsm`），生成：

```
.olav/workspace/itsm/
├── MANIFEST.yaml           ← 路由注册（route_keywords 从 API tags 推断）
├── AGENT.md                ← LLM-readable agent 描述（从 info.description 生成）
├── SKILL.md                ← 技能清单（从 paths 推断操作语义）
└── tools/
    ├── query_itsm.py       ← 通用 REST 调用封装（GET /incidents → query_incidents）
    └── mutate_itsm.py      ← 写操作封装（POST/PUT/PATCH，仅当 role=user/admin）

# 可选导出
dist/claude-plugin-itsm/
├── .claude-plugin/plugin.json
├── skills/
│   └── itsm-query/
│       └── SKILL.md
└── agents/
    └── itsm-operator.md
```

### 7.3 与 quick / ops Agent 的集成

生成的 agent 根据 OpenAPI spec 的操作性质自动注册：

| API 操作类型 | 注册到 | 理由 |
|:--|:--|:--|
| 只读 GET（查询聚合数据） | `quick` Agent subagents | 低延迟查询场景 |
| 混合 GET+POST（业务操作） | `ops` Agent subagents | 复杂工作流场景 |
| 纯写入 POST/PATCH/DELETE | `ops` Agent（需 `user` role） | 修改需权限门控 |

### 7.4 安全约束

- 写操作工具自动添加 `@require_role("user")` 装饰器（来自 auth 层）
- 生成代码仅调用 `httpx.AsyncClient`，**不执行 eval / exec**
- API key / Bearer token 从 `api.json` 读取，**不硬编码**
- 生成前展示 diff，用户确认后再写入（`olav workspace upgrade` 同款流程）

### 7.5 局限与边界

- 生成物是**起点**，不保证 100% 可用，复杂业务逻辑仍需人工微调
- Phase 1 仅支持 OpenAPI 3.x REST（GraphQL / gRPC 后续）
- 对高度定制化系统，产出作为模板参考，而非直接部署

### 7.6 渐进式披露约束

`scaffold_domain_agent` 生成物必须遵守“descriptor / playbook / reference”三层拆分：

1. **Descriptor**：`MANIFEST.yaml`，只保留名称、用途、route keywords、权限等级、版本、来源。
2. **Playbook**：`AGENT.md` / `SKILL.md`，只保留执行骨架，不塞入大段参考资料。
3. **Reference**：OpenAPI 规范、示例 payload、认证说明、脚本，放到 supporting files，按需读取。

这条规则是强约束，不是建议。否则 discovery 会继续膨胀成单体 control-plane agent。

### 7.7 写入边界

`config/discovery` 可以提出 schema mutation request，但不直接执行共享存储写入。
真正的写入统一经：

- `SchemaMutationService`
- `IngestManager`
- 或平台级 migration / staging pipeline

这样才能和 AGENTS.md 的 “NO Direct DB Writes” 保持一致。

---

## 8. 实施路线图

```
阶段零（准备）— 在现有单仓库内，无破坏性改动
┌─────────────────────────────────────────────────────────────┐
│ 1. core/config.py: 为网络属性加 # NETOPS-ONLY 注释         │
│ 2. cli/main.py: 将系统提示提取为 get_domain_prompt() 函数  │
│ 3. cli/commands/builtin.py: 网络命令移至 builtin_netops.py │
│ 4. cli/commands/init.py: 新建平台级 InitCommand            │
│ 5. workspace/*/MANIFEST.yaml: 现有 Agent 补写声明文件       │
│ 6. core/agent_registry.py: MANIFEST 发现 + 路由自动构建    │
│ 7. 定义 SchemaMutationService，收口 schema 相关写入路径    │
│    估时: 3天                                                │
└─────────────────────────────────────────────────────────────┘
            ↓
阶段一（结构分离）— 创建两个仓库
┌─────────────────────────────────────────────────────────────┐
│ 1. 从现有仓库提取 PLATFORM 文件 → olav-platform 仓库       │
│ 2. 建立 olav-netops 仓库，depends on olav-platform         │
│ 3. 移动 NETOPS 文件到 olav-netops                          │
│ 4. 配置 workspace 分发（olav init 命令）                   │
│    估时: 1周                                                │
└─────────────────────────────────────────────────────────────┘
            ↓
阶段二（接口化）— 稳定扩展点 API
┌─────────────────────────────────────────────────────────────┐
│ 1. 定义 olav.ingest_tables / olav.agents entry point 机制  │
│ 2. config agent 拆分为 config-base + config-netops         │
│ 3. 增加 `olav export claude-skills/plugin` 兼容层          │
│ 4. 发布 olav-platform v0.12 RC                             │
│    估时: 1周                                                │
└─────────────────────────────────────────────────────────────┘
            ↓
阶段三（正式发布）
┌─────────────────────────────────────────────────────────────┐
│ 1. olav-platform → PyPI                                    │
│ 2. olav-netops → PyPI                                     │
│ 3. 文档更新（README 分别维护）                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. 风险与缓解

| 风险 | 严重性 | 缓解措施 |
|:--|:--|:--|
| `OLAVAgent.olav_base_path=".olav"` 硬编码，域包无法自定义 workspace 路径 | 高 | 阶段零改为可配置参数，支持 `~/.olav/workspace` 全局路径 |
| `onboard.py` 全部逻辑平移至 `olav-netops` CLI 独立二进制 | 无（设计消解） | 独立二进制与平台零耦合，无过渡期别名，无额外代码 |
| Workspace 文件被包更新覆盖，用户自定义丢失 | 高 | 采用方案 B（显式 `olav init`），永远不自动覆盖 |
| 内部 `MANIFEST.yaml` 被误认为 Claude 标准，导致外部生态对接失败 | 高 | 明确导出兼容层，不宣称运行时结构直接兼容 |
| 生命周期缺少 disable/remove/rollback，长期运行后残留脏注册 | 高 | 补齐 workspace 生命周期命令并引入归档回滚 |
| 两个仓库的版本兼容矩阵维护 | 中 | 语义化版本 + CI 矩阵测试（`olav-netops` 每次发布测试所有支持的 `olav-platform` 版本） |
| `discovery/` 子 Agent 升级为通用引擎后，现有网络测试失效 | 低 | 网络 schema 分类作为 `discovery` 的一个 profile，向下兼容 |

---

## 10. 现有代码支持程度总结

> **约 65% 代码可直接切分，35% 需要迁移或重构。**

- ✅ **零成本切分**：`core/memory/`、`core/knowledge/`、`core/router.py`、`agents/agent.py` — 完全无领域耦合
- ⚠️ **小手术**：`core/config.py`（移除 3 个属性）、`cli/main.py`（参数化提示）
- 🔧 **中等重构**：`cli/commands/onboard.py`（基类+继承模式）
- 🔧 **新增兼容层**：Claude skill / plugin export，不改变内部控制面结构
- ❌ **直接迁移**：`core/command_registry.py`、`core/simulation/`、`workspace/ops/`、`workspace/config/sync/learner/`

### 10.1 2026-03-17 三仓库发布目标（Gitea）

| 仓库 | 目标远端 | 首次承载内容 |
|:--|:--|:--|
| `olav-core` | `http://192.168.100.50:3000/admin/olav-core.git` | 平台根仓：`src/olav/`（去掉 `enterprise/`）、`AGENTS.md`、`dev_docs/olav_*.md`、`docs/olav/`、平台级 `.olav/workspace/{olav,quick,audit,config/{creator,discovery,knowledge,system}}` |
| `olav-netops` | `http://192.168.100.50:3000/admin/olav-netops.git` | 当前 `olav-netops/` 包内容 + netops workspace 资产：`.olav/workspace/ops`、`.olav/workspace/config/sync`、`.olav/workspace/config/learner`、`docs/netops/` |
| `olav-ent` | `http://192.168.100.50:3000/admin/olav-ent.git` | `src/olav/enterprise/`、企业加密/导出相关文档、未来 `pyproject.toml` 与 entry-point / adapter 层 |

### 10.2 首次迁移顺序

1. **先发 `olav-core`**：先消除 core 对 enterprise 的直接 import 和强依赖。
2. **再发 `olav-netops`**：现有 `olav-netops/` 已具备 package 骨架，下一步是把 monorepo 根下的 netops workspace 资产迁过去。
3. **最后发 `olav-ent`**：待 core 完成 optional bridge 后，再把 `src/olav/enterprise/` 拆成独立私有包。

### 10.3 当前阻塞点（必须先处理）

| 编号 | 阻塞点 | 影响 |
|:--|:--|:--|
| CORE-B1 | `src/olav/cli/main.py` 仍直接 `from olav.enterprise... import ...` | `olav-core` 在没有 enterprise 源码时无法运行 |
| CORE-B2 | 主 `pyproject.toml` 仍包含 `tink` / `PyJWT` | `olav-core` 不能独立发布为“无企业依赖”平台包 |
| NETOPS-B1 | `.olav/workspace/ops`、`config/sync`、`config/learner` 仍在 monorepo 根 | `olav-netops` 仍不是自洽的源码/控制面分发单元 |
| ENT-B1 | `olav-ent` 还没有独立包元数据与发布入口 | 无法推送到私有 Gitea 后直接安装使用 |

### 10.4 目录迁移清单（首版）

```text
olav-core
├── src/olav/{agents,api,cli,core,platform,plugins}
├── docs/olav/**
├── .olav/workspace/olav
├── .olav/workspace/quick
├── .olav/workspace/audit
└── .olav/workspace/config/{creator,discovery,knowledge,system}

olav-netops
├── olav-netops/src/olav_netops/**
├── olav-netops/scripts/**
├── docs/netops/**
├── .olav/workspace/ops/**
└── .olav/workspace/config/{sync,learner}/**

olav-ent
└── src/olav/enterprise/**
```

> 注意：`.olav/config/`、`.olav/databases/`、`.olav/logs/`、`.olav/run/` 继续是项目运行态，
> 不作为任何一个源码仓库的静态内容整体迁移。
> `docs/{01_README.md,cn/}` 保留为平台总 hub，分别指向三个独立仓库文档。

---

## 11. Domain Extension Contract（域扩展公开契约）

> **这是让「平台」名副其实的核心层。** 前 10 节描述了文件如何分、代码如何归属；
> 本节定义第三方开发者实际要 `import` 什么、能依赖什么稳定接口。
> 没有这层，分包只是「重构」，不是「平台」。

### 11.1 当前的隐患：无公开契约层

```python
# 域包开发者现在只能这样写（内部模块，unstable）：
from olav.agents.agent import OLAVAgent          # ← 内部实现
from olav.core.ingest_manager import IngestManager  # ← 网络专用表结构
from olav.core.llm import LLMFactory             # ← 内部模块
```

任何内部重构都会无声地 breaking 域包。

### 11.2 新增 `src/olav/platform/` 公开模块

```
src/olav/platform/
├── __init__.py          ← 所有公开 API 的统一入口
├── extensions.py        ← Protocol 定义（域包实现的接口）
├── agent_base.py        ← BaseDomainAgent（可选继承）
├── ingest_base.py       ← BaseIngestTable（域包注册自己的 DuckDB 表）
└── table_registry.py   ← TableRegistry 单例（统一管理所有域表）
```

**`src/olav/platform/__init__.py` 导出：**

```python
# 域包唯一需要 import 的命名空间
from olav.platform.extensions import (
    DomainAgent,        # Protocol — 域包 Agent 必须实现的接口
    BaseIngestTable,    # 抽象基类 — 注册自定义 DuckDB 表
)
from olav.platform.table_registry import TableRegistry  # 表注册单例
from olav.platform.agent_base import BaseDomainAgent    # 可选继承
```

### 11.3 域 CLI — 独立二进制模式（G4 消解）

> **G4 重新定价**：「CLI 子命令硬编码」这个问题本身就不该存在。
> 把域包命令塞进平台 CLI 才是制造耦合；正确答案是**域包通过 `[project.scripts]` 注册自己的独立可执行文件**，
> 平台 CLI 保持零体积、零发现开销、零耦合。

**域包注册独立二进制（标准 Python scripts）：**

```toml
# olav-netops/pyproject.toml
[project.scripts]
olav-netops = "olav_netops.cli:main"

# olav-k8sops/pyproject.toml
[project.scripts]
olav-k8sops = "olav_k8sops.cli:main"
```

**平台 `cli/main.py` 不变（无任何域插件发现代码）：**

```python
# cli/main.py — 保持原样，无需任何修改
# 已不存在: _register_domain_commands(), olav.cli_commands entry point group
```

**淘汰物清单（对比旧 G4 解法）：**

- ~~`src/olav/platform/cli_plugin.py`~~ — 文件不创建
- ~~`CLICommandPlugin` Protocol~~ — 类不存在
- ~~`olav.cli_commands` entry point group~~ — 不需要
- ~~`_register_domain_commands(subparsers)`~~ — 函数不存在
- ~~`olav onboard` 别名~~ — 彻底不需要，干净过渡

**用户体验对比：**

```bash
# 安装即用，与 pip install 标准体验完全一致
pip install olav-platform && olav init          # 平台初始化
pip install olav-netops  && olav-netops init    # 网络域初始化
pip install olav-k8sops  && olav-k8sops init    # K8s 域初始化
```

### 11.4 BaseIngestTable — 通用 DuckDB 表注册

解决 G2：`IngestManager` / `parsed_outputs` 绑定网络专用列的问题。

```python
# src/olav/platform/ingest_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ColumnDef:
    name: str
    type: str          # DuckDB 类型字符串，如 "VARCHAR", "JSON", "TIMESTAMP"
    nullable: bool = True

class BaseIngestTable(ABC):
    """域包注册自定义 DuckDB 表的基类。

    平台 IngestManager 在 bulk_load() 前调用所有已注册表的 ensure_schema()。
    """
    @property
    @abstractmethod
    def table_name(self) -> str: ...

    @property
    @abstractmethod
    def columns(self) -> list[ColumnDef]: ...

    @property
    def conflict_key(self) -> list[str]:
        """ON CONFLICT 的主键列，默认空（无 upsert）。"""
        return []

    def ensure_schema(self, conn) -> None:
        """幂等建表，不存在则创建，已存在则跳过（不改列）。"""
        cols_sql = ",\n  ".join(
            f"{c.name} {c.type}{'' if c.nullable else ' NOT NULL'}"
            for c in self.columns
        )
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
              {cols_sql}
            )
        """)
```

**网络域注册示例：**

```python
# olav-netops: core/tables.py
from olav.platform.ingest_base import BaseIngestTable, ColumnDef

class ParsedOutputsTable(BaseIngestTable):
    table_name = "parsed_outputs"
    columns = [
        ColumnDef("device_name",  "VARCHAR",   nullable=False),
        ColumnDef("command",      "VARCHAR",   nullable=False),
        ColumnDef("parsed_data",  "JSON"),
        ColumnDef("snapshot_id",  "VARCHAR"),
        ColumnDef("raw_output",   "TEXT"),
        ColumnDef("ingested_at",  "TIMESTAMP"),
    ]
    conflict_key = ["device_name", "command", "snapshot_id"]
```

**K8s 域注册示例（无需改平台代码）：**

```python
# olav-k8sops: core/tables.py
class PodMetricsTable(BaseIngestTable):
    table_name = "pod_metrics"
    columns = [
        ColumnDef("namespace",   "VARCHAR", nullable=False),
        ColumnDef("pod_name",    "VARCHAR", nullable=False),
        ColumnDef("metrics_data","JSON"),
        ColumnDef("collected_at","TIMESTAMP"),
    ]
    conflict_key = ["namespace", "pod_name", "collected_at"]
```

**`TableRegistry` 单例（平台层）：**

```python
# src/olav/platform/table_registry.py
class TableRegistry:
    _tables: dict[str, BaseIngestTable] = {}

    @classmethod
    def register(cls, table: BaseIngestTable) -> None:
        cls._tables[table.table_name] = table

    @classmethod
    def ensure_all_schemas(cls, conn) -> None:
        for table in cls._tables.values():
            table.ensure_schema(conn)
```

域包通过 entry points 自动注册：

```toml
# olav-netops/pyproject.toml
[project.entry-points."olav.ingest_tables"]
parsed_outputs = "olav_netops.core.tables:ParsedOutputsTable"
```

### 11.5 MANIFEST.yaml → OLAVAgent 接线（解决 G3）

`OLAVAgent.__init__` 在读完 `AGENT.md` 之后，新增 `_load_manifests()` 调用：

```python
# src/olav/agents/agent.py — OLAVAgent.__init__ 末尾追加
from olav.core.agent_registry import discover_agents, merge_into_config

# 在 _build_subagents() 之前：
manifest_additions = discover_agents(self.olav_base_path / "workspace")
olav_config = merge_into_config(olav_config, manifest_additions, self.agent_id)
# 此后 _build_subagents(olav_config) 已含 MANIFEST 注入的 subagents
```

`merge_into_config` 规则：AGENT.md 显式声明的 subagents 优先；MANIFEST 追加不覆盖；
同名 MANIFEST 后写的覆盖先写的（由 `olav-<domain> init` 顺序决定）。

### 11.6 `quick` Agent 兼容 subagent 注入（解决结构性隐患）

`quick` 当前 `subagents: []`，SKILL.md 直接加载工具。需改为：

```yaml
# .olav/workspace/quick/AGENT.md
subagents: []    # 平台默认空；MANIFEST 可追加只读域 Agent
static_context:
  - path: ./references/SCHEMA_REFERENCE.md
```

`scaffold_domain_agent` 对只读 API 生成的 MANIFEST 写 `agent: quick`；
混合/写入 API 写 `agent: ops`。`OLAVAgent._build_subagents()` 已通用，不需要改。

### 11.7 公开契约稳定性承诺

```
src/olav/platform/   ← Stable Public API，遵循 SemVer，minor 版本向下兼容
src/olav/core/       ← Internal，随时可改，域包不应直接 import
src/olav/agents/     ← Internal
.olav/workspace/     ← User-owned，包版本仅建议，不强制
```

**版本策略**：
- `olav-platform` 0.x → API 可变（当前阶段）
- `olav-platform` 1.0 → `src/olav/platform/` 冻结为稳定 API
- 内部 `src/olav/core/` 变动不触发 major bump

### 11.8 域包开发者完整流程（最终态）

```bash
# 1. 安装平台
pip install olav-platform

# 2. 开发域包
mkdir olav-k8sops && cd olav-k8sops
# pyproject.toml 声明 entry points（olav.ingest_tables）+ [project.scripts]
# src/olav_k8sops/: 实现 BaseIngestTable
# workspace_data/k8s/: MANIFEST.yaml + AGENT.md + tools/

# 3. 安装
pip install -e .
olav-k8sops init   # ← 独立二进制，写 MANIFEST.yaml + workspace 文件

# 4. 验证
olav workspace status
# k8s/inspect  ✅ v1.0.0  (olav-k8sops)

# 5. 使用
olav "show all pods in production with OOMKilled events"
# → SemanticRouter → k8s/inspect agent → query pod_metrics table
```

---

## 12. 数据库通用化设计

> **背景**：当前三个数据库（DuckDB `main.duckdb`、LanceDB、`audit.duckdb`）的表结构和命名
> 均为网络运维场景设计。本节解决：
> 1. 这三个数据库本身是否需要重新设计才能通用？
> 2. 不同 OpenAPI 集成的数据应共享一个 DuckDB 文件，还是每个用独立文件？

### 12.1 三个数据库的通用程度评估

| 数据库 | 当前状态 | 通用化成本 |
|:--|:--|:--|
| `audit.duckdb` | ✅ 已通用 | 零——记录用户操作事件，与域无关 |
| `users.duckdb` | ✅ 已通用 | 零——auth 用户/token 表，纯平台层 |
| `main.duckdb` | ❌ 网络专用 | 中——文件本身无状态，但默认表（`parsed_outputs`、`devices`、`topology_links`）是网络专用列；**重构方向：DuckDB Schema 隔离** |
| LanceDB collections | ⚠️ 混合 | 低——引擎代码通用；`field_classifications` 集合名未体现域归属；**重构方向：`{domain}_` 前缀命名约定** |

结论：**文件数量不变，重构文件内部的组织方式**。

### 12.2 核心决策：一个 DuckDB 文件 + 多 Schema（不用多文件）

#### 方案对比

| 方案 | 描述 | 关键代价 |
|:--|:--|:--|
| **A：多文件**（每域一个 `.duckdb`） | `netops.duckdb`、`k8sops.duckdb`、`itsm.duckdb` | 跨域查询必须用 `ATTACH`，连接管理复杂；`IngestManager` 需要知道写哪个文件 |
| **B：单文件 + DuckDB Schema**（✅ 推荐） | 一个 `domain.duckdb`，内部 `CREATE SCHEMA netops / k8sops / itsm` | 零额外连接；跨域 JOIN 原生支持；逻辑隔离充分 |

**选择 B 的核心理由**：DuckDB 本质是 OLAP 引擎，其价值在于跨表 JOIN 做分析。
把域数据拆到多个文件等于主动放弃这个能力。Schema 级别的隔离已足够：

```sql
-- 这种跨域分析查询在单文件中是自然的，多文件需要 ATTACH+复杂路径
SELECT d.hostname, k.pod_name, k.status
FROM netops.devices d
JOIN k8sops.pod_metrics k ON d.management_ip = k.node_ip
WHERE k.status = 'OOMKilled';
```

#### 文件规划（最终态）

```
.olav/databases/
├── audit.duckdb        ← PLATFORM — 只增不改的审计日志；独立文件是因为需要不同保护策略
├── users.duckdb        ← PLATFORM — auth 用户/token；独立文件是因为需要最小权限访问
└── domain.duckdb       ← ALL DOMAINS — 所有域数据；内部用 Schema 隔离
    ├── SCHEMA platform   (agent_traces, workspace_versions)
    ├── SCHEMA netops     (parsed_outputs, devices, topology_links, …)
    ├── SCHEMA k8sops     (pod_metrics, deployments, …)
    └── SCHEMA itsm       (incidents, changes, …)   ← scaffold_domain_agent 生成
```

> **为什么 `audit` 和 `users` 仍然独立文件**（不进 `domain.duckdb`）：
> - `audit.duckdb`：需要不同的备份策略（append-only，链式哈希校验），可能被异地存储
> - `users.duckdb`：auth 数据应有最小权限原则，不应与业务数据同文件

### 12.3 `BaseIngestTable` 补充 `schema_name`（§11.4 补丁）

```python
# src/olav/platform/ingest_base.py — 在 BaseIngestTable 中新增

class BaseIngestTable(ABC):
    @property
    def schema_name(self) -> str:
        """域包声明自己的 DuckDB Schema 名称，默认 'main'（向下兼容）。"""
        return "main"

    @property
    def qualified_name(self) -> str:
        """完整限定表名：schema.table_name。"""
        return f"{self.schema_name}.{self.table_name}"

    def ensure_schema(self, conn) -> None:
        """幂等建 Schema + 建表。"""
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}")
        cols_sql = ",\n  ".join(
            f"{c.name} {c.type}{'' if c.nullable else ' NOT NULL'}"
            for c in self.columns
        )
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (
              {cols_sql}
            )
        """)
```

**域包声明各自的 Schema：**

```python
# olav-netops: core/tables.py
class ParsedOutputsTable(BaseIngestTable):
    schema_name = "netops"          # ← 新增
    table_name = "parsed_outputs"
    columns = [...]

# olav-k8sops: core/tables.py
class PodMetricsTable(BaseIngestTable):
    schema_name = "k8sops"          # ← 不同域，不同 Schema
    table_name = "pod_metrics"
    columns = [...]

# scaffold_domain_agent 生成的 ITSM
class IncidentsTable(BaseIngestTable):
    schema_name = "itsm"            # ← 从 OpenAPI spec info.title 推断
    table_name = "incidents"
    columns = [...]
```

**entry point 声明不变**，平台 `TableRegistry.ensure_all_schemas()` 会依次对每个注册表创建 Schema + 表。

### 12.4 `domain.duckdb` 命名约定（替换 `main.duckdb`）

`main.duckdb` 这个名字过于模糊，它实际上是「所有域的业务数据存储」：

```python
# src/olav/core/config.py — PathsConfig 中重命名
@property
def domain_db(self) -> str:
    """统一域数据存储。内部用 DuckDB Schema 隔离各域。"""
    return os.path.join(self.databases_dir, "domain.duckdb")

# 迁移：main.duckdb → domain.duckdb（阶段零一次性 rename，向下无破坏）
```

> **AGENTS.md 需同步更新**：`duckdb .olav/databases/main.duckdb` 改为 `domain.duckdb`。

### 12.5 LanceDB 命名约定：`{domain}_` 前缀

LanceDB 无内置 Schema 概念，用命名前缀实现逻辑隔离：

| 当前集合名 | 新命名 | 说明 |
|:--|:--|:--|
| `kb_documents` | `kb_documents`（不变） | 平台级 KB，无前缀 |
| `agent_memory` | `agent_memory`（不变） | 平台级记忆，无前缀 |
| `field_classifications` | `netops_field_mappings` | 由 `olav-netops init` 创建；引擎代码按前缀发现 |
| （K8s 资源类型库） | `k8sops_resource_types` | 由 `olav-k8sops init` 创建 |
| （ITSM 字段映射） | `itsm_field_mappings` | 由 `scaffold_domain_agent` 生成 |

**Schema Engine 发现逻辑（`schema_engine.py`）**：

```python
def get_domain_collection(domain: str) -> str:
    """按约定推导 LanceDB 集合名。"""
    return f"{domain}_field_mappings"  # e.g. "netops_field_mappings"

# 平台代码不再硬编码 "field_classifications"
```

### 12.6 OpenAPI 集成数据的归宿

回答「不同 OpenAPI 应共享 DuckDB 还是隔离？」：

```
scaffold_domain_agent 生成 ITSM Agent 时：
  ① 在 domain.duckdb 新建 SCHEMA itsm
  ② 注册 BaseIngestTable 子类（schema_name="itsm"）
  ③ 在 LanceDB 创建 itsm_field_mappings 集合
  ④ IngestManager 通过 TableRegistry 自动建表（不需要修改平台代码）
```

**同一 `domain.duckdb` 存放所有 OpenAPI 集成数据**，通过 Schema 隔离：

```sql
-- 跨 API 分析（原生支持，无 ATTACH 复杂度）
SELECT i.number, i.title, d.hostname
FROM itsm.incidents i
JOIN netops.devices d ON i.affected_ci = d.hostname
WHERE i.priority = 'P1';
```

### 12.7 迁移路径（阶段零补充步骤）

```
当前状态                           目标状态
─────────────────────────────────────────────────────────────
main.duckdb（扁平表，网络专用）  → domain.duckdb（多 Schema）
  parsed_outputs                  →   netops.parsed_outputs
  devices                         →   netops.devices
  topology_links                  →   netops.topology_links

field_classifications (LanceDB)  → netops_field_mappings
```

迁移脚本（幂等，阶段零随 `olav-netops` 打包）：

```python
# olav-netops: migrations/v0_12_schema_split.py
def migrate(conn):
    conn.execute("CREATE SCHEMA IF NOT EXISTS netops")
    for table in ["parsed_outputs", "devices", "topology_links", ...]:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS netops.{table}
            AS SELECT * FROM {table}
        """)
        conn.execute(f"DROP TABLE IF EXISTS {table}")  # 迁移完成后删除裸表
```

**向下兼容策略**：创建视图桥接旧名称（过渡一个版本）：

```sql
-- domain.duckdb 中的兼容视图（v0.12 一个版本后删除）
CREATE VIEW IF NOT EXISTS parsed_outputs AS SELECT * FROM netops.parsed_outputs;
```
