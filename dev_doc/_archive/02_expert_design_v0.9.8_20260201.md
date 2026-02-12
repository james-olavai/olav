# OLAV Network Expert Agent 设计文档

> **版本**: v0.9.8  
> **创建日期**: 2026-02-01  
> **状态**: 架构设计方案

---

## 📋 执行摘要

### Expert Agent 核心定位

> **复杂问题专家 + 自进化知识系统**

#### 适用场景

**1. 故障诊断** (传统场景)
```
用户: "为什么 R2 BGP 邻居 Down?"
Expert: 
  - 检索知识库（白名单模式）
  - 网络搜索（可选，未知问题）
  - ReAct 推理 → 根因分析 → 解决方案
  - 自动记录案例 → 更新知识库草稿
```

**2. 复杂查询**
```
用户: "R1 和 R2 的 BGP 路由有什么差异？"
Orchestrator: DB Query 返回 10000 条 → 质量评估低 → 升级到 Expert
Expert: 计算差异集 → 归类分析 → 总结关键差异
```

**3. 根因分析**
```
用户: "为什么最近一周核心路由器的 CPU 使用率波动这么大？"
Expert: 时间序列分析 → 事件关联 → 推理根因
```

**4. 趋势预测**
```
用户: "按照当前增长速度，R1 的接口带宽什么时候会耗尽？"
Expert: 历史数据拟合 → 趋势外推 → 容量规划建议
```

---

## 🏗️ 架构设计

### 三层知识架构

**目录位置**: `.olav/knowledge/` （运行时数据，用户管理）

**为什么选择 `.olav/` 而不是根目录？**
- ✅ 架构一致性：`.olav/` 是运行时数据，`src/` 是应用代码
- ✅ 对称设计：`.olav/skills/` (能力) + `.olav/knowledge/` (知识)
- ✅ 平台兼容：对应 Claude Code 的 `.claude/knowledge/`
- ✅ 数据管理：用户只需备份 `.olav/` 目录
- ✅ 版本控制：`.gitignore` 排除 `.olav/`，避免提交自动生成的案例

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Static Knowledge Base (白名单模式)             │
│ .olav/knowledge/ (Markdown 文档)                         │
│ - protocols/bgp_troubleshooting.md                      │
│ - solutions/mtu_mismatch.md                             │
│ - 文档为准，Agent 可编辑，自动触发向量化               │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Vector Index (向量索引)                        │
│ .olav/db/knowledge.duckdb (自动生成)                     │
│ - document_embedding                                    │
│ - RAG 检索                                              │
│ - 通过命令更新: olav knowledge index                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Dynamic Cases (Embedding 搜索)                 │
│ .olav/skills/network-expert/skill.duckdb                │
│ - history_cases 表                                      │
│ - symptom_embedding (语义检索)                          │
│ - Agent 自动记录                                        │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Layer 4: Web Search (可选增强)                          │
│ - 未知问题时触发                                        │
│ - 敏感信息过滤                                          │
│ - 来源标注                                              │
└─────────────────────────────────────────────────────────┘
```

---

## 🛠️ 核心能力

### 1. Embedding 语义检索

**历史案例表（升级）**:
```sql
CREATE TABLE history_cases (
    id UUID PRIMARY KEY DEFAULT uuid(),
    
    -- 症状（语义检索）
    symptom TEXT NOT NULL,
    symptom_embedding FLOAT[768],  -- ✅ 新增
    
    -- 诊断过程
    devices_checked JSON,
    commands_used JSON,
    diagnosis_steps TEXT,
    
    -- 结论
    root_cause TEXT,
    solution TEXT,
    
    -- 时间信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    age_days INTEGER GENERATED ALWAYS AS (
        CAST((CURRENT_DATE - created_at::DATE) AS INTEGER)
    ) STORED
);

-- 向量搜索索引
CREATE INDEX idx_symptom_embedding ON history_cases 
    USING HNSW(symptom_embedding) WITH (M=16, EFC=200);
```

**语义检索示例**:
```python
# ✅ Embedding 搜索（语义相似）
similar_cases = search_similar_cases_embedding(
    symptom="BGP 邻居不稳定",
    threshold=0.85
)

