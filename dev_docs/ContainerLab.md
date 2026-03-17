# ContainerLab E2E Testing Skill — 设计文档

**版本**: v0.4.0-draft  
**状态**: 设计阶段（可实现版草案）  
**目标**: 让 IDE Agent 自动搭建 ContainerLab 环境，对 OLAV 做包含设备配置管理、真实采集验证、失败证据保留和覆盖率追踪的完整 E2E 测试

---

## 1. 设计原则

### 测试基础设施必须与生产代码隔离

E2E 测试 Skill 运行在 `.agent/skills/` 里，**不 import `.olav/` 或 `src/olav/` 下的业务模块**。

原因：
- **耦合陷阱**：测试依赖被测对象 = 测试不可信（OLAV 崩了，测试也崩）
- **部署隔离**：Skill 应能在全新机器上独立运行，只依赖标准 Python 包和系统 CLI
- **职责清晰**：测试 Skill 只负责搭环境、下配置、等收敛、验结果、留证据

### 与 OLAV 的唯一合法交互点

```text
IDE Agent
    │
    ├─→ [测试 Skill 脚本]  直接用 containerlab / ssh / netmiko / duckdb
    │
    └─→ [uv run olav ...]  以正常 CLI 方式触发 OLAV 采集（黑盒）
                               ↓
                       exports/snapshots/{date}/raw/
                               ↓
                       exports/snapshots/json/
                               ↓
                       .olav/databases/main.duckdb
                               ↓
    └─→ [run_assertions.py]   只读查询验证
```

OLAV 始终以**黑盒**方式被测试，测试 Skill 不知道也不关心 OLAV 的内部实现。

### 这份文档解决的问题

本设计只解决以下问题：
- 如何部署和销毁 ContainerLab 测试环境
- 如何为多厂商节点渲染并下发配置
- 如何等待设备 SSH 就绪和协议收敛
- 如何触发一次真实的 OLAV 采集
- 如何验证采集结果并保留完整测试证据
- 如何把测试结果映射到覆盖率矩阵

本设计**不**包含以下内容：
- 审计日志导出为训练集
- OLAV 内部代码改造
- Web UI 集成
- 生产环境变更回滚

若测试完成后需要进入企业版数据导出或自动训练链路，应由上层编排文档处理，而不是在本 Skill 内直接实现。相关企业能力统一按以下功能标识引用：

- `ent_field_redaction`
- `ent_sft_export`
- `ent_trajectory_export`
- `ent_atif_export`
- `ent_dataset_export_encryption`
- `ent_local_train_one_time_token`

---

## 2. 设计结论

这份 Skill 不是单纯的“5 个脚本集合”，而是一个**状态明确的 E2E 编排器**。  
为避免文档停留在示意层，下面统一引入 3 个核心概念：

### 2.1 `test_run_id`

每次 E2E 执行都必须生成一个唯一 `test_run_id`，例如：

```text
clab-e2e-20260316-153045-bgp-full-mesh
```

它用于关联以下所有产物：
- lab 部署日志
- 设备配置日志
- 就绪检查日志
- OLAV 采集命令
- SQL 断言结果
- 覆盖率更新记录
- 清理结果

### 2.2 证据目录

每次 E2E 必须落盘一个证据目录：

```text
.agent/skills/containerlab-e2e/evidence/<test_run_id>/
```

最少包含：
- `deploy.json`：拓扑部署结果和节点连接信息
- `config-preview/`：每台设备渲染后的配置预览
- `config-apply/`：每台设备配置下发输出
- `readiness.json`：SSH 就绪、协议收敛、重试次数
- `collect.txt`：触发 OLAV 采集的 CLI 记录
- `assertions.json`：所有断言结果
- `artifacts.json`：raw/json/db/topology 证据索引
- `destroy.json`：清理结果

### 2.3 场景编译

测试场景 YAML 不是最终执行输入。  
它必须先经过一次“场景编译”，生成一个可执行计划：

```text
scenario.yaml
   ↓ compile_scenario.py
execution-plan.json
```

