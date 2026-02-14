# Backend增强方案 - FilesystemMiddleware + CompositeBackend + StoreBackend

**创建日期**: 2026-02-06  
**版本**: v0.9.8+  
**目标**: 完善OLAV的持久化存储和Learning工作流  
**数据库集成**: 见 [backend_database_integration.md](backend_database_integration.md) - ✅ **零破坏性变更，完美兼容**

---

## 🔍 现状分析

### 1. 代码现状（已实现但未使用）

#### `src/olav/core/storage.py` - 配置框架存在 ✅
```python
def get_storage_backend(project_root: Path | None = None) -> object:
    """Get the configured storage backend for OLAV."""
    
    # Persistent paths
    persistent_paths = [
        agent_dir / "skills",
        agent_dir / "knowledge",
        agent_dir / "imports" / "commands",
    ]
    
    # Read-only paths
    read_only_paths = [
        agent_dir / "imports" / "apis",
        project_root / "OLAV.md",
    ]
    
    # Temporary paths
    temp_paths = [
        agent_dir / "scratch",
    ]
    
    # Create composite backend
    composite = CompositeBackend(backends={
        **{str(path): persistent_backend for path in persistent_paths},
        **{str(path): temp_backend for path in temp_paths},
        "/": persistent_backend,  # Default
    })
    
    return composite
```

**问题**: ❌ **从未被调用！**

#### 实际使用情况

**QueryAgent** (`src/olav/agents/query_agent.py:124`):
```python
self.backend = FilesystemBackend(root_dir=str(project_root))
```
- ❌ 直接使用FilesystemBackend
- ❌ 未使用CompositeBackend路由规则
- ❌ 所有路径都是persistent（没有ephemeral/readonly区分）

**Orchestrator** (`src/olav/agents/orchestrator.py:167`):
```python
backend = FilesystemBackend(root_dir=str(Path.cwd()))
```
- ❌ 仅用于SummarizationMiddleware
- ❌ 未配置CompositeBackend

**create_olav_agent** (`src/olav/agent.py:185`):
```python
agent = create_deep_agent(
    model=llm,
    tools=tools,
    system_prompt=system_prompt,
    checkpointer=checkpointer,
    interrupt_on=interrupt_on,
    # ❌ 缺失：backend参数
)
```

### 2. Learning工作流断裂

#### `src/olav/core/learning.py:save_solution()` - 流程不完整
```python
def save_solution(title, problem, process, root_cause, solution, commands, tags, ...):
    """Save a successful troubleshooting case to the knowledge base."""
    
    # ✅ Step 1: 写入markdown文件
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
    
    # ❌ 缺失：Step 2: Git commit (版本控制)
    # ❌ 缺失：Step 3: 触发向量化 (semantic search)
    # ❌ 缺失：Step 4: 通知其他agents (cache invalidation)
    # ❌ 缺失：Step 5: HITL审批 (可选，用户确认)
```

#### 向量化入口存在但需手动触发
```bash
# 需要手动运行
uv run olav knowledge index
```

**问题**: ❌ Learning后不会自动生效，需要手动向量化

### 3. 持久化策略混乱

#### Checkpointer配置不一致

| Component | Checkpointer | Store | Persistence |
|-----------|-------------|-------|-------------|
| QueryAgent | DuckDBSaver | DuckDBStore | ✅ Persistent |
| Orchestrator | None | None | ❌ In-memory |
| SubAgents | Per-agent | Per-agent | ✅ Persistent |

#### Backend配置不一致

| Component | Backend | 临时文件 | 持久化文件 |
|-----------|---------|----------|------------|
| QueryAgent | FilesystemBackend | ❌ 全部persistent | ❌ 无ephemeral |
| Orchestrator | FilesystemBackend | ❌ 全部persistent | ❌ 无ephemeral |
| create_olav_agent | ❌ None | ❌ 无backend | ❌ 无backend |

**问题**: ❌ 缺乏统一的存储策略

---

## 🎯 增强目标

### **Goal 1**: 统一Backend配置 - 使用CompositeBackend路由规则

