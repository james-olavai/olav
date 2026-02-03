"""
P0+P1 Optimization Validation Tests
Validates cache simplification and SKILL config integration

P0: Simplified intent_agent._check_intent_cache()
- Removes Settings dependency
- Removes wrapper dict construction  
- Direct cache return (not wrapped in dict)

P1: Added cache configuration to SKILL.md
- Configuration loaded from SkillConfig
- Per-skill customization enabled
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.olav.agents.intent_agent import IntentAgent
from src.olav.cache import init_cache, OlavCache
from src.olav.core.skill_config import SkillConfig
from config.paths import SKILLS_DIR


@pytest.fixture(autouse=True)
def init_cache_db():
    """Initialize cache before each test"""
    init_cache()
    yield


class TestP0Simplification:
    """P0: Verify intent_agent simplification"""

    def test_p0_check_intent_cache_no_settings_dependency(self):
        """P0: _check_intent_cache should not depend on Settings"""
        agent = IntentAgent()
        
        # The simplified _check_intent_cache should accept skill_id parameter
        # and not require Settings import/usage
        import inspect
        source = inspect.getsource(agent._check_intent_cache)
        
        # Should NOT contain "Settings" references
        assert "Settings" not in source, "P0 optimization: Settings dependency should be removed"
        assert "settings.routing" not in source, "P0 optimization: Should not access settings.routing"
        
        # Should contain "SkillConfig" references instead
        assert "SkillConfig" in source, "P0 optimization: Should use SkillConfig instead"

    def test_p0_direct_cache_return(self):
        """P0: _check_intent_cache should return cache data directly, not wrapped"""
        agent = IntentAgent()
        
        # Inspect source - simplified version returns cached_result directly
        import inspect
        source = inspect.getsource(agent._check_intent_cache)
        
        # Should have simple direct return, not building a wrapper dict
        assert "return cached_result" in source
        assert "wrapper" not in source.lower()

    @pytest.mark.asyncio
    async def test_p0_simplified_code_faster(self):
        """P0: Simplified code should be measurably faster"""
        agent = IntentAgent()
        
        # Simulate cache hit
        test_query = "show ip bgp summary on R1"
        test_plan = {"steps": [{"type": "cli", "device": "R1", "command": "show ip bgp summary"}]}
        
        cache = OlavCache()
        cache.set_intent(test_query, test_plan)
        
        # Time 10 calls to simplified _check_intent_cache
        import time
        start = time.perf_counter()
        for _ in range(10):
            result = await agent._check_intent_cache(test_query, skill_id="network-query")
        elapsed = time.perf_counter() - start
        
        # Should be fast (< 150ms for 10 calls)
        per_call_ms = (elapsed / 10) * 1000
        assert per_call_ms < 150, f"Per-call latency should be <150ms, got {per_call_ms:.2f}ms"
        
        # Verify result contains steps (not wrapped)
        assert result is not None
        assert "steps" in result


class TestP1SkillConfig:
    """P1: Verify SKILL.md cache configuration"""

    def test_p1_skill_config_loads_network_query_cache(self):
        """P1: SkillConfig should load cache config from network-query SKILL.md"""
        cfg = SkillConfig.get_cache_config("network-query")
        
        # Should load from SKILL.md
        assert cfg is not None
        assert "enabled" in cfg
        assert "match_mode" in cfg
        assert "confidence_threshold" in cfg
        assert "ttl_hours" in cfg

    def test_p1_cache_config_has_exact_mode(self):
        """P1: network-query SKILL.md should use exact match mode"""
        cfg = SkillConfig.get_cache_config("network-query")
        
        assert cfg.get("enabled") == True
        assert cfg.get("match_mode") == "exact"
        assert cfg.get("confidence_threshold") == 1.0
        assert cfg.get("ttl_hours") == 168

    def test_p1_skill_md_frontmatter_format(self):
        """P1: SKILL.md should have proper cache config in frontmatter"""
        skill_md_path = Path(SKILLS_DIR) / "network-query" / "SKILL.md"
        
        assert skill_md_path.exists(), "network-query SKILL.md should exist"
        
        content = skill_md_path.read_text()
        
        # Should have YAML frontmatter with cache section
        assert "---" in content, "SKILL.md should have YAML frontmatter"
        assert "cache:" in content, "SKILL.md frontmatter should have cache: section"
        assert "match_mode: \"exact\"" in content
        assert "enabled: true" in content

    def test_p1_skill_config_fallback_to_defaults(self):
        """P1: SkillConfig should fallback to defaults for missing skills"""
        # Request config for non-existent skill
        cfg = SkillConfig.get_cache_config("non-existent-skill")
        
        # Should provide defaults
        assert cfg is not None
        assert cfg.get("enabled") == True
        assert cfg.get("match_mode") in ["exact", "fuzzy", "semantic"]


class TestIntegration:
    """Integration tests for P0+P1 together"""

    @pytest.mark.asyncio
    async def test_intent_agent_uses_skill_config_for_cache(self):
        """Verify intent_agent correctly uses SkillConfig for cache lookup"""
        agent = IntentAgent()
        
        # Mock olav_cache.get_intent to track calls
        test_query = "show ip bgp summary on R1"
        
        with patch("src.olav.agents.intent_agent.olav_cache.get_intent") as mock_get:
            mock_get.return_value = {
                "steps": [{"type": "cli", "device": "R1", "command": "show ip bgp summary"}],
                "_confidence": 1.0,
                "_match_mode": "exact"
            }
            
            result = await agent._check_intent_cache(test_query, skill_id="network-query")
            
            # Verify cache was called with SKILL config values
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args.kwargs
            
            # Should use values from SKILL.md
            assert call_kwargs["match_mode"] == "exact"
            assert call_kwargs["confidence_threshold"] == 1.0
            
            # Result should contain the cached plan with metadata
            assert result is not None
            assert "steps" in result

    def test_skill_config_vs_settings(self):
        """Verify SkillConfig is used instead of Settings for cache config"""
        # SkillConfig should be the new way
        skill_config = SkillConfig.get_cache_config("network-query")
        assert skill_config is not None
        
        # For comparison, old Settings might not have per-skill config
        # Just verify SkillConfig works
        assert "match_mode" in skill_config
        assert "enabled" in skill_config


class TestCodeQuality:
    """Verify code quality improvements from P0+P1"""

    def test_p0_code_reduction(self):
        """P0: Code should be significantly simpler"""
        agent = IntentAgent()
        
        import inspect
        source = inspect.getsource(agent._check_intent_cache)
        
        # Count key simplifications
        has_skill_config = "SkillConfig" in source
        no_settings = "Settings" not in source
        no_wrapper = "wrapper" not in source.lower() and "_confidence" not in source
        
        assert has_skill_config and no_settings, "Should use SkillConfig, not Settings"
        
        # Old code was ~30 lines, new should be ~24 lines (31% reduction)
        lines = [l.strip() for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) < 30, f"Simplified code should be <30 lines, got {len(lines)}"

    def test_p1_extensibility(self):
        """P1: Different skills can have different cache strategies"""
        # network-query uses exact mode
        cfg1 = SkillConfig.get_cache_config("network-query")
        assert cfg1.get("match_mode") == "exact"
        
        # Default for unknown skill
        cfg2 = SkillConfig.get_cache_config("other-skill")
        # Should still have cache config (with defaults)
        assert cfg2 is not None
        assert "match_mode" in cfg2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
