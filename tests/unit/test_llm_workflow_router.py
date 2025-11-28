"""Unit tests for LLM Workflow Router.

Tests the LLM-based workflow routing that replaces hardcoded keyword matching.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.core.llm_workflow_router import (
    LLMWorkflowRouter,
    WorkflowRouteResult,
    get_workflow_router,
    route_workflow,
)


class TestWorkflowRouteResult:
    """Tests for WorkflowRouteResult model."""
    
    def test_valid_route_result(self):
        """Test creating a valid route result."""
        result = WorkflowRouteResult(
            workflow="query_diagnostic",
            confidence=0.9,
            reasoning="Network status query detected",
        )
        assert result.workflow == "query_diagnostic"
        assert result.confidence == 0.9
        assert result.requires_expert_mode is False
    
    def test_confidence_bounds(self):
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            WorkflowRouteResult(
                workflow="query_diagnostic",
                confidence=1.5,  # Invalid
                reasoning="Test",
            )
    
    def test_valid_workflows(self):
        """Test all valid workflow types."""
        valid_workflows = [
            "query_diagnostic",
            "device_execution",
            "netbox_management",
            "inspection",
            "deep_dive",
        ]
        for workflow in valid_workflows:
            result = WorkflowRouteResult(
                workflow=workflow,
                confidence=0.8,
                reasoning=f"Testing {workflow}",
            )
            assert result.workflow == workflow
    
    def test_deep_dive_with_expert_mode_flag(self):
        """Test deep_dive with requires_expert_mode."""
        result = WorkflowRouteResult(
            workflow="deep_dive",
            confidence=0.95,
            reasoning="Complex audit detected",
            requires_expert_mode=True,
        )
        assert result.workflow == "deep_dive"
        assert result.requires_expert_mode is True


class TestLLMWorkflowRouter:
    """Tests for LLMWorkflowRouter class."""
    
    def test_router_init(self):
        """Test router initialization."""
        router = LLMWorkflowRouter(expert_mode=True)
        assert router.expert_mode is True
        assert router._llm is None  # Lazy loaded
    
    def test_fallback_prompt_normal_mode(self):
        """Test fallback prompt without expert mode."""
        router = LLMWorkflowRouter(expert_mode=False)
        prompt = router._fallback_prompt()
        assert "deep_dive" not in prompt or "专家模式" in prompt
        assert "query_diagnostic" in prompt
        assert "device_execution" in prompt
    
    def test_fallback_prompt_expert_mode(self):
        """Test fallback prompt with expert mode."""
        router = LLMWorkflowRouter(expert_mode=True)
        prompt = router._fallback_prompt()
        assert "deep_dive" in prompt
        assert "批量审计" in prompt
    
    @pytest.mark.asyncio
    async def test_route_success(self):
        """Test successful LLM routing."""
        mock_llm = MagicMock()
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = WorkflowRouteResult(
            workflow="inspection",
            confidence=0.92,
            reasoning="Sync operation detected",
        )
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        router = LLMWorkflowRouter(llm=mock_llm)
        result = await router.route("同步 NetBox 与网络状态")
        
        assert result.workflow == "inspection"
        assert result.confidence == 0.92
    
    @pytest.mark.asyncio
    async def test_route_dict_response(self):
        """Test handling dict response from LLM."""
        mock_llm = MagicMock()
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = {
            "workflow": "device_execution",
            "confidence": 0.85,
            "reasoning": "Config change detected",
            "requires_expert_mode": False,
        }
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        router = LLMWorkflowRouter(llm=mock_llm)
        result = await router.route("配置 R1 的 VLAN 100")
        
        assert result.workflow == "device_execution"
        assert result.confidence == 0.85
    
    @pytest.mark.asyncio
    async def test_deep_dive_without_expert_mode(self):
        """Test deep_dive is blocked when expert mode is disabled."""
        mock_llm = MagicMock()
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.return_value = WorkflowRouteResult(
            workflow="deep_dive",
            confidence=0.9,
            reasoning="Complex audit detected",
            requires_expert_mode=True,
        )
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        router = LLMWorkflowRouter(llm=mock_llm, expert_mode=False)
        result = await router.route("审计所有路由器")
        
        # Should fallback to query_diagnostic
        assert result.workflow == "query_diagnostic"
        assert result.requires_expert_mode is True
        assert "expert mode disabled" in result.reasoning
    
    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        """Test fallback when LLM fails."""
        mock_llm = MagicMock()
        mock_structured_llm = AsyncMock()
        mock_structured_llm.ainvoke.side_effect = Exception("LLM error")
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        router = LLMWorkflowRouter(llm=mock_llm)
        result = await router.route("查询 R1 的 BGP 状态")
        
        # Should use keyword fallback
        assert result.workflow == "query_diagnostic"
        assert result.confidence == 0.5
        assert "Fallback" in result.reasoning
    
    def test_fallback_route_inspection(self):
        """Test fallback routing for inspection keywords."""
        router = LLMWorkflowRouter()
        result = router._fallback_route("同步 NetBox 数据")
        assert result.workflow == "inspection"
    
    def test_fallback_route_netbox(self):
        """Test fallback routing for NetBox keywords."""
        router = LLMWorkflowRouter()
        result = router._fallback_route("查看 NetBox 设备清单")
        assert result.workflow == "netbox_management"
    
    def test_fallback_route_device_execution(self):
        """Test fallback routing for config keywords."""
        router = LLMWorkflowRouter()
        result = router._fallback_route("配置 VLAN 100")
        assert result.workflow == "device_execution"
    
    def test_fallback_route_deep_dive(self):
        """Test fallback routing for deep dive in expert mode."""
        router = LLMWorkflowRouter(expert_mode=True)
        result = router._fallback_route("审计所有边界路由器")
        assert result.workflow == "deep_dive"
        assert result.requires_expert_mode is True
    
    def test_fallback_route_default(self):
        """Test fallback routing defaults to query_diagnostic."""
        router = LLMWorkflowRouter()
        result = router._fallback_route("hello world")
        assert result.workflow == "query_diagnostic"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_workflow_router_singleton(self):
        """Test singleton pattern for router."""
        # Reset singleton
        import olav.core.llm_workflow_router as module
        module._router = None
        
        router1 = get_workflow_router(expert_mode=False)
        router2 = get_workflow_router(expert_mode=False)
        assert router1 is router2
    
    def test_get_workflow_router_recreate_on_mode_change(self):
        """Test router is recreated when expert mode changes."""
        import olav.core.llm_workflow_router as module
        module._router = None
        
        router1 = get_workflow_router(expert_mode=False)
        router2 = get_workflow_router(expert_mode=True)
        assert router1 is not router2
        assert router2.expert_mode is True
    
    @pytest.mark.asyncio
    async def test_route_workflow_function(self):
        """Test convenience function route_workflow."""
        with patch("olav.core.llm_workflow_router.get_workflow_router") as mock_get:
            mock_router = MagicMock()
            mock_router.route = AsyncMock(return_value=WorkflowRouteResult(
                workflow="query_diagnostic",
                confidence=0.8,
                reasoning="Test",
            ))
            mock_get.return_value = mock_router
            
            result = await route_workflow("查询 BGP 状态")
            
            assert result.workflow == "query_diagnostic"
            mock_get.assert_called_once_with(expert_mode=False)
