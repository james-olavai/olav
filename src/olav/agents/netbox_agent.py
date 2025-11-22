"""NetBox SubAgent factory.

Provides NetBox SSOT (Single Source of Truth) management capabilities.
This agent handles device inventory, site management, and configuration sync.
"""
from deepagents import SubAgent

from olav.tools.netbox_tool import netbox_schema_search, netbox_api_call
from olav.tools.netbox_inventory_tool import (
    import_devices_from_csv,
    sync_device_configs,
    query_netbox_devices,
)
from olav.core.prompt_manager import prompt_manager


def create_netbox_subagent() -> SubAgent:
    """Create the NetBox SSOT management SubAgent.

    This agent is responsible for:
    - Querying and managing device inventory in NetBox
    - Importing devices from CSV files
    - Ensuring dependency objects exist (sites, roles, manufacturers)
    - Synchronizing configurations to Nornir/SuzieQ (init time)

    Returns:
        Configured SubAgent for NetBox operations.
        
    Tools:
        - netbox_schema_search: Discover NetBox API endpoints (read-only)
        - netbox_api_call: Execute direct API calls (GET/POST/PUT/PATCH/DELETE)
        - query_netbox_devices: Query devices with filters (read-only)
        - import_devices_from_csv: Batch import from CSV (write operation)
        - sync_device_configs: Regenerate config files (init only)
        
    HITL (Human-in-the-Loop) Approval:
        Write operations require human approval:
        - netbox_api_call: POST/PUT/PATCH/DELETE methods trigger interrupt
        - import_devices_from_csv: Always requires approval (batch write)
        - GET requests: No approval needed (read-only)
        
    Example workflow:
        User: "从 CSV 导入设备"
        → Agent calls import_devices_from_csv()
        → LangGraph interrupts with preview
        → Human approves/edits/rejects
        → If approved, executes import
        
    Note:
        Query operations (netbox_schema_search, query_netbox_devices) do not
        require approval as they are read-only.
    """
    netbox_prompt = prompt_manager.load_agent_prompt("netbox_agent")
    
    return SubAgent(
        name="netbox-manager",
        description="管理 NetBox 设备清单和 SSOT (Single Source of Truth)",
        system_prompt=netbox_prompt,
        tools=[
            netbox_schema_search,      # Discover API endpoints
            netbox_api_call,           # Direct API access (with HITL for writes)
            query_netbox_devices,      # Query devices with filters (read-only)
            import_devices_from_csv,   # Batch CSV import (with HITL)
            sync_device_configs,       # Config regeneration (init only)
        ],
        # 🔑 HITL 审批：所有写操作工具必须经过人工批准
        interrupt_on={
            "netbox_api_call": True,        # 所有 API 调用都审批（简化版）
            "import_devices_from_csv": True  # CSV 导入必须审批
        }
    )