# 可以匹配到：
# - "BGP neighbor flapping"
# - "BGP peer 不可达"
# - "BGP session down intermittently"
```

### 2. 网络搜索能力

**应用场景**:
```python
class ExpertAgent:
    def __init__(self, enable_web_search: bool = False):
        self.enable_web_search = enable_web_search
        if enable_web_search:
            from deepagents.middleware.web_search import WebSearchMiddleware
            self.web_search = WebSearchMiddleware()
    
    async def diagnose(self, symptom: str):
        # 1. 本地知识（优先）
        local_knowledge = await self.search_local_knowledge(symptom)
        
        # 2. 网络搜索（可选）
        web_knowledge = None
        if self.enable_web_search and not local_knowledge:
            # 敏感信息过滤
            filtered_query = self._filter_sensitive_info(symptom)
            web_knowledge = await self.web_search.search(filtered_query)
        
        # 3. 融合知识（标注来源）
        context = {
            "local": local_knowledge,       # 优先级: ⭐⭐⭐⭐⭐
            "web": web_knowledge,           # 优先级: ⭐⭐
            "priority": "local > web"
        }
        
        return await self.llm_diagnose(symptom, context)
    
    def _filter_sensitive_info(self, query: str) -> str:
        """移除敏感信息（设备名、IP、域名）"""
        import re
        
        # 替换设备名（R1, SW1, etc.）
        query = re.sub(r'\b(R|SW|FW|AP)\d+\b', 'DEVICE', query)
        
        # 替换 IP 地址
        query = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', 'IP_ADDRESS', query)
        
        # 替换域名
        query = re.sub(r'\b[\w-]+\.(com|net|org|cn)\b', 'DOMAIN', query)
        
        return query
```

**示例**:
```
场景: 未知新特性配置

用户: "Cisco IOS-XR 的 BGP ADD-PATH 功能怎么配置？"

Expert:
1. search_local_knowledge("BGP ADD-PATH") → 空
2. web_search("BGP ADD-PATH DEVICE configuration") → Cisco 官方文档
3. 综合给出配置建议（标注"来自网络搜索"）

结果: ✅ 处理了之前无法回答的问题
```

### 3. 文档编辑能力（白名单模式）

**设计原则**:
- ✅ **文档为准**: `.olav/knowledge/` 目录为唯一真理源
- ✅ **Agen可编辑**: 诊断完成后自动创建/更新 Markdown
- ✅ **自动向量化**: 文档变更触发向量索引更新
- ❌ **无需审核**: 去掉草稿/审核流程，直接编辑

**目录结构**:
```
.olav/
├── knowledge/              # 知识库（文档为准，白名单模式）
│   ├── protocols/          # 协议排错手册
│   │   ├── bgp_troubleshooting.md
│   │   ├── ospf_troubleshooting.md
│   │   └── vlan_stp_guide.md
│   │
│   ├── solutions/          # 解决方案文档
│   │   ├── mtu_mismatch.md
│   │   ├── route_leaking.md
│   │   └── acl_troubleshooting.md
│   │
│   ├── cases/              # Agent 自动维护的案例集
│   │   ├── 2026-02-01_bgp_mtu_mismatch.md
│   │   └── 2026-01-31_ospf_neighbor_down.md
│   │
│   └── best_practices/     # 最佳实践
│       ├── bgp_design.md
│       └── high_availability.md
│
├── db/
│   └── knowledge.duckdb    # 向量索引（自动生成）
│
└── skills/network-expert/
    └── skill.duckdb        # 历史案例数据库