**Before**:
```python
# 每个agent各自配置，不一致
backend = FilesystemBackend(root_dir=...)  # 全部persistent
```

**After**:
```python
# 统一使用CompositeBackend，按路径路由
backend = get_storage_backend()  # 自动区分ephemeral/persistent/readonly
```

### **Goal 2**: 完善Learning工作流 - Git + Vectorization + HITL

**Before**:
```python
save_solution(...) → 写入文件 → 返回
```

**After**:
```python
save_solution(...) → 写入文件 → Git commit → 触发向量化 → HITL审批 → 完成
```

### **Goal 3**: 启用Long-term Memory - 跨Thread知识共享

**Before**:
```python
StateBackend() → ephemeral → 每个thread独立 → 知识不共享
```

**After**:
```python
CompositeBackend(
    default=StateBackend(),  # 工作文件（临时）
    routes={
        "/knowledge/": FilesystemBackend(...),  # 知识库持久化
        "/memories/": StoreBackend(...),         # 跨thread记忆
    }
)
```

---

## 📋 增强方案

### **Phase 1**: 修复Backend配置（1-2天）⭐ 最高优先级

#### 1.1 修复`create_olav_agent` - 使用CompositeBackend

**文件**: `src/olav/agent.py`

```python
def create_olav_agent(...) -> "CompiledStateGraph":
    """Create the OLAV DeepAgent."""
    
    # ... existing code ...
    
    # ✅ NEW: 使用统一的CompositeBackend
    from olav.core.storage import get_storage_backend
    backend = get_storage_backend()
    
    # Create agent
    agent = create_deep_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
        backend=backend,  # ⭐ NEW: 添加backend参数
        debug=debug,
        name="olav",
    )
    
    return agent
```

**变更点**:
- ✅ 添加`backend=get_storage_backend()`
- ✅ `.olav/knowledge/` 文件写入会持久化
- ✅ `.olav/scratch/` 文件写入会ephemeral
- ✅ `OLAV.md` 只读保护

#### 1.2 修复`create_orchestrator` - 使用CompositeBackend

**文件**: `src/olav/agents/orchestrator.py`

```python
def create_orchestrator(...) -> Any:
    """Create SubAgent-based orchestrator."""
    
    # ... existing code ...
    
    # ✅ NEW: 统一Backend配置
    from olav.core.storage import get_storage_backend
    backend = get_storage_backend()
    
    # Use parameter if provided, otherwise use settings
    use_summarization = enable_summarization if enable_summarization is not None else settings.agent.enable_summarization
    
    if use_summarization:
        # ❌ OLD: backend = FilesystemBackend(root_dir=str(Path.cwd()))
        # ✅ NEW: 复用统一backend
        
        middleware.append(
            SummarizationMiddleware(
                model=summ_model,
                backend=backend,  # ⭐ 使用统一backend
                trigger=("tokens", settings.agent.summarization_trigger_tokens),
                keep=("messages", settings.agent.summarization_keep_messages),
            )
        )
    
    # Create orchestrator with SubAgent routing
    agent = create_deep_agent(
        model=orch_model,
        system_prompt=system_prompt,
        tools=orchestrator_tools,
        subagents=subagents if subagents else None,
        middleware=middleware if middleware else [],
        checkpointer=checkpointer,
        store=store,
        backend=backend,  # ⭐ NEW: 添加backend参数
        name="orchestrator",
    )
    
    return agent
```

#### 1.3 修复`QueryAgent` - 使用CompositeBackend

**文件**: `src/olav/agents/query_agent.py`

```python
class QueryAgent:
    def __init__(self, ...):
        # ... existing code ...
        
        # ❌ OLD: self.backend = FilesystemBackend(root_dir=str(project_root))
        # ✅ NEW: 使用统一backend
        from olav.core.storage import get_storage_backend
        self.backend = get_storage_backend()
        
        # ... rest of code ...
```

**影响范围**:
- ✅ QueryAgent的文件读写遵循统一路由规则
- ✅ `.olav/scratch/` 临时缓存不会持久化
- ✅ `.olav/knowledge/` 知识库自动持久化

