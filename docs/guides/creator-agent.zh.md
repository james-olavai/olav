# Creator Agent

Creator Agent 是 OLAV 的"技能工厂"——它能读取任何 OpenAPI 规范，自动生成一套可立即使用的 Python 工具函数。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-20 | Creator Agent 从 OpenAPI schema 自动生成 Skill 工作空间 | ✅ v0.10.0 |

---

## 为什么需要它？

当你通过 `registry register` 快速连接了一个服务后，可能会发现：

- 通用代理生成的工具太多或不够精确
- 某些 API 操作需要特殊的参数处理
- 你想为团队定制更友好的工具描述

Creator Agent 解决了这些问题——它生成**可编辑的 Python 代码**，你可以根据实际需求调整。

---

## 使用方法

告诉 config Agent 你要接入的服务：

```bash
olav --agent config "为 Zabbix API http://zabbix.internal/api_jsonrpc.php 创建技能"
olav --agent config "为 http://myservice/openapi.json 创建一个技能"
```

Creator Agent 会自动：

1. 获取目标服务的 OpenAPI schema
2. 分析 API 端点，选择关键操作
3. 为每个操作生成一个 `@tool` Python 函数
4. 创建完整的 Skill 目录，包含元数据和路由关键词

## 生成结果

```
.olav/workspace/<service>/
├── SKILL.md        ← 技能描述和 Agent 绑定
└── tools.py        ← Python 工具函数（每个关键 API 操作一个函数）
```

你可以直接编辑 `tools.py`：修改函数名、调整参数、添加错误处理、增加业务逻辑。

## 生成后立即可用

```bash
olav "显示 Zabbix 中所有有活跃问题的主机"
olav "最近 1 小时有哪些新告警？"
```

OLAV 的语义路由器会根据你的问题内容，自动调用新生成的工具。

---

## 与 `registry register` 的区别

| | `registry register` | Creator Agent |
|-|---------------------|---------------|
| 产出 | 通用 API 代理（不可编辑） | Python 工具函数代码（完全可编辑） |
| 精确度 | 所有端点一视同仁 | 只为关键操作生成工具 |
| 自定义 | 无法修改 | 可以修改函数逻辑、参数、描述 |
| 适合 | 快速接入，验证可行性 | 长期使用，深度定制 |

!!! tip "推荐工作流"
    先用 `registry register` 快速验证 API 是否可用，确认后再用 Creator Agent 生成正式的技能代码。
