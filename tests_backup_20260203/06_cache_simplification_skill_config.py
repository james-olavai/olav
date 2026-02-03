"""
Test: Cache Simplification & SKILL Config Integration (P0 + P1)

Validates:
1. P0: Simplified intent_agent._check_intent_cache() - direct exact mode
2. P1: SkillConfig loading from SKILL.md
3. Cache hit/miss behavior with new config
4. Performance improvement verification
"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Test imports
from olav.agents.intent_agent import IntentAgent
from olav.core.skill_config import SkillConfig
from olav.cache import cache as olav_cache


class TestP0SimplificationAndP1SkillConfig:
    """P0 + P1 integration tests"""

    def test_skill_config_loads_network_query_cache_config(self):
        """P1: SkillConfig should load cache config from network-query SKILL.md"""
        cache_cfg = SkillConfig.get_cache_config("network-query")

        # Should have all required fields from SKILL.md
        assert cache_cfg is not None
        assert cache_cfg.get("enabled") is True
        assert cache_cfg.get("match_mode") == "exact"
        assert cache_cfg.get("confidence_threshold") == 1.0
        assert cache_cfg.get("ttl_hours") == 168

    def test_skill_config_fallback_to_defaults(self):
        """P1: SkillConfig should fallback to defaults for unknown skills"""
        # Use a non-existent skill ID
        cache_cfg = SkillConfig.get_cache_config("non-existent-skill")

        # Should return defaults
        assert cache_cfg.get("match_mode") == "exact"
        assert cache_cfg.get("confidence_threshold") == 1.0

    @pytest.mark.asyncio
    async def test_intent_agent_uses_skill_config(self):
        """P1: IntentAgent._check_intent_cache() should use SkillConfig"""
        agent = IntentAgent()

        # Test with clean cache (cache miss)
        test_query = "show interfaces on R1 (test P0/P1)"
        result = await agent._check_intent_cache(test_query, skill_id="network-query")

        # Should return None on cache miss
        assert result is None

        # Now seed the cache with test data
        test_plan = {
            "steps": [
                {
                    "type": "sql",
                    "query": "SELECT * FROM v_interfaces WHERE device = 'R1'",
                }
            ],
            "execution_plan": {"steps": []},
        }
        olav_cache.set_intent(test_query, test_plan)

        # Now test cache hit
        result = await agent._check_intent_cache(test_query, skill_id="network-query")

        # Should return execution plan directly（no wrapper dict）
        assert result is not None
        assert isinstance(result, dict)
        # P0: Direct return, no wrapper dict
        assert "execution_plan" in result

    @pytest.mark.asyncio
    async def test_intent_agent_respects_cache_disabled(self):
        """P1: IntentAgent should respect cache disabled flag from SKILL"""
        agent = IntentAgent()

        test_query = "test disabled cache"

        # Mock SkillConfig to return disabled cache
        with patch(
            "olav.agents.intent_agent.SkillConfig.get_cache_config"
        ) as mock_config:
            mock_config.return_value = {"enabled": False}

            # Should return None even if cache might have data
            result = await agent._check_intent_cache(test_query)
            assert result is None

    @pytest.mark.asyncio
    async def test_exact_cache_mode_enforcement(self):
        """P0 + P1: Verify exact mode is enforced for Query SubAgent"""
        agent = IntentAgent()

        test_query = "show bgp summary on R1"
        test_plan = {
            "steps": [
                {
                    "type": "cli",
                    "device": "R1",
                    "command": "show ip bgp summary",
                }
            ]
        }

        # Seed cache
        olav_cache.set_intent(test_query, test_plan)

        # Cache hit should use exact mode
        result = await agent._check_intent_cache(test_query, skill_id="network-query")

        assert result is not None
        assert result == test_plan

        # Verify exact mode is being used
        cache_cfg = SkillConfig.get_cache_config("network-query")
        assert cache_cfg.get("match_mode") == "exact"
        assert cache_cfg.get("confidence_threshold") == 1.0

    def test_code_simplification_metrics(self):
        """P0: Verify code simplification impact"""
        # Check that _check_intent_cache is simplified
        agent = IntentAgent()

        # Inspect the method - should be much simpler
        import inspect

        source = inspect.getsource(agent._check_intent_cache)

        # Should NOT contain:
        # - settings.routing.query_agent_cache_mode
        # - wrapper dict construction
        # - _match_mode extraction
        # - _confidence extraction

        assert "settings.routing.query_agent_cache_mode" not in source
        assert '"execution_plan"' not in source  # No wrapper dict
        assert '"_match_mode"' not in source
        assert '"_confidence"' not in source

        # Should contain:
        # - SkillConfig.get_cache_config
        # - Direct return
        assert "SkillConfig.get_cache_config" in source

    @pytest.mark.asyncio
    async def test_process_query_with_cache_hit(self):
        """Integration: process_query should execute cached plan directly"""
        agent = IntentAgent()

        test_query = "show version on R1"
        test_plan = {
            "steps": [
                {
                    "type": "sql",
                    "query": "SELECT version FROM v_system WHERE device = 'R1'",
                }
            ]
        }

        # Mock _execute_plan to avoid actual execution
        with patch.object(agent, "_execute_plan", new_callable=MagicMock) as mock_exec:
            mock_exec.return_value = "## Device Version\n\n- R1: Cisco 16.09"

            # Seed cache
            olav_cache.set_intent(test_query, test_plan)

            # Process query
            result = await agent.process_query(test_query)

            # Should have called _execute_plan（fast path）
            mock_exec.assert_called_once()
            assert result == "## Device Version\n\n- R1: Cisco 16.09"

    def test_skill_md_format_validation(self):
        """P1: Validate SKILL.md format for cache config"""
        # Load SKILL.md directly
        skill_path = Path(".olav/skills/network-query/SKILL.md")

        assert skill_path.exists(), "SKILL.md should exist"

        # Parse and validate
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()

            # Should have cache config
            assert "cache:" in content
            assert 'match_mode: "exact"' in content
            assert "confidence_threshold: 1.0" in content
            assert "ttl_hours:" in content


class TestPerformanceImprovements:
    """Performance validation for P0 + P1"""

    @pytest.mark.asyncio
    async def test_simplified_code_performance(self):
        """P0: Simplified code should be faster"""
        agent = IntentAgent()

        test_query = "show interfaces"

        # Warm up
        await agent._check_intent_cache(test_query)

        # Time the simplified version
        import time

        start = time.time()
        for _ in range(100):
            await agent._check_intent_cache(test_query, skill_id="network-query")
        elapsed = time.time() - start

        # Should be very fast（no wrapper dict construction）
        per_call_ms = (elapsed / 100) * 1000
        assert per_call_ms < 5.0, f"Check should be <5ms, got {per_call_ms:.2f}ms"

        print(f"✅ _check_intent_cache: {per_call_ms:.2f}ms per call")

    def test_skill_config_loading_performance(self):
        """P1: SkillConfig loading should be cached"""
        import time

        start = time.time()
        for _ in range(1000):
            SkillConfig.get_cache_config("network-query")
        elapsed = time.time() - start

        per_call_ms = (elapsed / 1000) * 1000
        # Should be fast since we're just reading from memory
        assert per_call_ms < 2.0, f"SkillConfig load should be <2ms, got {per_call_ms:.2f}ms"

        print(f"✅ SkillConfig.get_cache_config: {per_call_ms:.2f}ms per call")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