编译阶段负责：
- 地址分配
- 节点名与接口名映射
- 模板变量展开
- 平台驱动选择
- 收敛等待规则注入

### 2.4 与企业能力的边界

ContainerLab E2E Skill 只负责产生真实测试证据，并把这些证据交给上游或下游流程消费。

它与企业功能的关系应限定为：

1. 可以为 `ent_sft_export`、`ent_trajectory_export`、`ent_atif_export` 提供 run 级证据索引
2. 可以为 `ent_dataset_export_encryption` 提供 `test_run_id` 与证据目录关联信息
3. 不直接实现 `ent_field_redaction`、`ent_dataset_export_encryption`、`ent_local_train_one_time_token`
4. 企业功能开关应由顶层 orchestration 或导出模块决定，而不是在测试脚本里分叉

---

## 3. 目录结构（补齐版）

```text
.agent/
├── rules/
│   └── project-overview.md
└── skills/
    └── containerlab-e2e/
        ├── SKILL.md
        ├── topologies/
        │   ├── bgp-dual-vendor.clab.yml
        │   └── ospf-ring.clab.yml
        ├── device-configs/
        │   ├── cisco_ios/
        │   │   ├── base.j2
        │   │   ├── bgp_peer.j2
        │   │   └── ospf_area0.j2
        │   ├── juniper_junos/
        │   │   ├── base.j2
        │   │   └── bgp_peer.j2
        │   ├── arista_eos/
        │   │   ├── base.j2
        │   │   └── bgp_peer.j2
        │   └── frr/
        │       ├── base.j2
        │       └── bgp_peer.j2
        ├── test-scenarios/
        │   ├── bgp_full_mesh.yaml
        │   └── ospf_area0.yaml
        ├── coverage/
        │   └── matrix.yaml
        ├── evidence/
        │   └── .gitkeep
        ├── scripts/
        │   ├── deploy_lab.py            # 部署 lab，返回标准化节点信息
        │   ├── compile_scenario.py      # 场景编译：地址、变量、驱动、等待规则
        │   ├── configure_device.py      # 配置渲染 + 平台驱动下发
        │   ├── wait_readiness.py        # SSH / 协议收敛等待
        │   ├── run_assertions.py        # SQL + 文件存在性断言
        │   ├── collect_artifacts.py     # 汇总 raw/json/db/topology 证据
        │   ├── track_coverage.py        # 读写 coverage/matrix.yaml
        │   └── destroy_lab.py           # 销毁 ContainerLab
        └── schemas/
            ├── scenario.schema.yaml
            └── execution-plan.schema.yaml
```

新增脚本的原因：
- `compile_scenario.py`：把声明式场景变成真正可执行的数据
- `wait_readiness.py`：避免把“sleep 10 秒”当成设计
- `collect_artifacts.py`：把测试证据保留下来，而不是只在终端里看一眼

---

## 4. 脚本设计（stdin/stdout 标准，零 OLAV 依赖）

### 4.1 `deploy_lab.py`

职责：
- 部署本地或远程 ContainerLab
- 正确解析 lab 名称
- 标准化输出每个节点的 SSH 连接信息
- 等待 `containerlab inspect` 可读
- 写出 `deploy.json`

#### 关键约束

- **不能**用 `Path(topo_file).stem` 直接推导 lab 名
- **不能**用固定 `sleep(10)` 代表就绪
- **不能**用 `port_base + i + 1` 猜远程 SSH 端口
- 必须把“节点 SSH 怎么连”变成显式、可落盘的事实

#### 连接信息标准化输出

统一输出结构：

```json
{
  "test_run_id": "clab-e2e-20260316-153045-bgp-full-mesh",
  "lab_name": "bgp-dual-vendor",
  "mode": "local",
  "nodes": {
    "R1": {
      "name": "R1",
      "kind": "ceos",
      "platform": "arista_eos",
      "host": "172.20.20.2",
      "port": 22,
      "username": "admin",
      "password": "admin",
      "save_mode": "write_memory",
      "config_mode": "netmiko"
    }
  }
}
```

#### 本地 / 远程解析原则

