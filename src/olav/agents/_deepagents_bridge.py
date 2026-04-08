"""
_deepagents_bridge.py — deepagents API 的版本隔离层。

升级 deepagents 时只需改这一个文件。
agent.py 和其他模块从这里导入，不直接接触 deepagents 包。

版本策略:
  supported range: >=0.5.0, <1.0
  - 低于 _DA_MIN  → ImportError (明确告知升级路径)
  - >=1.0         → UserWarning (可能有 breaking changes，需人工验证)

0.5 新增功能:
  - AsyncSubAgent / AsyncSubAgentMiddleware: 非阻塞后台子智能体 (需 LangGraph Platform)
  - SummarizationToolMiddleware: 工具形式的摘要中间件
  - 多模态 read_file: 支持 PDF / 音频 / 视频
  - 后端协议 binary 文件支持 (base64)
  - Anthropic Prompt Caching 改进
"""

from __future__ import annotations

import warnings
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from packaging.version import Version as V

# ── Version detection ─────────────────────────────────────────────────────────

try:
    _DA_VERSION = V(_pkg_version("deepagents"))
except PackageNotFoundError as exc:
    raise ImportError(
        "deepagents is not installed. Run: pip install 'deepagents>=0.5.0,<1.0'"
    ) from exc

_DA_MIN = V("0.5.0")
_DA_NEXT_MAJOR = V("1.0.0")

if _DA_VERSION < _DA_MIN:
    raise ImportError(
        f"deepagents {_DA_VERSION} is too old. "
        f"Olav requires deepagents>={_DA_MIN}. "
        f"Run: pip install -U 'deepagents>={_DA_MIN},<{_DA_NEXT_MAJOR}'"
    )

if _DA_VERSION >= _DA_NEXT_MAJOR:
    warnings.warn(
        f"deepagents {_DA_VERSION} may have breaking changes — Olav was validated "
        f"against <{_DA_NEXT_MAJOR}. Verify compatibility before using in production. "
        f"See dev_docs/17. RELEASE_PLAN.md for the upgrade checklist.",
        stacklevel=2,
    )

# ── Feature flags ─────────────────────────────────────────────────────────────
# Gate new features behind version checks so the codebase degrades gracefully
# when running against an older patch.

HAS_SUMMARIZATION: bool = _DA_VERSION >= V("0.4.0")
"""True when SummarizationMiddleware is available (auto context compression)."""

HAS_PROMPT_CACHING: bool = True
"""True when AnthropicPromptCachingMiddleware is available (from langchain_anthropic)."""

HAS_LOCAL_SHELL_BACKEND: bool = _DA_VERSION >= V("0.4.0")
"""True when LocalShellBackend is available (subprocess execution backend)."""

HAS_NAMESPACE_FACTORY: bool = _DA_VERSION >= V("0.4.0")
"""True when NamespaceFactory / BackendContext pattern is available."""

HAS_ASYNC_SUBAGENTS: bool = _DA_VERSION >= V("0.5.0")
"""True when AsyncSubAgent / AsyncSubAgentMiddleware are available (non-blocking background subagents).
Requires LangGraph Platform or self-hosted LangGraph server for actual remote execution."""

# ── Core exports (stable across 0.4.x → 0.5.x) ───────────────────────────────

from deepagents import create_deep_agent as _create_deep_agent  # noqa: E402
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent  # noqa: E402

# ── Version-gated exports ─────────────────────────────────────────────────────

if HAS_SUMMARIZATION:
    try:
        from deepagents.backends import StateBackend as _StateBackend
        from deepagents.middleware.summarization import (
            SummarizationToolMiddleware,
            create_summarization_middleware as _create_summarization_middleware,
            create_summarization_tool_middleware,
        )
        from deepagents.middleware import SummarizationMiddleware
    except ImportError:
        SummarizationMiddleware = None  # type: ignore[assignment,misc]
        SummarizationToolMiddleware = None  # type: ignore[assignment,misc]
        create_summarization_tool_middleware = None  # type: ignore[assignment,misc]
        _StateBackend = None  # type: ignore[assignment,misc]
        _create_summarization_middleware = None  # type: ignore[assignment,misc]
