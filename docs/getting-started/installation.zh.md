# 安装

本页将引导你在 5 分钟内完成 OLAV 的安装和初始化。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-01 | `olav version` 正确报告版本号 | ✅ v0.10.0 |
    | C-L2-13 | `olav init` 创建项目目录结构 | ✅ v0.10.0 |

---

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.11+ | OLAV 的运行环境 |
| [`uv`](https://docs.astral.sh/uv/) | 推荐的 Python 包管理器，比 pip 快 10-100 倍 |
| LLM API Key | 支持 OpenAI、Anthropic、Ollama（本地）等多种提供商 |

## 第一步：下载并安装

```bash
git clone https://github.com/olav-ai/olav.git
cd olav
uv sync
```

验证安装是否成功：

```bash
uv run olav version
```

看到类似输出即表示安装成功：
```
Version:   v0.10.0
```

## 第二步：初始化项目

进入你的工作目录（通常是管理基础设施的项目目录），运行：

```bash
olav init
```

OLAV 会在当前目录创建 `.olav/` 文件夹，包含所有运行所需的配置和数据：

```
.olav/
├── config/
│   ├── api.json        ← LLM 和认证配置（包含密钥，不要提交到 git）
│   ├── services.yaml   ← 已注册的外部服务
│   └── settings.json   ← 平台设置（当前活跃 Agent 等）
├── databases/
│   ├── audit.duckdb    ← 审计日志（自动记录所有操作）
│   └── domain.duckdb   ← 业务数据（设备信息、解析结果等）
└── workspace/
    └── core/           ← 预装的核心 Agent
        ├── AGENT.md    ← Agent 的能力定义
        └── MANIFEST.yaml ← 路由关键词和版本信息
```

## 第三步：配置 LLM

编辑 `.olav/config/api.json`，填入你的 LLM API Key：

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
=== "OpenRouter（多模型聚合）"
    ```json
    {
      "llm": {
        "provider": "custom",
        "model": "openai/gpt-4o",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-..."
      }
    }
    ```
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

!!! warning "保护你的密钥"
    `api.json` 包含 API 密钥，**务必**加入 `.gitignore`，不要提交到版本控制。

## 第四步：设置 .gitignore

工作空间（workspace）可以安全提交到 git，与团队共享 Agent 定义。但配置和数据库不应提交：

```gitignore
# .gitignore
.olav/config/      # 包含 API 密钥
.olav/databases/   # 包含审计日志和业务数据
.olav/run/         # 运行时 PID 文件
```

```bash
git add .olav/workspace/
git commit -m "feat: init olav workspace"
```

---

!!! tip "环境变量方式配置"
    如果不想在文件中存储密钥，也可以通过环境变量配置：
    ```bash
    export OLAV_LLM_API_KEY="sk-..."
    export OLAV_LLM_MODEL="gpt-4o"
    ```
    详见 [配置参考 →](../reference/configuration.md)

**下一步：** [运行你的第一个查询 →](first-query.md)
