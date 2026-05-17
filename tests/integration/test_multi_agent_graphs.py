"""
tests/integration/test_multi_agent_graphs.py
─────────────────────────────────────────────
TDD tests for the make_graph(config) factory added to
src/olav/server/graph_factory.py in Phase 2.

make_graph(config) is called by native langgraph_api once per
graph_id, and must dispatch to the correct OLAV compiled graph.
It caches by graph_id so subsequent calls with the same id return
the same object without rebuilding.

The existing module-level ``graph`` variable (used by the TUI's
langgraph dev subprocess) must remain unchanged.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Tests — written BEFORE implementation (TDD red phase)
# ---------------------------------------------------------------------------

class TestMakeGraph:
    def test_make_graph_builds_core_by_default(self):
        """No graph_id in config → falls back to core."""
        from olav.server.graph_factory import make_graph  # noqa: PLC0415

        compiled = make_graph({})
        # Must be a compiled LangGraph object (has .invoke / .astream)
        assert hasattr(compiled, "invoke") or hasattr(compiled, "astream")

    def test_make_graph_explicit_core(self):
        from olav.server.graph_factory import make_graph  # noqa: PLC0415

        compiled = make_graph({"configurable": {"graph_id": "core"}})
        assert hasattr(compiled, "invoke") or hasattr(compiled, "astream")

    def test_make_graph_unknown_raises(self):
        from olav.server.graph_factory import make_graph  # noqa: PLC0415

        with pytest.raises((ValueError, FileNotFoundError, KeyError)):
            make_graph({"configurable": {"graph_id": "__no_such_agent__"}})

    def test_make_graph_caches_by_graph_id(self):
        """Second call with same graph_id returns the cached object."""
        from olav.server.graph_factory import make_graph, _graph_cache  # noqa: PLC0415

        _graph_cache.clear()
        g1 = make_graph({"configurable": {"graph_id": "core"}})
        g2 = make_graph({"configurable": {"graph_id": "core"}})
        assert g1 is g2

    def test_make_graph_none_config_uses_core(self):
        """Passing None config should not crash."""
        from olav.server.graph_factory import make_graph  # noqa: PLC0415

        compiled = make_graph(None)
        assert hasattr(compiled, "invoke") or hasattr(compiled, "astream")


class TestModuleLevelGraph:
    def test_module_level_graph_still_exists(self):
        """TUI backward compat: module-level graph must still be present."""
        import olav.server.graph_factory as gf  # noqa: PLC0415

        assert hasattr(gf, "graph")
        assert gf.graph is not None

    def test_graph_cache_dict_exists(self):
        """_graph_cache module attr must exist for reload endpoint."""
        import olav.server.graph_factory as gf  # noqa: PLC0415

        assert hasattr(gf, "_graph_cache")
        assert isinstance(gf._graph_cache, dict)


@pytest.mark.skipif(
    not __import__("pathlib").Path(".olav/workspace/netops").exists(),
    reason="netops workspace not installed",
)
class TestMakeGraphNetops:
    def test_make_graph_builds_netops(self):
        from olav.server.graph_factory import make_graph  # noqa: PLC0415

        compiled = make_graph({"configurable": {"graph_id": "netops"}})
        assert hasattr(compiled, "invoke") or hasattr(compiled, "astream")
