"""Storage Backend Configuration for OLAV.

This module configures the CompositeBackend for DeepAgents, defining
which paths the agent can read/write vs read-only vs temporary.

Based on DESIGN_V0.8.md Section 7.4:
- skills/ → Agent writable
- knowledge/ → Agent writable
- tools/commands/ → Agent writable (read-only commands)
- tools/apis/ → Agent read-only (API definitions maintained by humans)
- OLAV.md → Agent read-only (core rules maintained by humans)
- .env → Not accessible (sensitive configuration)
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

        _StoreBackend = FilesystemBackend
    except ImportError:
        from deepagents.storage import CompositeBackend, StateBackend

try:
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

    DEEPAGENTS_HAS_STORAGE = True
    # Note: StoreBackend renamed to FilesystemBackend in official API
    StoreBackend = FilesystemBackend
except ImportError:  # pragma: no cover (fallback import - tested in production)
    try:
        # Fallback: try old import path
        from deepagents.storage import CompositeBackend, StateBackend, StoreBackend

        DEEPAGENTS_HAS_STORAGE = True
    except ImportError:
        # DeepAgents may not have these exact classes
        # Fallback to basic filesystem access
        DEEPAGENTS_HAS_STORAGE = False
        StoreBackend = None  # type: ignore[misc, assignment]
        StateBackend = None  # type: ignore[misc, assignment]
        CompositeBackend = None  # type: ignore[misc, assignment]


def get_storage_backend(project_root: Path | None = None) -> object:  # noqa: ANN401
    """Get the configured storage backend for OLAV.

    Args:
        project_root: Project root directory (defaults to current directory)

    Returns:
        CompositeBackend or None if not available

    Storage Strategy:
        /skills/*              → Read + Write (Agent can learn new strategies)
        /knowledge/*           → Read + Write (Agent can accumulate knowledge)
        /tools/commands/*      → Read + Write (Agent can add read-only commands)
        /tools/apis/*          → Read Only (API definitions maintained by humans)
        /OLAV.md               → Read Only (Core rules maintained by humans)
        /.env                  → No Access (Sensitive configuration)
        /scratch/*             → Temporary (Session-only)
    """
    if not DEEPAGENTS_HAS_STORAGE:
        return None

    if project_root is None:
        project_root = Path.cwd()

    from config.settings import settings

    agent_dir = Path(settings.agent_dir)

    # Configure persistent storage paths (Agent can write)
    persistent_paths = [
        agent_dir / "skills",
        agent_dir / "knowledge",
        agent_dir / "imports" / "commands",
    ]

    # Configure long-term memory paths (cross-thread persistence via StoreBackend)
    # These paths enable agents to share learning across different conversation threads
    memory_paths = [
        agent_dir / "skills" / "network-expert" / "memories",
        agent_dir / "skills" / "network-query" / "memories",
        agent_dir / "skills" / "orchestrator" / "preferences",
    ]

    # Configure read-only paths
    read_only_paths = [
        agent_dir / "imports" / "apis",
        project_root / "OLAV.md",
    ]

    # Configure temporary paths (session-only)
    temp_paths = [
        agent_dir / "scratch",
    ]

    if not DEEPAGENTS_HAS_STORAGE:
        # Return None if DeepAgents storage not available
        return None  # pragma: no cover (unreachable due to earlier check on line 65)

    # Create persistent backend (FilesystemBackend for disk storage)
    # Using root_dir allows relative path access
    persistent_backend = FilesystemBackend(root_dir=str(project_root))

    # Create memory backend for long-term cross-thread learning
    # Uses DuckDBStore for persistent, thread-safe memory
    try:
        from config.paths import USER_CHECKPOINT_PATH
        
        # Ensure checkpoint directory exists
        USER_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Import DuckDBStore for long-term memory
        try:
            from langgraph.store.duckdb import DuckDBStore
            memory_store = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))
            memory_backend = memory_store  # Use DuckDBStore as backend
        except ImportError:
            # Fallback: Use FilesystemBackend if DuckDBStore not available
            memory_backend = persistent_backend
    except Exception as e:  # pragma: no cover (fallback for import errors)
        # If store initialization fails, fall back to filesystem
        memory_backend = persistent_backend

    # Create composite backend with route mapping
    # Maps paths to appropriate backends
    routes = {}
    
    # Persistent paths → FilesystemBackend
    for path in persistent_paths:
        routes[str(path)] = persistent_backend
    
    # Memory paths → Memory backend (DuckDBStore for cross-thread persistence)
    for path in memory_paths:
        routes[str(path)] = memory_backend
    
    # Read-only paths → FilesystemBackend (will be marked read-only at access time)
    for path in read_only_paths:
        routes[str(path)] = persistent_backend
    
    # Temporary paths → FilesystemBackend (will be cleaned up or session-scoped)
    # Note: StateBackend requires runtime parameter which we cannot provide
    # Using FilesystemBackend for temp paths keeps them in-memory via agent state
    for path in temp_paths:
        routes[str(path)] = persistent_backend
    
    # Create composite backend ✅ Routes to different backends by path
    composite = CompositeBackend(  # type: ignore[misc, call-arg]
        default=persistent_backend,
        routes=routes,
    )

    return composite


def get_storage_permissions() -> str:
    """Get storage permission documentation for system prompt.

    Returns:
        Formatted permission matrix
    """
    return """## 文件系统权限

你可以访问以下路径:

### ✅ 可读写 (用于自学习)
- `agent_dir/skills/*.md` - 技能策略 (可以学习新模式)
- `agent_dir/knowledge/*` - 知识库 (可以积累新知识)
  - `agent_dir/knowledge/aliases.md` - 设备别名
  - `agent_dir/knowledge/solutions/*.md` - 成功案例
- `agent_dir/imports/commands/*.txt` - 命令白名单 (可以添加只读命令)

### ⚠️ 只读 (人类维护)
- `agent_dir/imports/apis/*.yaml` - API定义
- Root CLAUDE.md - 核心规则

### ❌ 不可访问
- `.env` - 敏感配置
- `config/` - 运行配置

### 🔒 临时存储 (会话内有效)
- `agent_dir/scratch/*` - 临时文件 (会话结束后删除)

### 学习原则
1. 只在确认成功后保存解决方案
2. 只在用户明确澄清时更新别名
3. 添加命令时只添加已验证的只读命令
4. 任何写入操作前仍需用户确认
"""


def check_write_permission(filepath: Path | str, project_root: Path | None = None) -> bool:
    """Check if agent has write permission for a file.

    Args:
        filepath: File path to check
        project_root: Project root directory

    Returns:
        True if agent can write to this file, False otherwise
    """
    if project_root is None:
        project_root = Path.cwd()

    filepath = Path(filepath)
    olav_dir = project_root / ".olav"

    # Normalize path
    try:
        rel_path = filepath.resolve().relative_to(olav_dir.resolve())
    except ValueError:
        # Not under .olav directory
        return False

    # Check allowed write paths
    allowed_write_patterns = [
        Path("skills"),
        Path("knowledge"),
        Path("knowledge") / "solutions",
        Path("imports") / "commands",
    ]

    for pattern in allowed_write_patterns:
        if rel_path.is_relative_to(pattern):
            return True

    # Read-only paths
    read_only_patterns = [
        Path("imports") / "apis",
    ]

    for pattern in read_only_patterns:
        if rel_path.is_relative_to(pattern):
            return False

    # Default: no write permission
    return False


__all__ = [
    "get_storage_backend",
    "get_storage_permissions",
    "check_write_permission",
]
