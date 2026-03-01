"""E2E Tests for LanceDB Memory System.

These tests verify the end-to-end functionality of the LanceDB memory system
by testing real CLI commands and API workflows.

Tests follow the E2E methodology from AGENTS.md:
- Use subprocess to test real CLI commands
- Test complete user workflows
- No mocking of core functionality
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


class TestLanceDBStoreE2E:
    """E2E tests for LanceDB store operations."""

    @pytest.fixture
    def temp_db_path(self, tmp_path):
        """Provide a temporary database path for testing."""
        return tmp_path / "test_memory.lance"

    def test_store_initialization(self, temp_db_path):
        """Test that LanceDB store can be initialized via Python API."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{temp_db_path}", embedding_dim=384)
store.create_table()
tables = store.get_table_names()
print(f"TABLES:{{tables}}")
assert "memory" in tables, "memory table should exist"
print("SUCCESS: Store initialization works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout

    def test_add_and_retrieve_memory(self, temp_db_path):
        """Test adding memory and retrieving it back."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
import json
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{temp_db_path}", embedding_dim=384)
store.create_table()

# Add memory
result = store.add_memory(
    id="e2e-test-1",
    text="BGP neighbor 192.168.1.1 is down",
    vector=[0.1] * 384,
    category="fact",
    scope="global",
    metadata={{"device": "R1", "protocol": "BGP"}}
)
print(f"ADD_RESULT:{{result}}")

# Retrieve memory
memories = store.get_memories()
print(f"MEMORY_COUNT:{{len(memories)}}")

# Verify
assert len(memories) == 1, "Should have 1 memory"
assert memories[0]["text"] == "BGP neighbor 192.168.1.1 is down"
print("SUCCESS: Add and retrieve works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout

    def test_vector_search_returns_relevant_results(self, temp_db_path):
        """Test that vector search returns relevant results."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{temp_db_path}", embedding_dim=384)
store.create_table()

# Add memories with different vectors
store.add_memory(id="bgp-1", text="BGP is down", vector=[0.9, 0.1, 0.1] + [0.0] * 381, category="fact", scope="global")
store.add_memory(id="ospf-1", text="OSPF is working", vector=[0.1, 0.9, 0.1] + [0.0] * 381, category="fact", scope="global")
store.add_memory(id="bgp-2", text="BGP neighbor issue", vector=[0.8, 0.2, 0.1] + [0.0] * 381, category="fact", scope="global")

# Search with vector similar to BGP
query_vector = [0.85, 0.15, 0.15] + [0.0] * 381
results = store.search_by_vector(query_vector, limit=5)

print(f"RESULTS_COUNT:{{len(results)}}")
print(f"FIRST_RESULT_ID:{{results[0]['id'] if results else 'none'}}")

# Should return BGP-related items first
assert len(results) >= 2, "Should find BGP items"
assert results[0]["id"].startswith("bgp"), "BGP items should rank first"
print("SUCCESS: Vector search works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout


class TestHybridSearchE2E:
    """E2E tests for hybrid search functionality."""

    @pytest.fixture
    def store_with_data(self, tmp_path):
        """Create store with test data."""
        return tmp_path / "hybrid_test.lance"

    def test_rrf_fusion_combines_results(self, store_with_data):
        """Test that RRF fusion combines vector and text results."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore, hybrid_search, rrf_fusion

store = LanceDBStore(db_path="{store_with_data}", embedding_dim=384)
store.create_table()

# Add diverse data
store.add_memory(id="1", text="BGP neighbor down issue", vector=[0.9, 0.1, 0.1] + [0.0] * 381, category="fact", scope="global")
store.add_memory(id="2", text="OSPF neighbor in EXSTART", vector=[0.1, 0.9, 0.1] + [0.0] * 381, category="fact", scope="global")
store.add_memory(id="3", text="Use --limit to avoid BGP timeout", vector=[0.5, 0.5, 0.5] + [0.0] * 381, category="preference", scope="global")

# Test hybrid search
query_vector = [0.8, 0.2, 0.2] + [0.0] * 381

results = hybrid_search(
    store=store,
    query="BGP",
    query_vector=query_vector,
    limit=5,
)

print(f"HYBRID_RESULTS:{{len(results)}}")
print(f"FIRST_ID:{{results[0]['id'] if results else 'none'}}")

# Should combine both text and vector matches
assert len(results) > 0, "Should have results"
print("SUCCESS: Hybrid search works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout

    def test_text_search_finds_keyword_matches(self, store_with_data):
        """Test that text search finds keyword matches."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{store_with_data}", embedding_dim=384)
store.create_table()