- 本地模式：优先使用 ContainerLab 管理网 IP + 设备默认 SSH 端口
- 远程模式：从 `containerlab inspect --format json` 的端口映射结果中解析；如果 inspect 不含端口映射，再通过远端 `docker inspect` 查询容器 `22/tcp` 的 published port
- lab 名称优先级：
  1. 调用参数显式传入的 `lab_name`
  2. topo YAML 中的 `name`
  3. 文件名去掉 `.clab.yml`

#### 伪代码

```python
def resolve_lab_name(topo_file: Path, explicit_name: str | None) -> str:
    if explicit_name:
        return explicit_name
    topo = yaml.safe_load(topo_file.read_text())
    if topo.get("name"):
        return str(topo["name"])
    return topo_file.name.removesuffix(".clab.yml")


def wait_for_inspect(local: bool, lab_name: str, timeout_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    last_error = None
    while time.time() < deadline:
        try:
            return run_containerlab_inspect(...)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"inspect timeout for {lab_name}: {last_error}")


def normalize_node(container: dict, remote_host: str | None) -> dict:
    platform = map_kind_to_platform(container["kind"])
    endpoint = resolve_ssh_endpoint(container, remote_host)
    return {
        "name": short_name(container["name"]),
        "kind": container["kind"],
        "platform": platform,
        "host": endpoint.host,
        "port": endpoint.port,
        "username": default_username(platform),
        "password": default_password(platform),
        "save_mode": save_mode(platform),
        "config_mode": config_mode(platform),
    }
```

#### `kind -> platform` 映射

建议映射：

```python
KIND_TO_PLATFORM = {
    "ceos": "arista_eos",
    "veos": "arista_eos",
    "junos": "juniper_junos",
    "vr-vmx": "juniper_junos",
    "iosv": "cisco_ios",
    "csr1000v": "cisco_ios",
    "xrd": "cisco_xr",
    "frr": "frr",
    "linux": "linux",
    "srl": "nokia_srlinux",
}
```

`srl` 不应映射成 `nokia_sros`。

---

### 4.2 `compile_scenario.py`

职责：
- 读取场景 YAML
- 做地址分配
- 为每个节点生成最终模板变量
- 为每个节点分配平台驱动
- 输出 `execution-plan.json`

这是本设计补齐后最关键的新组件。

#### 为什么需要它

当前场景 YAML 只适合“人工理解”，不适合直接执行。  
例如 BGP peer 的 `10.0.0.1` / `10.0.0.2` 不能长期手写，否则场景会和拓扑脱节。

#### 地址分配模型

每个场景需要显式声明一个地址池和链路到接口的映射方式：

```yaml
addressing:
  p2p_pool_v4: 10.0.0.0/24
  loopback_pool_v4: 10.255.0.0/24
  p2p_prefixlen_v4: 30
```

编译阶段负责：
- 给每条 p2p 链路分配一个 `/30`
- 给每个节点分配 loopback
- 生成模板可直接使用的变量

#### 输出结构

```json
{
  "test_run_id": "clab-e2e-20260316-153045-bgp-full-mesh",
  "scenario": "bgp_full_mesh",
  "lab_name": "bgp-dual-vendor",
  "nodes": {
    "R1": {
      "platform": "cisco_ios",
      "configs": ["base", "bgp_peer"],
      "driver": {
        "config_mode": "netmiko",
        "save_mode": "write_memory"
      },
      "vars": {
        "hostname": "R1",
        "loopback0": "10.255.0.1/32",
        "links": [
          {
            "interface": "GigabitEthernet1",
            "peer": "R2",
            "ipv4": "10.0.0.1/30",
            "peer_ipv4": "10.0.0.2/30"
          }
        ],
        "bgp": {
          "local_as": 65001,
          "router_id": "10.255.0.1",
          "neighbors": [
            {"peer": "R2", "peer_ip": "10.0.0.2", "remote_as": 65002}
          ]
        }
      }
    }
  }
}
```

---

### 4.3 `configure_device.py`

