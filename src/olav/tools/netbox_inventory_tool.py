"""NetBox inventory management tools.

Wraps InventoryManager functionality as LangChain tools for agent use.
"""
import logging
from typing import Dict, Any
from langchain_core.tools import tool

from olav.core.inventory_manager import InventoryManager

logger = logging.getLogger(__name__)


@tool
async def import_devices_from_csv(csv_content: str) -> Dict[str, Any]:
    """Import devices from CSV content into NetBox.
    
    This tool creates devices along with their dependencies (sites, roles, types).
    Expected CSV format with headers:
    - name (required): Device hostname
    - device_role (required): Device role (e.g., "router", "switch")
    - device_type (required): Device model (e.g., "IOSv", "vEOS")
    - site (required): Site name
    - platform (optional): Platform driver name (e.g., "cisco_ios", "arista_eos")
    - status (optional): Device status (default: "active")
    - ip_address (optional): Management IP address with CIDR (e.g., "192.168.1.1/24")
    
    Args:
        csv_content: CSV content as string with headers
        
    Returns:
        Dictionary with success count, failed count, and error messages:
        {
            "success": 5,
            "failed": 2,
            "errors": ["Device R1: Connection failed", ...]
        }
        
    Example CSV:
        name,device_role,device_type,site,platform,status,ip_address
        R1,router,IOSv,DC1,cisco_ios,active,192.168.1.1/24
        SW1,switch,vEOS,DC1,arista_eos,active,192.168.1.2/24
    """
    try:
        manager = InventoryManager()
        result = manager.import_from_csv(csv_content)
        
        logger.info(f"CSV import completed: {result['success']} succeeded, {result['failed']} failed")
        if result['errors']:
            logger.warning(f"Import errors: {result['errors']}")
        
        return result
    except Exception as e:
        logger.error(f"CSV import failed: {e}")
        return {
            "success": 0,
            "failed": 0,
            "errors": [f"CSV parsing error: {str(e)}"]
        }


@tool
async def sync_device_configs(devices: list[str] | None = None) -> Dict[str, Any]:
    """Synchronize device configurations from NetBox to generated config files.
    
    This tool generates Nornir and SuzieQ configuration files based on current
    NetBox inventory, ensuring all tools use the same SSOT.
    
    Args:
        devices: Optional list of device names to sync. If None, syncs all devices
                tagged with "olav-managed" in NetBox.
        
    Returns:
        Dictionary with sync status:
        {
            "nornir_config": "path/to/nornir_config.yml",
            "suzieq_config": "path/to/suzieq_config.yml",
            "device_count": 10,
            "status": "success"
        }
        
    Note:
        This is primarily used during initialization. Runtime operations
        directly query NetBox API via NBInventory plugin.
    """
    # TODO: Implement config sync logic
    # This would be similar to olav-init container's generate_suzieq_config.py
    # For now, return placeholder
    logger.warning("sync_device_configs not yet implemented - configs are generated at init time")
    return {
        "status": "not_implemented",
        "message": "Config sync is handled by olav-init container. Use docker-compose --profile init up olav-init"
    }


@tool
async def query_netbox_devices(
    site: str | None = None,
    role: str | None = None,
    platform: str | None = None,
    tag: str | None = None,
) -> Dict[str, Any]:
    """Query NetBox for devices matching filters.
    
    Retrieves device information from NetBox inventory based on filter criteria.
    This is useful for understanding current inventory before making changes.
    
    Args:
        site: Filter by site name (e.g., "DC1", "Branch-Office")
        role: Filter by device role (e.g., "router", "switch", "firewall")
        platform: Filter by platform (e.g., "cisco_ios", "juniper_junos")
        tag: Filter by tag (default uses "olav-managed" if not specified)
        
    Returns:
        Dictionary with device list and metadata:
        {
            "count": 5,
            "devices": [
                {
                    "name": "R1",
                    "site": "DC1",
                    "role": "router",
                    "platform": "cisco_ios",
                    "status": "active",
                    "primary_ip": "192.168.1.1/24"
                },
                ...
            ]
        }
    """
    from olav.tools.netbox_tool import netbox_api_call
    
    # Build query parameters
    params = {}
    if site:
        params["site"] = site
    if role:
        params["role"] = role
    if platform:
        params["platform"] = platform
    if tag:
        params["tag"] = tag
    else:
        params["tag"] = "olav-managed"  # Default filter
    
    try:
        response = netbox_api_call("/dcim/devices/", "GET", params=params)
        
        if response.get("status") == "error":
            return {
                "count": 0,
                "devices": [],
                "error": response.get("message")
            }
        
        # Simplify device data for agent consumption
        devices = []
        for device in response.get("results", []):
            devices.append({
                "name": device.get("name"),
                "site": device.get("site", {}).get("name"),
                "role": device.get("role", {}).get("name"),
                "platform": device.get("platform", {}).get("name"),
                "status": device.get("status", {}).get("value"),
                "primary_ip": device.get("primary_ip4", {}).get("address") if device.get("primary_ip4") else None,
            })
        
        return {
            "count": len(devices),
            "devices": devices
        }
        
    except Exception as e:
        logger.error(f"NetBox device query failed: {e}")
        return {
            "count": 0,
            "devices": [],
            "error": str(e)
        }
