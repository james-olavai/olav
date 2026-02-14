# OLAV Knowledge Base 实施指南

> **版本**: v0.9.8  
> **创建日期**: 2026-02-01  
> **状态**: 实施计划

---

## 📋 执行摘要

### 知识库架构

**设计原则**:
- ✅ **文档为准**: `.olav/knowledge/` 目录为唯一真理源（白名单模式）
- ✅ **自动向量化**: 文档变更自动触发向量索引更新
- ✅ **Agent 可编辑**: Expert 诊断完成后自动创建/更新 Markdown
- ✅ **Embedding 检索**: 统一使用语义相似度搜索

**目录位置**: `.olav/knowledge/` （运行时数据）

---

## 🗂️ 目录结构

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
│   ├── knowledge.duckdb    # 向量索引（自动生成）
│   └── orchestrator.duckdb
│
└── skills/network-expert/
    └── skill.duckdb        # 历史案例数据库（symptom_embedding）
```

**为什么选择 `.olav/knowledge/` 而不是根目录？**

| 理由 | 说明 |
|:---|:---|
| **架构一致性** | `.olav/` 是运行时数据，`src/` 是应用代码，清晰分离 |
| **对称设计** | `.olav/skills/` (能力) + `.olav/knowledge/` (知识) |
| **平台兼容** | 对应 Claude Code 的 `.claude/knowledge/` |
| **数据管理** | 用户只需备份 `.olav/` 目录 |
| **版本控制** | `.gitignore` 排除 `.olav/`，避免提交自动生成的案例 |

---

## 📊 代码现状审查

### 已有的基础设施（80%）

#### 1. 数据库 Schema ✅

**文件**: `src/olav/core/database.py`

**函数**: `init_knowledge_db()`

**现有表结构**:
```sql
-- knowledge_sources 表
CREATE TABLE knowledge_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    base_path TEXT,
    version TEXT,
    platform TEXT,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- knowledge_chunks 表
CREATE TABLE knowledge_chunks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES knowledge_sources(id),
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    platform TEXT,
    doc_type TEXT,
    keywords TEXT[],
    file_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 全文搜索索引 (FTS)
CREATE INDEX idx_chunks_fts
ON knowledge_chunks USING FTS(title, content, keywords);
```

**状态**: ✅ 可用，需要升级添加向量支持

#### 2. 索引脚本 ✅

**文件**: `scripts/index_knowledge.py`

**功能**:
- 初始化知识库数据库
- 注册知识源
- 索引 Markdown 文件

**状态**: ✅ 框架可用，需要替换缺失的依赖

### 缺失的组件（20%）

#### 1. KnowledgeEmbedder ❌

**预期位置**: `src/olav/tools/knowledge_embedder.py`

**状态**: ❌ 脚本引用但不存在

**需要替换为**: `KnowledgeIndexer`

#### 2. 向量列和索引 ❌

**需要添加**:
```sql
ALTER TABLE knowledge_chunks 
ADD COLUMN embedding FLOAT[768];

CREATE INDEX idx_chunks_embedding
ON knowledge_chunks USING HNSW(embedding);
```

#### 3. RAG 检索工具 ❌

**预期位置**: `src/olav/tools/knowledge_search.py`

**状态**: ❌ 不存在

#### 4. CLI 命令 ❌

**预期位置**: `src/olav/cli/commands/knowledge.py`

**状态**: ❌ 不存在

---

## 🎯 实施方案：渐进式利旧

### 保留的代码（80%）

- ✅ `src/olav/core/database.py::init_knowledge_db()` （升级 Schema）
- ✅ `scripts/index_knowledge.py` （改写 import）
- ✅ 现有数据库结构（`knowledge_sources`、`knowledge_chunks`）

### 新增的代码（20%）

- ✅ `src/olav/tools/knowledge_indexer.py` （替代缺失的 KnowledgeEmbedder）
- ✅ `src/olav/tools/knowledge_search.py` （RAG 检索）
- ✅ `src/olav/cli/commands/knowledge.py` （CLI 命令）

---

## 🔧 具体实施步骤

### Phase 1: 数据库升级（0.5天）

**修改**: `src/olav/core/database.py::init_knowledge_db()`

```python
def init_knowledge_db(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Initialize the knowledge database with vector support."""
    
    # ... 现有代码 ...
    
    # ✅ 添加向量列
    try:
        conn.execute("""
            ALTER TABLE knowledge_chunks
            ADD COLUMN IF NOT EXISTS embedding FLOAT[768]
        """)
    except Exception:
        # 列已存在
        pass
    
    # ✅ 添加向量索引
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_embedding
            ON knowledge_chunks USING HNSW(embedding)
            WITH (M=16, EFC=200)
        """)
    except Exception as e:
        print(f"Warning: Could not create vector index: {e}")
    
    return conn