---

### **Phase 2**: 完善Learning工作流（3-5天）⭐ 高优先级

#### 2.1 增强`save_solution` - 添加后处理hooks

**文件**: `src/olav/core/learning.py`

```python
import subprocess
from pathlib import Path
from typing import Callable

# Hook registry for post-save actions
_post_save_hooks: list[Callable[[Path], None]] = []

def register_post_save_hook(hook: Callable[[Path], None]) -> None:
    """Register a hook to run after saving solutions."""
    _post_save_hooks.append(hook)

def save_solution(
    title: str,
    problem: str,
    process: list[str],
    root_cause: str,
    solution: str,
    commands: list[str],
    tags: list[str],
    knowledge_dir: Path | None = None,
    auto_commit: bool = True,  # ⭐ NEW: 自动Git commit
    auto_vectorize: bool = True,  # ⭐ NEW: 自动向量化
) -> str:
    """Save a successful troubleshooting case to the knowledge base.
    
    Args:
        ... (existing args)
        auto_commit: Automatically commit to Git (default: True)
        auto_vectorize: Trigger vectorization after save (default: True)
    
    Returns:
        Path to created file
    """
    if knowledge_dir is None:
        from config.settings import settings
        knowledge_dir = Path(settings.agent_dir) / "knowledge" / "solutions"
    
    knowledge_dir = Path(knowledge_dir)
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    # Create filename
    safe_title = title.lower().replace(" ", "-").replace("/", "-")
    filename = f"{safe_title}.md"
    filepath = knowledge_dir / filename
    
    # Build markdown content (existing code)
    tag_line = " ".join(tags) if tags else "#uncategorized"
    content = f"""# 案例: {title}
...
"""
    
    # ✅ Step 1: Write file
    filepath.write_text(content, encoding="utf-8")
    logger.info(f"Saved solution: {filepath}")
    
    # ⭐ NEW: Step 2: Git commit (optional)
    if auto_commit:
        _git_commit_solution(filepath)
    
    # ⭐ NEW: Step 3: Trigger vectorization (optional)
    if auto_vectorize:
        _trigger_vectorization(filepath)
    
    # ⭐ NEW: Step 4: Run post-save hooks
    for hook in _post_save_hooks:
        try:
            hook(filepath)
        except Exception as e:
            logger.warning(f"Post-save hook failed: {e}")
    
    return str(filepath)

def _git_commit_solution(filepath: Path) -> None:
    """Git commit saved solution (optional)."""
    try:
        # Check if Git repo exists
        repo_root = Path.cwd()
        if not (repo_root / ".git").exists():
            logger.debug("Not a Git repo, skipping commit")
            return
        
        # Git add
        subprocess.run(
            ["git", "add", str(filepath.relative_to(repo_root))],
            cwd=repo_root,
            check=True,
            capture_output=True
        )
        
        # Git commit
        commit_msg = f"chore(knowledge): auto-save solution - {filepath.stem}"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_root,
            check=False,  # Don't fail if nothing to commit
            capture_output=True
        )
        
        logger.info(f"Git committed: {filepath.name}")
    except Exception as e:
        logger.warning(f"Git commit failed: {e}")

def _trigger_vectorization(filepath: Path) -> None:
    """Trigger vectorization for saved solution (async)."""
    try:
        # Option 1: Fire-and-forget subprocess
        subprocess.Popen(
            ["uv", "run", "olav", "knowledge", "index", "--incremental"],
            cwd=Path.cwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logger.info(f"Triggered vectorization for: {filepath.name}")
    except Exception as e:
        logger.warning(f"Vectorization trigger failed: {e}")
```

**变更点**:
- ✅ `auto_commit=True` - 自动Git commit (可选)
- ✅ `auto_vectorize=True` - 触发向量化 (fire-and-forget)
- ✅ Hook注册机制 - 支持自定义后处理

#### 2.2 添加HITL审批 (可选) - 用户确认Learning

**文件**: `src/olav/tools/learning_tools.py`

