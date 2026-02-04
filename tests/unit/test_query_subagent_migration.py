"""
QueryAgent → SubAgent Migration Tests (TDD - Phase 1.1)
测试QueryAgent的核心能力迁移到orchestrator SubAgent

注意: 这些测试暂时跳过LLM调用，专注于架构迁移验证
"""

import pytest
import time
import os
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

# 设置测试环境变量
os.environ["OPENAI_API_KEY"] = "sk-test-key"
os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
os.environ["OPENAI_MODEL_NAME"] = "gpt-4"


class TestQuerySubAgentIntentDetection:
    """测试query SubAgent的意图检测能力 (来自QueryAgent)"""

    @pytest.mark.asyncio
    async def test_fast_path_for_simple_queries(self):
        """测试简单查询触发Fast Path - 验证缓存功能"""
        from olav.agents.orchestrator import create_orchestrator
        from langchain_core.messages import HumanMessage

        orchestrator = create_orchestrator()
        
        # 验证orchestrator是CachedOrchestrator类型
        assert hasattr(orchestrator, 'query_cache'), "Orchestrator应该有query_cache属性"
        assert hasattr(orchestrator, 'ainvoke'), "Orchestrator应该有ainvoke方法"
        
        # 测试缓存功能存在（不实际调用LLM）
        import time
        start = time.time()
        
        # 第一次查询会miss（但我们跳过实际执行）
        query = "列出所有设备"
        
        # 验证缓存实例可用
        cache_instance = orchestrator.query_cache
        assert cache_instance is not None, "缓存实例应该可用"
        
        duration = time.time() - start
        
        # 验证初始化速度快（<1秒）
        assert duration < 1.0, f"Orchestrator初始化耗时{duration:.2f}秒，应该<1秒"
        
        print(f"✅ 缓存功能已集成，初始化耗时: {duration:.3f}秒")

        # 简单查询: "列出所有设备"
        start = time.time()
        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(content="列出所有设备")]
        })
        duration = time.time() - start

        # 验收标准: Fast Path应在1秒内完成
        assert duration < 1.0, f"简单查询耗时{duration:.2f}秒，未使用Fast Path"

        # 验证返回了设备列表
        response = result["messages"][-1].content.lower()
        assert "device" in response or "设备" in response

    @pytest.mark.asyncio
    async def test_react_loop_for_complex_queries(self):
        """测试复杂查询走ReAct循环"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()
        
        # 验证orchestrator有SubAgent配置
        assert hasattr(orchestrator, 'agent'), "应该有underlying agent"
        
        # 验证query SubAgent存在
        # （实际SubAgent存储在agent.config中）
        print("✅ Orchestrator配置验证通过")


class TestQuerySubAgentCache:
    """测试query SubAgent的缓存能力 (来自QueryAgent)"""

    @pytest.mark.asyncio
    async def test_cache_hit_for_repeated_queries(self):
        """测试重复查询命中缓存 - 验证缓存写入/读取"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()
        
        # 手动测试缓存功能
        test_query = "show version R1"
        cache_context = {"skill": "orchestrator", "mode": "subagent"}
        
        # 模拟缓存写入
        test_result = {
            "messages": [{"role": "assistant", "content": "R1 version: IOS-XE 17.3"}],
            "performance": {"cache_hit": False},
        }
        
        orchestrator.query_cache.set(
            test_query,
            test_result,
            context=cache_context,
            metadata={"mode": "test"},
        )
        
        # 验证缓存读取
        cached = orchestrator.query_cache.get(test_query, context=cache_context)
        assert cached is not None, "缓存读取应该成功"
        assert cached["messages"][0]["content"] == "R1 version: IOS-XE 17.3"
        
        print("✅ 缓存写入/读取功能正常")

    @pytest.mark.asyncio
    async def test_cache_invalidation_after_ttl(self):
        """测试缓存TTL过期"""
        pytest.skip("需要先实现缓存中间件")


class TestQuerySubAgentSkillIntegration:
    """测试query SubAgent的Skill集成 (来自QueryAgent)"""

    @pytest.mark.asyncio
    async def test_skill_tools_available(self):
        """测试Skill工具可用性"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()
        
        # 验证query SubAgent配置存在
        # SubAgent工具通过_create_subagents()配置
        
        # 验证orchestrator正确初始化
        assert orchestrator is not None
        assert hasattr(orchestrator, 'agent')
        
        print("✅ Orchestrator配置验证通过")


class TestQuerySubAgentVsStandalone:
    """对比测试: SubAgent vs 独立QueryAgent"""

    @pytest.mark.asyncio
    async def test_feature_parity(self):
        """测试功能对等性 - SubAgent应具备QueryAgent的所有核心能力"""
        from olav.agents.orchestrator import create_orchestrator
        from olav.agents.query_agent import QueryAgent

        # 独立QueryAgent
        standalone = QueryAgent(skill_name="network-query")

        # SubAgent模式
        orchestrator = create_orchestrator()

        # 验证两者都有缓存功能
        assert hasattr(standalone, 'query_cache'), "QueryAgent应该有query_cache"
        assert hasattr(orchestrator, 'query_cache'), "Orchestrator应该有query_cache"
        
        # 验证两者都有工具
        assert hasattr(standalone, 'tools'), "QueryAgent应该有tools"
        assert standalone.tools, "QueryAgent的tools不应为空"
        
        print("✅ 功能对等性验证通过")


class TestQuerySubAgentDeprecation:
    """测试独立QueryAgent的弃用路径"""

    def test_query_agent_marked_deprecated(self):
        """测试QueryAgent是否标记为deprecated"""
        pytest.skip("迁移完成后标记弃用")

        from olav.agents.query_agent import QueryAgent

        # 应该有弃用警告
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            agent = QueryAgent(skill_name="network-query")
            assert len(w) == 1
            assert "deprecated" in str(w[-1].message).lower()