```

**测试**:
```bash
# 测试数据库创建
uv run python -c "from olav.core.database import init_knowledge_db; init_knowledge_db()"
```

---

### Phase 2: 实现 KnowledgeIndexer（1.5天）

**新文件**: `src/olav/tools/knowledge_indexer.py`

```python
"""知识库向量化工具"""

from pathlib import Path
import duckdb
import hashlib
from langchain_community.document_loaders import DirectoryLoader
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import MarkdownTextSplitter

class KnowledgeIndexer:
    """知识库向量化工具"""
    
    def __init__(self, knowledge_dir: str, index_db: str):
        self.knowledge_dir = Path(knowledge_dir)
        self.index_db = Path(index_db)
        self.embeddings = OpenAIEmbeddings()
        
        # 初始化数据库
        from olav.core.database import init_knowledge_db
        self.conn = init_knowledge_db(str(self.index_db))
    
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
        
        # 3. 向量化并插入
        for i, chunk in enumerate(chunks):
            # 计算文件 hash
            file_hash = hashlib.md5(
                chunk.page_content.encode()
            ).hexdigest()
            
            # 检查是否已存在
            existing = self.conn.execute("""
                SELECT id FROM knowledge_chunks
                WHERE file_path = ? AND chunk_index = ? AND file_hash = ?
            """, [
                chunk.metadata["source"],
                i,
                file_hash
            ]).fetchone()
            
            if existing:
                continue  # 跳过未变更的文档
            
            # 生成 Embedding
            embedding = self.embeddings.embed_query(chunk.page_content)
            
            # 插入数据库
            self.conn.execute("""
                INSERT OR REPLACE INTO knowledge_chunks 
                (source_id, file_path, chunk_index, content, embedding, file_hash)
                VALUES (1, ?, ?, ?, ?, ?)
            """, [
                chunk.metadata["source"],
                i,
                chunk.page_content,
                embedding,
                file_hash
            ])
        
        self.conn.commit()
        print(f"✅ 索引完成: {len(chunks)} 个文档块")
    
    def index_file(self, file_path: str):
        """单文件向量化"""
        # 实现类似逻辑，仅处理单个文件
        pass
```

**测试**:
```python
# 测试向量化
from olav.tools.knowledge_indexer import KnowledgeIndexer

indexer = KnowledgeIndexer(
    knowledge_dir=".olav/knowledge/",
    index_db=".olav/db/knowledge.duckdb"
)
indexer.scan_and_index()
```

---

### Phase 3: 实现 Knowledge Search（1天）

**新文件**: `src/olav/tools/knowledge_search.py`

```python
"""知识库 RAG 检索工具"""

import duckdb
from pathlib import Path
from langchain_openai import OpenAIEmbeddings

