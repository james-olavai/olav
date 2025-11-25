"""
Unit tests for refactored NetBox tool (BaseTool + NetBoxAdapter).
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import requests

from olav.tools.netbox_tool_refactored import (
    NetBoxAPITool,
    NetBoxSchemaSearchTool,
    get_opensearch_client,
)
from olav.tools.base import ToolOutput


class TestNetBoxAPITool:
    """Test NetBoxAPITool BaseTool implementation."""
    
    @pytest.fixture
    def netbox_tool(self):
        """Create NetBoxAPITool with mock credentials."""
        return NetBoxAPITool(
            base_url="https://netbox.example.com",
            token="test-token-123"
        )
    
    def test_initialization(self, netbox_tool):
        """Test tool initialization."""
        assert netbox_tool.name == "netbox_api"
        assert netbox_tool.base_url == "https://netbox.example.com"
        assert netbox_tool.token == "test-token-123"
        assert "NetBox" in netbox_tool.description
    
    def test_initialization_from_settings(self):
        """Test initialization using default settings."""
        with patch("olav.tools.netbox_tool_refactored.settings") as mock_settings:
            mock_settings.netbox_url = "https://netbox.prod.com"
            mock_settings.netbox_token = "prod-token"
            
            tool = NetBoxAPITool()
            
            assert tool.base_url == "https://netbox.prod.com"
            assert tool.token == "prod-token"
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.settings")
    async def test_execute_missing_config(self, mock_settings):
        """Test execute with missing configuration."""
        # Mock settings to return None/empty
        mock_settings.netbox_url = None
        mock_settings.netbox_token = None
        
        tool = NetBoxAPITool()
        
        result = await tool.execute(path="/api/dcim/devices/")
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netbox"
        assert result.error == "NetBox not configured"
        assert result.data[0]["status"] == "CONFIG_ERROR"
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_get_success(self, mock_request, netbox_tool):
        """Test successful GET request."""
        # Mock response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 2,
            "results": [
                {"id": 1, "name": "R1", "status": {"value": "active"}},
                {"id": 2, "name": "R2", "status": {"value": "active"}},
            ]
        }
        mock_response.elapsed.total_seconds.return_value = 0.25
        mock_request.return_value = mock_response
        
        result = await netbox_tool.execute(
            path="/dcim/devices/",
            method="GET",
            params={"status": "active"}
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netbox"
        assert isinstance(result.data, list)
        assert result.error is None
        assert result.metadata["status_code"] == 200
        assert result.metadata["method"] == "GET"
        
        # Verify request was made correctly
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["method"] == "GET"
        assert "/api/dcim/devices/" in call_kwargs["url"]
        assert call_kwargs["params"] == {"status": "active"}
        assert "Token test-token-123" in call_kwargs["headers"]["Authorization"]
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_post_success(self, mock_request, netbox_tool):
        """Test successful POST request."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 3,
            "name": "R3",
            "device_type": {"id": 5, "model": "ISR4321"},
            "site": {"id": 1, "name": "HQ"},
            "status": {"value": "active"}
        }
        mock_response.elapsed.total_seconds.return_value = 0.35
        mock_request.return_value = mock_response
        
        device_data = {
            "name": "R3",
            "device_type": 5,
            "site": 1,
            "status": "active"
        }
        
        result = await netbox_tool.execute(
            path="/api/dcim/devices/",
            method="POST",
            data=device_data
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netbox"
        assert result.error is None
        assert result.metadata["status_code"] == 201
        
        # Verify POST data
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["json"] == device_data
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_delete_success(self, mock_request, netbox_tool):
        """Test successful DELETE request (204 No Content)."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 204
        mock_response.elapsed.total_seconds.return_value = 0.15
        mock_request.return_value = mock_response
        
        result = await netbox_tool.execute(
            path="/api/dcim/devices/5/",
            method="DELETE"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netbox"
        assert result.error is None
        assert "success" in result.data[0]["status"].lower()
        assert result.metadata["status_code"] == 204
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_http_error_404(self, mock_request, netbox_tool):
        """Test handling of 404 Not Found error."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 404
        mock_response.reason = "Not Found"
        mock_response.json.return_value = {"detail": "Device not found."}
        mock_request.return_value = mock_response
        
        result = await netbox_tool.execute(path="/api/dcim/devices/999/")
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "404" in result.error
        assert result.data[0]["status"] == "HTTP_ERROR"
        assert result.data[0]["code"] == 404
        assert "not found" in result.data[0]["message"].lower()
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_http_error_400(self, mock_request, netbox_tool):
        """Test handling of 400 Bad Request error."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.reason = "Bad Request"
        mock_response.json.return_value = {
            "name": ["This field is required."],
            "device_type": ["Invalid pk '999' - object does not exist."]
        }
        mock_request.return_value = mock_response
        
        result = await netbox_tool.execute(
            path="/api/dcim/devices/",
            method="POST",
            data={}
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "400" in result.error
        assert result.data[0]["code"] == 400
        assert "errors" in result.data[0]
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_timeout(self, mock_request, netbox_tool):
        """Test handling of request timeout."""
        mock_request.side_effect = requests.exceptions.Timeout("Request timeout")
        
        result = await netbox_tool.execute(path="/api/dcim/devices/")
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "timeout" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_connection_error(self, mock_request, netbox_tool):
        """Test handling of connection error."""
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")
        
        result = await netbox_tool.execute(path="/api/dcim/devices/")
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "connection" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_path_normalization(self, mock_request, netbox_tool):
        """Test automatic /api prefix addition."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_request.return_value = mock_response
        
        # Path without /api prefix
        await netbox_tool.execute(path="/dcim/devices/")
        
        call_kwargs = mock_request.call_args.kwargs
        assert "/api/dcim/devices/" in call_kwargs["url"]
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_device_extraction_single(self, mock_request, netbox_tool):
        """Test device name extraction from single object response."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "name": "R1", "status": "active"}
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_request.return_value = mock_response
        
        result = await netbox_tool.execute(path="/api/dcim/devices/1/")
        
        assert result.device == "R1"
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_execute_device_extraction_list(self, mock_request, netbox_tool):
        """Test device name extraction from list response."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 2,
            "results": [
                {"id": 1, "name": "R1"},
                {"id": 2, "name": "R2"}
            ]
        }
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_request.return_value = mock_response
        
        result = await netbox_tool.execute(path="/api/dcim/devices/")
        
        # Should extract from results list or default to "multi"
        assert result.device in ["R1", "multi"]  # Depends on adapter logic
    
    def test_extract_device_from_response_single_object(self, netbox_tool):
        """Test _extract_device_from_response with single object."""
        data = {"id": 1, "name": "R1", "status": "active"}
        device = netbox_tool._extract_device_from_response(data)
        assert device == "R1"
    
    def test_extract_device_from_response_nested_device(self, netbox_tool):
        """Test _extract_device_from_response with nested device object."""
        data = {"id": 5, "device": {"id": 1, "name": "R1"}, "interface": "Gi0/1"}
        device = netbox_tool._extract_device_from_response(data)
        assert device == "R1"
    
    def test_extract_device_from_response_list(self, netbox_tool):
        """Test _extract_device_from_response with list."""
        data = [{"id": 1, "name": "R1"}, {"id": 2, "name": "R2"}]
        device = netbox_tool._extract_device_from_response(data)
        assert device == "R1"
    
    def test_extract_device_from_response_no_name(self, netbox_tool):
        """Test _extract_device_from_response with no name field."""
        data = {"id": 1, "description": "Test"}
        device = netbox_tool._extract_device_from_response(data)
        assert device == "multi"


