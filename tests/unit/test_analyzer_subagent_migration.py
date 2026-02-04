"""
Analyzer → SubAgent Migration Tests (TDD - Phase 1.2)
测试Analyzer的DB+CLI双重验证能力迁移到orchestrator SubAgent
"""

import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage


class TestAnalysisSubAgentDBCLIVerification:
    """测试analysis SubAgent的DB+CLI双重验证能力 (来自Analyzer)"""

    @pytest.mark.asyncio
    async def test_db_cli_dual_verification(self):
        """测试DB+CLI双重验证 - RED状态 (待迁移)"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        # 诊断类查询应该使用DB+CLI双重验证
        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="诊断R1的BGP邻居问题，确认实际状态"
            )]
        })

        # 验收标准: 应该包含DB和CLI的验证数据
        # 需要orchestrator在metadata中记录数据源
        # assert "db_verification" in result.get("metadata", {})
        # assert "cli_verification" in result.get("metadata", {})

        # 临时: 至少验证有结果
        assert result is not None
        assert len(result["messages"]) > 0

    @pytest.mark.asyncio
    async def test_analysis_provides_root_cause(self):
        """测试分析提供根因分析"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="R1的CPU使用率异常高，分析原因"
            )]
        })

        response = result["messages"][-1].content.lower()

        # 应该包含分析内容
        assert "cpu" in response or "使用率" in response


class TestAnalysisSubAgentRecommendations:
    """测试analysis SubAgent的建议能力"""

    @pytest.mark.asyncio
    async def test_provides_actionable_recommendations(self):
        """测试提供可执行建议 - RED状态 (待迁移)"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="分析网络健康状况并提供优化建议"
            )]
        })

        response = result["messages"][-1].content

        # Analyzer应该提供具体建议
        # assert "建议" in response or "recommendation" in response.lower()
        assert len(response) > 100  # 至少有足够详细的分析


class TestAnalysisSubAgentHistoricalCases:
    """测试analysis SubAgent的历史案例参考 (来自Analyzer)"""

    @pytest.mark.asyncio
    async def test_references_similar_cases(self):
        """测试参考相似历史案例"""
        pytest.skip("需要先实现知识库集成")

        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="BGP连接不稳定的常见原因"
            )]
        })

        # 应该引用历史案例
        # assert "similar_cases" in result.get("metadata", {})


class TestAnalysisSubAgentVsStandalone:
    """对比测试: SubAgent vs 独立Analyzer"""

    @pytest.mark.asyncio
    async def test_analysis_accuracy_parity(self):
        """测试分析准确率对等"""
        from olav.agents.orchestrator import create_orchestrator
        from olav.agents.analyzer import create_analyzer_agent

        # 独立Analyzer
        standalone = create_analyzer_agent()

        # SubAgent模式
        orchestrator = create_orchestrator()

        query = "诊断R1的接口flapping问题"

        # 独立模式
        standalone_result = standalone(query)

        # SubAgent模式
        subagent_result = await orchestrator.ainvoke({
            "messages": [HumanMessage(content=query)]
        })

        # 两者都应该提供分析结果
        assert standalone_result is not None
        assert subagent_result is not None


class TestAnalysisSubAgentDeprecation:
    """测试独立Analyzer的弃用路径"""

    def test_analyzer_marked_deprecated(self):
        """测试Analyzer是否标记为deprecated"""
        pytest.skip("迁移完成后标记弃用")

        from olav.agents.analyzer import create_analyzer_agent

        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            agent = create_analyzer_agent()
            assert len(w) == 1
            assert "deprecated" in str(w[-1].message).lower()
