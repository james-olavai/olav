"""Command Registry for Unified Command Discovery.

This module provides a unified interface for discovering available
network commands and their capabilities, replacing hardcoded logic.

Architecture (v0.9.10):
- Queries _schema_catalog to discover available commands
- Provides command metadata: platform, parsing_status, field info
- Supports fuzzy search for command discovery
- Used by AnalysisAgent and Router for command planning

Roadmap: Task 9.2 - Command Library Integration
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from config.paths import NETWORK_DB_PATH

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class CommandMetadata:
    """Metadata about a network command."""

    command_name: str  # Normalized command (e.g., "show ip bgp summary")
    display_name: str  # User-friendly display name
    platforms: list[str]  # Device platforms supporting this command
    devices: list[str]  # Specific devices with this command data
    record_count: int  # Number of records in database
    field_count: int  # Number of extracted fields
    sample_fields: list[str]  # Sample field names (top 5)
    has_inspection_rules: bool  # Whether plan_type is configured

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "command_name": self.command_name,
            "display_name": self.display_name,
            "platforms": self.platforms,
            "devices": self.devices,
            "record_count": self.record_count,
            "field_count": self.field_count,
            "sample_fields": self.sample_fields,
            "has_inspection_rules": self.has_inspection_rules,
        }


# =============================================================================
# Command Registry
# =============================================================================


class CommandRegistry:
    """Registry for discovering and querying available network commands.

    This replaces hardcoded command lists (smart_query) with a
    dynamic, data-driven approach using the _schema_catalog table.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize Command Registry.

        Args:
            db_path: Path to DuckDB database (uses default if None)
        """
        self.db_path = db_path or NETWORK_DB_PATH
        self._cache: dict[str, CommandMetadata] | None = None

    def _ensure_connection(self) -> duckdb.DuckDBPyConnection:
        """Create DuckDB connection.

        Returns:
            DuckDB connection
        """
        return duckdb.connect(str(self.db_path))

    def refresh(self) -> None:
        """Refresh command cache from database.

        Queries _schema_catalog to rebuild the command registry.
        """
        conn = self._ensure_connection()
        try:
            # Query _schema_catalog for all commands
            result = conn.execute("""
                WITH expanded_devices AS (
                    SELECT command_name, field_name, record_count, plan_type,
                           UNNEST(devices) as device
                    FROM _schema_catalog
                )
                SELECT
                    command_name,
                    COUNT(DISTINCT device) as device_count,
                    SUM(record_count) as total_records,
                    COUNT(DISTINCT field_name) as field_count,
                    COUNT(DISTINCT CASE WHEN plan_type IS NOT NULL THEN 1 END) > 0 as has_rules,
                    ARRAY_AGG(DISTINCT device) as devices_array,
                    GROUP_CONCAT(DISTINCT field_name, ',') as fields
                FROM expanded_devices
                GROUP BY command_name
                ORDER BY command_name
            """).fetchall()

            self._cache = {}
            for row in result:
                (
                    command_name,
                    device_count,
                    total_records,
                    field_count,
                    has_rules,
                    devices_array,
                    fields_str,
                ) = row

                # Parse device list
                devices = devices_array if devices_array else []

                # Parse field list (take first 5)
                all_fields = fields_str.split(",") if fields_str else []
                sample_fields = all_fields[:5]

                # Create display name (replace underscores with spaces)
                display_name = command_name.replace("_", " ").title()

                self._cache[command_name] = CommandMetadata(
                    command_name=command_name,
                    display_name=display_name,
                    platforms=[],  # TODO: Extract from device metadata
                    devices=devices,
                    record_count=total_records or 0,
                    field_count=field_count or 0,
                    sample_fields=sample_fields,
                    has_inspection_rules=bool(has_rules),
                )

            logger.info(f"Refreshed command registry: {len(self._cache)} commands")

        finally:
            conn.close()

    def _ensure_cache(self) -> None:
        """Ensure cache is populated."""
        if self._cache is None:
            self.refresh()

    def get_all_commands(self) -> dict[str, CommandMetadata]:
        """Get all available commands.

        Returns:
            Dictionary mapping command name to metadata
        """
        self._ensure_cache()
        return self._cache.copy()

    def get_command(self, command_name: str) -> CommandMetadata | None:
        """Get metadata for a specific command.

        Args:
            command_name: Command to look up (supports fuzzy matching)

        Returns:
            CommandMetadata or None if not found
        """
        self._ensure_cache()

        # Exact match
        if self._cache and command_name in self._cache:
            return self._cache[command_name]

        # Fuzzy match (case-insensitive)
        command_lower = command_name.lower()
        for cmd, meta in self._cache.items():
            if cmd.lower() == command_lower:
                return meta

        # Partial match (contains)
        for cmd, meta in self._cache.items():
            if command_lower in cmd.lower():
                return meta

        return None

    def search_commands(
        self,
        query: str,
        limit: int = 10,
    ) -> list[CommandMetadata]:
        """Search for commands by keyword.

        Args:
            query: Search query (e.g., "bgp", "interface", "route")
            limit: Maximum results to return

        Returns:
            List of matching CommandMetadata
        """
        self._ensure_cache()
        query_lower = query.lower()

        matches = []
        for cmd, meta in self._cache.items():
            # Search in command name and display name
            if query_lower in cmd.lower() or query_lower in meta.display_name.lower():
                matches.append(meta)
                if len(matches) >= limit:
                    break

        return matches

    def get_commands_with_inspection_rules(self) -> list[CommandMetadata]:
        """Get commands that have inspection rules configured.

        Returns:
            List of CommandMetadata with plan_type configured
        """
        self._ensure_cache()

        return [meta for meta in self._cache.values() if meta.has_inspection_rules]

    def get_commands_for_device(self, device: str) -> list[CommandMetadata]:
        """Get commands available for a specific device.

        Args:
            device: Device name

        Returns:
            List of CommandMetadata available for this device
        """
        self._ensure_cache()

        return [meta for meta in self._cache.values() if device in meta.devices]

    def get_field_info(self, command_name: str, field_name: str) -> dict[str, Any] | None:
        """Get detailed information about a specific field.

        Args:
            command_name: Command name
            field_name: Field name

        Returns:
            Field metadata dictionary or None
        """
        conn = self._ensure_connection()
        try:
            result = conn.execute(
                """
                SELECT
                    field_name,
                    field_type,
                    sample_values,
                    plan_type,
                    threshold,
                    keyword
                FROM _schema_catalog
                WHERE command_name = ? AND field_name = ?
            """,
                [command_name, field_name],
            ).fetchone()

            if not result:
                return None

            (
                field,
                ftype,
                samples,
                plan_type,
                threshold,
                keyword,
            ) = result

            return {
                "field_name": field,
                "field_type": ftype,
                "sample_values": samples,
                "plan_type": plan_type,
                "threshold": threshold,
                "keyword": keyword,
            }

        finally:
            conn.close()

    def format_command_list(self, commands: list[CommandMetadata] | None = None) -> str:
        """Format command list for display.

        Args:
            commands: List of commands (uses all if None)

        Returns:
            Formatted string for CLI output
        """
        self._ensure_cache()
        if self._cache is None:
            return "No commands available (registry not initialized)."

        if commands is None:
            commands = list(self._cache.values())

        if not commands:
            return "No commands found."

        lines = [
            "Available Commands:",
            "",
            f"{'Command':<40} {'Records':<10} {'Fields':<8} {'Inspection'}",
            "-" * 75,
        ]

        for meta in sorted(commands, key=lambda m: m.command_name):
            inspection = "✅" if meta.has_inspection_rules else "❌"
            lines.append(
                f"{meta.display_name:<40} {meta.record_count:<10} "
                f"{meta.field_count:<8} {inspection}"
            )

        return "\n".join(lines)


# =============================================================================
# Singleton Instance
# =============================================================================

# Global registry instance
_registry_instance: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    """Get global CommandRegistry instance (singleton).

    Returns:
        CommandRegistry instance
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = CommandRegistry()
        _registry_instance.refresh()
    return _registry_instance


def refresh_command_registry() -> None:
    """Refresh the global command registry."""
    global _registry_instance
    if _registry_instance is not None:
        _registry_instance.refresh()
