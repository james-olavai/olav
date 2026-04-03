# 配置参考

所有配置集中在 `.olav/config/api.json` 文件中。运行 `olav init` 会创建一个基础版本。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-38 | `agent_overrides` 为不同 Agent 指定不同 LLM 模型 | ✅ v0.10.0 |
    | C-L2-39 | `OLAV_LLM_*` 环境变量覆盖配置文件 | ✅ v0.10.0 |

!!! warning "保护配置文件"
    `api.json` 包含 API 密钥，不要提交到 Git。请将 `.olav/config/` 加入 `.gitignore`。

---

## 文件结构

```json
{
  "llm": { ... },
  "embedding": { ... },
  "auth": { ... },
  "agent_overrides": { ... }
}
```

---

## LLM 配置

OLAV 支持多种 LLM 提供商。选择你使用的提供商：

=== "OpenAI"
    ```json
    {
      "llm": {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "sk-..."
      }
    }
    ```

=== "Anthropic"
    ```json
    {
      "llm": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "api_key": "sk-ant-..."
      }
    }
    ```
    Anthropic 模型自动启用 Prompt Caching，减少重复请求的成本。

=== "OpenRouter（多模型聚合）"
    ```json
    {
      "llm": {
        "provider": "custom",
        "model": "x-ai/grok-2",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-..."
      }
    }
    ```
    通过 OpenRouter 可以使用几乎所有主流模型。

=== "Ollama（本地离线）"
    ```json
    {
      "llm": {
        "provider": "ollama",
        "model": "llama3.1",
        "base_url": "http://localhost:11434"
      }
    }
    ```
    无需 API Key，数据不出本机。

### LLM 字段说明

| 字段 | 必填 | 默认值 | 说明 |
|------|------|-------|------|
| `provider` | ✅ | | 提供商：`openai` / `anthropic` / `azure_openai` / `ollama` / `groq` / `mistral` / `custom` |
| `model` | ✅ | | 模型 ID（如 `gpt-4o`、`claude-3-5-sonnet-20241022`） |
| `api_key` | ✅* | | API 密钥（Ollama 不需要） |
| `base_url` | | | `custom` 提供商必填，其他可选（用于自建代理） |
| `temperature` | | `0.1` | 生成温度，越低越确定性 |
| `max_tokens` | | `32000` | 最大生成 Token 数 |

---

## 向量嵌入配置

知识库和 Agent 记忆使用向量嵌入进行语义搜索。

=== "API 模式（推荐）"
    ```json
    "embedding": {
      "mode": "api",
      "api": {
        "model": "openai/text-embedding-3-small",
        "base_url": "https://openrouter.ai/api/v1"
      },
      "fallback": { "enabled": true }
    }
    ```
    `fallback` 启用后，API 不可用时自动回退到本地模型。

=== "本地模式（离线/气隙环境）"
    ```json
    "embedding": {
      "mode": "local"
    }
    ```
    使用 BAAI/bge 模型，仅需 CPU，无需网络连接。

---

## 认证模式 { #认证模式 }

在 `auth` 部分配置，决定如何识别用户身份：

| 模式 | 适用场景 | 说明 |
|------|---------|------|
| `none` | 个人使用、本地开发 | 默认，使用操作系统用户名 |
| `token` | 小团队 | OLAV 内置令牌认证 |
| `ldap` | 企业 | 对接 LDAP 目录 |
| `ad` | 企业 | 对接 Active Directory |
| `oidc` | SSO | 对接 OpenID Connect |

---

## 为不同 Agent 指定不同模型

你可以为特定 Agent 使用不同的 LLM 模型——比如快速查询用便宜的小模型，复杂分析用强大的大模型：

```json
"agent_overrides": {
  "quick": { "model": "gpt-4o-mini" },
  "audit": { "provider": "anthropic", "model": "claude-3-5-sonnet-20241022" }
}
```

未在 `agent_overrides` 中指定的 Agent 使用顶层 `llm` 配置。

---

## 环境变量

所有配置都可以通过环境变量覆盖，优先级高于 `api.json`：

| 环境变量 | 对应配置 | 说明 |
|---------|---------|------|
| `OLAV_LLM_MODEL` | `llm.model` | 模型 ID |
| `OLAV_LLM_API_KEY` | `llm.api_key` | API 密钥 |
| `OLAV_LLM_BASE_URL` | `llm.base_url` | API 地址 |
| `OPENAI_API_KEY` | `llm.api_key` | OpenAI 快捷方式 |
| `ANTHROPIC_API_KEY` | `llm.api_key` | Anthropic 快捷方式 |
| `OLAV_WEB_PORT` | | Web 服务端口 |
| `OLAV_WEB_HOST` | | Web 服务绑定地址 |

!!! tip "CI/CD 推荐用环境变量"
    在 CI/CD 流水线中，推荐通过环境变量而非文件传递密钥，避免密钥写入磁盘。

---

## 远程 AsyncSubAgent

OLAV 可将 LangGraph Cloud 或自托管 LangGraph 部署接入为 AsyncSubAgent。在 `api.json` 中添加 `async_subagents` 数组：

```json
{
    "async_subagents": [
        {
            "name": "remote-ops",
            "description": "运行在 LangGraph Cloud 上的高算力 Ops Agent",
            "url": "https://my-deployment.langsmith.com",
            "assistant_id": "ops",
            "api_key_env": "LANGGRAPH_API_KEY"
        }
    ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 唯一 SubAgent 名称（供 `olav_delegate` 工具路由） |
| `description` | ✅ | 供 Orchestrator 路由决策的描述 |
| `url` | ✅ | LangGraph 部署 URL |
| `assistant_id` | ✅ | 远程部署上的 Graph/Assistant ID |
| `api_key_env` | ❌ | 持有 API 密钥的环境变量名，未设置时回退到 `LANGGRAPH_API_KEY` |

远程 SubAgent 在启动时与本地 workspace SubAgent 一起加载。连接失败时优雅跳过，不阻塞本地 Agent 初始化。

---

## Hook 系统

在 `~/.olav/hooks.json` 中配置由 OLAV 会话事件触发的外部命令：

```json
{
    "hooks": [
        { "event": "session.start", "command": "notify-send 'OLAV 会话已启动'" },
        { "event": "tool.call",     "command": "logger -t olav '工具: $OLAV_HOOK_TOOL'" }
    ]
}
```

完整事件参考见 [Agent Harness → 事件 Hook 系统](../concepts/agent-harness.md#hook)。