```python
class SaveSolutionTool(BaseTool):
    """Save troubleshooting solution to knowledge base (with HITL approval)."""
    
    name: str = "save_solution"
    description: str = """Save a successful troubleshooting case to knowledge base.
    
Requires HITL approval before saving. Use after successfully resolving issues.
    
Args:
    title: Case title (filename-safe)
    problem: Problem description
    root_cause: Root cause analysis
    solution: Solution implemented
    commands: Key commands used (list)
    tags: Tags for indexing (list, with # prefix)
"""
    
    def _run(self, title: str, problem: str, root_cause: str, 
             solution: str, commands: str, tags: str) -> str:
        """Execute save_solution with parsed arguments."""
        try:
            # Parse lists from strings
            import json
            commands_list = json.loads(commands) if isinstance(commands, str) else commands
            tags_list = json.loads(tags) if isinstance(tags, str) else tags
            
            # Save solution (HITL approval handled by interrupt_on config)
            filepath = save_solution(
                title=title,
                problem=problem,
                process=[],  # Agent should provide this
                root_cause=root_cause,
                solution=solution,
                commands=commands_list,
                tags=tags_list,
                auto_commit=True,
                auto_vectorize=True
            )
            
            return f"✅ Solution saved: {filepath}\n📚 Vectorization triggered (will complete in background)"
        except Exception as e:
            return f"❌ Failed to save solution: {e}"
```

**HITL配置**:
```python
# In create_olav_agent (src/olav/agent.py)
interrupt_on = {
    "save_solution": True,  # ⭐ NEW: 需要HITL审批
    "update_aliases": True,  # Existing
}
```

**用户体验**:
```
Agent: 故障已解决！是否保存案例到知识库？
       
       📋 将保存:
       - Title: bgp-flapping-r1
       - Root Cause: MTU mismatch
       - Solution: Adjusted MTU to 1500
       - Commands: 3 commands
       
       🔐 HITL Approval Required
       Continue? [Y/n/edit]

User: Y

Agent: ✅ Solution saved: .olav/knowledge/solutions/bgp-flapping-r1.md
       📚 Vectorization triggered (will complete in background)
       🔄 Git committed: chore(knowledge): auto-save solution
```

---

### **Phase 3**: 启用Long-term Memory（2-3天）⭐ 中优先级

#### 3.1 扩展`storage.py` - 添加StoreBackend路由

**文件**: `src/olav/core/storage.py`

```python
def get_storage_backend(project_root: Path | None = None) -> object:
    """Get the configured storage backend for OLAV."""
    
    if not DEEPAGENTS_HAS_STORAGE:
        return None
    
    if project_root is None:
        project_root = Path.cwd()
    
    from config.settings import settings
    agent_dir = Path(settings.agent_dir)
    
    # ✅ Persistent paths (FilesystemBackend)
    persistent_paths = [
        agent_dir / "skills",
        agent_dir / "knowledge",
        agent_dir / "imports" / "commands",
    ]
    
    # ✅ Read-only paths
    read_only_paths = [
        agent_dir / "imports" / "apis",
        project_root / "OLAV.md",
    ]
    
    # ✅ Temporary paths (StateBackend)
    temp_paths = [
        agent_dir / "scratch",
    ]
    
    # ⭐ NEW: Long-term memory paths (StoreBackend)
    memory_paths = [
        agent_dir / "memories",      # 跨thread记忆
        agent_dir / "preferences",   # 用户偏好
    ]
    
    # Create backends
    persistent_backend = FilesystemBackend(
        root_dir=project_root,
        allowed_paths=persistent_paths,
        read_only_paths=read_only_paths,
    )
    
    temp_backend = StateBackend()  # Ephemeral
    
    # ⭐ NEW: StoreBackend for long-term memory
    from langgraph.store.memory import InMemoryStore
    # TODO: Use DuckDBStore for production
    # from langgraph.store.duckdb import DuckDBStore
    # memory_store = DuckDBStore.from_conn_string(str(agent_dir / "store.db"))
    memory_store = InMemoryStore()  # POC: in-memory
    
    memory_backend = StoreBackend(store=memory_store)
    
    # Create composite backend with routing
    composite = CompositeBackend(
        default=temp_backend,  # ⭐ Default: ephemeral
        routes={
            **{str(path): persistent_backend for path in persistent_paths},
            **{str(path): persistent_backend for path in read_only_paths},
            **{str(path): temp_backend for path in temp_paths},
            **{str(path): memory_backend for path in memory_paths},  # ⭐ NEW
        }
    )
    
    return composite
```