else:
    SummarizationMiddleware = None  # type: ignore[assignment,misc]
    SummarizationToolMiddleware = None  # type: ignore[assignment,misc]
    create_summarization_tool_middleware = None  # type: ignore[assignment,misc]
    _StateBackend = None  # type: ignore[assignment,misc]
    _create_summarization_middleware = None  # type: ignore[assignment,misc]

if HAS_LOCAL_SHELL_BACKEND:
    try:
        from deepagents.backends import LocalShellBackend
    except ImportError:
        LocalShellBackend = None  # type: ignore[assignment,misc]
else:
    LocalShellBackend = None  # type: ignore[assignment,misc]

if HAS_ASYNC_SUBAGENTS:
    try:
        from deepagents.middleware.async_subagents import AsyncSubAgent, AsyncSubAgentMiddleware
    except ImportError:
        AsyncSubAgent = None  # type: ignore[assignment,misc]
        AsyncSubAgentMiddleware = None  # type: ignore[assignment,misc]
else:
    AsyncSubAgent = None  # type: ignore[assignment,misc]
    AsyncSubAgentMiddleware = None  # type: ignore[assignment,misc]

# AnthropicPromptCachingMiddleware: from langchain_anthropic (available in 0.4.x via deepagents dep)
if HAS_PROMPT_CACHING:
    try:
        from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
    except ImportError:
        AnthropicPromptCachingMiddleware = None  # type: ignore[assignment,misc]
        HAS_PROMPT_CACHING = False
else:
    AnthropicPromptCachingMiddleware = None  # type: ignore[assignment,misc]


# ── Stable wrapper ────────────────────────────────────────────────────────────

def create_deep_agent(**kwargs):  # type: ignore[no-untyped-def]
    """Stable wrapper around deepagents.create_deep_agent.

    Normalises keyword argument names if the upstream API changes between
    minor versions. Current 0.4.x signature is backward-compatible; this
    wrapper provides a shim point without requiring changes to agent.py.

    Upgrade procedure (dev_docs/17 §4.3):
      1. Update _DA_MIN / _DA_NEXT_MAJOR if needed
      2. Add kwarg remapping here (e.g. old_name → new_name)
      3. Update feature flags above for new gated features
      4. Run: pytest tests/unit/test_agent_bridge.py -v
    """
    return _create_deep_agent(**kwargs)


def build_summarization_middleware(model):  # type: ignore[no-untyped-def]
    """Create a SummarizationMiddleware instance for the given model.

    Uses StateBackend (in-memory, no filesystem dependency) as the backend
    so compiled subagents get context compression without needing a real
    filesystem or sandbox backend.

    Returns None when SummarizationMiddleware or StateBackend are unavailable.
    """
    if not HAS_SUMMARIZATION:
        return None
    if _create_summarization_middleware is None or _StateBackend is None:
        return None
    try:
        return _create_summarization_middleware(model, _StateBackend)
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

__all__ = [
    # Core
    "create_deep_agent",
    "build_summarization_middleware",
    "CompiledSubAgent",
    "SubAgent",
    # Version-gated (may be None if version too old)
    "SummarizationMiddleware",
    "SummarizationToolMiddleware",
    "create_summarization_tool_middleware",
    "AnthropicPromptCachingMiddleware",
    "LocalShellBackend",
    "AsyncSubAgent",
    "AsyncSubAgentMiddleware",
    # Feature flags
    "HAS_SUMMARIZATION",
    "HAS_PROMPT_CACHING",
    "HAS_LOCAL_SHELL_BACKEND",
    "HAS_NAMESPACE_FACTORY",
    "HAS_ASYNC_SUBAGENTS",
    # Version info
    "_DA_VERSION",
    "_DA_MIN",
    "_DA_NEXT_MAJOR",
]
