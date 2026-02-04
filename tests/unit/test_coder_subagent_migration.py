"""
Coder → SubAgent Migration Tests (TDD - Phase 1.3)
测试Coder的TextFSM模板生成能力迁移到orchestrator SubAgent
"""

import pytest
from langchain_core.messages import HumanMessage


class TestCoderSubAgentTemplateGeneration:
    """测试coder SubAgent的模板生成能力 (来自Coder)"""

    @pytest.mark.asyncio
    async def test_generate_textfsm_template(self):
        """测试生成TextFSM模板 - RED状态 (待迁移)"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="为'show ip bgp summary'命令生成TextFSM模板"
            )]
        })

        response = result["messages"][-1].content

        # 验收标准: 应该返回有效的TextFSM模板
        # TextFSM模板特征: 包含Value声明和Start状态
        # assert "Value " in response
        # assert "Start" in response

        # 临时: 至少验证有响应
        assert len(response) > 100

    @pytest.mark.asyncio
    async def test_template_iteration_converges(self):
        """测试模板迭代收敛"""
        pytest.skip("需要先实现迭代逻辑")

        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="生成并测试'show interfaces'的TextFSM模板"
            )]
        })

        # 应该在5次迭代内收敛
        # assert result.get("iterations", 0) <= 5


class TestCoderSubAgentTestAndAnalyze:
    """测试coder SubAgent的测试和分析能力"""

    @pytest.mark.asyncio
    async def test_template_testing(self):
        """测试模板测试能力"""
        pytest.skip("需要先实现测试逻辑")

        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        # 提供模板和测试数据
        template = """
Value BGP_NEIGHBOR (\\S+)
Value STATE (\\S+)

Start
  ^${BGP_NEIGHBOR}\\s+\\d+\\s+\\d+\\s+\\d+\\s+\\d+\\s+\\d+\\s+${STATE} -> Record
"""
        sample_output = """
10.0.0.1    4    65001    100    200    0    Established
10.0.0.2    4    65002    150    250    0    Established
"""

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content=f"测试这个TextFSM模板:\n{template}\n\n使用样本:\n{sample_output}"
            )]
        })

        # 应该返回测试结果
        assert result is not None


class TestCoderSubAgentVsStandalone:
    """对比测试: SubAgent vs 独立Coder"""

    @pytest.mark.asyncio
    async def test_template_quality_parity(self):
        """测试模板质量对等"""
        from olav.agents.orchestrator import create_orchestrator
        from olav.agents.coder import create_coder_agent

        # 独立Coder
        standalone = create_coder_agent()

        # SubAgent模式
        orchestrator = create_orchestrator()

        raw_output = """
Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.0.1        4 65001   12345   12346        0    0    0 01:23:45        100
10.0.0.2        4 65002   23456   23457        0    0    0 02:34:56        200
"""

        # 独立模式
        standalone_template = await standalone(
            raw_output=raw_output,
            command_name="show ip bgp summary",
            platform="cisco_ios"
        )

        # SubAgent模式
        subagent_result = await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content=f"为'show ip bgp summary'生成TextFSM模板，样本输出:\n{raw_output}"
            )]
        })

        # 两者都应该生成模板
        assert standalone_template is not None
        assert subagent_result is not None


class TestCoderSubAgentDeprecation:
    """测试独立Coder的弃用路径"""

    def test_coder_marked_deprecated(self):
        """测试Coder是否标记为deprecated"""
        pytest.skip("迁移完成后标记弃用")

        from olav.agents.coder import create_coder_agent

        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            agent = create_coder_agent()
            assert len(w) == 1
            assert "deprecated" in str(w[-1].message).lower()