职责：
- 根据 `execution-plan.json` 渲染配置
- 支持 `dry_run`
- 按平台驱动选择正确的下发和保存方式
- 写出每台设备的配置预览与配置回显

#### 配置下发必须有平台驱动层

不能把所有厂商都当成：

```python
send_config_set(...)
save_config()
```

建议显式建模为：

```python
PLATFORM_DRIVERS = {
    "cisco_ios": {
        "netmiko_type": "cisco_ios",
        "apply": "send_config_set",
        "save": "write_memory",
    },
    "arista_eos": {
        "netmiko_type": "arista_eos",
        "apply": "send_config_set",
        "save": "copy_run_start",
    },
    "juniper_junos": {
        "netmiko_type": "juniper_junos",
        "apply": "send_config_set",
        "save": "commit",
    },
    "frr": {
        "netmiko_type": "linux",
        "apply": "vtysh_batch",
        "save": "write_frr",
    },
}
```

#### `dry_run` 的真实要求

`dry_run` 不只是打印文本，还要把以下内容写入证据目录：
- 渲染后的完整配置
- 使用的模板名
- 使用的最终变量
- 设备平台驱动

#### 输出结构

```json
{
  "success": true,
  "test_run_id": "clab-e2e-20260316-153045-bgp-full-mesh",
  "node": "R1",
  "platform": "cisco_ios",
  "template": "bgp_peer.j2",
  "dry_run": false,
  "lines_sent": 12,
  "save_mode": "write_memory",
  "output": "...device response..."
}
```

---

### 4.4 `wait_readiness.py`

职责：
- 等待 SSH 就绪
- 等待基础配置完成后的协议收敛
- 用轮询替代固定 sleep
- 输出每个检查点的耗时和最终状态

#### 就绪检查分层

每次场景至少分三层等待：
- **L1 容器就绪**：`containerlab inspect` 可读
- **L2 SSH 就绪**：目标端口可连接，能成功登录
- **L3 协议收敛**：例如 BGP 邻居 `Established`，OSPF 邻居 `Full`

#### 收敛检查建议

收敛不是靠 SQL 查库判断，而是靠设备自身状态判断。  
例如：
- Cisco / Arista：`show ip bgp summary`
- Junos：`show bgp summary`
- FRR：`vtysh -c 'show bgp summary json'`

只有设备侧状态稳定后，才触发 OLAV 采集。

#### 输出结构

```json
{
  "all_ready": true,
  "nodes": {
    "R1": {
      "ssh_ready": true,
      "ssh_attempts": 4,
      "protocol_ready": true,
      "protocol_attempts": 3,
      "elapsed_sec": 28.4
    }
  }
}
```

---

### 4.5 `run_assertions.py`

职责：
- 只读验证采集结果
- 既验证 SQL，也验证文件证据
- 输出统一断言结果 JSON

#### 断言类型不再使用任意 `eval`

当前文档的 `eval(assertion["expect"])` 只适合作为草稿。  
正式设计里建议收敛为有限断言类型：

```yaml
assertions:
  - type: sql_count
    description: "所有 BGP 邻居 Established"
    query: "SELECT COUNT(*) FROM bgp_neighbors WHERE state != 'Established'"
    operator: eq
    expected: 0

  - type: file_exists
    description: "R1 raw 输出存在"
    path_glob: "exports/snapshots/*/raw/R1/*"

  - type: sql_count
    description: "发现跨厂商链路"
    query: "SELECT COUNT(*) FROM topology_links WHERE ..."
    operator: gte
    expected: 1
```

支持的操作符建议限制为：
- `eq`
- `ne`
- `gt`
- `gte`
- `lt`
- `lte`

#### 必检项

每个 E2E 场景默认都要自动附加 4 类断言：
- raw CLI 文件存在
- parsed JSON 文件存在
- `parsed_outputs` 有记录
- `topology_links` 满足场景最低要求

---

### 4.6 `collect_artifacts.py`

职责：
- 从真实文件系统和数据库生成证据索引
- 让一次测试结果可独立复核

#### 输出结构