```

**文档编辑流程**:
```python
class ExpertAgent:
    async def save_to_knowledge_base(self, diagnosis_result: dict):
        """诊断完成后，直接创建/更新知识库文档"""
        
        # 1. 评估是否典型案例
        if not self._is_typical_case(diagnosis_result):
            return
        
        # 2. 生成 Markdown 文档
        from deepagents.middleware.filesystem import FilesystemMiddleware
        
        case_id = f"{date.today()}_{diagnosis_result.category}"
        markdown_content = self._generate_markdown(
            symptom=diagnosis_result.symptom,
            root_cause=diagnosis_result.root_cause,
            solution=diagnosis_result.solution,
            diagnosis_steps=diagnosis_result.steps
        )
        
        # 3. 直接保存到知识库
        file_path = f".olav/knowledge/cases/{case_id}.md"
        await self.filesystem.write_file(file_path, markdown_content)
        
        # 4. 触发向量化
        await self._trigger_knowledge_index()
        
        return {
            "knowledge_updated": True,
            "file_path": file_path,
            "message": "知识库已更新，向量索引刷新完成"
        }
    
    async def _trigger_knowledge_index(self):
        """触发知识库向量化"""
        from olav.cli.commands import index_knowledge
        await index_knowledge()
```

**Markdown 模板**:
```markdown
# [症状] - [分类]

**症状描述**: R2 BGP 邻居 Down

**影响设备**: R2, R3

**诊断时间**: 2026-02-01

---

## 诊断步骤

1. 检查 BGP 状态
   ```
   R2# show ip bgp summary
   Neighbor        State    
   10.0.0.3        Idle
   ```

2. 检查接口 MTU
   ```
   R2# show interface Gi0/1 | include MTU
   MTU 9000 bytes
   
   R3# show interface Gi0/1 | include MTU
   MTU 1500 bytes
   ```

---

## 根因

**MTU 不匹配**: R2 配置 MTU=9000，R3 使用默认 MTU=1500，导致 TCP 连接失败。

---

## 解决方案

```
R2(config)# interface Gi0/1
R2(config-if)# mtu 1500
R2(config-if)# end

R2# clear ip bgp *
```

---

## 验证

```
R2# show ip bgp summary
Neighbor        State    
10.0.0.3        Established
```

---

**标签**: BGP, MTU, TCP Connection  
**相关案例**: bgp_authentication.md, bgp_acl_blocking.md
```

### 4. 向量化命令工具

**CLI 命令**:
```bash
# 手动触发向量化
olav knowledge index

# 自动监听文件变更（可选）
olav knowledge watch
```

**实现**:
```python
# src/olav/cli/commands/knowledge.py

import click
from olav.tools.knowledge_indexer import KnowledgeIndexer

@click.command()
def index():
    """向量化知识库 Markdown 文档"""
    
    indexer = KnowledgeIndexer(
        knowledge_dir=".olav/knowledge/",
        index_db=".olav/db/knowledge.duckdb"
    )
    
    # 扫描所有 Markdown 文件
    indexer.scan_and_index()
    
    click.echo("✅ 知识库向量化完成")

