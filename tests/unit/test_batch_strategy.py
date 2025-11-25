"""
Unit tests for BatchPathStrategy.

Tests YAML config loading, device resolution, parallel execution, validation,
and intent compilation.
"""

import pytest
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import yaml

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from olav.strategies.batch_path import (
    BatchPathStrategy,
    DeviceCheckResult,
    BatchExecutionSummary,
    BatchPathResult
)
from olav.schemas.inspection import InspectionConfig, CheckTask, ThresholdRule, DeviceSelector
from olav.validation.threshold import DeviceValidationResult, ValidationResult
from olav.tools.base import ToolOutput


# Test fixtures

@pytest.fixture
def mock_llm():
    """Create mock LLM (minimal use in batch path)."""
    llm = MagicMock(spec=BaseChatModel)
    return llm


@pytest.fixture
def mock_tool_registry():
    """Create mock ToolRegistry."""
    registry = MagicMock()
    
    # Mock get_tool to return different tools
    def get_tool(name):
        if name == "suzieq_query":
            tool = MagicMock()
            
            async def execute(**kwargs):
                hostname = kwargs.get("hostname", "unknown")
                table = kwargs.get("table", "")
                
                if table == "bgp":
                    # Simulate different results for different devices
                    if hostname == "R1":
                        peer_count = 3  # Pass threshold
                    elif hostname == "R2":
                        peer_count = 1  # Fail threshold
                    else:
                        peer_count = 2
                    
                    return ToolOutput(
                        source="suzieq",
                        device=hostname,
                        data=[{"count": peer_count, "state": "Established"}],
                        metadata={"table": "bgp"}
                    )
                
                elif table == "interfaces":
                    return ToolOutput(
                        source="suzieq",
                        device=hostname,
                        data=[
                            {"ifname": "Gi0/1", "state": "up", "adminState": "up"},
                            {"ifname": "Gi0/2", "state": "down", "adminState": "down"}
                        ],
                        metadata={"table": "interfaces"}
                    )
                
                return ToolOutput(
                    source="suzieq",
                    device=hostname,
                    data=[],
                    error=f"Unknown table: {table}"
                )
            
            tool.execute = AsyncMock(side_effect=execute)
            return tool
        
        elif name == "netbox_api_call":
            tool = MagicMock()
            
            async def execute(**kwargs):
                # Mock NetBox device query
                return ToolOutput(
                    source="netbox",
                    device="multi",
                    data=[
                        {"name": "R1", "role": "router", "status": "active"},
                        {"name": "R2", "role": "router", "status": "active"}
                    ],
                    metadata={"endpoint": kwargs.get("endpoint")}
                )
            
            tool.execute = AsyncMock(side_effect=execute)
            return tool
        
        return None
    
    registry.get_tool = MagicMock(side_effect=get_tool)
    
    return registry


@pytest.fixture
def batch_strategy(mock_llm, mock_tool_registry):
    """Create BatchPathStrategy with mocked dependencies."""
    return BatchPathStrategy(
        llm=mock_llm,
        tool_registry=mock_tool_registry
    )


@pytest.fixture
def sample_config_dict():
    """Sample inspection config as dictionary."""
    return {
        "name": "bgp_health_check",
        "description": "Check BGP peer counts",
        "devices": {
            "explicit": ["R1", "R2", "R3"]
        },
        "checks": [
            {
                "name": "bgp_peer_count",
                "description": "Verify BGP peers established",
                "tool": "suzieq_query",
                "parameters": {
                    "table": "bgp",
                    "state": "Established"
                },
                "threshold": {
                    "field": "count",
                    "operator": ">=",
                    "value": 2,
                    "severity": "critical",
                    "message": "BGP peer count on {device} is {actual}, expected >= {value}"
                },
                "enabled": True
            }
        ],
        "parallel": True,
        "max_workers": 10
    }