class TestNetBoxSchemaSearchTool:
    """Test NetBoxSchemaSearchTool implementation."""
    
    @pytest.fixture
    def schema_tool(self):
        """Create schema search tool instance."""
        return NetBoxSchemaSearchTool()
    
    def test_initialization(self, schema_tool):
        """Test tool initialization."""
        assert schema_tool.name == "netbox_schema_search"
        assert "schema" in schema_tool.description.lower()
        assert "endpoint" in schema_tool.description.lower()
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.get_opensearch_client")
    async def test_execute_successful_search(self, mock_get_client, schema_tool):
        """Test successful schema search."""
        # Mock OpenSearch client
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {
                "total": {"value": 2},
                "max_score": 2.5,
                "hits": [
                    {
                        "_score": 2.5,
                        "_source": {
                            "path": "/api/dcim/devices/",
                            "method": "GET",
                            "summary": "List all devices",
                            "parameters": json.dumps([
                                {"name": "status", "type": "string", "required": False}
                            ])
                        }
                    },
                    {
                        "_score": 2.0,
                        "_source": {
                            "path": "/api/dcim/devices/",
                            "method": "POST",
                            "summary": "Create a new device",
                            "parameters": json.dumps([]),
                            "request_body": json.dumps({
                                "name": {"type": "string", "required": True},
                                "device_type": {"type": "integer", "required": True}
                            })
                        }
                    }
                ]
            }
        }
        mock_get_client.return_value = mock_client
        
        result = await schema_tool.execute(query="list devices")
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netbox_schema"
        assert len(result.data) == 2
        
        # Check first result
        assert result.data[0]["path"] == "/api/dcim/devices/"
        assert result.data[0]["method"] == "GET"
        assert result.data[0]["summary"] == "List all devices"
        assert isinstance(result.data[0]["parameters"], list)
        assert result.data[0]["score"] == 2.5
        
        # Check second result (has request_body)
        assert result.data[1]["method"] == "POST"
        assert "request_body" in result.data[1]
        
        # Check metadata
        assert result.metadata["total_hits"] == 2
        assert result.metadata["max_score"] == 2.5
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.get_opensearch_client")
    async def test_execute_opensearch_error(self, mock_get_client, schema_tool):
        """Test handling of OpenSearch error."""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Connection timeout")
        mock_get_client.return_value = mock_client
        
        result = await schema_tool.execute(query="list devices")
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "failed" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.get_opensearch_client")
    async def test_execute_invalid_json_parameters(self, mock_get_client, schema_tool):
        """Test handling of invalid JSON in parameters field."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {
                "total": {"value": 1},
                "max_score": 1.5,
                "hits": [
                    {
                        "_score": 1.5,
                        "_source": {
                            "path": "/api/dcim/sites/",
                            "method": "GET",
                            "summary": "List sites",
                            "parameters": "invalid json"  # Invalid JSON
                        }
                    }
                ]
            }
        }
        mock_get_client.return_value = mock_client
        
        result = await schema_tool.execute(query="list sites")
        
        assert isinstance(result, ToolOutput)
        assert len(result.data) == 1
        # Should handle invalid JSON gracefully
        assert "parameters" in result.data[0]
        assert result.data[0]["parameters"] == []  # Default to empty list


class TestNetBoxToolRegistration:
    """Test tool registration with ToolRegistry."""
    
    def test_tools_registered(self):
        """Test both tools are registered on import."""
        from olav.tools.base import ToolRegistry
        
        registered_names = [tool.name for tool in ToolRegistry.list_tools()]
        
        assert "netbox_api" in registered_names
        assert "netbox_schema_search" in registered_names
    
    def test_get_tool_by_name(self):
        """Test retrieving tools by name."""
        from olav.tools.base import ToolRegistry
        
        api_tool = ToolRegistry.get_tool("netbox_api")
        assert api_tool is not None
        assert isinstance(api_tool, NetBoxAPITool)
        
        schema_tool = ToolRegistry.get_tool("netbox_schema_search")
        assert schema_tool is not None
        assert isinstance(schema_tool, NetBoxSchemaSearchTool)


class TestNetBoxToolEdgeCases:
    """Test edge cases and boundary conditions."""
    
    @pytest.mark.asyncio
    @patch("olav.tools.netbox_tool_refactored.requests.request")
    async def test_non_json_response(self, mock_request):
        """Test handling of non-JSON response."""
        tool = NetBoxAPITool(
            base_url="https://netbox.test.com",
            token="test-token"
        )
        
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("err", "doc", 0)
        mock_response.text = "Plain text response"
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_request.return_value = mock_response
        
        result = await tool.execute(path="/api/dcim/devices/")
        
        assert isinstance(result, ToolOutput)
        # Should handle non-JSON gracefully
        assert result.error is None
    
    @pytest.mark.asyncio
    async def test_explicit_device_parameter(self):
        """Test using explicit device parameter."""
        tool = NetBoxAPITool(
            base_url="https://netbox.test.com",
            token="test-token"
        )
        
        with patch("olav.tools.netbox_tool_refactored.requests.request") as mock_request:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 200
            mock_response.json.return_value = {"results": []}
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_request.return_value = mock_response
            
            result = await tool.execute(
                path="/api/dcim/devices/",
                device="ExplicitDevice"
            )
            
            # Should use explicit device parameter
            assert result.device == "ExplicitDevice"