```json
{
  "test_run_id": "clab-e2e-20260316-153045-bgp-full-mesh",
  "raw_files": [
    "exports/snapshots/2026-03-16_1532/raw/R1/show_ip_bgp_summary.txt"
  ],
  "json_files": [
    "exports/snapshots/json/R1_20260316_1532.staging.json"
  ],
  "db_checks": {
    "parsed_outputs_count": 42,
    "topology_links_count": 2
  }
}
```

---

### 4.7 `destroy_lab.py`

职责：
- 销毁本地或远程 lab
- 尝试多次清理
- 如果失败，记录残留资源

#### 清理不是可选项

即使中间步骤失败，也必须执行 `destroy_lab.py`。  
只有以下两种情况可以保留环境：
- 用户显式要求保留现场
- `keep_on_failure: true`

---

## 5. Agent 工作流（完整 E2E 循环）

```text
IDE Agent 收到任务: "对 BGP 跨厂商场景做 E2E 测试"

Step 0: 生成 test_run_id 和证据目录
  mkdir evidence/<test_run_id>/

Step 1: 查覆盖率 gap
  track_coverage.py → 找到尚未覆盖的 platform / feature / scenario

Step 2: 编译场景
  compile_scenario.py ← {"scenario": "bgp_full_mesh", "test_run_id": "..."}
                      → execution-plan.json

Step 3: 部署 Lab
  deploy_lab.py ← {"topology": "bgp-dual-vendor.clab.yml", "test_run_id": "..."}
               → deploy.json

Step 4: 等 SSH 就绪
  wait_readiness.py ← {"mode": "ssh", "test_run_id": "..."}
                    → readiness.json

Step 5: dry_run 渲染配置
  configure_device.py ← {"node": "R1", "dry_run": true, ...}
                      → 写 evidence/config-preview/R1.txt

Step 6: [用户确认] 正式下发配置
  configure_device.py ← {"node": "R1", "dry_run": false, ...}
  configure_device.py ← {"node": "R2", "dry_run": false, ...}

Step 7: 等协议收敛
  wait_readiness.py ← {"mode": "protocol", "test_run_id": "..."}

Step 8: 触发 OLAV 采集（黑盒调用）
  execute_shell: "cd /home/yhvh/Olav && uv run olav"

Step 9: 汇总证据
  collect_artifacts.py ← {"test_run_id": "..."}

Step 10: 跑断言
  run_assertions.py ← {"scenario": "bgp_full_mesh", "test_run_id": "..."}

Step 11: 更新覆盖率
  track_coverage.py ← {"action": "mark_passed", ...}

Step 12: 清理
  destroy_lab.py ← {"test_run_id": "...", "topology": "bgp-dual-vendor.clab.yml"}
```

失败路径规则：
- `deploy` 失败：终止，写 `deploy.json`，不更新覆盖率
- `configure` 失败：写失败证据，默认仍执行清理
- `protocol wait` 超时：不触发 OLAV 采集，保留设备状态证据
- `collect` 失败：写 `collect.txt` 和错误输出，仍执行断言中的文件缺失项
- `assertions` 失败：标记 failed，仍执行清理
- `destroy` 失败：标记 `cleanup_incomplete`，保留残留节点列表

---

## 6. 覆盖率矩阵（Platform × Feature × Scenario）

```yaml
# coverage/matrix.yaml — 持久化在 Git，团队可见
cisco_ios:
  BGP:
    basic_peering:    { status: not_tested, last_run: null, last_result: null }
    route_reflector:  { status: not_tested, last_run: null, last_result: null }
    failover:         { status: not_tested, last_run: null, last_result: null }
  OSPF:
    area0_basic:      { status: not_tested, last_run: null, last_result: null }
  LLDP:
    discovery:        { status: not_tested, last_run: null, last_result: null }

juniper_junos:
  BGP:
    basic_peering:    { status: not_tested, last_run: null, last_result: null }
  LLDP:
    discovery:        { status: not_tested, last_run: null, last_result: null }

arista_eos:
  BGP:
    basic_peering:    { status: not_tested, last_run: null, last_result: null }
  LLDP:
    discovery:        { status: not_tested, last_run: null, last_result: null }
```