@pytest.fixture
def sample_yaml_config(tmp_path):
    """Create temporary YAML config file."""
    config_data = {
        "name": "interface_health_check",
        "description": "Check interface states",
        "devices": {
            "explicit": ["R1", "R2"]
        },
        "checks": [
            {
                "name": "interface_up_check",
                "tool": "suzieq_query",
                "parameters": {"table": "interfaces"},
                "enabled": True
            }
        ],
        "parallel": False
    }
    
    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
    
    return str(config_file)


# Initialization tests

def test_batch_strategy_initialization(mock_llm, mock_tool_registry):
    """Test BatchPathStrategy initializes correctly."""
    strategy = BatchPathStrategy(llm=mock_llm, tool_registry=mock_tool_registry)
    
    assert strategy.llm == mock_llm
    assert strategy.tool_registry == mock_tool_registry
    assert strategy.validator is not None


# Device resolution tests

@pytest.mark.asyncio
async def test_resolve_explicit_devices(batch_strategy, sample_config_dict):
    """Test resolving explicit device list."""
    config = InspectionConfig(**sample_config_dict)
    devices = await batch_strategy._resolve_devices(config)
    
    assert devices == ["R1", "R2", "R3"]


@pytest.mark.asyncio
async def test_resolve_netbox_devices(batch_strategy):
    """Test resolving devices from NetBox filter."""
    config_dict = {
        "name": "test",
        "devices": {
            "netbox_filter": {"role": "router", "status": "active"}
        },
        "checks": [
            {
                "name": "dummy_check",
                "tool": "suzieq_query",
                "parameters": {"table": "device"}
            }
        ]
    }
    
    config = InspectionConfig(**config_dict)
    devices = await batch_strategy._resolve_devices(config)
    
    # Should return devices from mocked NetBox
    assert "R1" in devices
    assert "R2" in devices


@pytest.mark.asyncio
async def test_resolve_regex_devices(batch_strategy):
    """Test resolving devices with regex pattern."""
    config_dict = {
        "name": "test",
        "devices": {
            "regex": "^R[0-9]+"
        },
        "checks": [
            {
                "name": "dummy_check",
                "tool": "suzieq_query",
                "parameters": {"table": "device"}
            }
        ]
    }
    
    config = InspectionConfig(**config_dict)
    
    # This requires SuzieQ tool to return device list
    # For now, test that it doesn't crash
    devices = await batch_strategy._resolve_devices(config)
    
    # Should attempt resolution (may be empty without full SuzieQ mock)
    assert isinstance(devices, list)


# Single check execution tests

@pytest.mark.asyncio
async def test_execute_single_check_success(batch_strategy):
    """Test executing single check on single device."""
    check = CheckTask(
        name="bgp_check",
        tool="suzieq_query",
        parameters={"table": "bgp", "state": "Established"},
        threshold=ThresholdRule(
            field="count",
            operator=">=",
            value=2,
            severity="critical"
        )
    )
    
    result = await batch_strategy._execute_single_check("R1", check)
    
    assert result.device == "R1"
    assert result.check_name == "bgp_check"
    assert result.tool_output is not None
    assert result.tool_output.source == "suzieq"
    assert result.validation is not None
    assert result.execution_time_ms > 0


@pytest.mark.asyncio
async def test_execute_single_check_validation_pass(batch_strategy):
    """Test check passes threshold validation."""
    check = CheckTask(
        name="bgp_check",
        tool="suzieq_query",
        parameters={"table": "bgp"},
        threshold=ThresholdRule(
            field="count",
            operator=">=",
            value=2,
            severity="critical"
        )
    )
    
    result = await batch_strategy._execute_single_check("R1", check)
    
    # R1 has 3 peers, should pass >= 2
    assert result.validation is not None
    assert result.validation.passed is True


@pytest.mark.asyncio
async def test_execute_single_check_validation_fail(batch_strategy):
    """Test check fails threshold validation."""
    check = CheckTask(
        name="bgp_check",
        tool="suzieq_query",
        parameters={"table": "bgp"},
        threshold=ThresholdRule(
            field="count",
            operator=">=",
            value=2,
            severity="critical"
        )
    )
    
    result = await batch_strategy._execute_single_check("R2", check)
    
    # R2 has 1 peer, should fail >= 2
    assert result.validation is not None
    assert result.validation.passed is False


