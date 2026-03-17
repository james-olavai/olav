# 扩展生命周期

本文档说明当前 OLAV 平台中，受包管理的扩展是如何沿着完整生命周期流转的。

它适用于通过 `.olav/workspace/` 和 `olav workspace ...` 控制面命令管理的 agent 条目与 skill 条目。

## 1. 生命周期阶段

当前生命周期可以概括为：

1. 编写
2. 安装
3. 校验
4. 使用
5. 升级
6. 禁用
7. 删除
8. 回滚

这是一条控制面生命周期，不等同于 agent 运行时内部的工具执行生命周期。

## 2. 编写

编写发生在把内容安装进 `.olav/workspace/` 之前的源目录里。

对于一个受管扩展条目，源目录至少应包含：

- `MANIFEST.yaml`
- `SKILL.md` 或 `AGENT.md`
- 运行时实现文件，例如 `tools/*.py`

如果是 manifest 驱动的 skill，还应通过 `agent` 字段指明它要挂到哪个父 agent。

## 3. 安装

当前安装命令：

```bash
uv run olav workspace install <source_dir>
```

当前 install 的行为是：

1. 检查源目录是否存在。
2. 检查 `MANIFEST.yaml` 是否存在。
3. 解析 manifest。
4. 把目录复制到 `.olav/workspace/<manifest.name>`。
5. 如果 manifest 声明了未满足的依赖，会返回 warning。

安装属于控制面动作，应视为 admin-only。

## 4. 校验

当前校验命令：

```bash
uv run olav workspace validate <name>
```

当前 validate 的行为是：

1. 确认 workspace 条目存在。
2. 确认 `MANIFEST.yaml` 存在。
3. 解析 manifest。
4. 检查依赖是否可用。
5. 返回成功或“依赖不可用”的结果。

校验是当前平台里连接“已声明”和“可使用”之间的主要关口。

## 5. 发现与注入

一旦安装完成，agent builder 才能发现这个扩展。

当前发现路径是：

1. 递归扫描 `.olav/workspace/` 下的 `MANIFEST.yaml`。
2. 把它们解析为 `AgentManifest`。
3. 在 agent 装配时，把匹配的 skill manifest 合并进目标 agent 配置。
4. 永远不删除 `AGENT.md` 中已经显式声明的条目。

这意味着“安装完成”并不自动等于“任何地方都立即可见”。它仍然要通过运行时发现和合并规则。

## 6. 状态与差异查看

常用观察命令：

```bash
uv run olav workspace status
uv run olav workspace diff
```

当前含义：

- `status` 用于展示条目是 managed 还是 user、enabled 还是 disabled，以及依赖是否满足。
- `diff` 用于比较本地版本标记与上游版本标记。

这些命令属于控制面可观测性能力。

## 7. 升级

当前升级命令：

```bash
uv run olav workspace upgrade <name>
```

当前行为：

1. 拒绝升级 unmanaged 条目。
2. 优先读取 `.upstream-version`。
3. 否则尝试从已安装包的元数据里解析上游版本。
4. 更新本地 `.version` 标记。

当前实现仍然偏向“版本标记更新”，而不是完整的远端拉取并重新安装流程。

## 8. 禁用

当前禁用命令：

```bash
uv run olav workspace disable <name>
```

当前行为：

1. 确认 workspace 条目存在。
2. 写入 `.disabled` 标记。

禁用属于控制面状态变更，不会修改源包本身，而是把当前已安装的 workspace 条目标记为 disabled。

## 9. 删除

当前删除命令：

```bash
uv run olav workspace remove <name>
```

当前行为：

1. 拒绝删除 unmanaged 条目。
2. 删除已安装的 workspace 目录。

这是破坏性控制面动作，应视为 admin-only。

## 10. 回滚

当前回滚命令：

```bash
uv run olav workspace rollback <name> --from <archive_dir>
```

当前行为：

1. 检查归档条目是否存在。
2. 用归档版本替换当前 workspace 条目。

当前 rollback 假设你已经有一个归档源。平台本身还没有完整的内建制品版本仓库。

## 11. 实际操作规则

日常运维建议遵循以下规则：

1. 把 install、upgrade、disable、remove、rollback 都视为 admin 控制面动作。
2. 安装后、首次使用前先跑一次 `validate`。
3. 通过 `status` 区分依赖问题和 prompt/tool 本身的问题。
4. 记住内建 skill 与 manifest 驱动 skill 并不是完全相同的生命周期路径。

## 12. 本文档不宣称的内容

本文档不宣称 OLAV 当前已经具备：

1. 完整的包注册表 UI。
2. 自动回滚快照机制。
3. 对任意运行时依赖都能完全热插拔的通用模型。

当前模型是刻意保守的：受管条目沿着可见、可校验、可观察的控制面生命周期流转。

## 13. 相关文档

- [06_AAA.md](./06_AAA.md)
- [07_API_OPENAPI.md](./07_API_OPENAPI.md)
- [08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)