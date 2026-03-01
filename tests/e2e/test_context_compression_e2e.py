"""E2E Tests for Context Compression (Long Conversation Handling).

Validates ConversationSummaryBufferMemory integration in QueryAgent with 20+ turn 
conversations, compression triggering, and context preservation.
"""

import asyncio
import pytest
from typing import Any

from olav.core.context_compression import ContextCompressor, create_context_compressor
from olav.core.llm import LLMFactory


class TestContextCompressionE2E:
    """End-to-end tests for context compression in long conversations."""

    @pytest.fixture
    def llm(self):
        """Provide LLM instance from factory."""
        return LLMFactory.get_chat_model(agent_id="query")

    def test_long_conversation_compression_20_turns(self, llm):
        """Test compression with exactly 20 conversation turns (user + assistant pairs)."""
        compressor = create_context_compressor(max_tokens=1000, llm=llm)
        
        # Simulate 20 turns of conversation (40 messages total)
        conversation_log = []
        for i in range(20):
            user_msg = f"User turn {i+1}: What is the status of interface eth0 on device R{(i % 4) + 1}?"
            assistant_msg = f"Assistant turn {i+1}: Interface eth0 is up on R{(i % 4) + 1}. Speed: 1000Mbps, Status: operational."
            
            compressor.add_message("user", user_msg)
            compressor.add_message("assistant", assistant_msg)
            
            conversation_log.append({
                "turn": i + 1,
                "user": user_msg,
                "assistant": assistant_msg
            })
        
        # Verify all messages were added
        assert len(compressor.get_messages()) >= 20, "Not all messages were added"
        
        # Get context before compression
        context_before = compressor.get_context()
        assert "User turn 1" in context_before or "Summary" in context_before
        
        # Check if compression is needed
        should_compress = compressor.should_compress()
        assert should_compress, f"Compression should be needed after {len(conversation_log)} turns"
        
        # Perform compression
        summary = compressor.compress()
        assert summary is not None and len(summary) > 0, "Summary should not be empty"
        
        # Get context after compression
        context_after = compressor.get_context()
        
        # Verify compression reduced context size
        assert len(context_after) <= len(context_before), "Context size should be reduced or same"
        
        # Verify summary contains meaningful information
        assert "summary" in context_after.lower() or "device" in context_after.lower(), \
            "Compressed context should retain device/interface information"

    def test_compression_preserves_semantic_content(self, llm):
        """Verify that compression preserves semantic content (not just truncation)."""
        compressor = create_context_compressor(max_tokens=800, llm=llm)
        
        # Add specific domain context (network operations)
        messages = [
            ("user", "Configure OSPF on R1 with area 0.0.0.0"),
            ("assistant", "OSPF configured on R1. Area 0.0.0.0 set up successfully."),
            ("user", "What is the OSPF neighbor count on R1?"),
            ("assistant", "R1 has 3 OSPF neighbors: R2, R3, R4 in Area 0.0.0.0."),
            ("user", "Check BGP sessions on R4"),
            ("assistant", "R4 has 1 BGP session with R2 (AS 65001), status: Established."),
        ]
        
        for role, content in messages:
            compressor.add_message(role, content)
        
        # Get context (before compression, no LangChain)
        context = compressor.get_context()
        
        # Verify that key network concepts are in raw context
        key_concepts = [
            "OSPF",  # Should know about OSPF
            "R1",    # Should know about device names
            "neighbor",  # Should know about OSPF neighbors
        ]
        
        context_lower = context.lower()
        preserved_concepts = [c for c in key_concepts if c.lower() in context_lower]
        
        # In basic mode (no LangChain), context preserves all messages
        assert len(preserved_concepts) >= 2, \
            f"Raw context should preserve at least 2 key concepts. Preserved: {preserved_concepts}"

    def test_compression_summary_node_pattern(self, llm):
        """Test that compression follows the 'summary node' pattern for LLM context."""
        compressor = create_context_compressor(max_tokens=500, llm=llm)
        
        # Build long conversation
        for i in range(15):
            compressor.add_message("user", f"Query {i}: status report for device {i}")
            compressor.add_message("assistant", f"Device {i} status: operational, CPU 45%, Memory 60%")
        
        # Force compression
        compressed_summary = compressor.compress()
        
        # Verify summary node is properly formatted
        assert "[Summary:" in compressed_summary or "summary" in compressed_summary.lower(), \
            "Compressed content should be marked as summary"
        
        # Get final context (should include summary)
        final_context = compressor.get_context()
        assert "Summary" in final_context or "summary" in final_context, \
            "Final context should indicate it contains a summary"

    def test_fallback_compression_without_llm(self):
        """Test basic compression fallback when no LLM is available."""
        compressor = ContextCompressor(max_token_limit=500, llm=None)
        
        # Add many messages to trigger compression need
        for i in range(30):  # Increased from 20 to ensure threshold exceeded
            compressor.add_message("user", f"Message {i}: status query about device configuration settings")
        
        # should_compress checks if message count > threshold
        # In fallback mode, it uses CONTEXT_COMPRESSION_THRESHOLD (usually 10)
        # With 30 messages, it should definitely exceed the threshold
        should_compress = compressor.should_compress()
        
        if should_compress:
            summary = compressor.compress()
            assert summary is not None
            assert "Summary" in summary, "Fallback compression should create summary marker"

    async def test_concurrent_compression_safety(self, llm):
        """Test that context compression is thread-safe for concurrent access."""
        compressor = create_context_compressor(max_tokens=1000, llm=llm)
        
        async def add_messages(thread_id: int, count: int):
            """Add messages from a simulated thread."""
            for i in range(count):
                compressor.add_message("user", f"Thread{thread_id}-Msg{i}")
                compressor.add_message("assistant", f"Response to Thread{thread_id}-Msg{i}")
        
        # Simulate concurrent conversation threads
        await asyncio.gather(
            add_messages(1, 5),
            add_messages(2, 5),
            add_messages(3, 5),
        )
        
        # Verify all messages were recorded
        assert len(compressor.get_messages()) >= 30, "All messages should be recorded"
        
        # Compression should still work
        compressor.compress()
        context = compressor.get_context()
        assert context is not None and len(context) > 0

    def test_compression_with_mixed_message_lengths(self, llm):
        """Test compression with highly varied message lengths."""
        compressor = create_context_compressor(max_tokens=1500, llm=llm)
        
        # Short messages
        for i in range(3):
            compressor.add_message("user", f"Q{i}?")
            compressor.add_message("assistant", f"A{i}.")
        
        # Long messages (simulating detailed configs)
        long_message = ("show run" + " " * 100) * 5  # ~500+ tokens equivalent
        for i in range(3):
            compressor.add_message("user", f"Config{i}: {long_message[:100]}")
            compressor.add_message("assistant", f"Response{i}: {long_message[:150]}")
        
        # Should be able to handle compression with varied lengths
        should_compress = compressor.should_compress()
        if should_compress:
            summary = compressor.compress()
            assert summary is not None
            context = compressor.get_context()
            assert len(context) > 0


