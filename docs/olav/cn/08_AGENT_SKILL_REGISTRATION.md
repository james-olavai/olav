# Agent 与 Skill 注册

本文档说明当前 OLAV 平台里 agent 和 skill 的注册方式。

核心结论是：当前 OLAV 不是单一路径注册，而是并存两条路径：

1. 通过 `AGENT.md` 的静态内建声明。
2. 通过 `MANIFEST.yaml` 的扩展注入。

`SKILL.md` 很重要，但它不是唯一的注册机制。

## 1. 当前注册模型

### 路径 A：内建静态声明

平台内建 skill 通常直接在 agent 的 `AGENT.md` frontmatter 里，通过 `subagents` 条目声明。

示例模式：

```yaml
subagents:
  - path: ./discovery/SKILL.md
  - path: ./creator/SKILL.md
  - path: ./knowledge/SKILL.md
```

这仍然是当前仓库内平台内建 skill 的基础模式。

更具体的目录示意：

```text
.olav/workspace/config/
├── AGENT.md
├── MANIFEST.yaml
├── creator/
│   └── SKILL.md
├── discovery/
│   └── SKILL.md
└── tools/
```

### 路径 B：Manifest 驱动的扩展注入

对于包管理或外部安装的能力，OLAV 会递归扫描 `.olav/workspace/` 下的 `MANIFEST.yaml`。

在 agent 装配阶段，平台会：

1. 发现 manifest。
2. 过滤出 `kind: Skill`。
3. 仅保留 `agent` 字段与当前 agent 匹配的条目。
4. 验证 manifest 同目录下存在 `SKILL.md`。
5. 只有在目标 agent 没有显式声明该 skill 时，才把它注入进去。

显式写在 `AGENT.md` 里的声明始终优先。

## 2. Agent 注册

一个 agent 的 workspace 条目，通常位于 `.olav/workspace/<agent>/`。

常见的 agent 级文件包括：

- `AGENT.md`
- `MANIFEST.yaml`
- `prompts/`
- `tools/`

当前 manifest 发现逻辑至少要求 `MANIFEST.yaml` 中存在：

- `name`
- `kind`

当前实现里常见字段还包括：

- `version`
- `route_keywords`
- `tools_dir`
- `requires`
- `provider_package`
- `required_modules`
- `required_binaries`
- `config_namespace`

## 3. Skill 注册

对于 manifest 驱动的 skill，关键字段是：

- `name`
- `kind: Skill`
- `version`
- `agent`  — 这个 skill 要挂到哪个父 agent

当前注入逻辑还要求 manifest 同目录下必须存在 `SKILL.md`。

最小示例：

```yaml
kind: Skill
name: sync
version: "0.11.0"
agent: config
requires:
  - olav-netops>=0.11
provider_package: olav-netops
```

更具体的目录示意：

```text
source-extension/
├── MANIFEST.yaml
├── SKILL.md
└── tools/
  ├── execute_sync.py
  └── helpers.py
```

典型安装流程：

```bash
uv run olav workspace install ./source-extension
uv run olav workspace validate sync
uv run olav workspace status
```

## 4. `SKILL.md` 实际负责什么

当前 `SKILL.md` 主要承担两类职责：

1. 描述 skill 的用途、提示词契约和可用工具。
2. 用来校验文档里声明的工具列表和实际发现到的工具是否一致。

但 `SKILL.md` 本身不是运行时加载机制。

实际工具加载来自 `tools/` 下的 Python 模块，而 `SKILL.md` 主要承担文档和校验元数据的角色。

这个区分很重要：

- `SKILL.md` 对 skill 打包和 prompt 装配是必要的。
- `tools/*.py` 才提供真实工具实现。
- `MANIFEST.yaml` 才提供包管理场景下的发现与注入入口。

## 5. Workspace 生命周期命令

当前 workspace 控制面暴露了以下平台命令：

- `olav workspace install <source>`
- `olav workspace validate <name>`
- `olav workspace status`
- `olav workspace diff`
- `olav workspace upgrade <name>`
- `olav workspace disable <name>`
- `olav workspace remove <name>`
- `olav workspace rollback <name> --from <archive_dir>`

它们的实际含义是：

1. `install` 会把带有 `MANIFEST.yaml` 的源目录复制到 `.olav/workspace/<manifest.name>`。
2. `validate` 负责解析 manifest 并检查依赖是否可用。
3. `status` 负责展示条目是否被管理、是否启用、依赖是否完整。

## 6. `olav skills` CLI 不是完整注册流程

当前 `olav skills create <name> --agent <agent>` 只是在已有 agent 的 `tools/` 子树下创建一个 `SKILL.md` 模板。

这对编写文档很有帮助，但它不是完整的包管理注册路径。

换句话说：

1. `olav skills create` 主要是脚手架工具。
2. 它不会创建 `MANIFEST.yaml`。
3. 它本身不会把一个能力自动变成 package-managed workspace entry。

## 7. 推荐编写方式

新增能力时，建议按下面区分：

### 对于平台内建 skill

1. 把 skill 放到目标 agent 目录下。
2. 编写对应的 `SKILL.md`。
3. 在 `tools/` 下补真实 Python 工具。
4. 如果它属于内建能力，就在目标 agent 的 `AGENT.md` 里显式声明。

### 对于 package-managed 扩展 skill

1. 创建独立的 workspace 条目，并提供 `MANIFEST.yaml`。
2. 设置 `kind: Skill` 和 `agent: <target-agent>`。
3. 添加同目录的 `SKILL.md`。
4. 提供运行时实现与依赖元数据。
5. 通过 workspace 控制面执行安装。

## 8. 最小编写路径

对于一个新的受管 skill，最小可行流程是：

1. 创建源目录。
2. 编写 `MANIFEST.yaml`，至少包含 `kind: Skill`、`name` 和 `agent`。
3. 添加同目录的 `SKILL.md`。
4. 在 `tools/` 下补充运行时工具实现。
5. 通过 `olav workspace install <source_dir>` 执行安装。
6. 通过 `olav workspace validate <name>` 执行校验。
7. 通过 `olav workspace status` 检查可见性。

对于平台内建 skill，最小可行流程是：

1. 把 skill 目录放到已有 agent 目录下。
2. 添加 `SKILL.md`。
3. 添加运行时工具。
4. 在父 `AGENT.md` 中显式引用它。

## 9. 本文档不宣称的内容

本文档不宣称 OLAV 现在已经具备：

1. 所有内建与外部 skill 都走同一条统一注册路径。
2. 不安装 Python 包也能完全热插拔任意依赖的动态插件模型。
3. 基于 UI 的注册流程。

当前平台是有意保持混合模型的：内建能力走静态声明，受管扩展走 manifest 注入。

## 10. 相关文档

- [03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [06_AAA.md](./06_AAA.md)
- [07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [09_EXTENSION_LIFECYCLE.md](./09_EXTENSION_LIFECYCLE.md)