@pytest.mark.asyncio
async def test_execute_single_check_tool_not_found(batch_strategy):
    """Test handling of missing tool."""
    check = CheckTask(
        name="test_check",
        tool="nonexistent_tool",
        parameters={}
    )
    
    result = await batch_strategy._execute_single_check("R1", check)
    
    assert result.error is not None
    assert "not found" in result.error.lower()


# Batch execution tests

@pytest.mark.asyncio
async def test_execute_from_dict(batch_strategy, sample_config_dict):
    """Test executing batch from config dict."""
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    assert isinstance(result, BatchPathResult)
    assert result.config_name == "bgp_health_check"
    assert result.summary.total_devices == 3
    assert result.summary.total_checks == 1
    assert result.summary.total_executions == 3  # 3 devices x 1 check
    assert result.summary.passed + result.summary.failed + result.summary.errors == 3


@pytest.mark.asyncio
async def test_execute_from_yaml_file(batch_strategy, sample_yaml_config):
    """Test executing batch from YAML file."""
    result = await batch_strategy.execute(config_path=sample_yaml_config)
    
    assert isinstance(result, BatchPathResult)
    assert result.config_name == "interface_health_check"
    assert result.summary.total_devices == 2
    assert result.summary.total_checks == 1


@pytest.mark.asyncio
async def test_execute_parallel(batch_strategy, sample_config_dict):
    """Test parallel execution."""
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    # Should execute all 3 devices in parallel
    assert len(result.device_results) == 3
    
    # All devices should be present
    devices = {r.device for r in result.device_results}
    assert devices == {"R1", "R2", "R3"}


@pytest.mark.asyncio
async def test_execute_sequential(batch_strategy, sample_config_dict):
    """Test sequential execution."""
    # Disable parallel execution
    sample_config_dict["parallel"] = False
    
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    # Should still get all results
    assert len(result.device_results) == 3


@pytest.mark.asyncio
async def test_execute_no_config_error(batch_strategy):
    """Test error when no config provided."""
    with pytest.raises(ValueError, match="Must provide either config_path or config_dict"):
        await batch_strategy.execute()


# Summary generation tests

def test_generate_summary_all_passed(batch_strategy):
    """Test summary with all checks passed."""
    # Create actual validation results
    val_result1 = ValidationResult(
        passed=True,
        rule=MagicMock(),
        actual_value=3,
        expected_value=2,
        violation_message=None
    )
    val_result2 = ValidationResult(
        passed=True,
        rule=MagicMock(),
        actual_value=4,
        expected_value=2,
        violation_message=None
    )
    
    results = [
        DeviceCheckResult(
            device="R1",
            check_name="check1",
            tool_output=ToolOutput(source="test", device="R1", data=[]),
            validation=DeviceValidationResult(
                device="R1",
                check_name="check1",
                results=[val_result1]
            ),
            execution_time_ms=100
        ),
        DeviceCheckResult(
            device="R2",
            check_name="check1",
            tool_output=ToolOutput(source="test", device="R2", data=[]),
            validation=DeviceValidationResult(
                device="R2",
                check_name="check1",
                results=[val_result2]
            ),
            execution_time_ms=150
        )
    ]
    
    summary = batch_strategy._generate_summary(results, 2, 1, 250)
    
    assert summary.total_devices == 2
    assert summary.total_checks == 1
    assert summary.total_executions == 2
    assert summary.passed == 2
    assert summary.failed == 0
    assert summary.errors == 0
    assert summary.pass_rate == 100.0


