# NetOps 快速开始

本文档描述当前代码实现下的 NetOps 使用路径。

NetOps 是构建在 OLAV 平台之上的扩展能力，不是最小平台初始化本身。

## 1. 先初始化平台

在仓库根目录执行：

```bash
uv sync
uv run olav init
uv run olav admin "add-user admin --role admin"
```

把返回的 token 保存到 `~/.olav/token`，并收紧权限：

```bash
mkdir -p ~/.olav
printf '%s\n' 'PASTE_TOKEN_HERE' > ~/.olav/token
chmod 600 ~/.olav/token
```

开始 NetOps 引导前，先确认 `.olav/config/api.json` 已经具备可用的 LLM 配置。

## 2. 安装 NetOps 包

从当前仓库安装本地扩展包：

```bash
uv pip install -e olav-netops
```

## 3. 运行 NetOps 引导脚本

建议先跑 dry-run：

```bash
python olav-netops/scripts/netops_init.py --dry-run
```

然后执行正式引导：

```bash
python olav-netops/scripts/netops_init.py
```

该脚本负责：

1. 环境与基础设施检查。
2. LLM 连通性验证。
3. 采集与解析准备。
4. 拓扑生成。
5. `trace_learner` 的 cron 注册。

## 4. 查询网络数据

当前 CLI 直接接受自然语言查询，不需要 `query` 子命令。

```bash
uv run olav --agent ops "Show me the version of R1"
uv run olav --agent ops "What is the BGP status on all routers?"
uv run olav --agent ops "Draw the topology and show which devices are connected"
uv run olav --agent audit "Summarize current network health findings"
```

## 5. 运行说明

- 日常 CLI 使用不依赖单独的 Web 服务。
- NetOps 引导当前通过 `olav-netops/scripts/netops_init.py` 完成。
- 每日 `trace_learner` 调度由引导脚本写入 `~/.olav/cron.tab`。

## 6. 故障排查

### dry-run 失败

先解决 dry-run 输出的前置条件问题，再尝试完整引导。

### 找不到 NetOps 包

确认你位于仓库根目录，并重新安装本地包：

```bash
uv pip install -e olav-netops
```

### 你以为要运行 `olav onboard`

一些旧文档还保留着更早期的 onboarding 路径。当前 NetOps 实际路径是：

1. `olav init`
2. `olav admin "add-user ..."`
3. `uv pip install -e olav-netops`
4. `python olav-netops/scripts/netops_init.py`

## 7. 相关文档

- [01_README.md](./01_README.md)
- [02_QUICK_QUERY.md](./02_QUICK_QUERY.md)
- [03_NETWORK_OPS.md](./03_NETWORK_OPS.md)
- [04_NETWORK_AUDIT.md](./04_NETWORK_AUDIT.md)
- [../../olav/cn/02_QUICK_START.md](../../olav/cn/02_QUICK_START.md)