**变更点**:
- ✅ `default=temp_backend` - 默认临时存储（安全）
- ✅ `/memories/` → StoreBackend - 跨thread持久化
- ✅ `/preferences/` → StoreBackend - 用户偏好

#### 3.2 使用Long-term Memory - 跨Thread知识共享

**场景**: Agent从案例库学习，跨thread可见

```python
# In SubAgent或QueryAgent system prompt
system_prompt = """
你可以访问以下持久化存储:

### 📚 Knowledge Base (跨thread共享)
- /knowledge/solutions/*.md - 故障排除案例库
- /knowledge/protocols/*.md - 协议手册
- /memories/learned_patterns/ - Agent学到的模式

### 使用方式
当遇到类似问题时:
1. read_file("/knowledge/solutions/<case>.md") - 查看历史案例
2. read_file("/memories/learned_patterns/<pattern>.txt") - 查看学到的模式
3. 应用历史经验解决新问题

### 学习方式
解决问题后:
1. write_file("/memories/learned_patterns/<pattern>.txt", content) - 保存模式
2. save_solution(...) - 保存案例（自动Git + vectorize）
"""
```

**效果**:
```
# Thread 1
User: R1 BGP邻居振荡
Agent: 解决方案: MTU不匹配 → 调整MTU
       save_solution("bgp-flapping-r1", ...)

# Thread 2 (新会话)
User: R2 BGP邻居振荡
Agent: 检测到类似case: bgp-flapping-r1
       read_file("/knowledge/solutions/bgp-flapping-r1.md")
       建议: 检查MTU配置
```

---

### **Phase 4**: FilesystemMiddleware增强（可选，低优先级）

#### 4.1 添加文件操作审计日志

**文件**: `src/olav/tools/storage_tools.py`

```python
import logging
from datetime import datetime

audit_logger = logging.getLogger("olav.audit.filesystem")

def write_file(path: str, content: str, append: bool = False) -> str:
    """Write content to file with audit logging."""
    
    # ⭐ NEW: Audit log before write
    audit_logger.info(f"WRITE_FILE: {path} (append={append}, size={len(content)})")
    
    # Existing write logic
    ...
    
    # ⭐ NEW: Audit log after success
    audit_logger.info(f"WRITE_FILE_SUCCESS: {path}")
    
    return f"✅ File written: {path}"
```

**审计日志格式**:
```
2026-02-06 10:30:15 | WRITE_FILE | .olav/knowledge/solutions/bgp-case.md | size=1234
2026-02-06 10:30:15 | WRITE_FILE_SUCCESS | .olav/knowledge/solutions/bgp-case.md
2026-02-06 10:30:16 | GIT_COMMIT | chore(knowledge): auto-save solution - bgp-case
2026-02-06 10:30:17 | VECTORIZE_TRIGGER | .olav/knowledge/solutions/bgp-case.md
```

#### 4.2 添加文件操作权限检查

**文件**: `src/olav/core/storage.py`

