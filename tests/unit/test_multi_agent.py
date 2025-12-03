"""Unit tests for Intent Classifier and Multi-Agent Architecture.

Tests:
- Intent classification accuracy
- Agent tool counts
- Agent routing logic
- Agent Handoff mechanism
"""

import pytest

from olav.agents.intent_classifier import Intent, IntentClassifier, IntentType


class TestIntentClassifier:
    """Test Intent Classifier functionality."""

    @pytest.fixture
    def classifier(self):
        """Create intent classifier instance."""
        return IntentClassifier()

    @pytest.mark.asyncio
    async def test_query_intent_list_devices(self, classifier):
        """Test query intent detection for device listing."""
        intent = await classifier.classify("列出所有设备的接口状态")
        assert intent.primary == "query"
        assert intent.requires_hitl is False

    @pytest.mark.asyncio
    async def test_query_intent_show_bgp(self, classifier):
        """Test query intent detection for BGP status."""
        intent = await classifier.classify("查询 R1 的 BGP 邻居状态")
        assert intent.primary == "query"
        assert intent.requires_hitl is False

    @pytest.mark.asyncio
    async def test_diagnose_intent_why_down(self, classifier):
        """Test diagnose intent detection for failure analysis."""
        intent = await classifier.classify("为什么 BGP 邻居建不起来？")
        assert intent.primary == "diagnose"
        assert intent.requires_hitl is False

    @pytest.mark.asyncio
    async def test_diagnose_intent_troubleshoot(self, classifier):
        """Test diagnose intent detection for troubleshooting."""
        intent = await classifier.classify("排查 R2 到 R3 的连接问题")
        assert intent.primary == "diagnose"

    @pytest.mark.asyncio
    async def test_config_intent_create(self, classifier):
        """Test config intent detection for create operation."""
        intent = await classifier.classify("在 R1 上创建 Loopback0 接口")
        assert intent.primary == "config"
        assert intent.requires_hitl is True

    @pytest.mark.asyncio
    async def test_config_intent_delete(self, classifier):
        """Test config intent detection for delete operation."""
        intent = await classifier.classify("删除 VLAN 100")
        assert intent.primary == "config"
        assert intent.requires_hitl is True

    @pytest.mark.asyncio
    async def test_config_intent_netbox(self, classifier):
        """Test config intent detection for NetBox operations."""
        intent = await classifier.classify("在 NetBox 中添加新设备 SW01")
        assert intent.primary == "config"
        assert intent.requires_hitl is True

    @pytest.mark.asyncio
    async def test_compound_intent_diagnose_and_fix(self, classifier):
        """Test compound intent detection (diagnose then config)."""
        intent = await classifier.classify("诊断 BGP 问题并修复配置")
        assert intent.primary == "diagnose"
        assert intent.secondary == "config"
        assert intent.requires_hitl is True

    @pytest.mark.asyncio
    async def test_intent_has_confidence(self, classifier):
        """Test that intent includes confidence score."""
        intent = await classifier.classify("查询接口状态")
        assert 0.0 <= intent.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_intent_has_reasoning(self, classifier):
        """Test that intent includes reasoning."""
        intent = await classifier.classify("创建 VLAN 200")
        assert intent.reasoning is not None
        assert len(intent.reasoning) > 0


class TestIntentType:
    """Test IntentType enum."""

    def test_intent_type_values(self):
        """Test IntentType enum values."""
        assert IntentType.QUERY.value == "query"
        assert IntentType.DIAGNOSE.value == "diagnose"
        assert IntentType.CONFIG.value == "config"