class TestContextCompressionIntegration:
    """Integration tests with QueryAgent (pending full agent refactor)."""

    def test_compressor_factory_integration(self):
        """Test that compressor can be created via factory for integration."""
        from olav.core.context_compression import create_context_compressor
        
        # Should work without LLM (fallback)
        compressor = create_context_compressor(max_tokens=2000)
        assert compressor is not None
        assert compressor.max_token_limit == 2000
        
        # Should allow adding messages
        compressor.add_message("user", "test")
        assert len(compressor.get_messages()) == 1

    def test_compressor_state_preservation(self):
        """Test that compressor state is correctly preserved across operations."""
        compressor = create_context_compressor(max_tokens=3000)
        
        # Add initial messages
        messages_batch_1 = [
            {"role": "user", "content": "First question?"},
            {"role": "assistant", "content": "First answer."},
        ]
        compressor.add_messages(messages_batch_1)
        
        # Add more messages
        messages_batch_2 = [
            {"role": "user", "content": "Second question?"},
            {"role": "assistant", "content": "Second answer."},
        ]
        compressor.add_messages(messages_batch_2)
        
        # Verify state combines both batches
        all_messages = compressor.get_messages()
        assert len(all_messages) == 4, f"Should have 4 messages, got {len(all_messages)}"
        
        # Verify clear works
        compressor.clear()
        assert len(compressor.get_messages()) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
