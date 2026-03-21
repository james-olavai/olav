# ⚠️ 文件已迁移

本文件已重新编号为 [06. ContainerLab-Script-Interfaces.md](./06.%20ContainerLab-Script-Interfaces.md)，以统一 `/dev_docs/` 下的文件命名约定。

请使用新的编号版本。

## 1. 脚本职责

### 1.1 `compile_scenario.py`

输入声明式场景，输出可执行计划。职责只包括：

- 地址分配
- 模板变量展开
- 平台映射
- 收敛规则注入

不负责：

- 管理地址分配
- 设备登录
- 数据库写入

### 1.2 `deploy_lab.py`

职责：

- 部署 lab
- 解析 lab 名称
- 分配 MGMT Cloud 地址
- 输出标准化连接信息

输出最少字段：

- `test_run_id`
- `lab_name`
- `api_server`
- `nodes.<name>.platform`
- `nodes.<name>.mgmt_cloud_ip`
- `nodes.<name>.mgmt_cloud_port`
- `nodes.<name>.username`
- `nodes.<name>.password`

### 1.3 `configure_device.py`

职责：

- 渲染模板
- 通过 ContainerLab API 下发命令
- 支持 `dry_run`
- 记录平台保存命令

要求：

- 默认先 `dry_run`
- `dry_run` 必须落盘
- 正式执行结果必须按设备分别保存

### 1.4 `wait_readiness.py`

职责：

- 检查 SSH 就绪
- 检查协议收敛
- 输出重试次数和耗时

要求：

- 不能使用固定 `sleep` 代替 readiness
- SSH 检查只针对带外管理地址
- 协议检查以设备状态为准，不以数据库为准

### 1.5 `prepare_netops.py`

职责：

- 基于 `deploy.json` 动态生成 nornir inventory
- 为本次 `test_run_id` 初始化独立 DuckDB
- 写出 `prepare-netops.json`

约束：

- nornir 配置不能硬编码
- DuckDB 隔离由这里负责
- 采集前不允许复用上一次运行的数据库

### 1.6 `run_assertions.py`

只允许有限断言类型：

- `sql_count`
- `file_exists`

支持操作符：

- `eq`
- `ne`
- `gt`
- `gte`
- `lt`
- `lte`

默认必检项：

- raw 文件存在
- parsed JSON 存在
- `parsed_outputs` 有记录
- `topology_links` 达到场景最低要求

### 1.7 `collect_artifacts.py`

职责：

- 汇总 raw/json/db/配置日志
- 生成证据索引
- 让一次运行可以独立复核

### 1.8 `destroy_lab.py`

职责：

- 销毁实验
- 校验容器、网络、卷是否清理干净
- 标记残留资源

## 2. 场景文件最小结构

```yaml
scenario: bgp_full_mesh
topology: bgp-dual-vendor.clab.yml

addressing:
  p2p_pool_v4: 10.0.0.0/24
  p2p_prefixlen_v4: 30
  loopback_pool_v4: 10.255.0.0/24

defaults:
  ssh_timeout_sec: 180
  protocol_timeout_sec: 240
  keep_on_failure: false

nodes:
  R1:
    platform: cisco_ios
    configs: [base, bgp_peer]
  R2:
    platform: juniper_junos
    configs: [base, bgp_peer]

links:
  - endpoints: [R1:to_R2, R2:to_R1]

readiness:
  protocol:
    type: bgp

assertions:
  - type: sql_count
    query: "SELECT COUNT(*) FROM bgp_neighbors WHERE state != 'Established'"
    operator: eq
    expected: 0
```

约束：

- 场景只描述目标状态，不描述 deploy 后的管理地址
- 管理地址由 `deploy_lab.py` 生成
- 场景断言必须可被 `run_assertions.py` 直接解释

## 3. 最小输入输出约束

推荐所有脚本统一满足：

- stdin 接收 JSON 或命令行参数
- stdout 输出单个结果 JSON
- 所有副作用都必须落盘到 `evidence/<test_run_id>/`
- 所有失败都必须输出可读错误信息，并尽可能写结果文件

最少结果文件清单：

- `execution-plan.json`
- `deploy.json`
- `configure.json`
- `readiness.json`
- `prepare-netops.json`
- `assertions.json`
- `artifacts.json`
- `destroy.json`