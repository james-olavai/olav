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


# ── Helper: atomic multi-submodule import ────────────────────────────────────
# ARCH-22 E (Round 30): replaces 4 repeated ``if HAS_X: try/except: None; else:
# None`` blocks. "All or nothing" semantics mean a partial-install deepagents
# version degrades cleanly to "feature off" rather than half-available.


def _safe_imports(
    *specs: tuple[str, str, str | None],
    enabled: bool = True,
) -> dict[str, object | None]:
    """Atomically import ``(module_path, attr, alias_or_None)`` specs.

    Returns a dict keyed by ``alias or attr``. When ``enabled`` is False, or
    any import in the group fails, every key maps to ``None``.
    """
    import importlib

    keys = [alias or attr for _module, attr, alias in specs]
    if not enabled:
        return dict.fromkeys(keys, None)
    try:
        out: dict[str, object | None] = {}
        for module_path, attr, alias in specs:
            mod = importlib.import_module(module_path)
            out[alias or attr] = getattr(mod, attr)
        return out
    except (ImportError, AttributeError):
        return dict.fromkeys(keys, None)


# ── Version-gated exports ─────────────────────────────────────────────────────

_summ = _safe_imports(
    ("deepagents.backends", "StateBackend", "_StateBackend"),
    ("deepagents.middleware.summarization", "SummarizationToolMiddleware", None),
    ("deepagents.middleware.summarization", "create_summarization_middleware", "_create_summarization_middleware"),
    ("deepagents.middleware.summarization", "create_summarization_tool_middleware", None),
    ("deepagents.middleware", "SummarizationMiddleware", None),
    enabled=HAS_SUMMARIZATION,
)
_StateBackend = _summ["_StateBackend"]
SummarizationToolMiddleware = _summ["SummarizationToolMiddleware"]
_create_summarization_middleware = _summ["_create_summarization_middleware"]
create_summarization_tool_middleware = _summ["create_summarization_tool_middleware"]
SummarizationMiddleware = _summ["SummarizationMiddleware"]

LocalShellBackend = _safe_imports(
    ("deepagents.backends", "LocalShellBackend", None),
    enabled=HAS_LOCAL_SHELL_BACKEND,
)["LocalShellBackend"]

_async = _safe_imports(
    ("deepagents.middleware.async_subagents", "AsyncSubAgent", None),
    ("deepagents.middleware.async_subagents", "AsyncSubAgentMiddleware", None),
    enabled=HAS_ASYNC_SUBAGENTS,
)
AsyncSubAgent = _async["AsyncSubAgent"]
AsyncSubAgentMiddleware = _async["AsyncSubAgentMiddleware"]

# AnthropicPromptCachingMiddleware: from langchain_anthropic (available in 0.4.x
# via deepagents dep). Missing import demotes the feature flag too.
AnthropicPromptCachingMiddleware = _safe_imports(
    ("langchain_anthropic.middleware", "AnthropicPromptCachingMiddleware", None),
    enabled=HAS_PROMPT_CACHING,
)["AnthropicPromptCachingMiddleware"]
if AnthropicPromptCachingMiddleware is None:
    HAS_PROMPT_CACHING = False


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


_SUMMARIZATION_DEBUG_ENV = "OLAV_DEBUG_SUMMARIZATION"


def _summarization_debug_enabled() -> bool:
    """True when operator opts into SummarizationMiddleware config logging."""
    import os
    raw = os.environ.get(_SUMMARIZATION_DEBUG_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def compute_summarization_trigger(tier: str | None) -> tuple[str, int] | None:
    """Compute tier-specific ``trigger`` for SummarizationMiddleware (ARCH-19).

    Returns a ``("tokens", N)`` tuple so the trigger works regardless of
    whether the model carries a ``profile`` / ``max_input_tokens``
    attribute (upstream's ``("fraction", 0.85)`` default fails silently on
    profile-less models; our absolute-tokens threshold always fires).

    Resolution:
    * ``tier`` must be one of small/medium/large to enable tier-aware mode.
    * Threshold = ``TIER_DEFAULTS[tier].context_budget *
      summarization_trigger_pct``.
    * Returns ``None`` when tier is missing or config unavailable — caller
      must fall back to upstream defaults.
    """
    if tier not in {"small", "medium", "large"}:
        return None
    try:
        from olav.core.config import TIER_DEFAULTS, tier_default
        budget = int(TIER_DEFAULTS.get(tier, {}).get("context_budget") or 0)
        if budget <= 0:
            return None
        pct = float(tier_default(tier, "summarization_trigger_pct", 0.0) or 0.0)
        if pct <= 0 or pct >= 1:
            return None
        return ("tokens", int(budget * pct))
    except Exception:
        return None


def build_summarization_middleware(model, tier: str | None = None):  # type: ignore[no-untyped-def]
    """Create a SummarizationMiddleware instance for the given model.

    Uses StateBackend (in-memory, no filesystem dependency) as the backend
    so compiled subagents get context compression without needing a real
    filesystem or sandbox backend.

    Args:
        model: Resolved ``BaseChatModel`` instance.
        tier: Optional tier hint (``"small"`` / ``"medium"`` / ``"large"``).
            When provided, selects an ARCH-19 tier-aware ``trigger`` from
            ``TIER_DEFAULTS.summarization_trigger_pct`` × ``context_budget``
            instead of the upstream 85% default. ``None`` or unknown tier
            falls back to upstream ``create_summarization_middleware``.

    Returns None when SummarizationMiddleware or StateBackend are unavailable.
    """
    if not HAS_SUMMARIZATION:
        return None
    if _create_summarization_middleware is None or _StateBackend is None:
        return None

    trigger = compute_summarization_trigger(tier)
    try:
        if trigger is None:
            # Unknown / unsupported tier → upstream defaults (profile-aware
            # fraction=0.85 when available, fixed-token fallback otherwise).
            mw = _create_summarization_middleware(model, _StateBackend)
        else:
            # Tier-aware path — instantiate directly so we can override
            # trigger without fighting ``compute_summarization_defaults``.
            if SummarizationMiddleware is None:
                return _create_summarization_middleware(model, _StateBackend)
            mw = SummarizationMiddleware(
                model=model,
                backend=_StateBackend,
                trigger=trigger,
                keep=("messages", 6),
            )
    except Exception:
        return None

    if _summarization_debug_enabled():
        try:
            import logging
            _log = logging.getLogger(__name__)
            if trigger is not None:
                _log.info(
                    "OLAV_DEBUG_SUMMARIZATION: tier=%s trigger=%s keep=%s "
                    "(ARCH-19 tier-aware)",
                    tier, trigger, ("messages", 6),
                )
            else:
                _log.info(
                    "OLAV_DEBUG_SUMMARIZATION: tier=%r — upstream defaults "
                    "(compute_summarization_defaults auto-selected)",
                    tier,
                )
        except Exception:
            pass
    return mw


# ── Public API ────────────────────────────────────────────────────────────────

__all__ = [
    # Core
    "create_deep_agent",
    "build_summarization_middleware",
    "compute_summarization_trigger",
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