建议状态：
- `not_tested`
- `passed`
- `failed`
- `blocked`

覆盖率更新必须记录：
- `test_run_id`
- 最近一次执行时间
- 最近一次结果
- 最近一次证据目录路径

---

## 7. 测试场景定义（声明式 + 可编译）

```yaml
# test-scenarios/bgp_full_mesh.yaml
scenario: bgp_full_mesh
description: "2 个 AS 之间的 BGP peering（跨厂商）"

topology: bgp-dual-vendor.clab.yml
lab_name: bgp-dual-vendor

addressing:
  p2p_pool_v4: 10.0.0.0/24
  loopback_pool_v4: 10.255.0.0/24
  p2p_prefixlen_v4: 30

defaults:
  ssh_timeout_sec: 180
  protocol_timeout_sec: 240
  keep_on_failure: false

nodes:
  R1:
    platform: cisco_ios
    configs: [base, bgp_peer]
    interfaces:
      to_R2: GigabitEthernet1
    bgp:
      local_as: 65001

  R2:
    platform: juniper_junos
    configs: [base, bgp_peer]
    interfaces:
      to_R1: ge-0/0/0
    bgp:
      local_as: 65002

links:
  - endpoints: [R1:to_R2, R2:to_R1]
    purpose: bgp_underlay

readiness:
  ssh:
    retries: 30
    interval_sec: 5
  protocol:
    type: bgp
    retries: 24
    interval_sec: 10
    expected_sessions:
      - { node: R1, peer: R2, state: Established }
      - { node: R2, peer: R1, state: Established }

assertions:
  - type: sql_count
    description: "所有 BGP 邻居 Established"
    query: "SELECT COUNT(*) FROM bgp_neighbors WHERE state != 'Established'"
    operator: eq
    expected: 0

  - type: sql_count
    description: "跨厂商拓扑链路被发现"
    query: |
      SELECT COUNT(*) FROM topology_links
      WHERE (source_device='R1' AND destination_device='R2')
         OR (source_device='R2' AND destination_device='R1')
    operator: gte
    expected: 1

  - type: sql_count
    description: "两台设备都有 parsed_outputs"
    query: "SELECT COUNT(DISTINCT device_name) FROM parsed_outputs WHERE device_name IN ('R1','R2')"
    operator: eq
    expected: 2

  - type: file_exists
    description: "R1 raw 输出存在"
    path_glob: "exports/snapshots/*/raw/R1/*"

coverage_contribution:
  - { platform: cisco_ios, feature: BGP, scenario: basic_peering }
  - { platform: juniper_junos, feature: BGP, scenario: basic_peering }
  - { platform: cisco_ios, feature: LLDP, scenario: discovery }
  - { platform: juniper_junos, feature: LLDP, scenario: discovery }
```

---

## 8. `SKILL.md`（精简版）