```python
def check_write_permission(filepath: Path | str, project_root: Path | None = None) -> tuple[bool, str]:
    """Check if agent has write permission for a file.
    
    Returns:
        (allowed: bool, reason: str)
    """
    if project_root is None:
        project_root = Path.cwd()
    
    filepath = Path(filepath)
    olav_dir = project_root / ".olav"
    
    # Normalize path
    try:
        rel_path = filepath.resolve().relative_to(olav_dir.resolve())
    except ValueError:
        return (False, "Path outside .olav directory")
    
    # Check allowed write patterns
    allowed_write_patterns = [
        Path("skills"),
        Path("knowledge"),
        Path("memories"),  # ⭐ NEW: Long-term memory
        Path("imports") / "commands",
    ]
    
    for pattern in allowed_write_patterns:
        if rel_path.is_relative_to(pattern):
            return (True, "Write allowed")
    
    # Read-only paths
    read_only_patterns = [
        Path("imports") / "apis",
        Path("config"),  # ⭐ NEW: Config readonly
    ]
    
    for pattern in read_only_patterns:
        if rel_path.is_relative_to(pattern):
            return (False, f"Read-only path: {pattern}")
    
    # Default: no write permission
    return (False, "Path not in allowed write patterns")
```

**集成到write_file**:
```python
def write_file(path: str, content: str) -> str:
    """Write content to file with permission check."""
    
    # ⭐ NEW: Permission check
    allowed, reason = check_write_permission(path)
    if not allowed:
        return f"❌ Write denied: {reason}"
    
    # Existing write logic
    ...
```

---

## 📊 实施计划

### 优先级矩阵

| Phase | 优先级 | 实施时间 | 影响范围 | 风险 |
|-------|--------|----------|----------|------|
| **Phase 1: Backend配置** | ⭐⭐⭐ 最高 | 1-2天 | 所有agents | 低 |
| **Phase 2: Learning工作流** | ⭐⭐ 高 | 3-5天 | Learning模块 | 中 |
| **Phase 3: Long-term Memory** | ⭐ 中 | 2-3天 | 跨thread功能 | 中 |
| **Phase 4: Middleware增强** | 可选 | 2-3天 | 审计/权限 | 低 |

### 实施路径

```
Week 1:
□ Phase 1.1: 修复create_olav_agent backend
□ Phase 1.2: 修复create_orchestrator backend  
□ Phase 1.3: 修复QueryAgent backend
✅ 验证: 所有agents使用统一CompositeBackend

Week 2:
□ Phase 2.1: 增强save_solution (Git + Vectorize)
□ Phase 2.2: 添加SaveSolutionTool + HITL
□ 测试: Learning工作流端到端
✅ 验证: save后自动Git commit + vectorize

Week 3 (可选):
□ Phase 3.1: 扩展storage.py (StoreBackend路由)
□ Phase 3.2: 实现跨thread知识共享
✅ 验证: Thread 1学习 → Thread 2可见

Week 4 (可选):
□ Phase 4.1: 文件操作审计日志
□ Phase 4.2: 权限检查增强
✅ 验证: 审计日志完整，权限检查生效
```

---

## 🧪 测试验收标准

### Phase 1: Backend配置

**Test Case 1.1**: Backend路由正确
```python
# 测试临时文件 → StateBackend
agent.write_file("/scratch/temp.txt", "test")
assert not Path(".olav/scratch/temp.txt").exists()  # Ephemeral

# 测试知识库 → FilesystemBackend
agent.write_file("/knowledge/test.md", "test")
assert Path(".olav/knowledge/test.md").exists()  # Persistent
```

**Test Case 1.2**: 只读保护生效
```python
# 测试只读文件 → 写入失败
result = agent.write_file("/imports/apis/test.yaml", "malicious")
assert "Write denied" in result
```

### Phase 2: Learning工作流

**Test Case 2.1**: Git commit自动执行
```python
save_solution(
    title="test-case",
    problem="Test",
    ...,
    auto_commit=True
)

# 验证Git commit
result = subprocess.run(
    ["git", "log", "--oneline", "-1"],
    capture_output=True, text=True
)
assert "auto-save solution - test-case" in result.stdout
```

**Test Case 2.2**: 向量化自动触发
```python
save_solution(..., auto_vectorize=True)

# 等待向量化完成 (async)
import time
time.sleep(5)

# 验证向量库已更新
from olav.tools.capabilities import search_knowledge
result = search_knowledge.invoke({"query": "test-case", "limit": 1})
assert "test-case" in result
```

### Phase 3: Long-term Memory

