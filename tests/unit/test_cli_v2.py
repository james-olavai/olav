"""Tests for OLAV CLI v2 Components.

Tests:
- thin_client: HTTP client and SSE parsing
- display: ThinkingTree, HITLPanel, ResultRenderer
- commands: CLI command structure
"""

from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console


# ============================================
# SSE Parser Tests
# ============================================
class TestSSEParser:
    """Test SSE event parsing."""

    def test_parse_simple_event(self):
        """Test parsing a simple SSE event."""
        from olav.cli.thin_client import SSEParser, StreamEventType

        parser = SSEParser()

        # First line: event type
        result = parser.parse_line("event: token")
        assert result is None  # Not complete yet

        # Second line: data
        result = parser.parse_line('data: {"content": "hello"}')
        assert result is not None
        assert result.type == StreamEventType.TOKEN
        assert result.data["content"] == "hello"

    def test_parse_thinking_event(self):
        """Test parsing thinking event."""
        from olav.cli.thin_client import SSEParser, StreamEventType

        parser = SSEParser()

        parser.parse_line("event: thinking")
        result = parser.parse_line('data: {"text": "Analyzing BGP..."}')

        assert result.type == StreamEventType.THINKING
        assert result.data["text"] == "Analyzing BGP..."

    def test_parse_tool_call_event(self):
        """Test parsing tool_start event (tool invocation)."""
        from olav.cli.thin_client import SSEParser, StreamEventType

        parser = SSEParser()

        parser.parse_line("event: tool_start")
        result = parser.parse_line('data: {"name": "suzieq_query", "args": {"table": "bgp"}}')

        assert result.type == StreamEventType.TOOL_START
        assert result.data["name"] == "suzieq_query"
        assert result.data["args"]["table"] == "bgp"

    def test_parse_hitl_interrupt(self):
        """Test parsing HITL interrupt event."""
        from olav.cli.thin_client import SSEParser, StreamEventType

        parser = SSEParser()

        parser.parse_line("event: interrupt")
        result = parser.parse_line('data: {"workflow_type": "DEEP_DIVE", "risk_level": "high"}')

        assert result.type == StreamEventType.INTERRUPT
        assert result.data["workflow_type"] == "DEEP_DIVE"

    def test_parse_empty_line(self):
        """Test parsing empty line returns None."""
        from olav.cli.thin_client import SSEParser

        parser = SSEParser()
        result = parser.parse_line("")
        assert result is None

    def test_parse_unknown_event_type(self):
        """Test parsing unknown event type defaults to MESSAGE."""
        from olav.cli.thin_client import SSEParser, StreamEventType

        parser = SSEParser()

        parser.parse_line("event: unknown_type")
        result = parser.parse_line('data: {"foo": "bar"}')

        assert result.type == StreamEventType.MESSAGE


# ============================================
# Client Config Tests
# ============================================
class TestClientConfig:
    """Test client configuration."""

    def test_from_env_default(self):
        """Test loading config from environment with defaults."""
        from olav.cli.thin_client import ClientConfig

        config = ClientConfig.from_env()

        assert config.server_url == "http://localhost:8000"
        assert config.timeout == 300.0

    def test_from_env_custom(self, monkeypatch):
        """Test loading config from custom environment."""
        from olav.cli.thin_client import ClientConfig

        monkeypatch.setenv("OLAV_SERVER_URL", "http://prod:9000")
        monkeypatch.setenv("OLAV_TIMEOUT", "600")

        config = ClientConfig.from_env()

        assert config.server_url == "http://prod:9000"
        assert config.timeout == 600.0


