"""
_deepagents_bridge.py — deepagents API 的版本隔离层。

升级 deepagents 时只需改这一个文件。
agent.py 和其他模块从这里导入，不直接接触 deepagents 包。

版本策略:
  supported range: >=0.4.12, <1.0
  - 低于 _DA_MIN  → ImportError (明确告知升级路径)
  - >=1.0         → UserWarning (可能有 breaking changes，需人工验证)
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
        "deepagents is not installed. Run: pip install 'deepagents>=0.4.12,<1.0'"
    ) from exc

_DA_MIN = V("0.4.11")
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

HAS_LOCAL_SHELL_BACKEND: bool = _DA_VERSION >= V("0.4.0")
"""True when LocalShellBackend is available (subprocess execution backend)."""

HAS_NAMESPACE_FACTORY: bool = _DA_VERSION >= V("0.4.0")
"""True when NamespaceFactory / BackendContext pattern is available."""

# ── Core exports (stable across 0.4.x) ───────────────────────────────────────

from deepagents import create_deep_agent as _create_deep_agent  # noqa: E402
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent  # noqa: E402

# ── Version-gated exports ─────────────────────────────────────────────────────

if HAS_SUMMARIZATION:
    try:
        from deepagents.middleware import SummarizationMiddleware
    except ImportError:
        SummarizationMiddleware = None  # type: ignore[assignment,misc]
else:
    SummarizationMiddleware = None  # type: ignore[assignment,misc]

if HAS_LOCAL_SHELL_BACKEND:
    try:
        from deepagents.backends import LocalShellBackend
    except ImportError:
        LocalShellBackend = None  # type: ignore[assignment,misc]
else:
    LocalShellBackend = None  # type: ignore[assignment,misc]


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


# ── Public API ────────────────────────────────────────────────────────────────

__all__ = [
    # Core
    "create_deep_agent",
    "CompiledSubAgent",
    "SubAgent",
    # Version-gated (may be None if version too old)
    "SummarizationMiddleware",
    "LocalShellBackend",
    # Feature flags
    "HAS_SUMMARIZATION",
    "HAS_LOCAL_SHELL_BACKEND",
    "HAS_NAMESPACE_FACTORY",
    # Version info
    "_DA_VERSION",
    "_DA_MIN",
    "_DA_NEXT_MAJOR",
]