class TestAgentToolCounts:
    """Test that agents have correct tool counts (3-7 per agent)."""

    def test_query_agent_tools(self):
        """Test Query Agent has 3 tools."""
        from olav.agents.query_agent import QueryAgent

        agent = QueryAgent()
        assert agent.tools_count == 3
        assert 3 <= agent.tools_count <= 7  # LangChain best practice

    def test_diagnose_agent_tools(self):
        """Test Diagnose Agent has 4 tools."""
        from olav.agents.diagnose_agent import DiagnoseAgent

        agent = DiagnoseAgent()
        assert agent.tools_count == 4
        assert 3 <= agent.tools_count <= 7

    def test_config_agent_tools(self):
        """Test Config Agent has 3 tools."""
        from olav.agents.config_agent import ConfigAgent

        agent = ConfigAgent()
        assert agent.tools_count == 3
        assert 3 <= agent.tools_count <= 7


class TestAgentProperties:
    """Test agent property methods."""

    def test_query_agent_properties(self):
        """Test Query Agent name and description."""
        from olav.agents.query_agent import QueryAgent

        agent = QueryAgent()
        assert agent.name == "query_agent"
        assert "查询" in agent.description or "只读" in agent.description

    def test_diagnose_agent_properties(self):
        """Test Diagnose Agent name and description."""
        from olav.agents.diagnose_agent import DiagnoseAgent

        agent = DiagnoseAgent()
        assert agent.name == "diagnose_agent"
        assert "诊断" in agent.description

    def test_config_agent_properties(self):
        """Test Config Agent name and description."""
        from olav.agents.config_agent import ConfigAgent

        agent = ConfigAgent()
        assert agent.name == "config_agent"
        assert "配置" in agent.description or "审批" in agent.description


class TestBaseAgentProtocol:
    """Test BaseAgent protocol compliance."""

    def test_agent_protocol_compliance(self):
        """Test that all agents implement BaseAgent protocol."""
        from olav.agents.base import AgentProtocol
        from olav.agents.config_agent import ConfigAgent
        from olav.agents.diagnose_agent import DiagnoseAgent
        from olav.agents.query_agent import QueryAgent

        # All agents should be instances of AgentProtocol (runtime checkable)
        assert isinstance(QueryAgent(), AgentProtocol)
        assert isinstance(DiagnoseAgent(), AgentProtocol)
        assert isinstance(ConfigAgent(), AgentProtocol)


class TestMultiAgentOrchestrator:
    """Test Multi-Agent Orchestrator routing logic."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance (without checkpointer for unit tests)."""
        from olav.agents.multi_agent_orchestrator import MultiAgentOrchestrator

        return MultiAgentOrchestrator(checkpointer=None)

    def test_orchestrator_has_all_agents(self, orchestrator):
        """Test orchestrator has all three agents."""
        assert orchestrator.query_agent is not None
        assert orchestrator.diagnose_agent is not None
        assert orchestrator.config_agent is not None

    def test_orchestrator_has_classifier(self, orchestrator):
        """Test orchestrator has intent classifier."""
        assert orchestrator.intent_classifier is not None


class TestToolSeparation:
    """Test that tools are properly separated by read/write operations."""

    def test_netconf_tools_separated(self):
        """Test NETCONF tools are separated into get (read) and edit (write)."""
        from olav.tools.nornir_tool import netconf_edit, netconf_get

        # Both tools should exist
        assert netconf_get is not None
        assert netconf_edit is not None

        # Check tool descriptions indicate read/write separation
        get_desc = netconf_get.description.lower()
        edit_desc = netconf_edit.description.lower()
        
        assert "read-only" in get_desc or "只读" in get_desc
        assert "hitl" in edit_desc or "approval" in edit_desc or "审批" in edit_desc

    def test_cli_tools_separated(self):
        """Test CLI tools are separated into show (read) and config (write)."""
        from olav.tools.nornir_tool import cli_config, cli_show

        # Both tools should exist
        assert cli_show is not None
        assert cli_config is not None

        # Check tool descriptions indicate read/write separation
        show_desc = cli_show.description.lower()
        config_desc = cli_config.description.lower()
        
        assert "read-only" in show_desc or "只读" in show_desc
        assert "hitl" in config_desc or "approval" in config_desc or "审批" in config_desc