# ============================================
# Thin Client Tests
# ============================================
class TestOlavThinClient:
    """Test thin HTTP client."""

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check endpoint."""
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://test:8000")

        # Mock httpx client
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.get = AsyncMock(return_value=MagicMock(
                json=lambda: {
                    "status": "healthy",
                    "version": "1.0.0",
                    "environment": "test",
                    "orchestrator_ready": True,
                },
                raise_for_status=lambda: None,
            ))
            mock_client_class.return_value = mock_client

            client = OlavThinClient(config)
            client._client = mock_client

            health = await client.health()

            assert health.status == "healthy"
            assert health.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://test:8000")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.aclose = AsyncMock()
            mock_client_class.return_value = mock_instance

            async with OlavThinClient(config) as client:
                assert client._client is not None

            # Should close after exit
            mock_instance.aclose.assert_called_once()


# ============================================
# Display Component Tests
# ============================================
class TestThinkingTree:
    """Test ThinkingTree display component."""

    def test_add_thinking_step(self):
        """Test adding thinking steps."""
        from olav.cli.display import ThinkingTree

        console = Console(file=StringIO(), force_terminal=True)
        tree = ThinkingTree(console)

        tree.add_thinking("Analyzing query...")

        # Tree should have the step
        assert len(tree.tree.children) == 1

    def test_add_tool_call(self):
        """Test adding tool call."""
        from olav.cli.display import ThinkingTree

        console = Console(file=StringIO(), force_terminal=True)
        tree = ThinkingTree(console)

        tree.add_tool_call("suzieq_query", {"table": "bgp"})

        assert "suzieq_query" in tree.tool_nodes
        assert len(tree.tree.children) == 1

    def test_mark_tool_complete(self):
        """Test marking tool as complete."""
        from olav.cli.display import ThinkingTree

        console = Console(file=StringIO(), force_terminal=True)
        tree = ThinkingTree(console)

        tree.add_tool_call("suzieq_query", {"table": "bgp"})
        tree.mark_tool_complete("suzieq_query", success=True)

        # Tool should be marked complete
        assert "suzieq_query" in tree.tool_nodes


class TestHITLPanel:
    """Test HITL panel component."""

    def test_display_request(self):
        """Test displaying HITL request."""
        from olav.cli.display import HITLPanel
        from olav.cli.thin_client import HITLRequest

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        panel = HITLPanel(console)

        request = HITLRequest(
            plan_id="test-123",
            workflow_type="DEEP_DIVE",
            operation="shutdown interface",
            target_device="R1",
            commands=["interface shutdown"],
            risk_level="high",
            reasoning="Need to isolate faulty link",
        )

        panel.display(request)

        rendered = output.getvalue()
        assert "HITL" in rendered or "审批" in rendered

    def test_display_execution_plan(self):
        """Test displaying execution plan."""
        from olav.cli.display import HITLPanel
        from olav.cli.thin_client import HITLRequest

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        panel = HITLPanel(console)

        request = HITLRequest(
            plan_id="test-123",
            workflow_type="DEEP_DIVE",
            operation="audit",
            target_device="all",
            commands=[],
            risk_level="low",
            reasoning="",
            execution_plan={
                "summary": "Audit plan",
                "feasible_tasks": [1, 2],
                "uncertain_tasks": [3],
                "infeasible_tasks": [],
            },
            todos=[
                {"id": 1, "task": "Check BGP"},
                {"id": 2, "task": "Check OSPF"},
                {"id": 3, "task": "Check VPN"},
            ],
        )

        panel.display_execution_plan(request)

        rendered = output.getvalue()
        assert "执行计划" in rendered or "Plan" in rendered


class TestResultRenderer:
    """Test result rendering component."""

    def test_render_message(self):
        """Test rendering assistant message."""
        from olav.cli.display import ResultRenderer

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        renderer = ResultRenderer(console)

        renderer.render_message("Hello, I found 3 BGP issues.", role="assistant")

        rendered = output.getvalue()
        assert "OLAV" in rendered or "Hello" in rendered

    def test_render_table(self):
        """Test rendering data table."""
        from olav.cli.display import ResultRenderer

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        renderer = ResultRenderer(console)

        data = [
            {"device": "R1", "state": "Established"},
            {"device": "R2", "state": "NotEstablished"},
        ]

        renderer.render_table(data, title="BGP Neighbors")

        rendered = output.getvalue()
        assert "R1" in rendered or "device" in rendered

    def test_render_error(self):
        """Test rendering error message."""
        from olav.cli.display import ResultRenderer

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        renderer = ResultRenderer(console)

        renderer.render_error("Connection failed", details="Timeout after 30s")

        rendered = output.getvalue()
        assert "错误" in rendered or "Error" in rendered


# ============================================
# CLI Command Tests
# ============================================
class TestCLICommands:
    """Test CLI command structure."""

    def test_app_exists(self):
        """Test CLI app is properly defined."""
        from olav.cli.commands import app

        assert app is not None
        assert app.info.name == "olav"

    def test_query_command_exists(self):
        """Test core commands are registered."""
        from olav.cli.commands import app

        # Check core commands that should exist
        command_names = []
        for cmd in app.registered_commands:
            if cmd.callback is not None:
                command_names.append(cmd.callback.__name__)
        # Core commands (status merged into doctor, banner merged into version)
        assert "version" in command_names
        assert "doctor" in command_names

    def test_inspect_subcommand_exists(self):
        """Test inspect subcommand group exists."""
        from olav.cli.commands import inspect_app

        assert inspect_app is not None
        command_names = [cmd.name for cmd in inspect_app.registered_commands]
        assert "list" in command_names
        assert "run" in command_names

    def test_doc_subcommand_exists(self):
        """Test doc subcommand group exists."""
        from olav.cli.commands import doc_app

        assert doc_app is not None
        command_names = [cmd.name for cmd in doc_app.registered_commands]
        assert "list" in command_names
        assert "search" in command_names
        assert "upload" in command_names


# ============================================
# Integration Tests (Mock Server)
# ============================================
class TestIntegration:
    """Integration tests with mocked server."""

    @pytest.mark.asyncio
    async def test_chat_stream_flow(self):
        """Test complete chat streaming flow."""
        from olav.cli.thin_client import (
            ClientConfig,
            OlavThinClient,
        )

        # This would require a mock HTTP server
        # For now, just verify the interface
        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)

        # Verify method exists and has correct signature
        assert hasattr(client, "chat_stream")
        assert callable(client.chat_stream)


# ============================================
# Phase 3: Auto-completion Tests
# ============================================
class TestDynamicDeviceCompleter:
    """Tests for DynamicDeviceCompleter auto-completion."""

    def test_device_completer_initialization(self):
        """Test DynamicDeviceCompleter initializes correctly."""
        from olav.cli.repl import DynamicDeviceCompleter
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        completer = DynamicDeviceCompleter(client)

        assert completer._cache == []
        assert completer._fetching is False

    def test_device_completer_get_completions_empty(self):
        """Test completions when no devices loaded."""
        from prompt_toolkit.document import Document

        from olav.cli.repl import DynamicDeviceCompleter
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        completer = DynamicDeviceCompleter(client)

        # Empty cache should return no completions for short input
        doc = Document("R")
        completions = list(completer.get_completions(doc, None))

        # Needs at least 2 chars or a trigger word
        assert completions == []

    def test_device_completer_get_completions_with_devices(self):
        """Test completions with loaded devices."""
        import time

        from prompt_toolkit.document import Document

        from olav.cli.repl import DynamicDeviceCompleter
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        completer = DynamicDeviceCompleter(client)

        # Manually set cache (simulating loaded state)
        completer._cache = ["R1-Core", "R2-Edge", "SW1-Access", "SW2-Dist"]
        # Set fresh cache time to prevent background fetch attempt
        completer._cache_time = time.time()

        # Need trigger word or 2+ chars
        doc = Document("check R")
        completions = list(completer.get_completions(doc, None))

        # Should match R1-Core and R2-Edge
        completion_texts = [c.text for c in completions]
        assert "R1-Core" in completion_texts
        assert "R2-Edge" in completion_texts

    def test_device_completer_case_insensitive(self):
        """Test completions are case-insensitive."""
        import time

        from prompt_toolkit.document import Document

        from olav.cli.repl import DynamicDeviceCompleter
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        completer = DynamicDeviceCompleter(client)

        completer._cache = ["R1-Core", "R2-Edge"]
        # Set fresh cache time to prevent background fetch attempt
        completer._cache_time = time.time()

        doc = Document("check r1")
        completions = list(completer.get_completions(doc, None))

        completion_texts = [c.text for c in completions]
        assert "R1-Core" in completion_texts

    def test_device_completer_cache_ttl(self):
        """Test cache TTL refresh logic."""
        import time

        from olav.cli.repl import DynamicDeviceCompleter
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        completer = DynamicDeviceCompleter(client)

        # Fresh cache should not refresh
        completer._cache_time = time.time()
        assert not completer._should_refresh()

        # Old cache should refresh
        completer._cache_time = time.time() - 400  # > 300s TTL
        assert completer._should_refresh()


class TestAutocompleteClientMethods:
    """Tests for thin client autocomplete methods."""

    def test_get_device_names_method_exists(self):
        """Test get_device_names method exists."""
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)

        assert hasattr(client, "get_device_names")
        assert callable(client.get_device_names)

    def test_get_suzieq_tables_method_exists(self):
        """Test get_suzieq_tables method exists."""
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)

        assert hasattr(client, "get_suzieq_tables")
        assert callable(client.get_suzieq_tables)

    @pytest.mark.asyncio
    async def test_get_device_names_returns_list(self):
        """Test get_device_names returns a list of strings."""
        from unittest.mock import AsyncMock, MagicMock

        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)

        # Mock the internal httpx client
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "devices": ["R1", "R2", "SW1"],
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.get_device_names()

        assert isinstance(result, list)
        assert len(result) == 3
        assert "R1" in result

    @pytest.mark.asyncio
    async def test_get_suzieq_tables_returns_list(self):
        """Test get_suzieq_tables returns a list of strings."""
        from unittest.mock import AsyncMock, MagicMock

        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)

        # Mock the internal httpx client
        mock_http_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tables": ["bgp", "ospf", "interfaces", "routes"],
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.get_suzieq_tables()

        assert isinstance(result, list)
        assert len(result) == 4
        assert "bgp" in result


# ============================================
# Phase 3: Progress Tracking Tests
# ============================================
class TestProgressTracking:
    """Tests for file upload progress tracking."""

    def test_upload_document_has_progress_callback(self):
        """Test upload_document accepts on_progress callback."""
        import inspect

        from olav.cli.thin_client import OlavThinClient

        sig = inspect.signature(OlavThinClient.upload_document)
        params = list(sig.parameters.keys())

        assert "on_progress" in params

    def test_upload_document_signature(self):
        """Test upload_document has correct signature."""
        import inspect

        from olav.cli.thin_client import OlavThinClient

        sig = inspect.signature(OlavThinClient.upload_document)
        params = sig.parameters

        # Required params
        assert "self" in params
        assert "file_path" in params

        # Optional progress callback
        assert "on_progress" in params
        assert params["on_progress"].default is None


# ============================================
# Phase 3: Dashboard / TUI Tests
# ============================================
class TestDashboardComponents:
    """Tests for Dashboard TUI components."""

    def test_olav_logo_exists(self):
        """Test OLAV logo constant is defined."""
        from olav.cli.display import OLAV_LOGO

        assert OLAV_LOGO is not None
        assert "██████" in OLAV_LOGO  # Block characters in logo

    def test_snowman_ascii_exists(self):
        """Test snowman ASCII art is defined."""
        from olav.cli.display import SNOWMAN_ASCII

        assert SNOWMAN_ASCII is not None
        assert len(SNOWMAN_ASCII) > 50  # Should be substantial

    def test_snowman_mini_exists(self):
        """Test mini snowman constant is defined."""
        from olav.cli.display import SNOWMAN_MINI

        assert SNOWMAN_MINI is not None
        assert "⛄" in SNOWMAN_MINI

    def test_get_olav_banner_function(self):
        """Test get_olav_banner returns Text object."""
        from rich.text import Text

        from olav.cli.display import get_olav_banner

        result = get_olav_banner()
        assert isinstance(result, Text)

    def test_get_snowman_function(self):
        """Test get_snowman returns Text object."""
        from rich.text import Text

        from olav.cli.display import get_snowman

        result = get_snowman()
        assert isinstance(result, Text)

    def test_show_welcome_banner_callable(self):
        """Test show_welcome_banner is callable."""
        from olav.cli.display import show_welcome_banner

        assert callable(show_welcome_banner)

    def test_dashboard_class_exists(self):
        """Test Dashboard class exists."""
        from olav.cli.display import Dashboard

        assert Dashboard is not None

    def test_dashboard_initialization(self):
        """Test Dashboard initializes correctly."""
        from rich.console import Console

        from olav.cli.display import Dashboard
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        console = Console()

        dashboard = Dashboard(client, console)

        assert dashboard.client is client
        assert dashboard.console is console
        assert dashboard.running is False
        assert dashboard._activity_log == []

    def test_dashboard_add_activity(self):
        """Test Dashboard.add_activity method."""
        from rich.console import Console

        from olav.cli.display import Dashboard
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        console = Console()

        dashboard = Dashboard(client, console)
        dashboard.add_activity("Test activity")

        assert len(dashboard._activity_log) == 1
        assert dashboard._activity_log[0][1] == "Test activity"

    def test_dashboard_stop(self):
        """Test Dashboard.stop method."""
        from rich.console import Console

        from olav.cli.display import Dashboard
        from olav.cli.thin_client import ClientConfig, OlavThinClient

        config = ClientConfig(server_url="http://localhost:8000")
        client = OlavThinClient(config)
        console = Console()

        dashboard = Dashboard(client, console)
        dashboard.running = True
        dashboard.stop()

        assert dashboard.running is False


class TestDashboardCommands:
    """Tests for dashboard CLI commands."""

    def test_dashboard_command_exists(self):
        """Test dashboard command is registered."""
        from olav.cli.commands import app

        # Get all command names
        command_names = []
        for cmd in app.registered_commands:
            if cmd.callback is not None:
                command_names.append(cmd.callback.__name__)

        assert "dashboard" in command_names

    def test_version_command_has_banner_option(self):
        """Test version command includes banner option (banner command merged into version)."""
        from olav.cli.commands import app

        # Find version command
        version_cmd = None
        for cmd in app.registered_commands:
            if cmd.callback is not None and cmd.callback.__name__ == "version":
                version_cmd = cmd
                break

        assert version_cmd is not None, "version command should exist"
        # Check that it has --banner option by looking at the function signature
        import inspect
        sig = inspect.signature(version_cmd.callback)
        assert "banner" in sig.parameters, "version command should have --banner option"
