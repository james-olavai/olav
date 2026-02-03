"""Mock device infrastructure for testing without real network devices."""

from unittest.mock import MagicMock, patch
from typing import Any


class MockDeviceInventory:
    """Simulated device inventory for testing."""

    @staticmethod
    def create_mock_devices():
        """Create mock device inventory."""
        return {
            "R1": {
                "hostname": "R1",
                "ip": "10.1.12.1",
                "platform": "cisco_ios",
                "status": "reachable",
            },
            "R2": {
                "hostname": "R2",
                "ip": "10.1.23.2",
                "platform": "cisco_ios",
                "status": "reachable",
            },
        }

    @staticmethod
    def mock_command_output(device: str, command: str) -> str | None:
        """Return simulated command output for testing."""
        mock_outputs = {
            "show ip arp": """
Protocol  Address          Age (min)  Hardware Addr   Type   Interface
Internet  10.1.12.1             -   aaaa.bbbb.cccc  ARPA  GigabitEthernet1
Internet  10.1.12.2             2   dddd.eeee.ffff  ARPA  GigabitEthernet1
Internet  2.2.2.2               5   aabb.ccdd.eeff  ARPA  GigabitEthernet2
            """,
            "show interfaces description": """
Interface                      Status         Protocol Description
Gi1                            up             up       Uplink to Core
Gi2                            up             up       Uplink to R2
Lo0                            up             up       Loopback
            """,
            "show version": """
Cisco IOS Software, Linux Software...
ROM: System Bootstrap, Version 12.4
R1 uptime is 1 week
            """,
        }

        for cmd, output in mock_outputs.items():
            if cmd in command.lower():
                return output
        return None


@pytest.fixture
def mock_network_executor():
    """Mock network executor for testing without real devices."""
    with patch("olav.tools.network_executor.get_nornir") as mock_nornir:
        mock_nr = MagicMock()
        mock_nr.inventory.hosts = MockDeviceInventory.create_mock_devices()

        def mock_run(task, **kwargs):
            # Simulate task execution
            device = kwargs.get("device")
            command = getattr(task, "name", str(task))

            output = MockDeviceInventory.mock_command_output(device, command)

            # Return mock result
            from nornir.core.task import Result
            return Result(
                host=mock_nr.inventory.hosts.get(device),
                result=output or f"Mock output for {command}",
                changed=True,
            )

        mock_nornir.run.side_effect = mock_run
        mock_nornir.__enter__ = MagicMock(return_value=mock_nornir)
        mock_nornir.__exit__ = MagicMock(return_value=False)

        mock_nornir.return_value = mock_nornir
        yield mock_nornir
