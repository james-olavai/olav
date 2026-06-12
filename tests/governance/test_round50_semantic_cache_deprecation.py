"""Round 50 — ARCH-22 C5 SemanticCache ``store`` / ``table_name`` deprecation.

The cache has been process-local since v0.14 but the constructor still
accepts the legacy ``store`` and ``table_name`` kwargs silently. Round 50
ships a ``DeprecationWarning`` so callers passing those kwargs can fix
their code before the next-major removal. Runtime behaviour is
unchanged — the kwargs are still ignored, just warned about.

Pins:

* default construction (no deprecated kwargs) is warning-free
* passing ``store=<anything>`` emits ``DeprecationWarning`` referencing ARCH-22
* passing ``table_name=<non-default>`` emits ``DeprecationWarning``
* the explicit default ``table_name="query_cache"`` does NOT warn
  (backward-compat — common callers hardcode the default literal)
"""

from __future__ import annotations

import sys
import warnings

import pytest


@pytest.fixture(autouse=True)
def _clear_warning_registry():
    """Reset per-module __warningregistry__ dicts before each test.

    Python deduplicates warnings via per-module registries; earlier tests that
    import SemanticCache would mark the DeprecationWarning as "already shown,"
    causing catch_warnings(record=True) to miss it in subsequent tests.
    """
    for mod in list(sys.modules.values()):
        reg = getattr(mod, "__warningregistry__", None)
        if reg is not None:
            reg.clear()
    yield


def _semantic_cache_cls():
    # Governance pin should not fail in minimal envs where memory backend deps
    # are intentionally optional for test-only jobs.
    for dep in ("lancedb", "pyarrow"):
        pytest.importorskip(dep)
    from olav.core.memory import SemanticCache

    return SemanticCache


def test_default_construction_is_silent():
    SemanticCache = _semantic_cache_cls()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SemanticCache()
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deps == [], (
        f"Default SemanticCache() must not emit DeprecationWarning; got {deps}"
    )


def test_explicit_default_table_name_is_silent():
    """Callers hardcoding the literal default must not trigger the warning."""
    SemanticCache = _semantic_cache_cls()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SemanticCache(table_name="query_cache")
    deps = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "table_name" in str(w.message)
    ]
    assert deps == [], (
        f"SemanticCache(table_name='query_cache') matches the default and "
        f"must not warn; got: {[str(w.message) for w in deps]}"
    )


def test_store_kwarg_emits_deprecation_warning():
    SemanticCache = _semantic_cache_cls()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SemanticCache(store=object())
    deps = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "store" in str(w.message)
    ]
    assert len(deps) == 1, (
        f"SemanticCache(store=<obj>) must emit exactly one DeprecationWarning; "
        f"got {deps}"
    )
    # Message must reference the next-major plan so readers know what to do.
    msg = str(deps[0].message)
    assert "deprecated" in msg.lower()
    assert "next major" in msg.lower()


def test_nondefault_table_name_emits_deprecation_warning():
    SemanticCache = _semantic_cache_cls()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SemanticCache(table_name="custom_cache_table")
    deps = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "table_name" in str(w.message)
    ]
    assert len(deps) == 1
    assert "next major" in str(deps[0].message).lower()


def test_both_deprecated_kwargs_emit_both_warnings():
    SemanticCache = _semantic_cache_cls()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SemanticCache(store=object(), table_name="x")
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    msgs = [str(w.message) for w in deps]
    assert any("store" in m for m in msgs), f"missing store warning; got {msgs}"
    assert any("table_name" in m for m in msgs), f"missing table_name warning; got {msgs}"


def test_default_table_name_constant_pinned():
    SemanticCache = _semantic_cache_cls()
    assert SemanticCache._DEFAULT_TABLE_NAME == "query_cache", (
        "If the default table_name sentinel changes, the comparison in "
        "__init__ must be updated too — otherwise the warning fires for "
        "callers that already migrated to the new default."
    )


def test_runtime_behaviour_unchanged_by_deprecated_kwargs():
    """Deprecated kwargs emit warnings but must still produce a working
    cache instance — no TypeError, no broken state."""
    SemanticCache = _semantic_cache_cls()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cache = SemanticCache(store=object(), table_name="whatever")
    # The in-memory cache methods must still be callable.
    assert cache._threshold == 0.02
    assert cache._max_entries == 500
    # get() on an empty cache must return None, not raise.
    assert cache.get([0.1, 0.2, 0.3]) is None


def test_docstring_or_comment_references_arch_22_c5():
    """Post-round-50 the source must tag ARCH-22 C5 so future readers can
    cross-reference the ledger."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    src = (repo / "src" / "olav" / "core" / "memory" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "ARCH-22 C5" in src, (
        "SemanticCache deprecation must carry the ARCH-22 C5 tag for "
        "traceability back to the ledger entry."
    )
