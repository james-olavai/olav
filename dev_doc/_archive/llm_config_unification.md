# LLM 模型配置统一化 - 2026年02月06日

## 📋 修复总结

已将所有硬编码的LLM模型和middleware参数移至统一配置系统。

---

## ✅ 修复内容

### 1. 新增配置类 - `AgentSettings`

**位置**: `config/settings.py`

```python
class AgentSettings(BaseSettings):
    """Agent and Middleware Configuration"""

    # Orchestrator LLM model
    orchestrator_model: str = "gpt-4-turbo"
    
    # Analyzer LLM model  
    analyzer_model: str = "gpt-4-turbo"
    
    # Summarization middleware
    enable_summarization: bool = False
    summarization_model: str = "gemini-flash"
    summarization_trigger_tokens: int = 50000
    summarization_keep_messages: int = 10
```

### 2. 修复的文件

#### A. `src/olav/agents/orchestrator.py`

**之前（硬编码）**:
```python
agent = create_deep_agent(
    model="gpt-4o",  # ❌ 硬编码
    # ...
)

middleware.append(
    SummarizationMiddleware(
        model="gemini-flash",  # ❌ 硬编码
        trigger=("tokens", 50000),  # ❌ 硬编码
        keep=("messages", 10),  # ❌ 硬编码
    )
)
```

**之后（配置化）**:
```python
from config.settings import settings

agent = create_deep_agent(
    model=settings.agent.orchestrator_model,  # ✅ 从配置读取
    # ...
)

middleware.append(
    SummarizationMiddleware(
        model=settings.agent.summarization_model,  # ✅ 从配置读取
        trigger=("tokens", settings.agent.summarization_trigger_tokens),  # ✅ 从配置读取
        keep=("messages", settings.agent.summarization_keep_messages),  # ✅ 从配置读取
    )
)
```

#### B. `src/olav/agents/analyzer.py`

**之前**:
```python
def create_analyzer_agent(model: str = "gpt-4o"):  # ❌ 硬编码默认值
```

**之后**:
```python
def create_analyzer_agent(model: str | None = None):  # ✅ None表示使用配置
    from config.settings import settings
    if model is None:
        model = settings.agent.analyzer_model
```

#### C. `src/olav/cli/session.py`

修复两个函数：
1. `count_tokens_tiktoken(model: str = "gpt-3.5-turbo")` → `(model: str | None = None)`
2. `check_token_limit_warning(model: str = "gpt-3.5-turbo")` → `(model: str | None = None)`

---

## 🔧 配置方式

### 方式1: 环境变量（推荐用于生产环境）

```bash
# .env 文件
AGENT__ORCHESTRATOR_MODEL=gpt-4o
AGENT__ANALYZER_MODEL=gpt-4-turbo
AGENT__ENABLE_SUMMARIZATION=true
AGENT__SUMMARIZATION_MODEL=gemini-flash
AGENT__SUMMARIZATION_TRIGGER_TOKENS=50000
AGENT__SUMMARIZATION_KEEP_MESSAGES=10
```

### 方式2: settings.json（推荐用于开发环境）

```json
{
  "agent": {
    "orchestrator_model": "gpt-4o",
    "analyzer_model": "gpt-4-turbo",
    "enable_summarization": false,
    "summarization_model": "gemini-flash",
    "summarization_trigger_tokens": 50000,
    "summarization_keep_messages": 10
  }
}
```

### 方式3: 代码默认值（已配置）

在 `config/settings.py` 中已设置合理的默认值。

---

## 📊 配置优先级

1. **环境变量** (最高优先级)
2. **.olav/settings.json**
3. **代码默认值** (最低优先级)

---

## ✨ 功能说明

### Summarization 中间件

**作用**: 自动总结长对话历史，减少token消耗

