# 连接外部服务

OLAV 可以连接任何提供 REST API 的外部服务。连接一次后，你就可以永远用自然语言查询它。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-19 | `olav registry register <url>` 一行命令注册 OpenAPI 服务 | ✅ v0.10.0 |
    | C-L2-20 | Creator Agent 从 OpenAPI 自动生成 Skill 代码 | ✅ v0.10.0 |

---

## 适用场景

你的团队可能使用了多种运维工具：NetBox（IPAM）、Zabbix（监控）、ServiceNow（工单）、自研平台等。每个工具都有自己的 API 和查询方式。OLAV 让你用一句话就能跨系统查询：

```bash
olav "机柜 A1 里有多少台设备？"        # 查 NetBox
olav "Zabbix 上有哪些活跃告警？"        # 查 Zabbix
olav "列出欧洲所有站点"                 # 查 NetBox
```

---

## 快速注册：一行命令

如果目标服务提供 OpenAPI（Swagger）规范，注册只需要一行命令：

```bash
olav registry register http://netbox.example.com/api/schema/
```

OLAV 会自动读取 OpenAPI schema，生成调用工具，然后你就可以直接用自然语言查询了。

### 需要认证的服务

大多数服务需要 API Token 或其他认证方式：

```bash
olav registry register http://netbox.example.com/api/schema/ \
  --header "Authorization: Token YOUR_TOKEN"
```

OLAV 的服务注册支持多种认证方式（Bearer Token、API Key、Basic Auth、JWT），具体配置在 `.olav/config/services.yaml` 中管理。

### 管理已注册的服务

```bash
olav registry list                        # 列出所有已注册服务
olav registry status netbox               # 检查某个服务的可达性
olav registry refresh netbox              # 强制重新获取 schema
olav --agent config "取消注册 netbox"      # 通过 Agent 断开连接
```

---

## 深度集成：Creator Agent

`registry register` 适合快速接入，但生成的是通用 API 代理。如果你需要**更精准的工具**——比如只暴露关键操作、自定义参数名称、添加业务逻辑——可以使用 Creator Agent。

Creator Agent 会读取 OpenAPI schema，自动生成一套定制化的 Python 工具函数，你可以编辑和优化：

```bash
olav --agent config "为 http://zabbix.internal/api_jsonrpc.php 创建技能"
```

详见 [Creator Agent →](creator-agent.md)

---

## 两种方式对比

| | `registry register` | Creator Agent |
|-|---------------------|---------------|
| 速度 | 秒级完成 | 需要几分钟生成代码 |
| 产出 | 通用 API 代理 | 定制 Python 工具函数 |
| 可编辑 | 否 | 是——直接编辑 `tools.py` |
| 适合 | 快速试用、简单查询 | 深度集成、复杂业务逻辑 |
