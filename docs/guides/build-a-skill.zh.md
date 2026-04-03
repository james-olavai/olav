# 构建自定义技能

Skill（技能）是扩展 OLAV Agent 能力的方式。当内置工具不能满足你的需求时，你可以编写自己的技能——一组 Python 函数，让 Agent 学会新的操作。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-04 | `olav skill install <path>` 从本地目录安装 Skill | ✅ v0.10.0 |
    | C-L2-25 | `olav skill install <git-url>` 从 Git 仓库安装 | ✅ v0.10.0 |
    | C-L2-06 | `olav skill install --merge-into` 追加工具到已有 workspace | ✅ ⚠️ v0.10.0 |
    | C-L2-37 | `requires_packages` 声明依赖自动创建隔离 venv | ✅ v0.10.0 |

---

## 什么时候需要自定义技能？

- 你有内部 API（工单系统、CMDB、监控平台），想让 OLAV 能查询
- 你想封装常用的运维操作（批量配置、健康检查脚本）
- 你有特定的数据处理逻辑需要自动化

---

## 最小技能结构

一个技能只需要两个文件：

```
my-skill/
├── MANIFEST.yaml    ← 元数据：名称、版本、路由关键词
└── tools.py         ← 工具函数：Agent 可以调用的 Python 函数
```

### MANIFEST.yaml — 告诉 OLAV 这个技能是什么

```yaml
kind: Agent
name: my-skill
version: "0.1.0"
description: "查询工单系统的工具集"
route_keywords:      # 当用户提问包含这些关键词时，自动路由到此技能
  - ticket
  - jira
  - issue
  - 工单
```

`route_keywords` 很重要——OLAV 的语义路由器根据这些关键词决定将问题分配给哪个 Agent/Skill。

### tools.py — 定义 Agent 可以调用的工具

```python
from langchain_core.tools import tool

@tool
def get_open_tickets(team: str) -> list[dict]:
    """查询指定团队的所有未关闭工单。

    Args:
        team: 团队名称，例如 "platform" 或 "network"
    """
    import requests
    resp = requests.get(
        "https://jira.internal/api/search",
        params={"jql": f"assignee in membersOf('{team}') AND status != Closed"},
        headers={"Authorization": "Bearer YOUR_TOKEN"}
    )
    return resp.json()["issues"]

@tool
def get_ticket_detail(ticket_id: str) -> dict:
    """获取单个工单的详细信息。

    Args:
        ticket_id: 工单编号，例如 "OPS-1234"
    """
    import requests
    resp = requests.get(
        f"https://jira.internal/api/issue/{ticket_id}",
        headers={"Authorization": "Bearer YOUR_TOKEN"}
    )
    return resp.json()
```

!!! tip "工具函数的 docstring 非常重要"
    LLM 根据函数的 docstring 来决定何时调用这个工具、如何传递参数。写清晰的描述和参数说明能显著提升 Agent 的准确性。

---

## 安装技能

### 从本地目录安装

```bash
olav skill install ./my-skill/
```

输出：
```
installed my-skill v0.1.0 → .olav/workspace/my-skill/
```

验证：

```bash
olav skill list                  # 列出所有已安装技能
olav skill status my-skill       # 查看技能详情
```

### 从 Git 仓库安装

```bash
olav skill install https://github.com/your-org/my-skill
```

仓库根目录需要包含 `MANIFEST.yaml` 或 `workspace.yaml`。

### 追加到已有技能

如果你想给一个已存在的 Agent 添加新工具，而不是创建新的 Agent：

```bash
olav skill install ./extra-tools/ --merge-into my-skill
```

这会将 `extra-tools/` 中的 `tools.py` 追加到 `my-skill` 的工作空间中。

---

## 使用技能

安装完成后，直接用自然语言提问即可：

```bash
olav "platform 团队有多少个未关闭的工单？"
olav "查看 OPS-1234 的详情"
```

OLAV 会根据 `route_keywords` 自动将问题路由到你的技能。

---

## 声明 Python 依赖

如果你的技能需要额外的 Python 包，在 `MANIFEST.yaml` 中声明：

```yaml
requires_packages:
  - requests>=2.31.0
  - paramiko
```

OLAV 安装技能时会自动创建一个隔离的虚拟环境（`.venv/`），安装声明的包，不会影响主环境。

---

## 卸载技能

直接删除工作空间目录即可：

```bash
rm -rf .olav/workspace/my-skill/
```

---

## 进阶：技能开发建议

1. **函数命名要清晰**：`get_open_tickets` 比 `query_data` 好——LLM 能更准确地理解何时调用
2. **docstring 写完整**：包括功能描述、参数说明、返回值格式
3. **route_keywords 覆盖常见表述**：用户可能说"工单""ticket""issue"，都应该覆盖
4. **错误处理要友好**：返回有意义的错误信息，而不是让 Agent 面对 500 报错
5. **先小后大**：从 1-2 个工具函数开始，验证可用后再扩展
