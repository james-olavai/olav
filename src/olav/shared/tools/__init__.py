"""
Shared tools package - Skill-Centric Architecture

All tool implementations are now in .olav/skills/shared/tools/
Bridge location: src/olav/shared/tools/ (symlinks)
"""

# Re-export all modules
from . import api_client  # noqa: F401
from . import data_export  # noqa: F401
from . import inspection_views  # noqa: F401
from . import network  # noqa: F401
from . import network_executor  # noqa: F401
from . import network_parser  # noqa: F401
from . import raw_importer  # noqa: F401
from . import report_formatter  # noqa: F401
from . import sync_tools  # noqa: F401

# Core exports - only import what explicitly exists
from .network_executor import (
    BatchExecutionRequest,
    CommandExecutionResult,
    NetworkExecutor,
    get_executor,
    get_nornir,
    reset_nornir,
)
from .data_export import format_and_export
from .report_formatter import (
    generate_professional_inspection_report,
    generate_network_operations_report,
)
from .inspection_views import create_inspection_views
from .sync_tools import sync_all
from .network import nornir_execute, list_devices, get_device_platform
from .raw_importer import import_sync_data

__all__ = [
    # Modules
    "api_client",
    "data_export",
    "inspection_views",
    "network",
    "network_executor",
    "network_parser",
    "raw_importer",
    "report_formatter",
    "sync_tools",
    # Key exports
    "format_and_export",
    "get_executor",
    "get_nornir",
    "reset_nornir",
    "NetworkExecutor",
    "BatchExecutionRequest",
    "CommandExecutionResult",
    "generate_professional_inspection_report",
    "generate_network_operations_report",
    "create_inspection_views",
    "sync_all",
    "nornir_execute",
    "list_devices",
    "get_device_platform",
    "import_sync_data",
]
