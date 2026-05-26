"""
_deepagents_bridge.py — deepagents API 的版本隔离层。

升级 deepagents 时只需改这一个文件。
agent.py 和其他模块从这里导入，不直接接触 deepagents 包。

版本策略 (2026-05-16 更新, _DA_MIN bumped from 0.5.0 → 0.5.9 to match pyproject):
  supported range: >=0.5.9, <0.6
  - 低于 _DA_MIN  → ImportError (明确告知升级路径)
  - >=0.6.0       → UserWarning (实验性 CodeInterpreterMiddleware + v3 stream_events,
                    需 OLAV 单独验证再放行)

0.5 主要功能演进:
  - 0.5.2 FilesystemPermission (虚拟 FS 读/写访问控制 — 激活 agent.py:574-612 的写保护)
  - 0.5.4 Harness Profiles (按 provider/model 注册 prompt/tool/middleware 覆盖层 —
          OLAV 在 src/olav/agents/profiles/ 下使用)
  - 0.5.5 FilesystemBackend symlink-loop 加固
  - 0.5.6 CompiledSubAgent 名字传 lc_agent_name 元数据 (LangSmith trace 清晰化)
  - 0.5.7 GP-subagent 继承父级 permissions
  - 0.5.0 AsyncSubAgent / AsyncSubAgentMiddleware: 非阻塞后台子智能体 (需 LangGraph Platform)
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

_DA_MIN = V("0.5.9")
_DA_NEXT_MAJOR = V("0.6.0")  # 0.6.x adds experimental CodeInterpreter + v3 events; re-evaluate after upstream stabilises

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

# SkillsMiddleware — native deepagents skill discovery layer (ADR-0008).
# Available since deepagents 0.5.x; always present in our supported range.
_skills = _safe_imports(
    ("deepagents.middleware.skills", "SkillsMiddleware", None),
    ("deepagents.backends", "FilesystemBackend", None),
    enabled=True,
)
SkillsMiddleware = _skills["SkillsMiddleware"]
FilesystemBackend = _skills["FilesystemBackend"]
HAS_SKILLS_MIDDLEWARE: bool = SkillsMiddleware is not None
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
        # Per-deployment override: api.json `llm.context_budget` or
        # OLAV_LLM_CONTEXT_BUDGET env wins over the tier default.
        # Critical for local-llama.cpp deployments where the actual ctx
        # is far below the tier's nominal max (e.g. qwen3.6-27b at 64K
        # is "large" by name but 200K tier default would defer
        # summarization until 160K — we'd hit the 64K wall first).
        budget = 0
        try:
            import os
            if env_budget := os.environ.get("OLAV_LLM_CONTEXT_BUDGET"):
                budget = int(env_budget)
        except Exception:
            pass
        if budget <= 0:
            try:
                from olav.core.config import get_llm_config
                cfg = get_llm_config()
                cfg_budget = getattr(cfg, "context_budget", None)
                if isinstance(cfg_budget, int) and cfg_budget > 0:
                    budget = cfg_budget
            except Exception:
                pass
        if budget <= 0:
            budget = int(TIER_DEFAULTS.get(tier, {}).get("context_budget") or 0)
        if budget <= 0:
            return None
        pct = float(tier_default(tier, "summarization_trigger_pct", 0.0) or 0.0)
        if pct <= 0 or pct >= 1:
            return None
        return ("tokens", int(budget * pct))
    except Exception:
        return None


def _make_summarization_backend():  # type: ignore[no-untyped-def]
    """Return a backend for SummarizationMiddleware history offloading.

    Prefers LocalShellBackend (virtual_mode=True, root=.olav/logs) so history
    is offloaded to local disk without requiring the LangGraph ``files`` channel.
    StateBackend requires FilesystemMiddleware to register that channel; agents
    that skip FilesystemMiddleware (agent_type: api) hit KeyError: 'files' when
    StateBackend._read_files() is called during offloading.

    Falls back to StateBackend when LocalShellBackend is unavailable.
    """
    if LocalShellBackend is not None:
        from pathlib import Path as _Path
        return lambda _rt: LocalShellBackend(
            root_dir=str(_Path.cwd() / ".olav" / "logs"),
            virtual_mode=True,
        )
    return _StateBackend


def build_summarization_middleware(model, tier: str | None = None):  # type: ignore[no-untyped-def]
    """Create a SummarizationMiddleware instance for the given model.

    Uses LocalShellBackend (writes to .olav/logs/) for history offloading so
    the middleware works in agents that do not register FilesystemMiddleware
    (agent_type: api). StateBackend required the LangGraph ``files`` channel
    which only exists when FilesystemMiddleware is in the stack; omitting it
    caused KeyError: 'files' in _offload_to_backend for every api-type agent.

    Args:
        model: Resolved ``BaseChatModel`` instance.
        tier: Optional tier hint (``"small"`` / ``"medium"`` / ``"large"``).
            When provided, selects an ARCH-19 tier-aware ``trigger`` from
            ``TIER_DEFAULTS.summarization_trigger_pct`` × ``context_budget``
            instead of the upstream 85% default. ``None`` or unknown tier
            falls back to upstream ``create_summarization_middleware``.

    Returns None when SummarizationMiddleware is unavailable.
    """
    if not HAS_SUMMARIZATION:
        return None
    if _create_summarization_middleware is None:
        return None

    backend = _make_summarization_backend()
    if backend is None:
        return None

    trigger = compute_summarization_trigger(tier)
    try:
        if trigger is None:
            # Unknown / unsupported tier → upstream defaults (profile-aware
            # fraction=0.85 when available, fixed-token fallback otherwise).
            mw = _create_summarization_middleware(model, backend)
        else:
            # Tier-aware path — instantiate directly so we can override
            # trigger without fighting ``compute_summarization_defaults``.
            if SummarizationMiddleware is None:
                return _create_summarization_middleware(model, backend)
            mw = SummarizationMiddleware(
                model=model,
                backend=backend,
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
    "SkillsMiddleware",
    "FilesystemBackend",
    # Feature flags
    "HAS_SUMMARIZATION",
    "HAS_PROMPT_CACHING",
    "HAS_LOCAL_SHELL_BACKEND",
    "HAS_NAMESPACE_FACTORY",
    "HAS_ASYNC_SUBAGENTS",
    "HAS_SKILLS_MIDDLEWARE",
    # Version info
    "_DA_VERSION",
    "_DA_MIN",
    "_DA_NEXT_MAJOR",
]