def search_knowledge_rag(
    query: str, 
    db_path: str = ".olav/db/knowledge.duckdb",
    limit: int = 3
) -> list[dict]:
    """RAG 检索知识库
    
    Args:
        query: 用户查询
        db_path: 知识库数据库路径
        limit: 返回结果数量
        
    Returns:
        [
            {
                "file_path": str,
                "content": str,
                "similarity": float
            }
        ]
    """
    
    # 1. 查询向量化
    embeddings = OpenAIEmbeddings()
    query_embedding = embeddings.embed_query(query)
    
    # 2. 向量检索
    conn = duckdb.connect(db_path, read_only=True)
    
    results = conn.execute("""
        SELECT 
            file_path,
            content,
            array_cosine_similarity(embedding, ?) as similarity
        FROM knowledge_chunks
        WHERE array_cosine_similarity(embedding, ?) > 0.7
        ORDER BY similarity DESC
        LIMIT ?
    """, [query_embedding, query_embedding, limit]).fetchall()
    
    conn.close()
    
    # 3. 格式化结果
    return [
        {
            "file_path": row[0],
            "content": row[1],
            "similarity": row[2]
        }
        for row in results
    ]


def search_similar_cases_embedding(
    symptom: str,
    db_path: str = ".olav/skills/network-expert/skill.duckdb",
    threshold: float = 0.85
) -> list[dict]:
    """Embedding 检索历史案例
    
    Args:
        symptom: 故障症状
        db_path: 历史案例数据库路径
        threshold: 相似度阈值
        
    Returns:
        [
            {
                "symptom": str,
                "root_cause": str,
                "solution": str,
                "age_days": int,
                "similarity": float
            }
        ]
    """
    
    # 1. 症状向量化
    embeddings = OpenAIEmbeddings()
    symptom_embedding = embeddings.embed_query(symptom)
    
    # 2. 向量检索
    conn = duckdb.connect(db_path, read_only=True)
    
    results = conn.execute("""
        SELECT 
            symptom,
            root_cause,
            solution,
            age_days,
            array_cosine_similarity(symptom_embedding, ?) as similarity
        FROM history_cases
        WHERE array_cosine_similarity(symptom_embedding, ?) > ?
        ORDER BY similarity DESC, age_days ASC
        LIMIT 5
    """, [
        symptom_embedding, 
        symptom_embedding, 
        threshold
    ]).fetchall()
    
    conn.close()
    
    # 3. 格式化结果
    return [
        {
            "symptom": row[0],
            "root_cause": row[1],
            "solution": row[2],
            "age_days": row[3],
            "similarity": row[4]
        }
        for row in results
    ]
```

**测试**:
```python
# 测试 RAG 检索
from olav.tools.knowledge_search import search_knowledge_rag

results = search_knowledge_rag("BGP troubleshooting")
for result in results:
    print(f"{result['file_path']}: {result['similarity']:.2f}")
```

---

### Phase 4: 实现 CLI 命令（0.5天）

**新文件**: `src/olav/cli/commands/knowledge.py`

```python
"""Knowledge Base CLI commands"""

import click
from pathlib import Path
from olav.tools.knowledge_indexer import KnowledgeIndexer

@click.group()
def knowledge():
    """Knowledge base management commands"""
    pass

@knowledge.command()
@click.option(
    '--path',
    default='.olav/knowledge/',
    help='Knowledge base directory'
)
@click.option(
    '--db',
    default='.olav/db/knowledge.duckdb',
    help='Knowledge database path'
)
def index(path: str, db: str):
    """Index knowledge base Markdown documents"""
    
    indexer = KnowledgeIndexer(
        knowledge_dir=path,
        index_db=db
    )
    
    click.echo(f"📚 Indexing knowledge base: {path}")
    indexer.scan_and_index()
    click.echo("✅ Knowledge base indexed successfully")


@knowledge.command()
@click.option(
    '--path',
    default='.olav/knowledge/',
    help='Knowledge base directory to watch'
)
def watch(path: str):
    """Watch knowledge base for changes and auto-index"""
    
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    
    class KnowledgeHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.src_path.endswith('.md'):
                click.echo(f"📝 File changed: {event.src_path}")
                # TODO: 实现单文件索引
                click.echo("   Re-indexing...")
    
    observer = Observer()
    observer.schedule(KnowledgeHandler(), path, recursive=True)
    observer.start()
    
    click.echo(f"👀 Watching knowledge base: {path}")
    click.echo("   Press Ctrl+C to stop")
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

