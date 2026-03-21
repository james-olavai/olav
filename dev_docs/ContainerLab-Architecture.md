# ⚠️ 文件已迁移

本文件已重新编号为 [05. ContainerLab-Architecture.md](./05.%20ContainerLab-Architecture.md)，以统一 `/dev_docs/` 下的文件命名约定。

请使用新的编号版本。

## 1. 范围

本文档只定义：

- 如何部署和销毁 ContainerLab 实验
- 如何触发真实 OLAV 采集并验证结果
- 如何保留证据并回写覆盖率
- 运行边界和关键约束

本文档不处理：

- OLAV 内部实现细节
- 企业版导出链路
- UI 展示
- 训练集生成
- 自动回滚生产配置

## 2. 核心原则

### 2.1 黑盒测试

Skill 不 import `src/olav/` 或 `.olav/workspace/` 的业务模块。与 OLAV 的交互只通过 CLI，例如 `uv run olav ...`。

### 2.2 明确状态

每次执行必须生成唯一 `test_run_id`，并把所有产物落到：

```text
.agent/skills/containerlab-e2e/evidence/<test_run_id>/
```

### 2.3 配置与采集分离

- 设备配置通过 ContainerLab API 下发
- OLAV netops 通过带外管理地址 SSH 采集
- 脚本端不再依赖 netmiko

### 2.4 采集数据隔离

推荐方案：每个 `test_run_id` 使用独立 DuckDB 文件。

```text
.olav/databases/test_<test_run_id>.duckdb
```

### 2.5 Bug 修复重试不重新部署实验

如果问题出在采集、解析或断言，优先复用当前 lab：修代码，清空本次隔离 DuckDB，从采集步骤重跑。只有基础设施损坏时才重新 deploy。

## 3. 网络模型

E2E 流程里只关注三类地址：

| 类型 | 用途 | 说明 |
|---|---|---|
| Container 内部管理地址 | lab 内部控制 | 仅作参考，不作为采集入口 |
| MGMT Cloud 地址 | OLAV SSH 采集 | 固定使用 `192.168.100.110-160` |
| API 服务地址 | 配置下发 | 当前实例：`http://192.168.100.12:8080/api/v1` |

MGMT Cloud 分配规则：

```text
mgmt_cloud_ip = 192.168.100.(110 + node_index)
```

约束：

- 单场景最多 51 台设备
- `deploy_lab.py` 必须把带外地址写入 `deploy.json`
- `wait_readiness.py` 和 `prepare_netops.py` 只读 `deploy.json`

## 4. 最小执行流

完整 E2E 收敛为 9 步：

```text
1. compile_scenario.py -> execution-plan.json
2. deploy_lab.py -> deploy.json
3. configure_device.py --dry-run -> config-preview/
4. configure_device.py -> configure.json
5. wait_readiness.py -> readiness.json
6. prepare_netops.py -> nornir inventory + isolated duckdb + prepare-netops.json
7. uv run olav ... -> raw/json/db artifacts
8. run_assertions.py + collect_artifacts.py -> assertions.json + artifacts.json
9. destroy_lab.py + track_coverage.py -> destroy.json + coverage update
```

失败规则：

- `deploy` 失败：终止，但必须写 `deploy.json`
- `configure` 失败：终止，但默认仍清理 lab
- `readiness` 超时：不进入采集，保留状态证据
- `assertions` 失败：标记失败，保留证据，仍执行清理
- `destroy` 失败：写明残留资源，不能静默结束

## 5. 关键产物

每次运行至少产生：

- `deploy.json`
- `execution-plan.json`
- `configure.json`
- `readiness.json`
- `prepare-netops.json`
- `assertions.json`
- `artifacts.json`
- `destroy.json`

每次运行至少保留：

- `config-preview/`
- `config-apply/`
- `exports/snapshots/<date>/raw/`
- `exports/snapshots/json/`
- 本次隔离 DuckDB

## 6. 覆盖率矩阵

覆盖率维度固定为：

```text
Platform × Feature × Scenario
```

状态只保留 4 个：

- `not_tested`
- `passed`
- `failed`
- `blocked`

每次回写至少包含：

- `test_run_id`
- `last_run`
- `last_result`
- `evidence_path`

## 7. Definition of Done

满足以下条件，设计才算闭环：

1. 单个场景可编译出 `execution-plan.json`
2. lab 部署后能得到标准化 `deploy.json`
3. 配置下发默认支持 `dry_run`
4. readiness 使用轮询，不使用固定 sleep 充当收敛判定
5. 能触发一次真实 OLAV 采集并拿到 raw/json/db 证据
6. 断言失败时证据仍完整保留
7. 清理失败时会显式标记残留资源

## 8. 当前决策

- 配置下发统一使用 ContainerLab API
- MGMT Cloud 地址范围固定为 `192.168.100.110-160`
- 采集数据库按 `test_run_id` 单独隔离
- Bug 修复重试从采集步骤重来，不重新部署 lab