"""Unit tests for Schema-Aware tools."""

import pytest


def test_suzieq_schema_search():
    """Test SuzieQ schema search tool."""
    pytest.skip("Requires SuzieQ mock")
    # from olav.tools.suzieq_tool import SuzieQSchemaAwareTool
    # tool = SuzieQSchemaAwareTool()
    # TODO: Mock SuzieQ schema


def test_suzieq_query():
    """Test SuzieQ universal query tool."""
    # TODO: Test with mocked SqObject
    pytest.skip("Requires SuzieQ mock")


@pytest.mark.asyncio
async def test_openconfig_schema_search(opensearch_memory):
    """Test OpenConfig schema search."""
    from olav.tools.opensearch_tool import OpenSearchRAGTool
    
    tool = OpenSearchRAGTool(memory=opensearch_memory)
    
    # TODO: Populate test index
    pytest.skip("Requires OpenSearch test data")
