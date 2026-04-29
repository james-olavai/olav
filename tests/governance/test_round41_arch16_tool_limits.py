"""Round 41 — ARCH-16 tool-level LIMITs (execute_sql + search_logs tier-aware).

Completes the Round 40 recall_memory work. Remaining ARCH-16 tool gaps:

* ``execute_sql`` surfaces at most ``TIER_DEFAULTS.execute_sql_context_rows``
  rows to the LLM (small=10 / medium=20 / large=50). CSV export at >50
  rows stays regardless of tier — that's data persistence, not context.
* ``search_logs(limit=None)`` resolves to
  ``TIER_DEFAULTS.search_logs_default_limit`` (small=20 / medium=50 /
  large=100). Hard ceiling 500 even when a caller passes a bigger
  explicit value.

Both reuse the existing ``tier_default`` switchboard (ARCH-17/18/19 all
consume the same map), so the new keys land in a single place.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG_PY = REPO / "src" / "olav" / "core" / "config.py"
EXECUTE_SQL_PY = REPO / ".olav" / "workspace" / "core" / "tools" / "execute_sql.py"
# Post-R65 (ARCH-23): search_logs relocated from core/tools/ to admin/tools/.
# R100/S5 (2026-04-29): re-promoted to shared core/tools/ so ops, audit,
# and other top-level agents can access it without 2-hop delegation.
SEARCH_LOGS_PY = REPO / ".olav" / "workspace" / "core" / "tools" / "search_logs.py"


def _load(py: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── TIER_DEFAULTS new keys ──────────────────────────────────────────────


def test_tier_defaults_has_execute_sql_context_rows():
    from olav.core.config import TIER_DEFAULTS
    for tier, expected in [("small", 10), ("medium", 20), ("large", 50)]:
        assert "execute_sql_context_rows" in TIER_DEFAULTS[tier]
        assert TIER_DEFAULTS[tier]["execute_sql_context_rows"] == expected, (
            f"tier {tier} execute_sql_context_rows drifted from Round 41 spec"
        )


def test_tier_defaults_has_search_logs_default_limit():
    from olav.core.config import TIER_DEFAULTS
    for tier, expected in [("small", 20), ("medium", 50), ("large", 100)]:
        assert "search_logs_default_limit" in TIER_DEFAULTS[tier]
        assert TIER_DEFAULTS[tier]["search_logs_default_limit"] == expected, (
            f"tier {tier} search_logs_default_limit drifted from Round 41 spec"
        )


def test_tier_defaults_small_rows_smaller_than_large():
    """Monotonic invariant: small ≤ medium ≤ large for capacity keys."""
    from olav.core.config import TIER_DEFAULTS
    for key in ("execute_sql_context_rows", "search_logs_default_limit"):
        s, m, l = (TIER_DEFAULTS[t][key] for t in ("small", "medium", "large"))
        assert s <= m <= l, f"{key} must be monotonic across tiers: {s}, {m}, {l}"


# ── execute_sql helper pins ─────────────────────────────────────────────


def test_execute_sql_defines_resolve_context_rows():
    mod = _load(EXECUTE_SQL_PY, "execute_sql_u1")
    assert callable(getattr(mod, "_resolve_context_rows", None))


def test_execute_sql_resolve_returns_plausible_int():
    mod = _load(EXECUTE_SQL_PY, "execute_sql_u2")
    val = mod._resolve_context_rows()
    assert isinstance(val, int)
    assert val >= 1


def test_execute_sql_resolve_fallback_when_config_unavailable(monkeypatch):
    import sys as _sys
    mod = _load(EXECUTE_SQL_PY, "execute_sql_u3")
    monkeypatch.setitem(_sys.modules, "olav.core.config", None)
    val = mod._resolve_context_rows()
    assert val == mod._CONTEXT_ROWS_FALLBACK


def test_execute_sql_uses_resolver_not_hardcoded_20():
    """Make sure the hardcoded 20 didn't silently come back — the assignment
    must go through the resolver so the switchboard stays in use."""
    src = EXECUTE_SQL_PY.read_text(encoding="utf-8")
    assert "MAX_ROWS_TO_CONTEXT = _resolve_context_rows()" in src, (
        "execute_sql MAX_ROWS_TO_CONTEXT no longer goes through _resolve_context_rows()"
    )


def test_execute_sql_no_literal_20_for_max_rows():
    """Belt-and-braces: the old hardcoded ``MAX_ROWS_TO_CONTEXT = 20`` line
    must not reappear."""
    src = EXECUTE_SQL_PY.read_text(encoding="utf-8")
    assert "MAX_ROWS_TO_CONTEXT = 20" not in src


# ── search_logs helper pins ─────────────────────────────────────────────


def test_search_logs_defines_resolve_helper():
    mod = _load(SEARCH_LOGS_PY, "search_logs_u1")
    assert callable(getattr(mod, "_resolve_search_limit", None))


def test_search_logs_hard_ceiling_defined():
    mod = _load(SEARCH_LOGS_PY, "search_logs_u2")
    assert getattr(mod, "_SEARCH_LOGS_HARD_MAX", None) == 500


def test_search_logs_limit_is_optional():
    mod = _load(SEARCH_LOGS_PY, "search_logs_u3")
    schema = getattr(mod.search_logs, "args_schema", None)
    assert schema is not None
    fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
    assert "limit" in fields
    required = getattr(fields["limit"], "is_required", None)
    if callable(required):
        required = required()
    assert required is False, (
        "search_logs(limit=...) must be optional so tier default applies"
    )


def test_search_logs_resolve_explicit_clamps():
    mod = _load(SEARCH_LOGS_PY, "search_logs_u4")
    assert mod._resolve_search_limit(50) == 50
    assert mod._resolve_search_limit(0) == 1
    # Explicit 9999 must clamp to hard ceiling 500 — prevents a buggy caller
    # from blowing the budget.
    assert mod._resolve_search_limit(9999) == 500
    assert mod._resolve_search_limit(-10) == 1


def test_search_logs_resolve_none_uses_tier_default():
    mod = _load(SEARCH_LOGS_PY, "search_logs_u5")
    val = mod._resolve_search_limit(None)
    assert isinstance(val, int)
    assert 1 <= val <= 500


def test_search_logs_fallback_when_config_unavailable(monkeypatch):
    import sys as _sys
    mod = _load(SEARCH_LOGS_PY, "search_logs_u6")
    monkeypatch.setitem(_sys.modules, "olav.core.config", None)
    val = mod._resolve_search_limit(None)
    assert val == mod._SEARCH_LOGS_FALLBACK == 50


def test_search_logs_docstring_documents_tier():
    src = SEARCH_LOGS_PY.read_text(encoding="utf-8")
    assert "search_logs_default_limit" in src, (
        "search_logs docstring/code lost reference to search_logs_default_limit"
    )
    assert "ARCH-16" in src