```yaml
---
name: containerlab-e2e
description: "自动搭建 ContainerLab 测试环境，配置网络设备，验证 OLAV E2E 功能，保留测试证据，追踪多厂商覆盖率"
metadata:
  version: 0.4.0
  type: skill
  category: testing

tools:
  - name: compile_scenario
    script: .agent/skills/containerlab-e2e/scripts/compile_scenario.py
    description: "把声明式场景编译成 execution-plan.json"

  - name: deploy_lab
    script: .agent/skills/containerlab-e2e/scripts/deploy_lab.py
    description: "部署 ContainerLab 拓扑，返回标准化节点连接信息"

  - name: configure_device
    script: .agent/skills/containerlab-e2e/scripts/configure_device.py
    description: "Jinja2 渲染配置模板并按平台驱动下发到设备，支持 dry_run"

  - name: wait_readiness
    script: .agent/skills/containerlab-e2e/scripts/wait_readiness.py
    description: "等待 SSH 就绪和协议收敛"

  - name: run_assertions
    script: .agent/skills/containerlab-e2e/scripts/run_assertions.py
    description: "只读验证文件证据和 DuckDB 断言"

  - name: collect_artifacts
    script: .agent/skills/containerlab-e2e/scripts/collect_artifacts.py
    description: "收集 raw/json/db/topology 证据索引"

  - name: show_coverage
    script: .agent/skills/containerlab-e2e/scripts/track_coverage.py
    description: "显示或更新覆盖率矩阵（Platform × Feature × Scenario）"

  - name: destroy_lab
    script: .agent/skills/containerlab-e2e/scripts/destroy_lab.py
    description: "销毁 ContainerLab 环境并记录残留资源"
---

## 核心原则

- 零 OLAV 业务依赖：不 import OLAV 内部模块
- OLAV 以黑盒方式被测试：只通过 CLI 触发采集
- 所有测试必须生成 `test_run_id`
- 所有测试必须保留证据目录
- `dry_run` 默认启用：配置下发前展示预览，确认后执行
- 所有失败路径都必须尝试清理环境

## 工作流

1. show_coverage() → 找到 gap
2. compile_scenario() → 生成 execution-plan
3. deploy_lab() → 获取标准化节点信息
4. wait_readiness(mode="ssh") → 等 SSH 就绪
5. configure_device(dry_run=true) → 预览配置
6. [用户确认]
7. configure_device(dry_run=false) → 下发配置
8. wait_readiness(mode="protocol") → 等协议收敛
9. [触发 OLAV 采集：uv run olav 或 collect_commands]
10. collect_artifacts() → 汇总证据
11. run_assertions(scenario=...) → 验证结果
12. show_coverage(action="mark_passed", ...) → 更新覆盖率
13. destroy_lab() → 清理
```

---

## 9. 依赖清单（脚本层，与 OLAV 完全分离）

```toml
netmiko = ">=4.3.0"      # 设备 SSH 连接 + 配置下发
jinja2 = ">=3.1.0"       # 配置模板渲染
duckdb = ">=0.10.0"      # 只读查询 OLAV 的数据库
pyyaml = ">=6.0"         # 场景 / 拓扑 / schema 读写
paramiko = ">=3.0"       # 远程主机 SSH
containerlab               # 系统级 CLI
docker                     # 远程端口映射探测的后备方案
```

---

## 10. 最低完成标准（Definition of Done）

只有满足以下条件，才能认为这个 Skill 设计闭环：

1. 单场景可从 YAML 编译出 `execution-plan.json`
2. 本地 ContainerLab 能稳定部署并解析 SSH 连接信息
3. 至少 2 个平台具备正确的配置下发驱动
4. SSH 就绪和协议收敛都使用轮询，不使用固定 sleep 代替
5. 触发一次真实 OLAV 采集后，能找到 raw/json/db/topology 证据
6. 断言失败时仍保留完整证据目录
7. 清理失败时会标记残留环境，而不是静默结束

---

## 11. 迭代计划（KISS 顺序）

| 阶段 | 目标 | 产出 |
|:---|:---|:---|
| **Iteration 1** | 单节点本地部署 + SSH 就绪检查 | `deploy_lab.py` + `wait_readiness.py` |
| **Iteration 2** | 单平台 OSPF 场景跑通并留下证据目录 | `compile_scenario.py` + `configure_device.py` + `collect_artifacts.py` |
| **Iteration 3** | Cisco + Juniper BGP 跨厂商场景跑通 | 多平台驱动 + `bgp_full_mesh.yaml` |
| **Iteration 4** | 覆盖率矩阵和失败状态回写 | `track_coverage.py` |
| **Iteration 5** | 远程 ContainerLab 主机支持 | `deploy_remote` + 远端 docker inspect 后备逻辑 |
| **Iteration 6** | Agent 自动 coverage-driven 选场景 | `show_coverage` 驱动测试循环 |

---

## 12. 当前明确不做的事情

为了保持 KISS，本阶段明确不做：
- 日志导出训练集
- LangSmith 集成
- Web 面板展示测试进度
- 自动回滚设备配置
- 并行跑多个场景

这些都应在 E2E 主路径稳定后再讨论。