@click.command()
def watch():
    """监听知识库文件变更，自动向量化"""
    
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    
    class KnowledgeHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.src_path.endswith('.md'):
                click.echo(f"📝 检测到变更: {event.src_path}")
                indexer.index_file(event.src_path)
    
    observer = Observer()
    observer.schedule(KnowledgeHandler(), ".olav/knowledge/", recursive=True)
    observer.start()
    
    click.echo("👀 监听知识库文件变更...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

**向量化工具**:
```python
# src/olav/tools/knowledge_indexer.py

from pathlib import Path
import duckdb
from langchain_community.document_loaders import DirectoryLoader
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import MarkdownTextSplitter

class KnowledgeIndexer:
    """知识库向量化工具"""
    
    def __init__(self, knowledge_dir: str, index_db: str):
        self.knowledge_dir = Path(knowledge_dir)
        self.index_db = Path(index_db)
        self.embeddings = OpenAIEmbeddings()
        
        # 初始化向量数据库
        self._init_vector_db()
    
    def _init_vector_db(self):
        """初始化向量数据库表"""
        conn = duckdb.connect(str(self.index_db))
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                id UUID PRIMARY KEY DEFAULT uuid(),
                file_path TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding FLOAT[768],
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_embedding 
            ON knowledge_embeddings 
            USING HNSW(embedding) WITH (M=16, EFC=200);
        """)
        
        conn.close()
    
    def scan_and_index(self):
        """扫描并向量化所有 Markdown 文档"""
        
        # 1. 加载所有 Markdown 文件
        loader = DirectoryLoader(
            str(self.knowledge_dir), 
            glob="**/*.md",
            show_progress=True
        )
        documents = loader.load()
        
        # 2. 分块
        text_splitter = MarkdownTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        chunks = text_splitter.split_documents(documents)
        
        # 3. 清空旧索引
        conn = duckdb.connect(str(self.index_db))
        conn.execute("DELETE FROM knowledge_embeddings")
        
        # 4. 向量化并插入
        for chunk in chunks:
            embedding = self.embeddings.embed_query(chunk.page_content)
            
            conn.execute("""
                INSERT INTO knowledge_embeddings 
                (file_path, chunk_text, embedding, metadata)
                VALUES (?, ?, ?, ?)
            """, [
                chunk.metadata["source"],
                chunk.page_content,
                embedding,
                json.dumps(chunk.metadata)
            ])
        
        conn.close()
        
        print(f"✅ 索引完成: {len(chunks)} 个文档块")
    
    def index_file(self, file_path: str):
        """单文件向量化"""
        # 实现类似逻辑，仅处理单个文件
        pass
```

---

## 🧠 完整诊断流程

```python
async def diagnose(symptom: str) -> dict:
    """
    Expert 诊断流程（整合所有能力）
    
    1. Embedding 检索历史案例
    2. RAG 检索知识库
    3. 网络搜索（可选）
    4. ReAct 推理
    5. 自动记录 → 更新知识库 → 触发向量化
    """
    
    # Step 1: Embedding 检索历史案例
    similar_cases = await search_similar_cases_embedding(
        symptom=symptom,
        threshold=0.85
    )
    
    # Step 2: RAG 检索知识库
    knowledge_articles = await search_knowledge_rag(
        query=symptom,
        limit=3
    )
    
    # Step 3: 网络搜索（可选）
    web_results = None
    if enable_web_search and not (similar_cases or knowledge_articles):
        filtered_query = filter_sensitive_info(symptom)
        web_results = await web_search(filtered_query)
    
    # Step 4: ReAct 推理
    context = {
        "historical_cases": similar_cases,
        "knowledge_base": knowledge_articles,
        "web_search": web_results
    }
    
    diagnosis = await react_agent.diagnose(symptom, context)
    
    # Step 5: 自动学习
    # 5.1 保存到历史案例数据库
    await save_diagnosis_case(
        symptom=symptom,
        symptom_embedding=get_embedding(symptom),  # ✅ 向量化
        root_cause=diagnosis.root_cause,
        solution=diagnosis.solution
    )
    
    # 5.2 更新知识库（如果典型案例）
    if is_typical_case(diagnosis):
        markdown_path = await save_to_knowledge_base(diagnosis)
        
        # 5.3 触发向量化
        await trigger_knowledge_index()
    
    return diagnosis
```

---

## 🎯 实施路线图

### Phase 1: Embedding 升级（2天）

- [ ] 升级 `history_cases` 表，添加 `symptom_embedding`
- [ ] 实现 Embedding 检索函数
- [ ] 替换全文搜索为向量搜索

### Phase 2: 知识库向量化工具（2天）

- [ ] 实现 `KnowledgeIndexer`
- [ ] 实现 `olav knowledge index` 命令
- [ ] 实现 `olav knowledge watch`（可选）

### Phase 3: 网络搜索集成（1天）

- [ ] 集成 `WebSearchMiddleware`
- [ ] 实现敏感信息过滤
- [ ] 添加配置开关

### Phase 4: 文档编辑能力（2天）

- [ ] 集成 `FilesystemMiddleware`
- [ ] 实现 Markdown 模板生成
- [ ] 实现文档编辑 → 向量化触发

### Phase 5: E2E 验收（1天）

- [ ] 完整诊断流程测试
- [ ] 验证知识库自更新
- [ ] 验证向量检索精度

---

## 📚 参考文档

- `docs/03_router_design.md` - Orchestrator 设计（路由 + 评估 + 输出）
- `docs/01_db_design.md` - 数据库设计

---

**版本**: v0.9.8  
**完成日期**: TBD  
**负责人**: Development Team
