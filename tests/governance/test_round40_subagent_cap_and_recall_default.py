"""Round 40 — ARCH-18 #4 subagent return cap + ARCH-16 olav_recall_memory tier default.

Both land on the "tier-driven runtime output caps" theme:

* **ARCH-18 #4** — ``olav_delegate`` returned content is capped to the
  current tier's ``TIER_DEFAULTS.return_compact_chars`` (small=2000,
  medium=5000, large=10000). A chatty subagent can no longer eat a
  small-tier orchestrator's context window in a single delegate call.
* **ARCH-16**  — ``olav_recall_memory(limit=None)`` resolves via
  ``TIER_DEFAULTS.recall_top_k`` (small=1, medium=2, large=3). Explicit
  ``limit=`` still wins and keeps the 1..10 clamp.

Both reuse the ``tier_default`` switchboard that ARCH-17/19 already
consume, so all four issues share one config.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DELEGATE_PY = REPO / "src" / "olav" / "agents" / "delegate_tool.py"
RECALL_PY = REPO / ".olav" / "workspace" / "core" / "scripts" / "olav_recall_memory.py"

_MISSING = object()


def _load_module(py: Path, alias: str, *, stub_memory: bool = False):
    _saved = sys.modules.get("olav.core.memory", _MISSING)
    if stub_memory:
        fake_memory_pkg = types.ModuleType("olav.core.memory")
        fake_memory_pkg.__path__ = []
        fake_memory_pkg.get_store = lambda *a, **k: None
        fake_memory_pkg.hybrid_search = lambda *a, **k: []
        fake_memory_pkg.MEMORY_TABLE = "memory"
        sys.modules["olav.core.memory"] = fake_memory_pkg
    try:
        spec = importlib.util.spec_from_file_location(alias, py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if stub_memory:
            if _saved is _MISSING:
                sys.modules.pop("olav.core.memory", None)
            else:
                sys.modules["olav.core.memory"] = _saved


# ── ARCH-18 #4 delegate cap pins ─────────────────────────────────────────


def test_delegate_tool_defines_cap_helper():
    """_resolve_subagent_cap must exist — it's the single switchboard."""
    mod = _load_module(DELEGATE_PY, "delegate_tool_u1")
    assert callable(getattr(mod, "_resolve_subagent_cap", None)), (
        "delegate_tool._resolve_subagent_cap helper missing — ARCH-18 #4 regression"
    )


def test_delegate_tool_defines_truncate_helper():
    mod = _load_module(DELEGATE_PY, "delegate_tool_u2")
    assert callable(getattr(mod, "_truncate", None))


def test_delegate_tool_truncate_short_content_untouched():
    """Below-cap content must pass through unchanged — cap should not be
    a minimum enforcement, only a maximum."""
    mod = _load_module(DELEGATE_PY, "delegate_tool_u3")
    out = mod._truncate("short", cap=1000)
    assert out == "short"


def test_delegate_tool_truncate_above_cap_adds_suffix():
    mod = _load_module(DELEGATE_PY, "delegate_tool_u4")
    long_content = "x" * 5000
    out = mod._truncate(long_content, cap=200)
    assert out.startswith("x" * 200)
    assert "truncated" in out
    # Original length must be surfaced so the LLM knows *how* much was cut.
    assert "5000" in out
    assert "200" in out


def test_delegate_tool_truncate_cap_zero_is_noop():
    """Zero / negative cap disables truncation — defensive behaviour so a
    misconfigured tier can't silently zero out every delegate return."""
    mod = _load_module(DELEGATE_PY, "delegate_tool_u5")
    out = mod._truncate("x" * 500, cap=0)
    assert out == "x" * 500


def test_delegate_tool_fallback_when_config_unavailable(monkeypatch):
    """If olav.core.config can't be imported (e.g. minimal smoke env), the
    cap resolver must fall back to _SUBAGENT_RETURN_FALLBACK, not blow up."""
    import sys as _sys
    mod = _load_module(DELEGATE_PY, "delegate_tool_u6")
    # Force ImportError on config fetch by stashing a sentinel.
    monkeypatch.setitem(_sys.modules, "olav.core.config", None)
    try:
        cap = mod._resolve_subagent_cap()
    finally:
        pass
    assert cap == mod._SUBAGENT_RETURN_FALLBACK


def test_delegate_tool_cap_reads_tier_return_compact_chars():
    """Positive path: when TIER_DEFAULTS is present, cap reflects the tier."""
    mod = _load_module(DELEGATE_PY, "delegate_tool_u7")
    cap = mod._resolve_subagent_cap()
    # Whatever tier is active, the cap must be a plausible positive int.
    assert isinstance(cap, int)
    assert cap > 0


# ── ARCH-16 olav_recall_memory tier-aware default pins ────────────────────────


def test_olav_recall_memory_limit_is_optional():
    """The function signature must expose ``limit`` as optional."""
    import inspect
    mod = _load_module(RECALL_PY, "olav_recall_memory_u1", stub_memory=True)
    schema = getattr(mod.olav_recall_memory, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
        assert "limit" in fields
        limit_field = fields["limit"]
        required = getattr(limit_field, "is_required", None)
        if callable(required):
            required = required()
        assert required is False, "olav_recall_memory(limit=...) must be optional"
    else:
        sig = inspect.signature(mod.olav_recall_memory)
        assert "limit" in sig.parameters, "olav_recall_memory missing limit param"
        param = sig.parameters["limit"]
        assert param.default is not inspect.Parameter.empty, (
            "olav_recall_memory(limit=...) must be optional so tier default can apply"
        )


def test_olav_recall_memory_defines_resolve_helper():
    mod = _load_module(RECALL_PY, "olav_recall_memory_u2", stub_memory=True)
    assert callable(getattr(mod, "_resolve_recall_limit", None))


def test_olav_recall_memory_resolve_explicit_clamps_1_10():
    mod = _load_module(RECALL_PY, "olav_recall_memory_u3", stub_memory=True)
    assert mod._resolve_recall_limit(5) == 5
    assert mod._resolve_recall_limit(0) == 1   # lower clamp
    assert mod._resolve_recall_limit(100) == 10  # upper clamp
    assert mod._resolve_recall_limit(-1) == 1


def test_olav_recall_memory_resolve_none_uses_tier_default():
    """None → tier default via tier_default(tier, "recall_top_k", ...).
    Whatever tier is active, the result must be in [1, 10]."""
    mod = _load_module(RECALL_PY, "olav_recall_memory_u4", stub_memory=True)
    val = mod._resolve_recall_limit(None)
    assert isinstance(val, int)
    assert 1 <= val <= 10


def test_olav_recall_memory_fallback_when_config_unavailable(monkeypatch):
    import sys as _sys
    mod = _load_module(RECALL_PY, "olav_recall_memory_u5", stub_memory=True)
    monkeypatch.setitem(_sys.modules, "olav.core.config", None)
    val = mod._resolve_recall_limit(None)
    # Fallback is 3 per module constant.
    assert val == mod._RECALL_MEMORY_FALLBACK_TOP_K


def test_olav_recall_memory_docstring_documents_tier_default():
    src = RECALL_PY.read_text(encoding="utf-8")
    assert "tier default" in src.lower() or "TIER_DEFAULTS" in src, (
        "olav_recall_memory docstring must document that omitting limit triggers "
        "tier-aware default — otherwise LLMs won't know it's a feature."
    )
