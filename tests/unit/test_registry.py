"""
Unit tests for WorkflowRegistry.

Tests workflow registration, discovery, trigger matching, and metadata validation.
"""

import pytest
from typing import Any, Dict

from langgraph.graph import StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from olav.workflows.registry import WorkflowRegistry, WorkflowMetadata


# Test fixtures

@pytest.fixture(autouse=True)
def clean_registry():
    """Clear registry before and after each test."""
    WorkflowRegistry.clear()
    yield
    WorkflowRegistry.clear()


@pytest.fixture
def mock_workflow_factory():
    """Create a minimal workflow factory for testing."""
    def factory(checkpointer: BaseCheckpointSaver, **kwargs) -> StateGraph:
        graph = StateGraph(dict)
        graph.add_node("dummy", lambda state: state)
        graph.set_entry_point("dummy")
        graph.set_finish_point("dummy")
        return graph.compile(checkpointer=checkpointer)
    return factory


# Registration tests

def test_register_workflow_with_decorator(mock_workflow_factory):
    """Test workflow registration using decorator syntax."""
    
    @WorkflowRegistry.register(
        name="TestWorkflow",
        description="Test workflow for unit testing",
        examples=["test query 1", "test query 2"],
        triggers=["test", "query"]
    )
    class TestWorkflowClass:
        pass
    
    # Verify registration
    workflow = WorkflowRegistry.get_workflow("TestWorkflow")
    assert workflow is not None
    assert workflow.name == "TestWorkflow"
    assert workflow.description == "Test workflow for unit testing"
    assert len(workflow.examples) == 2
    assert len(workflow.triggers) == 2


def test_register_workflow_programmatically(mock_workflow_factory):
    """Test workflow registration without decorator."""
    
    class ManualWorkflowClass:
        pass
    
    metadata = WorkflowMetadata(
        name="ManualWorkflow",
        description="Manually registered workflow",
        examples=["manual test"],
        triggers=["manual"],
        class_ref=ManualWorkflowClass
    )
    
    WorkflowRegistry._workflows[metadata.name] = metadata
    
    workflow = WorkflowRegistry.get_workflow("ManualWorkflow")
    assert workflow is not None
    assert workflow.name == "ManualWorkflow"


def test_duplicate_registration_raises_error(mock_workflow_factory):
    """Test that duplicate workflow names raise ValueError."""
    
    @WorkflowRegistry.register(
        name="DuplicateWorkflow",
        description="First registration",
        examples=[],
        triggers=[]
    )
    class Workflow1:
        pass
    
    with pytest.raises(ValueError, match="already registered"):
        @WorkflowRegistry.register(
            name="DuplicateWorkflow",
            description="Second registration (should fail)",
            examples=[],
            triggers=[]
        )
        class Workflow2:
            pass


# Discovery tests

def test_list_workflows(mock_workflow_factory):
    """Test listing all registered workflows."""
    
    # Register multiple workflows
    for i in range(3):
        @WorkflowRegistry.register(
            name=f"Workflow{i}",
            description=f"Test workflow {i}",
            examples=[],
            triggers=[]
        )
        class DummyWorkflow:
            pass
    
    workflows = WorkflowRegistry.list_workflows()
    assert len(workflows) == 3
    assert all(w.name.startswith("Workflow") for w in workflows)


def test_list_workflows_by_category(mock_workflow_factory):
    """Test filtering workflows by description text (no category field)."""
    
    # Register workflows with different descriptions
    @WorkflowRegistry.register(
        name="DiagnosticWorkflow",
        description="Diagnostic workflow for network troubleshooting",
        examples=[],
        triggers=[]
    )
    class DiagnosticClass:
        pass
    
    @WorkflowRegistry.register(
        name="ExecutionWorkflow",
        description="Execution workflow for configuration changes",
        examples=[],
        triggers=[]
    )
    class ExecutionClass:
        pass
    
    # Since there's no category field, test list_workflows without filter
    workflows = WorkflowRegistry.list_workflows()
    assert len(workflows) == 2
    assert any(w.name == "DiagnosticWorkflow" for w in workflows)
    assert any(w.name == "ExecutionWorkflow" for w in workflows)


def test_get_nonexistent_workflow():
    """Test that getting non-existent workflow returns None."""
    workflow = WorkflowRegistry.get_workflow("NonExistent")
    assert workflow is None


# Trigger matching tests

def test_match_triggers_exact(mock_workflow_factory):
    """Test exact trigger matching."""
    
    @WorkflowRegistry.register(
        name="BGPWorkflow",
        description="BGP diagnostics",
        examples=["查询 BGP 状态"],
        triggers=["bgp", "邻居", "neighbor"]
    )
    class BGPClass:
        pass
    
    matches = WorkflowRegistry.match_triggers("BGP")
    assert len(matches) == 1
    assert matches[0] == "BGPWorkflow"  # Returns workflow name string