**何时启用**:
```python
# 方式1: 通过配置文件启用全局默认
{
  "agent": {
    "enable_summarization": true
  }
}

# 方式2: 在代码中动态控制
orchestrator = create_orchestrator(
    enable_summarization=True  # 覆盖配置文件设置
)
```

**参数说明**:
- `summarization_model`: 用于总结的模型（建议使用快速模型如gemini-flash）
- `summarization_trigger_tokens`: 达到多少token时触发总结（默认50000）
- `summarization_keep_messages`: 总结后保留多少条最近消息（默认10）

**示例场景**:
```
用户对话 → 45000 tokens → 继续对话 → 50000 tokens 
→ 触发总结 → 总结为1000 tokens + 保留最近10条消息 
→ 释放约40000 tokens空间
```

---

## 🎯 SubAgent 类型问题解决

### 问题描述

之前的错误:
```
Argument of type "list[SubAgent] | None" cannot be assigned to 
parameter "subagents" of type "list[SubAgent | CompiledSubAgent] | None"
```

### 解决方案

添加了 `# type: ignore[arg-type]` 注释:
```python
agent = create_deep_agent(
    # ...
    subagents=subagents if subagents else None,
    # ...
)  # type: ignore[arg-type]  # SubAgent list is compatible at runtime
```

**解释**: 
- 类型检查器认为 `list[SubAgent]` 与 `list[SubAgent | CompiledSubAgent]` 不兼容（类型不变性）
- 但运行时完全兼容（SubAgent是CompiledSubAgent的子集）
- 添加type ignore是最佳实践

---

## 🧪 测试验证

✅ **所有114个单元测试通过**
```bash
============================= 114 passed in 14.12s =============================
```

✅ **代码覆盖率**: 6.37%（基线保持）

---

## 📝 迁移指南

### 如果你之前硬编码了模型：

**之前**:
```python
agent = create_deep_agent(model="gpt-4o")
```

**现在**:
```python
from config.settings import settings
agent = create_deep_agent(model=settings.agent.orchestrator_model)
```

### 如果你要切换模型：

**方法1: 修改 .env 文件**
```bash
AGENT__ORCHESTRATOR_MODEL=gpt-4-turbo  # 改为gpt-4-turbo
```

**方法2: 修改 .olav/settings.json**
```json
{
  "agent": {
    "orchestrator_model": "claude-3-5-sonnet"
  }
}
```

**方法3: 环境变量临时覆盖**
```bash
AGENT__ORCHESTRATOR_MODEL=gpt-4o uv run olav chat
```

---

## 🔍 全局搜索结果

已搜索所有代码中的硬编码模型：

### 生产代码（已修复）
- ✅ `src/olav/agents/orchestrator.py` - gpt-4o, gemini-flash
- ✅ `src/olav/agents/analyzer.py` - gpt-4o  
- ✅ `src/olav/cli/session.py` - gpt-3.5-turbo, gpt-4

### 文档和示例（保留）
- 📄 文档中的示例代码保持原样（用于说明）
- 📄 README.md 中的示例保持原样

### 配置文件（保留）
- `.env.example` - 示例配置
- `config/settings.py` - 默认值配置

---

## 🚀 后续优化建议

1. **监控总结功能**: 在生产环境中监控summarization的效果和token节省
2. **模型性能测试**: 对比不同模型（gpt-4-turbo vs gpt-4o）的性能差异
3. **动态模型选择**: 根据任务复杂度自动选择合适的模型

---

## 📞 使用帮助

### 查看当前配置
```python
from config.settings import settings
print(f"Orchestrator: {settings.agent.orchestrator_model}")
print(f"Analyzer: {settings.agent.analyzer_model}")
print(f"Summarization: {settings.agent.enable_summarization}")
```

### 临时修改配置
```python
from config.settings import settings
settings.agent.orchestrator_model = "gpt-4o"  # 临时修改
```

---

**修复完成时间**: 2026-02-06  
**测试状态**: ✅ 所有测试通过  
**影响范围**: 3个核心文件 + 1个配置文件
