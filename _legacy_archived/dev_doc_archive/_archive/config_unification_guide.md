# OLAV Configuration Unification Guide

## 配置系统架构 (v0.9.8+)

OLAV使用三层配置优先级系统：

```
Environment Variables (.env) → Settings.json → Code Defaults
        (最高优先级)                              (最低优先级)
```

---

## 1. 全局LLM配置

### .env 配置（主配置文件）

```bash
# 主LLM API配置（所有agent默认使用）
LLM_PROVIDER=openai                # openai, ollama, azure, xai, anthropic
LLM_BASE_URL=https://openrouter.ai/api/v1  # OpenRouter / 自定义API端点
LLM_API_KEY=sk-or-v1-xxx...        # API密钥
LLM_MODEL_NAME=x-ai/grok-4.1-fast  # 默认模型名
LLM_TEMPERATURE=0.1                # 生成温度
LLM_MAX_TOKENS=32000               # 最大token数
```

### settings.py 映射

```python
class Settings(BaseSettings):
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model_name: str = "gpt-4-turbo"
    llm_base_url: str = ""
    llm_temperature: float = 0.1
    llm_max_tokens: int = 16000
```

---

## 2. Agent专属LLM配置（v0.9.8+）

### 配置架构说明

**每个Agent支持独立的三元组配置**：
- `{AGENT}_MODEL`: 模型名称
- `{AGENT}_BASE_URL`: API端点（为空时使用全局LLM_BASE_URL）
- `{AGENT}_API_KEY`: API密钥（为空时使用全局LLM_API_KEY）

### .env 配置示例

```bash
# ========== Orchestrator Agent (路由和协调) ==========
AGENT__ORCHESTRATOR_MODEL=x-ai/grok-4.1-fast
AGENT__ORCHESTRATOR_BASE_URL=https://openrouter.ai/api/v1
AGENT__ORCHESTRATOR_API_KEY=sk-or-v1-xxx...

# ========== Analyzer Agent (网络分析) ==========
AGENT__ANALYZER_MODEL=gpt-4o
AGENT__ANALYZER_BASE_URL=https://api.openai.com/v1
AGENT__ANALYZER_API_KEY=sk-xxx...

# ========== Guard Agent (安全过滤) ==========
AGENT__GUARD_MODEL=gpt-4o-mini
AGENT__GUARD_BASE_URL=https://openrouter.ai/api/v1
AGENT__GUARD_API_KEY=sk-or-v1-xxx...

# ========== TextFSM Agent (模板生成) ==========
AGENT__TEXTFSM_MODEL=gpt-4-turbo
AGENT__TEXTFSM_BASE_URL=https://openrouter.ai/api/v1
AGENT__TEXTFSM_API_KEY=sk-or-v1-xxx...

# ========== LLM Interface (Map-Reduce) ==========
AGENT__LLM_INTERFACE_MODEL=claude-sonnet-4-20250514
AGENT__LLM_INTERFACE_BASE_URL=https://api.anthropic.com/v1
AGENT__LLM_INTERFACE_API_KEY=sk-ant-xxx...

# ========== Summarization Middleware (对话摘要) ==========
AGENT__ENABLE_SUMMARIZATION=false
AGENT__SUMMARIZATION_MODEL=gemini-flash
AGENT__SUMMARIZATION_BASE_URL=https://generativelanguage.googleapis.com/v1
AGENT__SUMMARIZATION_API_KEY=AIzaSyxxx...
AGENT__SUMMARIZATION_TRIGGER_TOKENS=50000
AGENT__SUMMARIZATION_KEEP_MESSAGES=10
```

### settings.py 映射

```python
class AgentSettings(BaseSettings):
    # Orchestrator
    orchestrator_model: str = "gpt-4-turbo"
    orchestrator_base_url: str = ""  # 空 = 使用全局 LLM_BASE_URL
    orchestrator_api_key: str = ""   # 空 = 使用全局 LLM_API_KEY
    
    # Analyzer
    analyzer_model: str = "gpt-4-turbo"
    analyzer_base_url: str = ""
    analyzer_api_key: str = ""
    
    # Guard
    guard_model: str = "gpt-4-turbo"
    guard_base_url: str = ""
    guard_api_key: str = ""
    
    # TextFSM
    textfsm_model: str = "gpt-4-turbo"
    textfsm_base_url: str = ""
    textfsm_api_key: str = ""
    
    # LLM Interface
    llm_interface_model: str = "claude-sonnet-4-20250514"
    llm_interface_base_url: str = ""
    llm_interface_api_key: str = ""
    
    # Summarization
    summarization_model: str = "gemini-flash"
    summarization_base_url: str = ""
    summarization_api_key: str = ""

    # Helper method
    def get_agent_config(self, agent_name: str, global_settings: Settings) -> dict:
        """获取agent配置，自动fallback到全局配置"""
        return {
            "model": getattr(self, f"{agent_name}_model"),
            "base_url": getattr(self, f"{agent_name}_base_url") or global_settings.llm_base_url,
            "api_key": getattr(self, f"{agent_name}_api_key") or global_settings.llm_api_key,
        }
```

---

## 3. 配置优先级和Fallback机制

### Fallback规则

每个Agent的配置遵循以下fallback顺序：

```
Agent专属配置 → 全局LLM配置 → 代码默认值
```

**示例1: 完全使用全局配置**
```bash
# .env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-xxx
LLM_MODEL_NAME=x-ai/grok-4.1-fast
```
结果：所有agent都使用grok-4.1-fast + openrouter

