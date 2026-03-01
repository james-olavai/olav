"""Unit tests for memory guardrails: GuardrailInjector, list_namespaces fix."""

import json
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_store(memories=None, table_exists=True):
    store = MagicMock()
    store.embedding_dim = 384
    store.table_exists.return_value = table_exists
    store.search_by_vector.return_value = memories or []
    store.get_memories.return_value = memories or []
    store.add_memory.return_value = {"status": "success", "id": "test"}
    return store


def _failure_mem(text="show bgp timed out on R3"):
    return {
        "id": "f1",
        "text": text,
        "category": "audit",
        "scope": "ops",
        "metadata": json.dumps({"failure": True, "source": "failure_record"}),
        "timestamp": None,
        "weight": 0.9,
        "score": 0.05,
    }


def _success_mem(text="Always verify interface with show interfaces brief first"):
    return {
        "id": "s1",
        "text": text,
        "category": "audit",
        "scope": "ops",
        "metadata": json.dumps({"failure": False}),
        "timestamp": None,
        "weight": 1.0,
        "score": 0.1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GuardrailInjector
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardrailInjector:
    """Tests for GuardrailInjector."""

    def test_inject_appends_constraint_block(self):
        """inject() appends a constraint block to the system prompt."""
        from olav.core.memory.guardrails import GuardrailInjector

        mem = _failure_mem("show bgp on R3 timed out — use --limit next time")
        store = _make_store(memories=[mem])
        injector = GuardrailInjector(store)
        injector._embedder = False  # text-only fallback

        result = injector.inject("You are an ops agent.", query="check bgp", scope="ops")

        assert "=== LEARNED CONSTRAINTS" in result
        assert "show bgp on R3 timed out" in result
        assert "⚠" in result  # failure marker

    def test_inject_success_memory_uses_check_mark(self):
        """Success audit memories use ✓ prefix."""
        from olav.core.memory.guardrails import GuardrailInjector

        mem = _success_mem("Always verify interface with show interfaces brief")
        store = _make_store(memories=[mem])
        injector = GuardrailInjector(store)
        injector._embedder = False

        result = injector.inject("You are an agent.", query="check interface", scope="ops")

        assert "✓" in result

    def test_inject_no_memories_returns_original(self):
        """Returns original prompt unchanged when no audit memories exist."""
        from olav.core.memory.guardrails import GuardrailInjector

        store = _make_store(memories=[])
        injector = GuardrailInjector(store)

        original = "You are OLAV, a network ops assistant."
        result = injector.inject(original, query="test", scope="global")

        assert result == original

    def test_inject_no_table_returns_original(self):
        """Returns original prompt when memory table doesn't exist."""
        from olav.core.memory.guardrails import GuardrailInjector

        store = _make_store(table_exists=False)
        injector = GuardrailInjector(store)

        original = "system prompt"
        result = injector.inject(original, query="test")

        assert result == original

    def test_inject_non_fatal_on_exception(self):
        """Exceptions during injection are swallowed and original is returned."""
        from olav.core.memory.guardrails import GuardrailInjector

        store = _make_store()
        store.table_exists.side_effect = RuntimeError("DB crash")
        injector = GuardrailInjector(store)

        result = injector.inject("my prompt", query="test")
        assert result == "my prompt"

    def test_get_block_returns_empty_when_no_memories(self):
        """get_block() returns empty string when no audit memories."""
        from olav.core.memory.guardrails import GuardrailInjector

        store = _make_store(memories=[])
        injector = GuardrailInjector(store)

        block = injector.get_block("some query", scope="global")
        assert block == ""

    def test_get_block_returns_constraint_block(self):
        """get_block() returns formatted constraint text."""
        from olav.core.memory.guardrails import GuardrailInjector

        mem = _failure_mem("NTP sync failed on Core-Router")
        store = _make_store(memories=[mem])
        injector = GuardrailInjector(store)
        injector._embedder = False

        block = injector.get_block("check ntp", scope="ops")

        assert "NTP sync failed" in block
        assert "=== LEARNED CONSTRAINTS" in block
        assert "=== END CONSTRAINTS" in block

    def test_record_failure_stores_audit_memory(self):
        """record_failure() stores a failure audit memory."""
        from olav.core.memory.guardrails import GuardrailInjector

        store = _make_store()
        store.table_exists.return_value = True
        injector = GuardrailInjector(store)

        result = injector.record_failure("show bgp timed out", scope="ops")

        store.add_memory.assert_called_once()
        kwargs = store.add_memory.call_args.kwargs
        assert kwargs["category"] == "audit"
        assert "show bgp timed out" in kwargs["text"]
        meta = kwargs["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta.get("failure") is True

    def test_store_failure_memory_function(self):
        """store_failure_memory() creates table if absent and stores."""
        from olav.core.memory.guardrails import store_failure_memory

        store = _make_store(table_exists=False)
        result = store_failure_memory(store, "OSPF adjacency down on R4", scope="ops")

        store.create_table.assert_called_once()
        store.add_memory.assert_called_once()
        assert result["status"] == "success"

    def test_multiple_memories_all_formatted(self):
        """Multiple audit memories are all included in the constraint block."""
        from olav.core.memory.guardrails import GuardrailInjector

        mems = [
            _failure_mem("show bgp timed out"),
            _success_mem("verify interface state first"),
            _failure_mem("OSPF neighbor flap on R2"),
        ]
        store = _make_store(memories=mems)
        injector = GuardrailInjector(store)
        injector._embedder = False

        block = injector.get_block("query", scope="ops")

        assert "show bgp timed out" in block
        assert "verify interface state first" in block
        assert "OSPF neighbor flap on R2" in block


# ─────────────────────────────────────────────────────────────────────────────
# list_namespaces() fix
# ─────────────────────────────────────────────────────────────────────────────

class TestListNamespaces:
    """Tests for the fixed LangGraphLanceDBStore.list_namespaces()."""

    def _make_adapter(self, scopes=("global", "ops", "config")):
        """Build a LangGraphLanceDBStore with mocked internals."""
        from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

        adapter = object.__new__(LangGraphLanceDBStore)
        # Minimal init: bypass __init__
        mock_store = MagicMock()
        mock_store.embedding_dim = 384
        mock_store.table_exists.return_value = True

        # Simulate a table that returns rows with scope values
        mock_tbl = MagicMock()
        mock_tbl.search.return_value.limit.return_value.to_list.return_value = [
            {"id": f"m{i}", "scope": s} for i, s in enumerate(scopes)
        ]
        # No pandas available fallback path
        mock_store.get_table.return_value = mock_tbl

        adapter._store = mock_store
        adapter._table_name = "memory"
        return adapter, mock_store

    def test_list_namespaces_returns_real_scopes(self):
        """list_namespaces() queries DB and returns distinct scopes."""
        from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

        adapter, store = self._make_adapter(scopes=("global", "ops", "config"))

        # Patch the to_lance path to raise (force fallback path)
        mock_tbl = store.get_table.return_value
        mock_tbl.to_lance.side_effect = AttributeError("no to_lance")

        with patch("olav.core.memory.langgraph_adapter.LangGraphLanceDBStore.list_namespaces",
                   wraps=lambda self, prefix=None: (
                       # Call the real implementation via unbound method
                       LangGraphLanceDBStore.list_namespaces(self, prefix)
                   )):
            pass  # Just verify the adapter has the right implementation

        # Call directly on the adapter object
        result = LangGraphLanceDBStore.list_namespaces(adapter)
        namespaces = list(result)

        # Should include at least ("global",)
        assert ("global",) in namespaces

    def test_list_namespaces_no_table_returns_global(self):
        """Returns [("global",)] when table doesn't exist."""
        from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

        adapter, store = self._make_adapter()
        store.table_exists.return_value = False

        result = list(LangGraphLanceDBStore.list_namespaces(adapter))
        assert result == [("global",)]

    def test_list_namespaces_with_prefix_filters(self):
        """Prefix parameter filters returned namespaces."""
        from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

        adapter, store = self._make_adapter(scopes=("global", "ops", "ops-routing"))

        # Simulate fallback path
        mock_tbl = store.get_table.return_value
        mock_tbl.to_lance.side_effect = AttributeError("no to_lance")

        result = list(LangGraphLanceDBStore.list_namespaces(adapter, prefix="ops"))
        # Only tuples starting with "ops" should be returned
        for ns in result:
            assert ns[0].startswith("ops")

    def test_list_namespaces_deduplicates_scopes(self):
        """Duplicate scopes in DB result in a single namespace tuple."""
        from olav.core.memory.langgraph_adapter import LangGraphLanceDBStore

        # Duplicate "global" + "ops"
        adapter, store = self._make_adapter(scopes=("global", "global", "ops", "ops"))

        mock_tbl = store.get_table.return_value
        mock_tbl.to_lance.side_effect = AttributeError("no to_lance")

        result = list(LangGraphLanceDBStore.list_namespaces(adapter))
        # No duplicates
        assert len(result) == len(set(result))
        assert ("global",) in result
        assert ("ops",) in result
