"""Tests for Execution Backend Protocol and Implementations.

Tests cover:
1. ExecutionResult model
2. Protocol compliance (BackendProtocol, SandboxBackendProtocol, StoreBackendProtocol)
3. NornirSandbox functionality (blacklist, HITL, CLI/NETCONF execution)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from olav.execution.backends.protocol import (
    BackendProtocol,
    ExecutionResult,
    SandboxBackendProtocol,
    StoreBackendProtocol,
)


class TestExecutionResult:
    """Tests for ExecutionResult class."""

    def test_success_result(self):
        """Test successful execution result."""
        result = ExecutionResult(
            success=True,
            output="BGP neighbor 10.0.0.1 is up",
        )
        assert result.success is True
        assert result.output == "BGP neighbor 10.0.0.1 is up"
        assert result.error is None
        assert result.metadata == {}

    def test_failure_result(self):
        """Test failed execution result."""
        result = ExecutionResult(
            success=False,
            output="",
            error="Connection refused",
        )
        assert result.success is False
        assert result.output == ""
        assert result.error == "Connection refused"

    def test_result_with_metadata(self):
        """Test execution result with metadata."""
        result = ExecutionResult(
            success=True,
            output="config saved",
            metadata={"device": "R1", "is_write": True, "parsed": False},
        )
        assert result.metadata["device"] == "R1"
        assert result.metadata["is_write"] is True

    def test_result_with_all_fields(self):
        """Test execution result with all fields populated."""
        result = ExecutionResult(
            success=False,
            output="partial output",
            error="Timeout after 30s",
            metadata={"device": "R2", "should_fallback_to_cli": True},
        )
        assert result.success is False
        assert result.output == "partial output"
        assert result.error == "Timeout after 30s"
        assert result.metadata["should_fallback_to_cli"] is True


class TestProtocolCompliance:
    """Tests for Protocol interface compliance."""

    def test_backend_protocol_interface(self):
        """Test BackendProtocol defines required methods."""
        # Verify protocol has read/write methods
        assert hasattr(BackendProtocol, "read")
        assert hasattr(BackendProtocol, "write")

    def test_sandbox_protocol_interface(self):
        """Test SandboxBackendProtocol extends BackendProtocol."""
        # Verify it has execute method
        assert hasattr(SandboxBackendProtocol, "execute")
        # And inherits read/write
        assert hasattr(SandboxBackendProtocol, "read")
        assert hasattr(SandboxBackendProtocol, "write")

    def test_store_protocol_interface(self):
        """Test StoreBackendProtocol defines put/get."""
        assert hasattr(StoreBackendProtocol, "put")
        assert hasattr(StoreBackendProtocol, "get")
        # And inherits read/write
        assert hasattr(StoreBackendProtocol, "read")
        assert hasattr(StoreBackendProtocol, "write")


class MockBackend:
    """Mock backend implementation for testing."""

    async def read(self, path: str) -> str:
        return f"content at {path}"

    async def write(self, path: str, content: str) -> None:
        pass

    async def execute(
        self,
        command: str,
        background: bool = False,
        requires_approval: bool = True,
    ) -> ExecutionResult:
        return ExecutionResult(success=True, output=f"executed: {command}")

    async def put(self, namespace: str, key: str, value: dict) -> None:
        pass

    async def get(self, namespace: str, key: str) -> dict | None:
        return {"key": key, "namespace": namespace}


class TestMockBackendCompliance:
    """Test that mock backend satisfies protocols."""

    @pytest.mark.asyncio
    async def test_mock_backend_read(self):
        """Test mock backend read method."""
        backend = MockBackend()
        result = await backend.read("/config/bgp")
        assert "content at /config/bgp" in result

    @pytest.mark.asyncio
    async def test_mock_backend_write(self):
        """Test mock backend write method."""
        backend = MockBackend()
        await backend.write("/config/bgp", "router bgp 65001")
        # No exception means success

    @pytest.mark.asyncio
    async def test_mock_backend_execute(self):
        """Test mock backend execute method."""
        backend = MockBackend()
        result = await backend.execute("show ip bgp summary")
        assert result.success is True
        assert "executed: show ip bgp summary" in result.output

    @pytest.mark.asyncio
    async def test_mock_backend_put_get(self):
        """Test mock backend put/get methods."""
        backend = MockBackend()
        await backend.put("sessions", "user1", {"data": "test"})
        result = await backend.get("sessions", "user1")
        assert result is not None
        assert result["key"] == "user1"


class TestNornirSandboxBlacklist:
    """Tests for NornirSandbox blacklist functionality."""

    @pytest.fixture
    def mock_nornir(self):
        """Create mock Nornir instance."""
        with patch("olav.execution.backends.nornir_sandbox.InitNornir") as mock:
            nr_instance = MagicMock()
            nr_instance.inventory.hosts = {}
            mock.return_value = nr_instance
            yield mock

    @pytest.fixture
    def mock_memory(self):
        """Create mock OpenSearchMemory."""
        memory = MagicMock()
        memory.log_execution = AsyncMock()
        return memory

    def test_default_blacklist_contains_dangerous_commands(self, mock_nornir, mock_memory):
        """Test default blacklist includes dangerous commands."""
        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            # Check default dangerous commands are blocked
            dangerous = ["traceroute", "reload", "write erase", "erase startup-config"]
            for cmd in dangerous:
                assert cmd in sandbox.blacklist

    def test_blacklist_matching(self, mock_nornir, mock_memory):
        """Test blacklist pattern matching."""
        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            # Exact match
            assert sandbox._is_blacklisted("traceroute 10.0.0.1") is not None

            # Normalized match (hyphens to spaces)
            assert sandbox._is_blacklisted("trace-route 10.0.0.1") is not None

            # Safe command should not be blocked
            assert sandbox._is_blacklisted("show ip route") is None

    def test_write_operation_detection(self, mock_nornir, mock_memory):
        """Test write operation detection."""
        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            # Write operations
            assert sandbox._is_write_operation("edit-config /interfaces/interface[name='eth0']")
            assert sandbox._is_write_operation("commit confirmed 60")
            assert sandbox._is_write_operation("set system hostname R1")
            assert sandbox._is_write_operation("delete routing-options")

            # Read operations
            assert not sandbox._is_write_operation("get-config /interfaces")
            assert not sandbox._is_write_operation("show ip bgp")
            assert not sandbox._is_write_operation("display version")


class TestNornirSandboxExecution:
    """Tests for NornirSandbox command execution."""

    @pytest.fixture
    def mock_nornir_with_devices(self):
        """Create mock Nornir with devices."""
        with patch("olav.execution.backends.nornir_sandbox.InitNornir") as mock:
            nr_instance = MagicMock()

            # Create mock host
            host = MagicMock()
            host.name = "R1"
            host.platform = "cisco_ios"
            host.username = None
            host.password = None

            nr_instance.inventory.hosts = {"R1": host}
            nr_instance.filter.return_value = nr_instance

            mock.return_value = nr_instance
            yield mock, nr_instance

    @pytest.fixture
    def mock_memory(self):
        """Create mock OpenSearchMemory."""
        memory = MagicMock()
        memory.log_execution = AsyncMock()
        return memory

    @pytest.mark.asyncio
    async def test_execute_cli_command_success(self, mock_nornir_with_devices, mock_memory):
        """Test successful CLI command execution."""
        _mock_init, nr_instance = mock_nornir_with_devices

        # Mock netmiko result
        device_result = MagicMock()
        device_result.failed = False
        device_result.result = [{"neighbor": "10.0.0.1", "state": "Established"}]

        run_result = {"R1": device_result}
        nr_instance.run.return_value = run_result

        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            result = await sandbox.execute_cli_command(
                device="R1",
                command="show ip bgp summary",
                use_textfsm=True,
            )

            assert result.success is True
            assert result.metadata.get("parsed") is True

    @pytest.mark.asyncio
    async def test_execute_cli_command_blacklisted(self, mock_nornir_with_devices, mock_memory):
        """Test blacklisted command is rejected."""
        _mock_init, _nr_instance = mock_nornir_with_devices

        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            result = await sandbox.execute_cli_command(
                device="R1",
                command="traceroute 10.0.0.1",
            )

            assert result.success is False
            assert "blacklist" in result.error.lower()
            mock_memory.log_execution.assert_called()

    @pytest.mark.asyncio
    async def test_execute_device_not_found(self, mock_nornir_with_devices, mock_memory):
        """Test execution with non-existent device."""
        _mock_init, nr_instance = mock_nornir_with_devices

        # Filter returns empty hosts for unknown device
        empty_nr = MagicMock()
        empty_nr.inventory.hosts = {}
        nr_instance.filter.return_value = empty_nr

        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            result = await sandbox.execute_cli_command(
                device="NonExistent",
                command="show version",
            )

            assert result.success is False
            assert "not found" in result.error.lower()


class TestNornirSandboxHITL:
    """Tests for HITL approval flow."""

    @pytest.fixture
    def mock_nornir_with_devices(self):
        """Create mock Nornir with devices."""
        with patch("olav.execution.backends.nornir_sandbox.InitNornir") as mock:
            nr_instance = MagicMock()

            host = MagicMock()
            host.name = "R1"
            host.platform = "cisco_ios"
            host.username = None
            host.password = None

            nr_instance.inventory.hosts = {"R1": host}
            nr_instance.filter.return_value = nr_instance

            mock.return_value = nr_instance
            yield mock, nr_instance

    @pytest.fixture
    def mock_memory(self):
        """Create mock OpenSearchMemory."""
        memory = MagicMock()
        memory.log_execution = AsyncMock()
        return memory

    @pytest.mark.asyncio
    async def test_write_operation_requires_approval(self, mock_nornir_with_devices, mock_memory):
        """Test that write operations trigger HITL approval."""
        _mock_init, nr_instance = mock_nornir_with_devices

        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            # Patch _request_approval to track calls
            with patch.object(sandbox, "_request_approval") as mock_approval:
                from olav.execution.backends.nornir_sandbox import ApprovalDecision
                mock_approval.return_value = ApprovalDecision(decision="approve")

                # Mock successful NAPALM execution via the nornir run method
                device_result = MagicMock()
                device_result.failed = False
                device_result.result = {"config": "..."}
                nr_instance.run.return_value = {"R1": device_result}

                await sandbox.execute(
                    command="edit-config /interfaces",
                    device="R1",
                    requires_approval=True,
                )

                # HITL approval should be called for write operation
                mock_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_approval_rejection_aborts_execution(self, mock_nornir_with_devices, mock_memory):
        """Test that rejected approval aborts execution."""
        _mock_init, _nr_instance = mock_nornir_with_devices

        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            with patch("config.settings.settings") as mock_settings:
                mock_settings.enable_hitl = True

                from olav.execution.backends.nornir_sandbox import ApprovalDecision, NornirSandbox
                sandbox = NornirSandbox(memory=mock_memory)

                # Patch _request_approval to return rejection
                with patch.object(sandbox, "_request_approval") as mock_approval:
                    mock_approval.return_value = ApprovalDecision(
                        decision="reject",
                        reason="Too dangerous"
                    )

                    result = await sandbox.execute(
                        command="edit-config /system/hostname",
                        device="R1",
                        requires_approval=True,
                    )

                    assert result.success is False
                    assert "rejected" in result.error.lower()
                    assert result.metadata.get("reason") == "Too dangerous"


class TestApprovalDecision:
    """Tests for ApprovalDecision class."""

    def test_approve_decision(self):
        """Test approve decision."""
        from olav.execution.backends.nornir_sandbox import ApprovalDecision

        decision = ApprovalDecision(decision="approve")
        assert decision.decision == "approve"
        assert decision.modified_command is None
        assert decision.reason is None

    def test_reject_decision_with_reason(self):
        """Test reject decision with reason."""
        from olav.execution.backends.nornir_sandbox import ApprovalDecision

        decision = ApprovalDecision(
            decision="reject",
            reason="Command is too risky"
        )
        assert decision.decision == "reject"
        assert decision.reason == "Command is too risky"

    def test_edit_decision_with_modified_command(self):
        """Test edit decision with modified command."""
        from olav.execution.backends.nornir_sandbox import ApprovalDecision

        decision = ApprovalDecision(
            decision="edit",
            modified_command="show ip bgp summary | include Estab"
        )
        assert decision.decision == "edit"
        assert "include Estab" in decision.modified_command


class TestNornirSandboxNetconfFallback:
    """Tests for NETCONF to CLI fallback."""

    @pytest.fixture
    def mock_nornir_with_devices(self):
        """Create mock Nornir with devices."""
        with patch("olav.execution.backends.nornir_sandbox.InitNornir") as mock:
            nr_instance = MagicMock()

            host = MagicMock()
            host.name = "R1"
            host.platform = "cisco_ios"
            host.username = None
            host.password = None

            nr_instance.inventory.hosts = {"R1": host}
            nr_instance.filter.return_value = nr_instance

            mock.return_value = nr_instance
            yield mock, nr_instance

    @pytest.fixture
    def mock_memory(self):
        """Create mock OpenSearchMemory."""
        memory = MagicMock()
        memory.log_execution = AsyncMock()
        return memory

    @pytest.mark.asyncio
    async def test_netconf_connection_refused_suggests_cli_fallback(
        self, mock_nornir_with_devices, mock_memory
    ):
        """Test that NETCONF connection refused includes fallback hint."""
        _mock_init, _nr_instance = mock_nornir_with_devices

        with patch("olav.execution.backends.nornir_sandbox.OpenSearchMemory", return_value=mock_memory):
            from olav.execution.backends.nornir_sandbox import NornirSandbox
            sandbox = NornirSandbox(memory=mock_memory)

            # Simulate napalm_get raising ImportError (NETCONF not available)
            with patch.dict("sys.modules", {"nornir_napalm.plugins.tasks": None}):
                result = await sandbox.execute(
                    command="get-config /interfaces",
                    device="R1",
                    requires_approval=False,
                )

                # Should fail with helpful error
                assert result.success is False
                assert result.metadata.get("should_fallback_to_cli") is True or "NETCONF" in (result.error or "")