**示例2: 部分agent使用专属配置**
```bash
# .env - 全局配置
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-xxx
LLM_MODEL_NAME=x-ai/grok-4.1-fast

# Guard使用更快更便宜的模型
AGENT__GUARD_MODEL=gpt-4o-mini
# 不配置GUARD_BASE_URL和API_KEY，自动使用全局配置
```
结果：
- Orchestrator: grok-4.1-fast @ openrouter ✅
- Analyzer: grok-4.1-fast @ openrouter ✅  
- Guard: gpt-4o-mini @ openrouter ✅ (模型专属，端点继承)
- TextFSM: grok-4.1-fast @ openrouter ✅

**示例3: 多API端点混用**
```bash
# 全局使用OpenRouter
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-xxx
LLM_MODEL_NAME=x-ai/grok-4.1-fast

# Analyzer使用官方OpenAI
AGENT__ANALYZER_MODEL=gpt-4o
AGENT__ANALYZER_BASE_URL=https://api.openai.com/v1
AGENT__ANALYZER_API_KEY=sk-proj-xxx...

# LLM Interface使用Anthropic
AGENT__LLM_INTERFACE_MODEL=claude-sonnet-4-20250514
AGENT__LLM_INTERFACE_BASE_URL=https://api.anthropic.com/v1
AGENT__LLM_INTERFACE_API_KEY=sk-ant-xxx...
```
结果：每个agent使用各自的API端点！

### 在代码中使用配置

```python
from config.settings import settings

# 方法1: 直接访问
model = settings.agent.orchestrator_model
base_url = settings.agent.orchestrator_base_url or settings.llm_base_url
api_key = settings.agent.orchestrator_api_key or settings.llm_api_key

# 方法2: 使用辅助方法（推荐）
config = settings.agent.get_agent_config("orchestrator", settings)
# config = {"model": "...", "base_url": "...", "api_key": "..."}

# 方法3: 传递给LLM创建函数
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=config["model"],
    openai_api_base=config["base_url"],
    openai_api_key=config["api_key"],
)
```

---

## 4. 配置规范

### ✅ 推荐做法

1. **全局配置放在.env**
   ```bash
   LLM_API_KEY=xxx
   LLM_BASE_URL=https://api.xxx.com
   LLM_MODEL_NAME=default-model
   ```

2. **Agent专属配置使用前缀**
   ```bash
   AGENT__ORCHESTRATOR_MODEL=specific-model
   ```

3. **代码中使用settings读取**
   ```python
   from config.settings import settings
   model = settings.agent.orchestrator_model
   ```

### ❌ 避免做法

1. **硬编码模型名称**
   ```python
   # ❌ 错误
   model = "gpt-4o"
   
   # ✅ 正确
   model = settings.agent.orchestrator_model
   ```

2. **绕过配置系统**
   ```python
   # ❌ 错误
   import os
   model = os.getenv("LLM_MODEL_NAME")
   
   # ✅ 正确
   from config.settings import settings
   model = settings.llm_model_name
   ```

---

## 5. 配置验证

### 检查当前配置

```bash
# 通过CLI查看
uv run olav config show

# Python中检查
from config.settings import settings
print(settings.agent.model_dump())
```

### 配置测试

```python
# tests/test_config.py示例
def test_agent_config():
    from config.settings import settings
    
    # 验证默认值
    assert settings.agent.orchestrator_model == "gpt-4-turbo"
    
    # 验证环境变量覆盖
    os.environ["AGENT__ORCHESTRATOR_MODEL"] = "test-model"
    settings_reload = Settings()
    assert settings_reload.agent.orchestrator_model == "test-model"
```

---

## 6. 故障排查

### 问题: 配置未生效

**检查步骤**:
1. 确认.env文件加载
   ```bash
   cat .env | grep LLM_MODEL_NAME
   ```

2. 检查环境变量
   ```bash
   printenv | grep AGENT__
   ```

3. Python中验证
   ```python
   from config.settings import settings
   print(settings.agent.orchestrator_model)
   ```

### 问题: Type错误

**原因**: Pydantic严格类型检查

**解决**:
```python
# settings.py中添加validator
@field_validator("orchestrator_model")
def validate_model_name(cls, v: str) -> str:
    if not v:
        raise ValueError("Model name cannot be empty")
    return v
```

---

## 7. 迁移指南

### 从硬编码迁移到配置

**Before**:
```python
def create_agent():
    return ChatOpenAI(model="gpt-4o")
```

**After**:
```python
from config.settings import settings

def create_agent():
    return ChatOpenAI(model=settings.agent.orchestrator_model)
```

### 从环境变量迁移到配置

**Before**:
```python
import os
model = os.getenv("LLM_MODEL_NAME", "gpt-4-turbo")
```

**After**:
```python
from config.settings import settings
model = settings.llm_model_name  # 自动处理env + 默认值
```

---

## 8. 配置文件对照表

| 环境变量 | settings.py字段 | 代码默认值 | 说明 |
|---------|----------------|-----------|------|
| `LLM_MODEL_NAME` | `llm_model_name` | `gpt-4-turbo` | 全局默认模型 |
| `AGENT__ORCHESTRATOR_MODEL` | `agent.orchestrator_model` | `gpt-4-turbo` | Orchestrator模型 |
| `AGENT__ANALYZER_MODEL` | `agent.analyzer_model` | `gpt-4-turbo` | Analyzer模型 |
| `AGENT__TEXTFSM_MODEL` | `agent.textfsm_model` | `gpt-4-turbo` | TextFSM模型 |
| `AGENT__LLM_INTERFACE_MODEL` | `agent.llm_interface_model` | `claude-sonnet-4` | LLMInterface模型 |
| `AGENT__ENABLE_SUMMARIZATION` | `agent.enable_summarization` | `False` | 启用摘要 |
| `AGENT__SUMMARIZATION_MODEL` | `agent.summarization_model` | `gemini-flash` | 摘要模型 |

---

**版本**: v0.9.8  
**最后更新**: 2026-02-06