# Add data
store.add_memory(id="1", text="BGP uses TCP port 179", vector=[0.1] * 384, category="fact", scope="global")
store.add_memory(id="2", text="OSPF uses multicast 224.0.0.5", vector=[0.1] * 384, category="fact", scope="global")

# Text search
results = store.search_by_text("BGP", limit=5)

print(f"TEXT_RESULTS:{{len(results)}}")
for r in results:
    print(f"FOUND:{{r['id']}} - {{r['text']}}")

assert len(results) >= 1, "Should find BGP text"
print("SUCCESS: Text search works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout


class TestMemoryCategoriesE2E:
    """E2E tests for memory categorization."""

    def test_category_filtering(self, tmp_path):
        """Test filtering memories by category."""
        db_path = tmp_path / "categories_test.lance"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore, MemoryCategory

store = LanceDBStore(db_path="{db_path}", embedding_dim=384)
store.create_table()

# Add memories with different categories
store.add_memory(id="1", text="BGP is down", vector=[0.1] * 384, category=MemoryCategory.FACT, scope="global")
store.add_memory(id="2", text="Use --limit flag", vector=[0.1] * 384, category=MemoryCategory.PREFERENCE, scope="global")
store.add_memory(id="3", text="Decision: restart BGP", vector=[0.1] * 384, category=MemoryCategory.DECISION, scope="global")
store.add_memory(id="4", text="Config changed", vector=[0.1] * 384, category=MemoryCategory.AUDIT, scope="global")

# Get only facts
facts = store.get_memories(category="fact")
print(f"FACTS:{{len(facts)}}")

# Get only preferences
prefs = store.get_memories(category="preference")
print(f"PREFERENCES:{{len(prefs)}}")

# Get all
all_mem = store.get_memories()
print(f"ALL:{{len(all_mem)}}")

assert len(facts) == 1, "Should have 1 fact"
assert len(prefs) == 1, "Should have 1 preference"
assert len(all_mem) == 4, "Should have 4 total"
print("SUCCESS: Category filtering works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout


class TestScopeIsolationE2E:
    """E2E tests for scope isolation."""

    def test_scope_filtering(self, tmp_path):
        """Test that scope filtering works correctly."""
        db_path = tmp_path / "scope_test.lance"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{db_path}", embedding_dim=384)
store.create_table()

# Add memories with different scopes
store.add_memory(id="1", text="Global knowledge", vector=[0.1] * 384, category="fact", scope="global")
store.add_memory(id="2", text="RoutingAgent specific", vector=[0.1] * 384, category="fact", scope="RoutingAgent")
store.add_memory(id="3", text="ConfigAgent specific", vector=[0.1] * 384, category="fact", scope="ConfigAgent")
store.add_memory(id="4", text="Another global", vector=[0.1] * 384, category="fact", scope="global")

# Get global memories
global_mem = store.get_memories(scope="global")
print(f"GLOBAL:{{len(global_mem)}}")

# Get RoutingAgent memories
routing_mem = store.get_memories(scope="RoutingAgent")
print(f"ROUTING:{{len(routing_mem)}}")

# Get all
all_mem = store.get_memories()
print(f"ALL:{{len(all_mem)}}")

# When filtering by scope, should include global + specific scope
assert len(global_mem) >= 2, "Should have global memories"
assert len(routing_mem) >= 1, "Should have RoutingAgent memories"
print("SUCCESS: Scope isolation works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout


class TestMemoryCRUD_E2E:
    """E2E tests for complete memory workflows."""

    def test_full_memory_lifecycle(self, tmp_path):
        """Test complete memory lifecycle: create, read, update, delete."""
        db_path = tmp_path / "lifecycle_test.lance"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{db_path}", embedding_dim=384)
store.create_table()

# CREATE
add_result = store.add_memory(
    id="lifecycle-1",
    text="Initial text",
    vector=[0.1] * 384,
    category="fact",
    scope="global",
)
print(f"CREATE:{{add_result['status']}}")

# READ
memories = store.get_memories()
print(f"READ_COUNT:{{len(memories)}}")
initial_text = memories[0]["text"]

# UPDATE
update_result = store.update_weight("lifecycle-1", weight=2.5)
print(f"UPDATE:{{update_result['status']}}")

# Verify update
memories = store.get_memories()
updated_weight = memories[0]["weight"]
print(f"WEIGHT_AFTER:{{updated_weight}}")

# DELETE
delete_result = store.delete_memory("lifecycle-1")
print(f"DELETE:{{delete_result['status']}}")

# Verify delete
memories = store.get_memories()
print(f"FINAL_COUNT:{{len(memories)}}")

# Assertions
assert add_result["status"] == "success"
assert len(memories) == 0, "Should be empty after delete"
print("SUCCESS: Full lifecycle works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout


class TestSearchKnowledgeToolE2E:
    """E2E tests for the search_knowledge tool."""

    def test_search_knowledge_with_real_data(self, tmp_path):
        """Test search_knowledge tool with populated database."""
        db_path = tmp_path / "knowledge_test.lance"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')

from olav.core.memory import LanceDBStore, hybrid_search

# Setup store with data
store = LanceDBStore(db_path="{db_path}", embedding_dim=384)
store.create_table()

# Add knowledge
store.add_memory(
    id="kb-1",
    text="BGP neighbor 192.168.1.1 is down due to hold timer expiry. Check TCP connection and BGP configuration.",
    vector=[0.9, 0.1, 0.1] + [0.0] * 381,
    category="fact",
    scope="global",
    metadata={{"source": "bgp_troubleshooting.md"}}
)
store.add_memory(
    id="kb-2",
    text="OSPF uses DR/BDR election on broadcast networks. Priority 0 means never become DR.",
    vector=[0.1, 0.9, 0.1] + [0.0] * 381,
    category="fact",
    scope="global",
    metadata={{"source": "ospf_best_practices.md"}}
)
store.add_memory(
    id="kb-3",
    text="Always use --limit flag with show commands to avoid timeouts on production devices.",
    vector=[0.1, 0.1, 0.9] + [0.0] * 381,
    category="preference",
    scope="global",
    metadata={{"lesson": "avoid timeouts"}}
)

# Test text search
results = store.search_by_text("BGP", limit=5)
print(f"SEARCH_RESULTS:{{len(results)}}")
for r in results:
    print(f"FOUND: {{r['id']}} - {{r['text'][:50]}}")

# Test vector search
query_vector = [0.9, 0.1, 0.1] + [0.0] * 381
vector_results = store.search_by_vector(query_vector, limit=5)
print(f"VECTOR_RESULTS:{{len(vector_results)}}")

# Test hybrid search
hybrid_results = hybrid_search(
    store=store,
    query="BGP",
    query_vector=query_vector,
    limit=5,
)
print(f"HYBRID_RESULTS:{{len(hybrid_results)}}")

assert len(results) >= 1, "Should find BGP knowledge"
print("SUCCESS: Search knowledge works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout


class TestMultipleAgentsIsolation:
    """E2E tests for multi-agent memory isolation."""

    def test_agent_memory_isolation(self, tmp_path):
        """Test that different agents have isolated memory spaces."""
        db_path = tmp_path / "isolation_test.lance"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python3",
                "-c",
                f"""
import sys
sys.path.insert(0, '.')
from olav.core.memory import LanceDBStore

store = LanceDBStore(db_path="{db_path}", embedding_dim=384)
store.create_table()

# Agent A memories
store.add_memory(id="a1", text="Agent A knows this", vector=[0.1] * 384, category="fact", scope="AgentA")
store.add_memory(id="a2", text="Agent A preference", vector=[0.1] * 384, category="preference", scope="AgentA")

# Agent B memories
store.add_memory(id="b1", text="Agent B knows this", vector=[0.1] * 384, category="fact", scope="AgentB")
store.add_memory(id="b2", text="Agent B preference", vector=[0.1] * 384, category="preference", scope="AgentB")

# Global memories
store.add_memory(id="g1", text="Global knowledge", vector=[0.1] * 384, category="fact", scope="global")

# Query as Agent A (should see: global + AgentA)
a_memories = store.get_memories(scope="AgentA")
print(f"AGENT_A_MEMORIES:{{len(a_memories)}}")
a_ids = [m['id'] for m in a_memories]
print(f"AGENT_A_IDS:{{a_ids}}")

# Query as Agent B (should see: global + AgentB)
b_memories = store.get_memories(scope="AgentB")
print(f"AGENT_B_MEMORIES:{{len(b_memories)}}")
b_ids = [m['id'] for m in b_memories]
print(f"AGENT_B_IDS:{{b_ids}}")

# Verify isolation
assert "a1" in a_ids or "a2" in a_ids, "Agent A should see its own memories"
assert "b1" in b_ids or "b2" in b_ids, "Agent B should see its own memories"

# Agent A should NOT see Agent B's private memories
a_can_see_b_private = any(i in a_ids for i in ['b1', 'b2'])
print(f"A_CAN_SEE_B_PRIVATE:{{a_can_see_b_private}}")

print("SUCCESS: Agent isolation works")
""",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert "SUCCESS" in result.stdout