**Test Case 3.1**: 跨Thread知识共享
```python
# Thread 1: 保存知识
with agent.thread("thread-1"):
    agent.write_file("/memories/pattern1.txt", "BGP MTU pattern")

# Thread 2: 读取知识
with agent.thread("thread-2"):
    content = agent.read_file("/memories/pattern1.txt")
    assert "BGP MTU pattern" in content
```

---

## �️ 数据库集成说明

### **关键发现：✅ 零数据库改动！**

Backend增强方案**完全复用**OLAV现有数据库架构：

| Backend功能 | 需要的数据库 | OLAV现状 | 集成方式 |
|------------|------------|---------|---------|
| **Phase 1: Backend配置** | ❌ 不需要 | N/A | ✅ 纯文件路由 |
| **Phase 2: Auto Vectorize** | knowledge_chunks | ✅ 已存在 | ✅ 调用现有命令 |
| **Phase 3: Long-term Memory** | DuckDBStore | ✅ 已在用 | ✅ 添加新namespace |

**数据库架构（v0.10.1）**:
```
UNIFIED_DB = .olav/db/olav.duckdb
  ├─ devices, raw_outputs (网络数据)
  ├─ audit_logs (命令审计)
  └─ knowledge_chunks (知识库 + FTS + Vector) ← Phase 2使用

USER_CHECKPOINT_PATH = ~/.olav/checkpoints/{username}.duckdb
  ├─ checkpoints (session state - DuckDBSaver)
  └─ store (aliases + memories - DuckDBStore) ← Phase 3扩展
```

**详细分析**: 见 [backend_database_integration.md](backend_database_integration.md)

---

## �🔗 前置依赖

### DeepAgents版本要求

确保DeepAgents支持以下功能：
- ✅ `CompositeBackend` - 路由规则
- ✅ `FilesystemBackend` - 文件系统持久化
- ✅ `StateBackend` - Ephemeral存储
- ✅ `StoreBackend` - 跨thread持久化（需要LangGraph Store）

**检查方式**:
```bash
python -c "from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend; print('OK')"
```

### Git配置

Learning工作流需要Git环境：
```bash
# 检查Git可用
git --version

# 配置Git用户（如果未配置）
git config user.name "OLAV Agent"
git config user.email "olav@local"
```

---

## 📚 参考文档

### DeepAgents官方文档
- **Backend系统**: `archive/deepagents/README.md` (lines 200-260)
  - FilesystemBackend: Real disk operations
  - StateBackend: Ephemeral state
  - StoreBackend: Persistent storage with LangGraph Store
  - CompositeBackend: Route different paths to different backends

- **Long-term Memory**: `archive/deepagents/README.md` (lines 230-250)
  ```python
  backend=CompositeBackend(
      default=StateBackend(),
      routes={"/memories/": StoreBackend(store=InMemoryStore())},
  )
  ```

### OLAV现有代码
- **Storage模块**: `src/olav/core/storage.py` (完整配置框架)
- **Learning模块**: `src/olav/core/learning.py` (需要增强)
- **QueryAgent**: `src/olav/agents/query_agent.py:124` (需要修复backend)
- **Orchestrator**: `src/olav/agents/orchestrator.py:167` (需要修复backend)

---

## ✅ 成功标准

Backend增强完成后，应实现以下能力：

### 1. 统一的存储策略 ✅
- 所有agents使用`get_storage_backend()`
- 按路径自动路由到正确backend
- 临时文件ephemeral，知识库persistent

### 2. 完整的Learning工作流 ✅
```
故障解决 → save_solution() → 
  ├─ 写入markdown
  ├─ Git commit (auto)
  ├─ 触发向量化 (async)
  ├─ HITL审批 (optional)
  └─ 完成
```

### 3. 跨Thread知识共享 ✅
```
Thread 1: 学习案例 → /knowledge/solutions/
Thread 2: 自动检索 → 应用历史经验
```

### 4. 权限和审计 ✅
- 只读路径保护（`OLAV.md`, `config/`）
- 文件操作审计日志
- 权限检查失败时友好提示

---

**下一步**: 开始实施Phase 1（Backend配置修复）？
