# OLAV 快速开始

本文档以当前 v0.11 代码实现为准。

最短可用路径是：

1. 用 `olav init` 初始化平台目录。
2. 创建第一个管理员用户，并把返回的 token 保存到 `~/.olav/token`。
3. 从 CLI 运行第一条查询。
4. 如果需要网络采集，再安装并执行可选的 netops 引导脚本。

## 1. 前置条件

在仓库根目录执行：

```bash
uv sync
uv run olav version
```

如果你是直接从源码运行，下面示例统一使用 `uv run olav ...`。如果你已经把 OLAV 安装成系统命令，可以把它替换成 `olav`。

## 2. 初始化平台

先创建平台基础目录和默认配置：

```bash
uv run olav init
```

当前 `init` 会创建：

```text
.olav/config/
.olav/workspace/
.olav/databases/
.olav/logs/
exports/snapshots/json/
exports/snapshots/raw/
```

如果 `.olav/config/api.json` 不存在，还会自动写入一个基础版本。

## 3. 配置 LLM

编辑 `.olav/config/api.json`，填入你的模型提供商配置。

示例：

```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4-turbo",
    "api_key": "your-openai-api-key"
  },
  "embedding": {
    "mode": "local"
  }
}
```

即使还没有安装 netops 扩展，平台本身也已经可以启动和执行基础查询。

## 4. 创建第一个管理员用户

当前实现并不是依赖旧文档里描述的 `olav onboard` 引导流程来创建管理员，而是通过 admin 用户命令。

创建第一个管理员：

```bash
uv run olav admin "add-user admin --role admin"
```

命令只会显示一次 token，必须立刻保存：

```bash
mkdir -p ~/.olav
printf '%s\n' 'PASTE_TOKEN_HERE' > ~/.olav/token
chmod 600 ~/.olav/token
```

查看当前用户列表：

```bash
uv run olav admin "list-users"
```

新增普通用户：

```bash
uv run olav admin "add-user alice --role user"
```

注意：当前 CLI 的 admin 分发逻辑要求把 admin 动作作为一个整体字符串传入，也就是要加引号。

## 5. 运行第一条查询

交互模式：

```bash
uv run olav
```

单次查询模式：

```bash
uv run olav "有多少台设备在线？"
uv run olav --agent ops "检查网络状态"
uv run olav --agent audit "总结最近的审计结果"
```

这里直接传自然语言即可，不需要再写一个 `query` 子命令。

## 6. 可选：引导 NetOps 采集能力

网络采集目前属于扩展式能力，不在最小平台初始化范围内。

先安装仓库里的 netops 包：

```bash
uv pip install -e olav-netops
```

建议先跑一次 dry-run：

```bash
python olav-netops/scripts/netops_init.py --dry-run
```

确认通过后再执行完整引导：

```bash
python olav-netops/scripts/netops_init.py
```

这个脚本的目标是：

1. 检查基础设施和 LLM 连通性。
2. 处理 inventory 与采集初始化。
3. 解析采集输出。
4. 生成拓扑相关产物。
5. 注册 `trace_learner` 的 cron 任务。

如果你想看当前 NetOps 的引导和排障路径，可以继续参考 `../../netops/cn/06_QUICK_START.md`。

## 7. 常用首批命令

```bash
uv run olav help
uv run olav list
uv run olav version
uv run olav admin status
uv run olav workspace status
```

## 8. 开发者入口：新增扩展

如果你不是只使用平台，而是要扩展平台，当前最短路径是：

1. 准备一个带 `MANIFEST.yaml` 的源目录。
2. 添加 `SKILL.md` 或 `AGENT.md`，以及对应运行时实现。
3. 通过 workspace 控制面把它安装进 `.olav/workspace/`。
4. 在首次使用前执行校验。

典型命令：

```bash
uv run olav workspace install ./path/to/extension
uv run olav workspace validate <name>
uv run olav workspace status
```

如果这个能力属于平台内建 skill，而不是 package-managed 扩展，那么当前模型不同：

1. 把 skill 放到目标 agent 的 `.olav/workspace/` 目录下。
2. 添加对应的 `SKILL.md`。
3. 添加真实工具实现。
4. 在目标 agent 的 `AGENT.md` 里显式声明它。

在修改平台控制面文件前，建议先阅读 `07_API_OPENAPI.md`、`08_AGENT_SKILL_REGISTRATION.md` 和 `09_EXTENSION_LIFECYCLE.md`。

## 9. 常见问题

### `olav init` 成功了，但查询时 LLM 不可用

优先检查 `.olav/config/api.json`。当前 `init` 只会生成基础配置，不会替你写入真实密钥。

### 已经创建了 admin 用户，但认证仍然回退到 OS 身份

确认 token 已经保存到 `~/.olav/token`，并且权限为 `600`。

### 我以为要跑 `olav onboard`

旧文档里有一部分还保留了规划中的 bootstrap-token 引导流程。当前代码已实现的实际路径是：

1. `olav init`
2. `olav admin "add-user ..."`
3. 把 token 保存到 `~/.olav/token`

## 10. 下一步阅读

- [docs/cn/03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [docs/cn/06_AAA.md](./06_AAA.md)
- [docs/cn/07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [docs/cn/08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)
- [docs/cn/09_EXTENSION_LIFECYCLE.md](./09_EXTENSION_LIFECYCLE.md)
- [docs/cn/06_QUICK_START.md](../../netops/cn/06_QUICK_START.md)