# OLAV v0.9.8 开发指南

> **版本**: v0.9.8  
> **更新日期**: 2026-02-01  
> **状态**: 生产文档  
> **适用人群**: 开发者、架构师、贡献者

---

## 📚 目录

1. [项目概述](#项目概述)
2. [快速开始](#快速开始)
3. [架构设计](#架构设计)
4. [开发规范](#开发规范)
5. [测试策略](#测试策略)
6. [部署指南](#部署指南)
7. [常见问题](#常见问题)
8. [参考文档](#参考文档)

---

## 项目概述

### 🎯 核心定位

**OLAV (Open Logic Agent for Network Visibility and Analysis)**  
网络运维智能助手 - 基于 DeepAgents 框架的自然语言网络查询和诊断系统

### ✨ 核心特性

| 特性 | 说明 | 性能指标 |
|-----|------|---------|
| 🗣️ 自然语言查询 | 用户用自然语言提问，自动路由到合适的专家 | 路由准确率 >95% |
| ⚡ 精确缓存匹配 | 基于精确字符串匹配的快速响应 | 命中延迟 <0.2s |
| 🧠 统一网络专家 | L2-L7 全栈网络诊断（BGP/OSPF/STP/VLAN/Security） | 诊断准确率 >90% |
| 🗄️ 统一数据库 | DuckDB 实现跨数据库 JOINs 查询 | 查询延迟 <2s |
| 🔄 ReAct 编排模式 | 自我修复、计划执行、工具调用 | 成功率 >85% |
| 🔐 多层安全防护 | 意图过滤 + 白名单 + 黑名单 + HITL | 误执行率 <0.1% |

### 📊 技术栈

```
核心框架: DeepAgents (Agentic AI) + LangChain
数据库: DuckDB (OLAP) + SQLAlchemy (ORM)
LLM: OpenAI GPT-4 / Anthropic Claude / 本地模型
网络自动化: Nornir + Netmiko + Napalm
测试: pytest + pytest-asyncio + coverage
质量: ruff (linter) + pyright (type checker)
```

---

## 快速开始

### 🛠️ 环境准备

**系统要求**:
- Python 3.11+
- Docker 20.10+ (可选)
- Git 2.30+

**推荐 IDE**:
- VS Code + Python Extension + Pylance
- PyCharm Professional

### 📦 安装依赖

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/olav.git
cd olav

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 3. 安装依赖（推荐使用 uv）
pip install uv
uv pip install -e ".[dev]"

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API keys
```

### ⚙️ 配置说明

**统一配置管理** (Pydantic Settings):

```python
# config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM Configuration
    llm_provider: str = "openai"  # openai/anthropic/ollama
    openai_api_key: str | None = None
    
    # Agent Configuration
    agent_dir: Path = Path(".olav")
    enable_hitl: bool = True  # Human-in-the-loop
    
    # Logging
    log_level: str = "INFO"  # DEBUG/INFO/WARNING/ERROR
    log_file: Path = Path("logs/olav.log")
    
    # Security
    whitelist_file: Path = Path("config/whitelist.txt")
    blacklist_file: Path = Path("config/blacklist.txt")
```

**配置优先级**: 环境变量 > .olav/settings.json > 默认值

### 🚀 运行 OLAV

```bash
# 交互式 CLI
uv run olav

# 单次查询
uv run olav query "显示所有 BGP 邻居"

# 批处理模式
cat queries.txt | uv run olav batch


### 🧪 快速验证

```bash
# 运行单元测试（快速，无外部依赖）
uv run pytest tests/unit/ -v

# 运行端到端测试（完整流程）
uv run pytest tests/e2e/test_network_query.py -v

# 检查代码质量
uv run ruff check src/ --fix
uv run pyright src/
```

---

## 架构设计

### 🏗️ 系统架构（K.I.S.S. 原则）

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface                        │
│         CLI  │  Web API  │  MCP Server  │  Webhook       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Orchestrator (统一协调器)                   │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 1. Cache Check (精确匹配)                        │  │
│  │    └─ Hit → FastPath (0.2s)                      │  │
│  │                                                   │  │
│  │ 2. Route + Plan (LLM)                            │  │
│  │    ├─ Query Agent → 结构化查询                   │  │
│  │    ├─ Expert Agent → 复杂诊断                    │  │
│  │    └─ Threshold Agent → 阈值监控                 │  │
│  │                                                   │  │
│  │ 3. Execute Agent(s)                              │  │
│  │    └─ Parallel execution if independent          │  │
│  │                                                   │  │
│  │ 4. Quality Evaluation (LLM)                      │  │
│  │    └─ Upgrade decision if needed                 │  │
│  │                                                   │  │
│  │ 5. Markdown Output (LLM)                         │  │
│  │    └─ User-friendly formatting                   │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌─────────┐  ┌──────────────┐  ┌──────────┐
│ Query   │  │ Expert       │  │Threshold │
│ Agent   │  │ Agent        │  │ Agent    │
│         │  │              │  │          │
│DB Query │  │RAG+ReAct+Web │  │ Monitor  │
└────┬────┘  └──────┬───────┘  └────┬─────┘
     │              │               │
     └──────────────┼───────────────┘
                    ▼
     ┌──────────────────────────────┐
     │      Data Gateway            │
     │  (Unified Data Access)       │
     └──────────┬───────────────────┘
                │
      ┌─────────┼──────────┐
      ▼         ▼          ▼
 ┌─────────┐ ┌──────┐ ┌─────────┐
 │DuckDB   │ │Device│ │Knowledge│
 │(OLAP)   │ │APIs  │ │  Base   │
 └─────────┘ └──────┘ └─────────┘
```

### 🧩 核心组件

#### 1. Orchestrator (统一协调器)

**职责**: 路由 + 执行 + 评估 + 输出

```python
class Orchestrator:
    """Unified coordinator for all operations"""
    
    async def orchestrate(self, query: str) -> Response:
        # 1. Cache check (exact match)
        cached = await self.cache.get(query)
        if cached:
            return cached  # FastPath <0.2s
        
        # 2. Route + Plan (LLM)
        plan = await self.route_and_plan(query)
        
        # 3. Execute agents
        results = await self.execute_agents(plan)
        
        # 4. Quality evaluation
        quality = await self.evaluate_quality(results)
        if quality.score < 0.7:
            results = await self.upgrade_to_expert(query)
        
        # 5. Markdown output
        output = await self.format_markdown(results)
        
        # 6. Cache and learn
        await self.cache.set(query, output)
        await self.learn_from_result(query, output, quality)
        
        return output
```

**关键特性**:
- ✅ 单一 LLM 入口（避免多次 LLM 调用）
- ✅ 精确缓存匹配（IP/设备名精确匹配）
- ✅ 质量驱动的升级策略
- ✅ 统一 Markdown 输出

#### 2. Expert Agent (网络诊断专家)

**能力**: RAG + ReAct + Web Search + Document Editing

```python
class ExpertAgent:
    """Network diagnostics expert with knowledge base"""
    
    async def diagnose(self, symptom: str) -> Diagnosis:
        # 1. Embedding search historical cases
        similar_cases = await self.kb.search(symptom, top_k=5)
        
        # 2. RAG search knowledge base
        docs = await self.kb.retrieve_docs(symptom)
        
        # 3. Web search (optional, for unknown issues)
        if not similar_cases:
            web_results = await self.web_search(symptom)
        
        # 4. ReAct diagnosis
        diagnosis = await self.react_agent.run(
            context=similar_cases + docs,
            tools=self.get_diagnostic_tools()
        )
        
        # 5. Auto-update knowledge base
        if diagnosis.is_new_pattern:
            await self.kb.add_case(diagnosis)
            await self.kb.vectorize()  # Trigger re-indexing
        
        return diagnosis
```

**知识库架构**:
```
.olav/knowledge/
├── docs/              # 人工维护文档
│   ├── protocols/     # BGP/OSPF/STP 协议手册
│   └── solutions/     # 常见故障解决方案
└── cases/             # Agent 自动记录的案例
    ├── 2026-02/       # 按月分组
    └── index.json     # 案例索引
```

#### 3. Query Agent (结构化查询)

**职责**: SQL 生成 + 执行 + 结果格式化

```python
class QueryAgent:
    """Structured query executor"""
    
    async def query(self, natural_language: str) -> QueryResult:
        # 1. Generate SQL from NL
        sql = await self.nl_to_sql(natural_language)
        
        # 2. Security check (whitelist)
        if not self.security.is_allowed(sql):
            raise SecurityError("Query not allowed")
        
        # 3. Execute query
        results = await self.db.execute(sql)
        
        # 4. Format results
        return self.format_results(results)
```

### 🗄️ 数据库设计

**DuckDB 架构** (单文件多表):

#### 📁 目录结构

```
.olav/
├── db/                         # 共享数据层
│   ├── orchestrator.duckdb    # Orchestrator 数据
│   ├── snapshots.duckdb       # 网络快照（只读）
│   ├── topology.duckdb        # 拓扑数据（只读）
│   ├── knowledge.duckdb       # 知识库向量索引
│   └── audit_logs.duckdb      # 命令审计日志
│
├── knowledge/                  # 知识库（Markdown）
│   ├── docs/                  # 人工维护文档
│   │   ├── protocols/         # BGP/OSPF/STP 手册
│   │   └── solutions/         # 常见故障方案
│   └── cases/                 # Agent 自动案例
│       └── 2026-02/           # 按月分组
│
└── skills/                    # Skill 专有数据
    └── network-expert/
        └── skill.duckdb       # 历史案例数据库
```

#### 🗂️ 核心表结构

**Orchestrator 数据库** (`.olav/db/orchestrator.duckdb`):

```sql
-- 执行计划缓存（精确匹配 + 学习）
CREATE TABLE execution_plan_cache (
    id UUID PRIMARY KEY DEFAULT uuid(),
    
    -- 查询信息
    query_text TEXT NOT NULL UNIQUE,  -- 精确匹配 key
    query_category TEXT,
    
    -- 执行计划
    execution_plan JSON NOT NULL,
    /* 示例: {"steps": [{"agent": "query", "params": {...}}]} */
    
    -- 路由学习
    agents_involved JSON,           -- ["query"] 或 ["log", "expert"]
    is_multi_agent BOOLEAN,
    initial_route TEXT,             -- 初始路由
    final_route TEXT,               -- 最终路由（可能升级）
    was_upgraded BOOLEAN,
    
    -- 性能指标
    success_rate FLOAT DEFAULT 1.0,
    avg_execution_time FLOAT,
    hit_count INTEGER DEFAULT 1,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 质量指标
CREATE TABLE quality_metrics (
    id UUID PRIMARY KEY,
    query_id UUID REFERENCES execution_plan_cache(id),
    quality_score FLOAT,            -- 0.0-1.0
    user_feedback INTEGER,          -- -1 (差) / 0 (中) / 1 (好)
    upgrade_triggered BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**网络快照数据库** (`.olav/db/snapshots.duckdb`):

```sql
-- 设备快照
CREATE TABLE device_snapshots (
    id UUID PRIMARY KEY,
    hostname TEXT NOT NULL,
    snapshot_time TIMESTAMP NOT NULL,
    config_text TEXT,
    routing_table JSON,
    interfaces JSON,
    system_info JSON
);

-- 拓扑数据
CREATE TABLE topology (
    id UUID PRIMARY KEY,
    source_device TEXT,
    source_interface TEXT,
    target_device TEXT,
    target_interface TEXT,
    link_type TEXT,  -- physical/logical/tunnel
    discovered_at TIMESTAMP
);
```

**知识库数据库** (`.olav/db/knowledge.duckdb`):

```sql
-- 文档源
CREATE TABLE knowledge_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    base_path TEXT,
    doc_type TEXT,          -- protocol/solution/case
    indexed_at TIMESTAMP
);

-- 文档块（向量化）
CREATE TABLE knowledge_chunks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES knowledge_sources(id),
    file_path TEXT NOT NULL,
    chunk_index INTEGER,
    content TEXT NOT NULL,
    embedding FLOAT[768],   -- 向量索引
    file_hash TEXT,
    created_at TIMESTAMP
);
```

**Expert Skill 数据库** (`.olav/skills/network-expert/skill.duckdb`):

```sql
-- 历史诊断案例（语义检索）
CREATE TABLE history_cases (
    id UUID PRIMARY KEY,
    
    -- 症状（语义检索）
    symptom TEXT NOT NULL,
    symptom_embedding FLOAT[768],  -- 向量索引
    
    -- 诊断过程
    devices_checked JSON,
    commands_used JSON,
    diagnosis_steps TEXT,
    
    -- 结论
    root_cause TEXT,
    solution TEXT,
    
    -- 时间信息
    created_at TIMESTAMP,
    age_days INTEGER GENERATED ALWAYS AS (
        CAST(CURRENT_TIMESTAMP - created_at AS INTEGER)
    ) STORED
);

-- 向量索引
CREATE INDEX idx_symptom_embedding 
ON history_cases USING HNSW(symptom_embedding);
```

### 🔐 安全架构

**多层防护**:

```python
# 1. Intent Filtering
if is_malicious_intent(query):
    return "Query rejected: Malicious intent detected"

# 2. Command Whitelist
ALLOWED_COMMANDS = [
    "show ip bgp summary",
    "show ip route",
    "show interface status"
]

# 3. Blacklist Check
FORBIDDEN_PATTERNS = [
    r"reload",
    r"shutdown",
    r"no\s+.*"  # Disable commands
]

# 4. HITL (Human-in-the-Loop)
if is_destructive_operation(cmd):
    approval = await request_human_approval(cmd)
    if not approval:
        return "Operation cancelled by user"
```

---

## 开发规范

### 📝 代码风格

**工具链**:
- **Linter**: ruff (replacing flake8, isort, black)
- **Type Checker**: pyright
- **Formatter**: ruff format

**配置** (`pyproject.toml`):
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "ANN", "B", "A"]
ignore = ["ANN101", "ANN102"]  # self, cls annotations

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "basic"
reportMissingTypeStubs = false
```

**运行检查**:
```bash
# Lint + Auto-fix
uv run ruff check src/ --fix

# Format code
uv run ruff format src/

# Type check
uv run pyright src/

# All checks (CI pipeline)
uv run ruff check src/ && uv run ruff format --check src/ && uv run pyright src/
```

### 🏗️ 项目结构

```
src/olav/
├── cli/                    # CLI interface
│   ├── commands.py        # CLI commands
│   ├── display.py         # Output formatting
│   └── session.py         # Session management
│
├── agents/                # Agent implementations
│   ├── orchestrator.py    # Main coordinator
│   ├── query_agent.py     # Structured queries
│   ├── expert_agent.py    # Network diagnostics
│   └── threshold_agent.py # Monitoring & alerting
│
├── knowledge/             # Knowledge base
│   ├── knowledge_base.py  # KB interface
│   ├── vectorizer.py      # Embedding indexing
│   └── retriever.py       # RAG retrieval
│
├── network/               # Network automation
│   ├── executor.py        # Command execution
│   ├── parser.py          # Output parsing
│   └── inventory.py       # Device inventory
│
├── database/              # Data layer
│   ├── gateway.py         # Unified data access
│   ├── models.py          # SQLAlchemy models
│   └── cache.py           # Cache management
│
└── utils/                 # Utilities
    ├── security.py        # Security checks
    ├── metrics.py         # Performance metrics
    └── errors.py          # Custom exceptions
```

### 📐 架构原则

#### ✅ DO's (必须遵守)

1. **K.I.S.S. 原则** - 保持简单愚蠢
   ```python
   # ✅ GOOD: Simple and clear
   cached = await self.cache.get(query)
   if cached:
       return cached
   
   # ❌ BAD: Over-engineered
   similarity = await self.semantic_search(query, threshold=0.95)
   if similarity.score >= similarity.threshold:
       return similarity.result
   ```

2. **单一职责** - 每个类/函数只做一件事
   ```python
   # ✅ GOOD: Single responsibility
   class Orchestrator:
       async def orchestrate(query: str): ...
   
   # ❌ BAD: Multiple responsibilities
   class SuperAgent:
       async def route_and_execute_and_format(query: str): ...
   ```

3. **依赖注入** - 使用构造函数注入依赖
   ```python
   # ✅ GOOD: Dependency injection
   class ExpertAgent:
       def __init__(self, kb: KnowledgeBase, llm: LLM):
           self.kb = kb
           self.llm = llm
   
   # ❌ BAD: Hard-coded dependencies
   class ExpertAgent:
       def __init__(self):
           self.kb = KnowledgeBase()  # Hard to test
   ```

#### ❌ DON'Ts (禁止使用)

1. **禁止创建冗余组件**
   ```python
   # ❌ FORBIDDEN
   class QualityChecker: pass
   class ResultMerger: pass
   class PlanAgent: pass
   
   # ✅ UNIFIED in Orchestrator
   ```

2. **禁止硬编码时间窗口**
   ```python
   # ❌ FORBIDDEN
   WHERE age_days <= 30
   
   # ✅ LET LLM JUDGE RELEVANCE
   ORDER BY created_at DESC LIMIT 10
   ```

3. **禁止草稿审核流程**
   ```python
   # ❌ FORBIDDEN
   .olav/drafts/ → Human Review → .olav/knowledge/
   
   # ✅ DIRECT EDIT + GIT ROLLBACK
   .olav/knowledge/ → Git commit → Vectorization
   ```

### 🧪 测试规范

**测试分级**:

```
tests/
├── unit/              # 单元测试 (快速, 无外部依赖)
│   ├── test_config.py
│   ├── test_security.py
│   └── test_utils.py
│
├── integration/       # 集成测试 (中等速度, 有外部服务)
│   ├── test_database.py
│   ├── test_llm_api.py
│   └── test_knowledge_base.py
│
└── e2e/               # 端到端测试 (慢速, 完整流程)
    ├── test_network_query.py
    ├── test_expert_diagnosis.py
    └── test_complete_validation.py
```

**运行策略**:
```bash
# 快速反馈 (开发时)
uv run pytest tests/unit/ -v

# 完整验证 (PR 前)
uv run pytest tests/unit/ tests/integration/ -v

# 全量测试 (CI/CD)
uv run pytest tests/ -v --cov=src/olav --cov-report=html
```

**覆盖率要求**:
- 核心模块 (agents/, database/) ≥ 80%
- 工具模块 (utils/) ≥ 70%
- 整体项目 ≥ 70%

### 📊 性能指标

**目标 SLA**:

| 操作 | P50 | P95 | P99 |
|------|-----|-----|-----|
| Cache Hit | <0.2s | <0.5s | <1s |
| Simple Query | <2s | <5s | <10s |
| Expert Diagnosis | <5s | <15s | <30s |
| Knowledge Retrieval | <1s | <3s | <5s |

**监控指标**:
```python
# metrics.py
from prometheus_client import Counter, Histogram

query_counter = Counter('olav_queries_total', 'Total queries', ['agent_type'])
query_duration = Histogram('olav_query_duration_seconds', 'Query duration')
cache_hit_ratio = Gauge('olav_cache_hit_ratio', 'Cache hit ratio')
llm_token_usage = Counter('olav_llm_tokens_total', 'LLM tokens used', ['model'])
```

---

## 测试策略

### 🧪 测试金字塔

```
        ╱╲
       ╱E2E╲        10% - 完整流程测试
      ╱──────╲
     ╱Integration╲  30% - 集成测试
    ╱────────────╲
   ╱     Unit      ╲ 60% - 单元测试
  ╱────────────────╲
```

### 📝 编写测试

**单元测试示例**:
```python
# tests/unit/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock
from olav.agents.orchestrator import Orchestrator

@pytest.mark.asyncio
async def test_cache_hit_returns_cached_response():
    # Arrange
    orchestrator = Orchestrator()
    orchestrator.cache = AsyncMock()
    orchestrator.cache.get.return_value = "cached response"
    
    # Act
    result = await orchestrator.orchestrate("test query")
    
    # Assert
    assert result == "cached response"
    orchestrator.cache.get.assert_called_once_with("test query")
```

**集成测试示例**:
```python
# tests/integration/test_knowledge_base.py
import pytest
from olav.knowledge.knowledge_base import KnowledgeBase

@pytest.mark.asyncio
async def test_add_document_triggers_vectorization():
    # Arrange
    kb = KnowledgeBase()
    doc_path = "test_doc.md"
    
    # Act
    await kb.add_document(doc_path, category="protocols")
    
    # Assert
    results = await kb.search("test query", top_k=1)
    assert len(results) > 0
```

**E2E 测试示例**:
```python
# tests/e2e/test_network_query.py
import pytest
from olav.cli.commands import run_query

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bgp_neighbor_query():
    # Act
    result = await run_query("显示所有 BGP 邻居")
    
    # Assert
    assert "BGP" in result
    assert "neighbor" in result.lower()
    assert result.status == "success"
```

### 🎭 Mock 策略

**Mock LLM 调用**:
```python
from unittest.mock import patch

@patch('olav.agents.expert_agent.OpenAI')
async def test_expert_diagnosis(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = {
        "choices": [{"message": {"content": "Diagnosis: Link down"}}]
    }
    
    agent = ExpertAgent()
    result = await agent.diagnose("BGP neighbor down")
    
    assert "Link down" in result
```

**Mock 网络设备**:
```python
@patch('olav.network.executor.NetmikoConnection')
async def test_device_command(mock_connection):
    mock_connection.return_value.send_command.return_value = "interface up"
    
    executor = NetworkExecutor()
    result = await executor.execute("show interface")
    
    assert "interface up" in result
```

---

## 部署指南

###  生产部署

**环境准备**:
```bash
# 1. Create user
sudo useradd -m -s /bin/bash olav

# 2. Install dependencies
sudo -u olav python -m venv /home/olav/.venv
sudo -u olav /home/olav/.venv/bin/pip install olav

# 3. Configure systemd
sudo tee /etc/systemd/system/olav.service <<EOF
[Unit]
Description=OLAV Network Assistant
After=network.target

[Service]
Type=simple
User=olav
WorkingDirectory=/home/olav
ExecStart=/home/olav/.venv/bin/olav serve
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# 4. Start service
sudo systemctl enable olav
sudo systemctl start olav
```

**健康检查**:
```bash
# Check service status
systemctl status olav

# View logs
journalctl -u olav -f
```

---

## 开发路线图

### 🎯 开发阶段与里程碑

**验收原则**:
- ✅ **真实环境测试** - 使用真实 LLM API 和真实网络设备
- ✅ **功能性验收** - 生产级别的功能完整性
- ✅ **E2E 验收测试** - 参考 `tests/00_e2e_acceptance_test.py`
- ⚠️ **质量指标** - 测试覆盖率和代码质量工具暂不作为验收要求

### 📋 开发阶段

#### Phase 0: 基础架构 (Foundation)

**目标**: 建立核心架构和数据层

**里程碑**:
1. ✅ 统一配置管理 (Settings + pydantic-settings)
2. ✅ DuckDB 数据库架构设计
3. ✅ Data Gateway 统一数据访问层
4. ✅ 日志系统配置 (轮转 + 级别控制)

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase0Foundation

def test_database_schema():
    """验证数据库表结构正确创建"""
    from olav.core.database import get_database
    
    with get_database() as db:
        # 验证 Orchestrator 表
        tables = db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
        
        required_tables = [
            'execution_plan_cache',
            'quality_metrics',
            'device_snapshots',
            'topology',
        ]
        
        for table in required_tables:
            assert table in [t[0] for t in tables], f"Missing table: {table}"

def test_config_loading():
    """验证配置正确加载"""
    from config.settings import settings
    
    assert settings.llm_provider in ['openai', 'anthropic', 'ollama']
    assert settings.agent_dir.exists()
    assert settings.log_level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']
```

**完成标准**: 所有 Phase 0 测试通过 ✅

---

#### Phase 1: 网络数据采集 (Network Data Collection)

**目标**: 实现设备连接和快照采集

**里程碑**:
1. ✅ Nornir inventory 管理 (从 hosts.yaml)
2. ✅ Netmiko 设备连接 (SSH/Telnet)
3. ✅ 命令执行框架 (白名单 + 黑名单)
4. ✅ 快照采集脚本 (show 命令批量执行)
5. ✅ 快照存储 (exports/snapshots/{date}/)

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase1DataCollection

def test_device_connectivity():
    """验证设备连接 (真实设备)"""
    from olav.network.executor import NetworkExecutor
    
    executor = NetworkExecutor()
    test_devices = ['R1', 'R2', 'SW1']  # 测试环境设备
    
    for device in test_devices:
        result = executor.connect(device)
        assert result.success, f"Device {device} connection failed"
        
        # 执行简单命令验证
        output = executor.execute(device, 'show version')
        assert len(output) > 0, f"No output from {device}"

def test_snapshot_collection():
    """验证快照采集 (真实设备)"""
    import subprocess
    from pathlib import Path
    
    # 执行快照采集
    result = subprocess.run(
        ['uv', 'run', 'python', 'scripts/collect_snapshots.py'],
        capture_output=True,
        text=True,
        timeout=300  # 5 分钟超时
    )
    
    assert result.returncode == 0, f"Snapshot collection failed: {result.stderr}"
    
    # 验证快照文件存在
    snapshot_dir = Path('exports/snapshots/latest')
    assert snapshot_dir.exists(), "Snapshot directory not found"
    
    # 验证每个设备的快照
    for device in ['R1', 'R2', 'SW1']:
        device_files = list(snapshot_dir.glob(f'{device}_*.txt'))
        assert len(device_files) > 0, f"No snapshots for {device}"
```

**完成标准**: 
- ✅ 至少 3 台真实设备连接成功
- ✅ 快照文件正确生成 (show version, show ip interface, etc.)
- ✅ 快照存储结构符合设计

---

#### Phase 2: 数据解析与存储 (Data Parsing & Storage)

**目标**: 解析快照数据并导入数据库

**里程碑**:
1. ✅ TextFSM 模板集成 (ntc-templates)
2. ✅ 解析器框架 (structured data extraction)
3. ✅ 数据导入器 (raw_importer.py)
4. ✅ 拓扑发现 (CDP/LLDP)
5. ✅ 数据验证 (完整性检查)

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase2DataParsing

def test_snapshot_parsing():
    """验证快照解析 (真实数据)"""
    from olav.network.parser import NetworkParser
    from pathlib import Path
    
    parser = NetworkParser()
    snapshot_dir = Path('exports/snapshots/latest')
    
    # 解析接口数据
    interface_file = snapshot_dir / 'R1_show_ip_interface_brief.txt'
    if interface_file.exists():
        interfaces = parser.parse_interfaces(interface_file.read_text())
        assert len(interfaces) > 0, "No interfaces parsed"
        assert 'interface' in interfaces[0], "Invalid interface data"

def test_data_import():
    """验证数据导入数据库 (真实数据)"""
    from olav.tools.raw_importer import import_sync_data
    from olav.core.database import get_database
    from pathlib import Path
    
    snapshot_dir = Path('exports/snapshots/latest')
    import_sync_data(snapshot_dir)
    
    # 验证数据库中有数据
    with get_database() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM device_snapshots"
        ).fetchone()[0]
        
        assert count > 0, "No snapshots in database"
        
        # 验证拓扑数据
        topo_count = db.execute(
            "SELECT COUNT(*) FROM topology"
        ).fetchone()[0]
        
        assert topo_count > 0, "No topology data in database"
```

**完成标准**:
- ✅ 成功解析至少 5 种 show 命令输出
- ✅ 数据库包含真实设备数据
- ✅ 拓扑关系正确发现

---

#### Phase 3: Query Agent (结构化查询)

**目标**: 实现自然语言到 SQL 的查询功能

**里程碑**:
1. ✅ SQL 生成器 (NL → SQL)
2. ✅ 安全检查 (SQL 注入防护)
3. ✅ 查询执行器 (DuckDB)
4. ✅ 结果格式化 (Markdown table)
5. ✅ 缓存机制 (精确匹配)

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase3QueryAgent

def test_simple_query_real_llm():
    """验证简单查询 (真实 LLM + 真实数据)"""
    from olav.agents.query_agent import QueryAgent
    
    agent = QueryAgent()
    
    # 测试查询: "显示所有设备的主机名"
    result = agent.query("显示所有设备的主机名")
    
    assert result.success, f"Query failed: {result.error}"
    assert 'R1' in result.output or 'R2' in result.output, "No device data"
    assert '|' in result.output, "Output not in table format"

def test_complex_query_real_llm():
    """验证复杂查询 (真实 LLM + 真实数据)"""
    from olav.agents.query_agent import QueryAgent
    
    agent = QueryAgent()
    
    # 测试查询: "找出所有 down 状态的接口"
    result = agent.query("找出所有 down 状态的接口")
    
    assert result.success, f"Query failed: {result.error}"
    # 验证输出包含状态信息
    assert 'down' in result.output.lower() or 'up' in result.output.lower()

def test_query_cache():
    """验证查询缓存 (精确匹配)"""
    from olav.agents.query_agent import QueryAgent
    from olav.core.database import get_database
    
    agent = QueryAgent()
    query_text = "显示所有设备"
    
    # 第一次查询
    result1 = agent.query(query_text)
    
    # 验证缓存已创建
    with get_database() as db:
        cached = db.execute(
            "SELECT * FROM execution_plan_cache WHERE query_text = ?",
            [query_text]
        ).fetchone()
        
        assert cached is not None, "Query not cached"
    
    # 第二次相同查询应该命中缓存
    result2 = agent.query(query_text)
    assert result2.cached == True, "Cache not hit"
```

**完成标准**:
- ✅ 至少 10 个真实查询成功执行 (使用真实 LLM)
- ✅ 查询结果正确且格式化良好
- ✅ 缓存命中率 >80% (相同查询)
- ✅ SQL 注入防护有效

---

#### Phase 4: Expert Agent (诊断专家)

**目标**: 实现复杂故障诊断和根因分析

**里程碑**:
1. ✅ 知识库架构 (.olav/knowledge/)
2. ✅ 向量化索引 (Embedding)
3. ✅ RAG 检索 (知识库 + 历史案例)
4. ✅ ReAct Agent (推理 + 工具调用)
5. ✅ 案例自动记录

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase4ExpertAgent

def test_simple_diagnosis_real_llm_real_device():
    """验证简单故障诊断 (真实 LLM + 真实设备)"""
    from olav.agents.expert_agent import ExpertAgent
    
    agent = ExpertAgent()
    
    # 模拟故障: "R1 的 Gi0/1 接口 down"
    symptom = "R1 的 Gi0/1 接口状态异常"
    
    result = agent.diagnose(symptom)
    
    assert result.success, f"Diagnosis failed: {result.error}"
    assert 'root_cause' in result.diagnosis, "No root cause identified"
    assert 'solution' in result.diagnosis, "No solution provided"
    
    # 验证诊断过程合理
    assert len(result.steps) > 0, "No diagnosis steps recorded"

def test_bgp_diagnosis_real_llm_real_device():
    """验证 BGP 故障诊断 (真实 LLM + 真实设备)"""
    from olav.agents.expert_agent import ExpertAgent
    
    agent = ExpertAgent()
    
    # 实际故障场景
    symptom = "R1 和 R2 之间的 BGP 邻居无法建立"
    
    result = agent.diagnose(symptom)
    
    assert result.success, f"Diagnosis failed: {result.error}"
    
    # 验证诊断质量
    diagnosis_text = result.diagnosis.get('root_cause', '')
    assert any(keyword in diagnosis_text.lower() for keyword in 
               ['bgp', 'neighbor', 'peer', 'session']), \
        "Diagnosis not relevant to BGP"

def test_knowledge_base_retrieval():
    """验证知识库检索"""
    from olav.knowledge.knowledge_base import KnowledgeBase
    
    kb = KnowledgeBase()
    
    # 搜索 BGP 相关知识
    results = kb.search("BGP neighbor troubleshooting", top_k=3)
    
    assert len(results) > 0, "No knowledge base results"
    assert 'bgp' in results[0]['content'].lower(), "Irrelevant KB results"

def test_case_auto_recording():
    """验证案例自动记录"""
    from olav.agents.expert_agent import ExpertAgent
    from olav.core.database import get_database
    
    agent = ExpertAgent()
    
    # 执行诊断
    symptom = "测试案例自动记录"
    result = agent.diagnose(symptom)
    
    # 验证案例已记录到数据库
    with get_database() as db:
        cases = db.execute(
            "SELECT * FROM history_cases WHERE symptom LIKE ?",
            [f"%{symptom}%"]
        ).fetchall()
        
        assert len(cases) > 0, "Case not recorded"
```

**完成标准**:
- ✅ 至少 5 个真实故障场景诊断成功 (使用真实 LLM + 真实设备)
- ✅ 知识库检索准确率 >70%
- ✅ 诊断结果包含根因和解决方案
- ✅ 案例自动记录到数据库
- ✅ 诊断时间 <30 秒 (P95)

---

#### Phase 5: Orchestrator (统一协调)

**目标**: 实现智能路由和质量评估

**里程碑**:
1. ✅ 路由决策 (Query vs Expert)
2. ✅ 执行计划缓存
3. ✅ 质量评估机制
4. ✅ 升级策略 (Query → Expert)
5. ✅ Markdown 输出格式化

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase5Orchestrator

def test_routing_to_query_agent():
    """验证路由到 Query Agent (真实 LLM)"""
    from olav.agents.orchestrator import Orchestrator
    
    orchestrator = Orchestrator()
    
    # 简单查询应该路由到 Query Agent
    result = orchestrator.orchestrate("显示所有设备的主机名")
    
    assert result.success
    assert result.agent_used == 'query', "Wrong agent selected"

def test_routing_to_expert_agent():
    """验证路由到 Expert Agent (真实 LLM)"""
    from olav.agents.orchestrator import Orchestrator
    
    orchestrator = Orchestrator()
    
    # 复杂诊断应该路由到 Expert Agent
    result = orchestrator.orchestrate("为什么 R1 的 BGP 邻居无法建立?")
    
    assert result.success
    assert result.agent_used == 'expert', "Wrong agent selected"

def test_quality_evaluation_and_upgrade():
    """验证质量评估和升级 (真实 LLM)"""
    from olav.agents.orchestrator import Orchestrator
    
    orchestrator = Orchestrator()
    
    # 模拟低质量结果触发升级
    # 例如: Query Agent 返回 10000 行数据
    result = orchestrator.orchestrate("分析所有路由的差异")
    
    # 如果 Query Agent 结果质量低，应该升级到 Expert
    if result.quality_score < 0.7:
        assert result.upgraded == True, "Should upgrade to expert"
        assert result.final_agent == 'expert'

def test_cache_hit_fastpath():
    """验证缓存命中 FastPath (<0.2s)"""
    from olav.agents.orchestrator import Orchestrator
    import time
    
    orchestrator = Orchestrator()
    query = "显示设备列表"
    
    # 第一次查询
    orchestrator.orchestrate(query)
    
    # 第二次相同查询应该命中缓存
    start = time.time()
    result = orchestrator.orchestrate(query)
    duration = time.time() - start
    
    assert result.cached == True
    assert duration < 0.5, f"Cache hit too slow: {duration}s"

def test_markdown_output_quality():
    """验证 Markdown 输出质量"""
    from olav.agents.orchestrator import Orchestrator
    
    orchestrator = Orchestrator()
    
    result = orchestrator.orchestrate("显示所有设备")
    
    # 验证输出是 Markdown 格式
    assert '|' in result.output or '#' in result.output, "Not Markdown format"
    # 验证可读性
    assert len(result.output) > 0, "Empty output"
```

**完成标准**:
- ✅ 路由准确率 >95% (正确选择 Agent)
- ✅ 缓存命中延迟 <0.5s (P95)
- ✅ 质量评估准确触发升级
- ✅ Markdown 输出格式规范

---

#### Phase 6: CLI 集成 (Command Line Interface)

**目标**: 实现用户友好的 CLI 界面

**里程碑**:
1. ✅ 交互式 REPL
2. ✅ 命令补全
3. ✅ 历史记录
4. ✅ 输出美化 (Rich)
5. ✅ 错误处理

**验收标准**:
```python
# tests/00_e2e_acceptance_test.py::TestPhase6CLI

def test_cli_single_query():
    """验证 CLI 单次查询 (真实 LLM + 真实设备)"""
    import subprocess
    
    result = subprocess.run(
        ['uv', 'run', 'olav', 'query', '显示所有设备'],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert len(result.stdout) > 0, "No output"

def test_cli_interactive_mode():
    """验证 CLI 交互模式"""
    import subprocess
    
    # 使用管道模拟交互
    process = subprocess.Popen(
        ['uv', 'run', 'olav'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # 发送查询
    output, error = process.communicate(input='显示所有设备\nexit\n', timeout=30)
    
    assert process.returncode == 0, f"Interactive mode failed: {error}"
    assert len(output) > 0, "No interactive output"

def test_cli_error_handling():
    """验证 CLI 错误处理"""
    import subprocess
    
    # 测试无效查询
    result = subprocess.run(
        ['uv', 'run', 'olav', 'query', ''],  # 空查询
        capture_output=True,
        text=True,
        timeout=10
    )
    
    # 应该优雅地处理错误
    assert 'error' in result.stderr.lower() or 'invalid' in result.stderr.lower()
```

**完成标准**:
- ✅ CLI 命令成功执行
- ✅ 交互模式正常工作
- ✅ 错误信息清晰友好
- ✅ 输出格式美观

---

### 🎯 最终验收标准 (Production Ready)

**Phase 7: 端到端生产验收**

```python
# tests/00_e2e_acceptance_test.py::TestPhase7ProductionAcceptance

def test_production_scenario_1_real_env():
    """生产场景 1: 设备查询 (真实 LLM + 真实设备)"""
    import subprocess
    
    queries = [
        "显示所有设备的主机名和 IP 地址",
        "找出所有 down 状态的接口",
        "显示 R1 的 BGP 邻居状态",
    ]
    
    for query in queries:
        result = subprocess.run(
            ['uv', 'run', 'olav', 'query', query],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0, f"Query failed: {query}"
        assert len(result.stdout) > 0, f"No output for: {query}"

def test_production_scenario_2_real_env():
    """生产场景 2: 故障诊断 (真实 LLM + 真实设备)"""
    import subprocess
    
    # 模拟真实故障场景
    symptom = "R1 和 R2 之间的 BGP 邻居无法建立，请帮我诊断原因"
    
    result = subprocess.run(
        ['uv', 'run', 'olav', 'query', symptom],
        capture_output=True,
        text=True,
        timeout=60  # 诊断可能需要更长时间
    )
    
    assert result.returncode == 0, "Diagnosis failed"
    output = result.stdout
    
    # 验证诊断质量
    assert any(keyword in output.lower() for keyword in 
               ['原因', 'root cause', '问题', 'issue']), \
        "No root cause in diagnosis"
    
    assert any(keyword in output.lower() for keyword in 
               ['解决', 'solution', '建议', 'recommendation']), \
        "No solution in diagnosis"

def test_production_scenario_3_real_env():
    """生产场景 3: 性能分析 (真实 LLM + 真实设备)"""
    import subprocess
    import time
    
    # 测试性能
    queries = [
        "显示所有设备",  # 简单查询
        "分析核心路由器的 CPU 使用率趋势",  # 复杂分析
    ]
    
    for query in queries:
        start = time.time()
        result = subprocess.run(
            ['uv', 'run', 'olav', 'query', query],
            capture_output=True,
            text=True,
            timeout=60
        )
        duration = time.time() - start
        
        assert result.returncode == 0, f"Query failed: {query}"
        
        # 性能要求
        if '显示所有' in query:  # 简单查询
            assert duration < 5, f"Simple query too slow: {duration}s"
        else:  # 复杂分析
            assert duration < 30, f"Complex query too slow: {duration}s"

def test_production_reliability():
    """生产可靠性测试: 连续执行 10 次查询"""
    import subprocess
    
    query = "显示所有设备的主机名"
    failures = 0
    
    for i in range(10):
        result = subprocess.run(
            ['uv', 'run', 'olav', 'query', query],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            failures += 1
    
    # 成功率 >90%
    success_rate = (10 - failures) / 10
    assert success_rate >= 0.9, f"Success rate too low: {success_rate}"
```

**最终验收要求**:

| 类别 | 指标 | 要求 |
|------|------|------|
| **功能性** | 所有 Phase 测试通过 | ✅ 100% |
| **真实环境** | 使用真实 LLM API | ✅ 必须 |
| **真实设备** | 使用真实网络设备 | ✅ 至少 3 台 |
| **查询成功率** | 简单查询成功率 | ≥95% |
| **诊断成功率** | 故障诊断成功率 | ≥85% |
| **性能** | 简单查询延迟 (P95) | <5s |
| **性能** | 复杂诊断延迟 (P95) | <30s |
| **缓存** | 缓存命中延迟 | <0.5s |
| **可靠性** | 连续查询成功率 | ≥90% |

**运行完整验收测试**:
```bash
# 运行所有验收测试
uv run pytest tests/00_e2e_acceptance_test.py -v

# 运行特定阶段
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase3QueryAgent -v

# 运行生产验收
uv run pytest tests/00_e2e_acceptance_test.py::TestPhase7ProductionAcceptance -v
```

**验收通过标准**:
- ✅ 所有 Phase 0-7 测试通过
- ✅ 生产场景测试通过
- ✅ 性能指标达标
- ✅ 可靠性测试通过

**验收通过 = v0.9.8 生产就绪** 🎉

---

## 常见问题

### ❓ 开发相关

**Q: 如何添加新的 Agent?**

A: 继承 `BaseAgent` 并实现 `execute()` 方法:
```python
from olav.agents.base import BaseAgent

class MyAgent(BaseAgent):
    async def execute(self, query: str) -> Result:
        # Your logic here
        return Result(data=..., metadata=...)
```

然后在 Orchestrator 中注册:
```python
# orchestrator.py
self.agents = {
    "query": QueryAgent(),
    "expert": ExpertAgent(),
    "my_agent": MyAgent()  # Register here
}
```

**Q: 如何调试 LLM 调用?**

A: 设置环境变量启用详细日志:
```bash
export LOG_LEVEL=DEBUG
export LANGCHAIN_VERBOSE=true
uv run olav query "test"
```

**Q: 如何更新知识库?**

A: 直接编辑 `.olav/knowledge/docs/` 下的 Markdown 文件，然后运行:
```bash
uv run olav knowledge index
```

### ❓ 测试相关

**Q: 如何跳过慢速测试?**

A: 使用 pytest markers:
```bash
# Skip e2e tests
uv run pytest -m "not e2e"

# Only run unit tests
uv run pytest tests/unit/
```

**Q: 如何生成覆盖率报告?**

A:
```bash
uv run pytest --cov=src/olav --cov-report=html
open htmlcov/index.html
```

### ❓ 部署相关

**Q: 生产环境如何配置日志轮转?**

A: 使用 `logging.handlers.RotatingFileHandler`:
```python
# config/logging.py
handler = RotatingFileHandler(
    "logs/olav.log",
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
```

---

## 参考文档

### 📖 内部文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [01_db_design.md](01_db_design.md) | 数据库架构设计 | ✅ 稳定 |
| [02_expert_design.md](02_expert_design.md) | Expert Agent 设计 | ✅ 稳定 |
| [03_router_design.md](03_router_design.md) | Orchestrator 设计 | ✅ 稳定 |
| [04_knowledge_base_implementation.md](04_knowledge_base_implementation.md) | 知识库实现指南 | 🚧 待实现 |
| [100_audit_report_claude.md](100_audit_report_claude.md) | 架构审计报告 | ✅ 归档 |

### 📚 外部资源

- **DeepAgents**: https://github.com/langchain-ai/deepagents
- **LangChain**: https://python.langchain.com/docs/
- **DuckDB**: https://duckdb.org/docs/
- **Nornir**: https://nornir.readthedocs.io/

### 🎓 学习路径

**新手 (0-2周)**:
1. 阅读本文档 (00_development_guide.md)
2. 运行示例查询熟悉功能
3. 阅读 [01_db_design.md](01_db_design.md)
4. 修改简单 bug 或添加测试

**进阶 (2-4周)**:
1. 阅读 [02_expert_design.md](02_expert_design.md)
2. 阅读 [03_router_design.md](03_router_design.md)
3. 实现新的诊断规则
4. 优化现有 Agent 性能

**高级 (4周+)**:
1. 设计新的 Agent 类型
2. 优化架构设计
3. 贡献核心功能
4. Review 其他开发者的 PR

---

## 📝 变更日志

### v0.9.8 (2026-02-01)
- ✅ 统一配置管理 (Pydantic Settings)
- ✅ 知识库核心实现
- ✅ 测试策略标准化
- ✅ 性能监控框架

### v0.9.0 (2026-01-15)
- 🎯 K.I.S.S. 架构重构
- ⚡ 精确缓存匹配
- 🧠 统一网络专家
- 🗄️ DuckDB 数据库整合

---

## 🤝 贡献指南

欢迎贡献! 请遵循以下流程:

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交 Pull Request

**PR 检查清单**:
- [ ] 代码通过 ruff + pyright 检查
- [ ] 添加了单元测试
- [ ] 更新了相关文档
- [ ] 通过了 CI/CD pipeline

---

## 📄 许可证

MIT License - 详见 [LICENSE](../LICENSE)

---

**版本**: v0.9.8  
**更新**: 2026-02-01  
**维护者**: OLAV Development Team