def test_generate_summary_mixed_results(batch_strategy):
    """Test summary with mixed pass/fail/error."""
    val_pass = ValidationResult(
        passed=True,
        rule=MagicMock(),
        actual_value=3,
        expected_value=2
    )
    val_fail = ValidationResult(
        passed=False,
        rule=MagicMock(),
        actual_value=1,
        expected_value=2,
        violation_message="Failed"
    )
    
    results = [
        DeviceCheckResult(
            device="R1",
            check_name="check1",
            validation=DeviceValidationResult(
                device="R1",
                check_name="check1",
                results=[val_pass]
            ),
            execution_time_ms=100
        ),
        DeviceCheckResult(
            device="R2",
            check_name="check1",
            validation=DeviceValidationResult(
                device="R2",
                check_name="check1",
                results=[val_fail]
            ),
            execution_time_ms=150
        ),
        DeviceCheckResult(
            device="R3",
            check_name="check1",
            error="Connection timeout",
            execution_time_ms=200
        )
    ]
    
    summary = batch_strategy._generate_summary(results, 3, 1, 450)
    
    assert summary.total_executions == 3
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.errors == 1
    assert summary.pass_rate == pytest.approx(33.33, rel=0.1)


# Report generation tests

@pytest.mark.asyncio
async def test_report_text_format(batch_strategy, sample_config_dict):
    """Test text report generation."""
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    report = result.to_report(format="text")
    
    assert "Batch Inspection Report" in report
    assert "bgp_health_check" in report
    assert "Summary:" in report
    assert "Total Devices:" in report
    assert "Pass Rate:" in report
    assert "Detailed Results:" in report


@pytest.mark.asyncio
async def test_report_json_format(batch_strategy, sample_config_dict):
    """Test JSON report generation."""
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    report = result.to_report(format="json")
    
    # Should be valid JSON
    import json
    parsed = json.loads(report)
    
    assert parsed["config_name"] == "bgp_health_check"
    assert "summary" in parsed
    assert "device_results" in parsed


@pytest.mark.asyncio
async def test_report_yaml_format(batch_strategy, sample_config_dict):
    """Test YAML report generation."""
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    report = result.to_report(format="yaml")
    
    # Should be valid YAML
    parsed = yaml.safe_load(report)
    
    assert parsed["config_name"] == "bgp_health_check"
    assert "summary" in parsed


# Suitability tests

def test_is_suitable_batch_keywords():
    """Test suitability detection for batch queries."""
    assert BatchPathStrategy.is_suitable("批量检查所有路由器的 BGP 状态") is True
    assert BatchPathStrategy.is_suitable("Compliance check all devices") is True
    assert BatchPathStrategy.is_suitable("Audit all switches") is True
    assert BatchPathStrategy.is_suitable("Health check for all routers") is True


def test_is_suitable_non_batch_keywords():
    """Test non-batch queries are not suitable."""
    assert BatchPathStrategy.is_suitable("查询 R1 的 BGP 状态") is False
    assert BatchPathStrategy.is_suitable("Show interfaces on Switch-A") is False
    assert BatchPathStrategy.is_suitable("What is the config?") is False


# Violation collection tests

@pytest.mark.asyncio
async def test_violations_collected(batch_strategy, sample_config_dict):
    """Test violations are collected in result."""
    result = await batch_strategy.execute(config_dict=sample_config_dict)
    
    # R2 should fail threshold (1 < 2 peers)
    assert len(result.violations) > 0
    
    # Check violation message format
    violation = result.violations[0]
    assert "R2" in violation or "count" in violation.lower()


# Phase B.5 Tests: YAML Loading and Intent Compilation

def test_load_config_class_method(tmp_path):
    """Test BatchPathStrategy.load_config() class method."""
    config_data = {
        "name": "test_config",
        "description": "Test configuration",
        "devices": ["R1", "R2"],
        "checks": [
            {
                "name": "test_check",
                "tool": "suzieq_query",
                "parameters": {"table": "bgp"},
                "enabled": True
            }
        ]
    }
    
    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
    
    # Test class method
    config = BatchPathStrategy.load_config(config_file)
    
    assert config.name == "test_config"
    assert len(config.devices) == 2
    assert len(config.checks) == 1