**注册命令**: `src/olav/cli/cli_main.py`

```python
from olav.cli.commands.knowledge import knowledge

# 在 cli() 函数中添加
cli.add_command(knowledge)
```

**测试**:
```bash
# 测试索引命令
uv run olav knowledge index

# 测试监听命令（可选）
uv run olav knowledge watch
```

---

### Phase 5: 更新索引脚本（0.5天）

**修改**: `scripts/index_knowledge.py`

```python
#!/usr/bin/env python3
"""Index markdown files into the knowledge database."""

# ❌ from olav.tools.knowledge_embedder import KnowledgeEmbedder
# ✅ 新的 import
from olav.tools.knowledge_indexer import KnowledgeIndexer

def main() -> None:
    """Main entry point for knowledge indexing."""
    
    # ... 现有参数解析代码 ...
    
    # ❌ embedder = KnowledgeEmbedder(db_path=args.db)
    # ✅ 新的实例化
    indexer = KnowledgeIndexer(
        knowledge_dir=args.path,
        index_db=args.db or ".olav/db/knowledge.duckdb"
    )
    
    # ❌ embedder.embed_directory(...)
    # ✅ 新的调用
    indexer.scan_and_index()
```

---

## 📊 工作量估算

| 阶段 | 任务 | 工作量 |
|:---|:---|:---|
| Phase 1 | 数据库升级 | 0.5天 |
| Phase 2 | KnowledgeIndexer | 1.5天 |
| Phase 3 | Knowledge Search | 1天 |
| Phase 4 | CLI 命令 | 0.5天 |
| Phase 5 | 脚本更新 | 0.5天 |
| Phase 6 | 测试和文档 | 1天 |
| **总计** | | **5天** |

---

## 🧪 验收标准

### Phase 1: 数据库升级

```bash
# 验证数据库 Schema
uv run python -c "
from olav.core.database import init_knowledge_db
conn = init_knowledge_db()
schema = conn.execute('DESCRIBE knowledge_chunks').fetchall()
assert any('embedding' in str(row) for row in schema)
print('✅ Vector column exists')
"
```

### Phase 2: KnowledgeIndexer

```bash
# 验证向量化
uv run python -c "
from olav.tools.knowledge_indexer import KnowledgeIndexer
indexer = KnowledgeIndexer('.olav/knowledge/', '.olav/db/knowledge.duckdb')
indexer.scan_and_index()
# 应输出: ✅ 索引完成: N 个文档块
"
```

### Phase 3: Knowledge Search

```python
# 验证 RAG 检索
from olav.tools.knowledge_search import search_knowledge_rag

results = search_knowledge_rag("BGP troubleshooting")
assert len(results) > 0
assert "similarity" in results[0]
print(f"✅ Found {len(results)} results")
```

### Phase 4: CLI 命令

```bash
# 验证 CLI 命令
uv run olav knowledge index --path .olav/knowledge/
# 应输出: ✅ Knowledge base indexed successfully
```

### Phase 5: E2E 测试

```bash
# 完整流程测试
# 1. 创建测试知识库
mkdir -p .olav/knowledge/test
echo "# BGP Troubleshooting\nCheck MTU settings" > .olav/knowledge/test/bgp.md

# 2. 索引
uv run olav knowledge index

# 3. 检索
uv run python -c "
from olav.tools.knowledge_search import search_knowledge_rag
results = search_knowledge_rag('BGP MTU')
assert len(results) > 0
print('✅ E2E test passed')
"
```

---

## 📚 参考文档

- `docs/02_expert_design.md` - Expert Agent 增强设计
- `docs/03_router_design.md` - Orchestrator 设计
- `docs/01_db_design.md` - 数据库架构

---

**版本**: v0.9.8  
**完成日期**: TBD  
**负责人**: Development Team