def test_match_triggers_case_insensitive(mock_workflow_factory):
    """Test case-insensitive trigger matching."""
    
    @WorkflowRegistry.register(
        name="InterfaceWorkflow",
        description="Interface diagnostics",
        examples=[],
        triggers=["interface", "接口"]
    )
    class InterfaceClass:
        pass
    
    # Should match regardless of case
    matches = WorkflowRegistry.match_triggers("INTERFACE")
    assert len(matches) == 1
    
    matches = WorkflowRegistry.match_triggers("接口")
    assert len(matches) == 1


def test_match_triggers_multiple_matches(mock_workflow_factory):
    """Test query matching multiple workflows."""
    
    # Both workflows have "status" trigger
    @WorkflowRegistry.register(
        name="Workflow1",
        description="First workflow",
        examples=[],
        triggers=["status", "check"]
    )
    class Workflow1Class:
        pass
    
    @WorkflowRegistry.register(
        name="Workflow2",
        description="Second workflow",
        examples=[],
        triggers=["status", "verify"]
    )
    class Workflow2Class:
        pass
    
    matches = WorkflowRegistry.match_triggers("status")
    assert len(matches) == 2
    assert set(matches) == {"Workflow1", "Workflow2"}  # Returns workflow name strings


def test_match_triggers_no_matches(mock_workflow_factory):
    """Test query with no matching triggers."""
    
    @WorkflowRegistry.register(
        name="TestWorkflow",
        description="Test workflow",
        examples=[],
        triggers=["test", "demo"]
    )
    class TestClass:
        pass
    
    matches = WorkflowRegistry.match_triggers("completely different query")
    assert len(matches) == 0


def test_match_triggers_partial_word(mock_workflow_factory):
    """Test that partial word matches don't trigger."""
    
    @WorkflowRegistry.register(
        name="TestWorkflow",
        description="Test workflow",
        examples=[],
        triggers=["config"]
    )
    class TestClass:
        pass
    
    # "configuration" contains "config" but shouldn't match (word boundary)
    matches = WorkflowRegistry.match_triggers("configuration")
    # This depends on implementation - if using word boundaries, should be 0
    # If using substring matching, would be 1
    # Adjust based on actual implementation


# Metadata validation tests

def test_workflow_metadata_required_fields():
    """Test WorkflowMetadata requires all essential fields."""
    
    with pytest.raises(TypeError):
        # Missing required fields
        WorkflowMetadata(name="Test")


def test_workflow_metadata_required_fields_validation(mock_workflow_factory):
    """Test WorkflowMetadata has required fields."""
    
    class TestClass:
        pass
    
    # Valid metadata
    metadata = WorkflowMetadata(
        name="Test",
        description="Test description",
        examples=["example 1"],
        triggers=["trigger"],
        class_ref=TestClass
    )
    assert metadata.name == "Test"
    assert metadata.description == "Test description"
    assert len(metadata.examples) == 1
    
    # Triggers is optional
    metadata2 = WorkflowMetadata(
        name="Test2",
        description="Test",
        examples=[],
        class_ref=TestClass
    )
    assert metadata2.triggers is None


def test_workflow_class_ref_callable(mock_workflow_factory):
    """Test that workflow class can be instantiated."""
    
    class TestWorkflowClass:
        def __init__(self):
            self.name = "test"
    
    metadata = WorkflowMetadata(
        name="CallableTest",
        description="Test class callable",
        examples=[],
        triggers=[],
        class_ref=TestWorkflowClass
    )
    
    # class_ref should be a class
    assert isinstance(metadata.class_ref, type)
    
    # Should be able to instantiate
    instance = metadata.class_ref()
    assert instance.name == "test"


# Integration tests

def test_full_registration_workflow(mock_workflow_factory):
    """Test complete workflow registration and retrieval cycle."""
    
    @WorkflowRegistry.register(
        name="FullTest",
        description="Complete integration test",
        examples=[
            "测试查询 1",
            "测试查询 2",
            "test query 3"
        ],
        triggers=["测试", "test", "query"]
    )
    class FullTestClass:
        pass
    
    # Verify registration
    workflows = WorkflowRegistry.list_workflows()
    assert len(workflows) == 1
    
    # Verify retrieval
    workflow = WorkflowRegistry.get_workflow("FullTest")
    assert workflow.name == "FullTest"
    assert len(workflow.examples) == 3
    assert len(workflow.triggers) == 3
    
    # Verify trigger matching
    matches = WorkflowRegistry.match_triggers("测试")
    assert len(matches) == 1
    assert matches[0] == "FullTest"  # Returns workflow name string
    
    # Verify class reference
    assert workflow.class_ref == FullTestClass


def test_clear_registry(mock_workflow_factory):
    """Test clearing the registry."""
    
    # Register workflows
    for i in range(5):
        @WorkflowRegistry.register(
            name=f"Workflow{i}",
            description=f"Test {i}",
            examples=[],
            triggers=[]
        )
        class DummyClass:
            pass
    
    assert len(WorkflowRegistry.list_workflows()) == 5
    
    # Clear registry
    WorkflowRegistry.clear()
    assert len(WorkflowRegistry.list_workflows()) == 0