@pytest.mark.asyncio
async def test_compile_intent_to_parameters_bgp(batch_strategy, mock_llm):
    """Test intent compilation for BGP check."""
    mock_response = AIMessage(content='{"table": "bgp", "state": "Established", "method": "summarize"}')
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    batch_strategy.llm = mock_llm
    
    intent = "检查 BGP 邻居状态"
    tool = "suzieq_query"
    existing_params = {}
    
    compiled_params = await batch_strategy._compile_intent_to_parameters(
        intent=intent,
        tool=tool,
        existing_params=existing_params
    )
    
    assert "table" in compiled_params
    assert compiled_params["table"] == "bgp"
    assert compiled_params["state"] == "Established"


@pytest.mark.asyncio
async def test_compile_intent_preserves_existing_params(batch_strategy, mock_llm):
    """Test that existing parameters take precedence over compiled ones."""
    mock_response = AIMessage(content='{"table": "bgp", "method": "get"}')
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    batch_strategy.llm = mock_llm
    
    intent = "检查 BGP"
    tool = "suzieq_query"
    existing_params = {"method": "summarize"}  # Explicit param should override
    
    compiled_params = await batch_strategy._compile_intent_to_parameters(
        intent=intent,
        tool=tool,
        existing_params=existing_params
    )
    
    assert compiled_params["method"] == "summarize"  # Existing param preserved


@pytest.mark.asyncio
async def test_compile_intent_handles_invalid_json(batch_strategy, mock_llm):
    """Test intent compilation with invalid LLM response."""
    mock_response = AIMessage(content="This is not JSON")
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    batch_strategy.llm = mock_llm
    
    intent = "检查接口状态"
    tool = "suzieq_query"
    existing_params = {"table": "interfaces"}
    
    # Should fall back to existing params
    compiled_params = await batch_strategy._compile_intent_to_parameters(
        intent=intent,
        tool=tool,
        existing_params=existing_params
    )
    
    assert compiled_params == existing_params


@pytest.mark.asyncio
async def test_execute_check_with_intent(batch_strategy, mock_llm):
    """Test executing check with intent field."""
    # Mock LLM for intent compilation
    mock_response = AIMessage(content='{"table": "bgp", "state": "Established", "method": "summarize"}')
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    batch_strategy.llm = mock_llm
    
    # Mock tool
    tool = MagicMock()
    async def execute(**kwargs):
        return ToolOutput(
            source="suzieq_query",
            device=kwargs.get("hostname", "unknown"),
            data=[{"count": 3, "hostname": kwargs.get("hostname")}],
            error=None
        )
    tool.execute = execute
    batch_strategy.tool_registry.get_tool = MagicMock(return_value=tool)
    
    # Create check with intent
    check = CheckTask(
        name="bgp_intent_check",
        tool="suzieq_query",
        intent="检查 BGP 邻居状态",  # Intent instead of explicit params
        threshold=ThresholdRule(
            field="count",
            operator=">=",
            value=2,
            severity="critical"
        )
    )
    
    result = await batch_strategy._execute_single_check("R1", check)
    
    assert result.device == "R1"
    assert result.check_name == "bgp_intent_check"
    assert result.tool_output is not None
    assert result.tool_output.error is None
    assert mock_llm.ainvoke.called  # Intent was compiled


@pytest.mark.asyncio
async def test_load_and_execute_real_yaml(batch_strategy, tmp_path):
    """Test loading and executing a real YAML config file."""
    yaml_content = """
name: test_inspection
description: Test batch inspection
devices:
  - R1
  - R2
checks:
  - name: bgp_check
    tool: suzieq_query
    enabled: true
    parameters:
      table: bgp
      state: Established
      method: summarize
    threshold:
      field: count
      operator: ">="
      value: 2
      severity: critical
parallel: true
max_workers: 5
"""
    
    config_file = tmp_path / "test_inspection.yaml"
    config_file.write_text(yaml_content)
    
    # Execute from YAML file
    result = await batch_strategy.execute(config_path=str(config_file))
    
    assert result.config_name == "test_inspection"
    assert result.summary.total_devices == 2
    assert len(result.device_results) > 0  # Use correct field name
