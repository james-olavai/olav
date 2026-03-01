"""
Schema Mapper - Unified Key-Value Mapping for Cross-Platform Data

This module provides a mapping table that translates platform-specific keys
to a unified schema, enabling consistent querying across different network
platforms (Cisco IOS, Juniper JunOS, Arista EOS, etc.).

Usage:
    from olav.core.schema_mapper import SchemaMapper

    mapper = SchemaMapper()
    unified_data = mapper.to_unified(platform="cisco_ios", data=cisco_data)
"""

import logging
from typing import Any

import duckdb

from olav.core.config import MAIN_DB_PATH

logger = logging.getLogger(__name__)


# Default mappings for common platform-specific keys
# These are loaded into the mapping_table on first run
DEFAULT_MAPPINGS = {
    # Cisco IOS -> Unified
    "cisco_ios": {
        "neighbor_id": "neighbor_router_id",
        "neighbor_address": "neighbor_ip_address",
        "local_interface": "local_port",
        "device_id": "device_identifier",
        "holding_time": "neighbor_hold_time",
        "capabilities": "neighbor_capabilities",
        "platform": "neighbor_platform",
        "port_id": "neighbor_port",
    },
    # Juniper JunOS -> Unified
    "juniper_junos": {
        "peer_id": "neighbor_router_id",
        "peer_address": "neighbor_ip_address",
        "interface_name": "local_port",
        "peer_device_id": "device_identifier",
        "dead_after": "neighbor_hold_time",
        "peer_state": "neighbor_state",
    },
    # Arista EOS -> Unified
    "arista_eos": {
        "peer": "neighbor_router_id",
        "peer_ip": "neighbor_ip_address",
        "interface": "local_port",
        "state": "neighbor_state",
    },
    # Generic/Common mappings
    "_generic": {
        "ip_address": "ip_addr",
        "mac_address": "mac_addr",
        "interface": "port",
        "status": "state",
        "hostname": "device_name",
        "uptime": "device_uptime",
    },
}


class SchemaMapper:
    """Maps platform-specific keys to unified schema."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(MAIN_DB_PATH)

    def load_default_mappings(self) -> int:
        """DEPRECATED: Default mappings are now handled by sync_schemas.py."""
        return 0

    def to_unified(self, platform: str, data: dict[str, Any]) -> dict[str, Any]:
        """Transform platform-specific data to unified schema.

        Args:
            platform: Network platform (e.g., "cisco_ios")
            data: Dictionary with platform-specific keys

        Returns:
            Dictionary with unified keys
        """
        try:
            with duckdb.connect(self.db_path, read_only=True) as conn:
                # Get mappings for this platform
                rows = conn.execute(
                    """
                    SELECT platform_key, unified_key
                    FROM mapping_table
                    WHERE platform = ? OR platform = '_generic'
                """,
                    [platform],
                ).fetchall()

                mapping = {row[0]: row[1] for row in rows}

        except Exception as e:
            logger.debug(f"Failed to query mapping_table: {e}")
            # Fallback to default mappings
            platform_mappings = DEFAULT_MAPPINGS.get(platform, {})
            generic_mappings = DEFAULT_MAPPINGS.get("_generic", {})
            mapping = {**generic_mappings, **platform_mappings}

        # Transform data
        unified_data = {}
        for key, value in data.items():
            unified_key = mapping.get(key, key)  # Keep original if no mapping
            unified_data[unified_key] = value

        return unified_data

    def add_mapping(
        self, platform: str, platform_key: str, unified_key: str, description: str = ""
    ) -> bool:
        """Add a custom mapping.

        Args:
            platform: Network platform
            platform_key: Original key name
            unified_key: Target unified key name
            description: Optional description

        Returns:
            True if successful
        """
        try:
            with duckdb.connect(self.db_path, read_only=False) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO mapping_table (platform, platform_key, unified_key, description)
                    VALUES (?, ?, ?, ?)
                """,
                    [platform, platform_key, unified_key, description],
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to add mapping: {e}")
            return False

    def get_mappings(self, platform: str | None = None) -> list[dict]:
        """Get all mappings, optionally filtered by platform.

        Args:
            platform: Optional platform filter

        Returns:
            List of mapping dictionaries
        """
        try:
            with duckdb.connect(self.db_path, read_only=True) as conn:
                if platform:
                    rows = conn.execute(
                        """
                        SELECT platform, platform_key, unified_key, description
                        FROM mapping_table
                        WHERE platform = ? OR platform = '_generic'
                        ORDER BY platform, platform_key
                    """,
                        [platform],
                    ).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT platform, platform_key, unified_key, description
                        FROM mapping_table
                        ORDER BY platform, platform_key
                    """).fetchall()

                return [
                    {
                        "platform": row[0],
                        "platform_key": row[1],
                        "unified_key": row[2],
                        "description": row[3],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get mappings: {e}")
            return []


# Singleton instance
_mapper: SchemaMapper | None = None


def get_mapper() -> SchemaMapper:
    """Get the singleton SchemaMapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = SchemaMapper()
        # Load defaults on first use
        _mapper.load_default_mappings()
    return _mapper
