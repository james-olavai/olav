"""Command Registry - Unified Command and Template Management.

This module provides a centralized registry for network commands and their
associated TextFSM templates. It replaces the database-backed capabilities table
with a more maintainable file-based approach.

Roadmap: Task 1.1 - Create Command Registry (P3 Optional Optimization)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Command Registry
# =============================================================================


class CommandRegistry:
    """Centralized registry for network commands and TextFSM templates.

    This class provides:
    - Priority-based template lookup (custom > ntc-templates)
    - TextFSM parsing execution
    - Platform detection and command validation

    Attributes:
        custom_index: Path to custom template directory
        ntc_available: Whether ntc-templates is available
    """

    def __init__(self, custom_dir: Path | None = None) -> None:
        """Initialize the Command Registry.

        Args:
            custom_dir: Path to custom TextFSM template directory
        """
        from config.paths import TEXTFSM_TEMPLATES_DIR

        if custom_dir is None:
            # v0.10.1: Use skill-level config path
            custom_dir = TEXTFSM_TEMPLATES_DIR

        self.custom_index = custom_dir
        self.ntc_template_dir: Path | None = None
        self.ntc_available = self._check_ntc_available()
        self._custom_cache: dict[str, dict[str, Path]] = {}
        self._ntc_cache: dict[str, dict[str, Path]] = {}  # platform -> {command: path}

        # Load custom templates if index exists
        if (self.custom_index / "index").exists():
            self._load_custom_index()

        # Load NTC templates if available
        if self.ntc_available and self.ntc_template_dir:
            self._load_ntc_index()

        logger.info(
            f"CommandRegistry initialized (custom: {self.custom_index}, ntc: {self.ntc_available})"
        )

    def _check_ntc_available(self) -> bool:
        """Check if ntc-templates package is available.

        Returns:
            True if ntc-templates can be imported
        """
        try:
            from ntc_templates import parse

            # ntc-templates stores its template path in the internal parse module
            template_dir = Path(parse.__file__).parent / "templates"
            if template_dir.exists():
                self.ntc_template_dir = template_dir
                return True
            return False
        except ImportError:
            return False

    def _load_custom_index(self) -> None:
        """Load custom template index file.

        The index file maps platform-command pairs to template files.
        Format: platform,command,template_file
        """
        index_path = self.custom_index / "index"

        try:
            with open(index_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = line.split(",")
                    if len(parts) >= 3:
                        platform = parts[0].strip()
                        command = parts[1].strip()
                        template_file = parts[2].strip()

                        if platform not in self._custom_cache:
                            self._custom_cache[platform] = {}

                        self._custom_cache[platform][command] = self.custom_index / template_file

            logger.info(f"Loaded {len(self._custom_cache)} platforms from custom index")

        except Exception as e:
            logger.warning(f"Failed to load custom index: {e}")

    def _normalize_ntc_command(self, raw: str) -> str:
        r"""Generic normalization of NTC regex commands.

        Handles:
        - sh[[ow]] -> show
        - (?:all\s+)? -> (removed)
        - \s+ -> space
        - ^ and $ -> removed
        """

        # 1. Remove brackets sh[[ow]] -> show
        cmd = raw.replace("[[", "").replace("]]", "")

        # 2. Remove optional non-capturing groups: (?:all\s+)? -> ""
        cmd = re.sub(r"\(\?:\s*([^)]+)\)\?", r"", cmd)

        # 3. Handle non-optional non-capturing groups: (?:all\s+) -> all
        cmd = re.sub(r"\(\?:\s*([^)]+)\)", r"\1", cmd)

        # 4. Handle other optional parts like (\s+detail)? -> ""
        cmd = re.sub(r"\([^)]+\)\?", r"", cmd)

        # 5. Clean up special characters and whitespace
        cmd = cmd.replace("\\s+", " ")
        cmd = cmd.replace("^", "").replace("$", "")
        cmd = " ".join(cmd.split())

        return cmd.lower()

    def _load_ntc_index(self) -> None:
        """Load ntc-templates index file.

        The index file maps platform-command pairs to template files.
        Format: template_name, platform, command_regex
        Note: NTC uses a slightly different format than our custom index.
        """
        if not self.ntc_template_dir:
            return

        index_path = self.ntc_template_dir / "index"
        if not index_path.exists():
            return

        try:
            with open(index_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("Template"):  # Skip header
                        continue

                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        template_file = parts[0]
                        platform = parts[2]
                        command_raw = parts[3]

                        # Normalize NTC regex to full-form readable command
                        command = self._normalize_ntc_command(command_raw)

                        if platform not in self._ntc_cache:
                            self._ntc_cache[platform] = {}

                        self._ntc_cache[platform][command] = self.ntc_template_dir / template_file

            logger.info(f"Loaded {len(self._ntc_cache)} platforms from NTC index")

        except Exception as e:
            logger.warning(f"Failed to load NTC index from {index_path}: {e}")

    def get_template(
        self,
        platform: str,
        command: str,
    ) -> Path | None:
        """Get TextFSM template for a platform/command pair.

        Priority order (actual execution):
        1. User custom templates (.olav/templates)
        2. ntc-templates pip package (if available)
        3. Not found → returns None

        Args:
            platform: Device platform (e.g., "cisco_ios", "huawei_vrp")
            command: Command name (e.g., "show version", "show ip bgp summary")

        Returns:
            Path to template file, or None if not found
        """
        # Normalize command name for internal lookup
        # e.g., "show ip interface brief" -> "show_ip_interface_brief"
        normalized_command = command.strip().lower().replace(" ", "_")

        # 1. Check custom templates first (normalized)
        if platform in self._custom_cache:
            if normalized_command in self._custom_cache[platform]:
                return self._custom_cache[platform][normalized_command]

        # 2. Fall back to ntc-templates (normalized)
        if platform in self._ntc_cache:
            if normalized_command in self._ntc_cache[platform]:
                return self._ntc_cache[platform][normalized_command]

            # 3. Flexible lookup: check if any registered command's normalized version
            # matches the input's normalized version
            for registered_cmd, path in self._ntc_cache[platform].items():
                if registered_cmd.lower().replace(" ", "_") == normalized_command:
                    return path

        return None

    def parse(
        self,
        platform: str,
        command: str,
        output: str,
    ) -> list[dict[str, Any]] | None:
        """Parse command output using TextFSM.

        Args:
            platform: Device platform
            command: Command name
            output: Raw command output text

        Returns:
            Parsed data as list of dictionaries, or None if parsing fails
        """
        template_path = self.get_template(platform, command)

        if not template_path:
            logger.warning(f"No template found for {platform} {command}")
            return None

        try:
            import textfsm

            with open(template_path, encoding="utf-8") as f:
                template = textfsm.TextFSM(f)

            # Parse output
            fsm_results = template.ParseText(output)

            # Convert to list of dicts
            results = [dict(zip(template.header, row, strict=True)) for row in fsm_results]

            logger.info(f"Parsed {len(results)} records from {platform} {command}")

            return results

        except Exception as e:
            logger.error(f"TextFSM parsing failed for {platform} {command}: {e}")
            return None

    def list_commands(
        self,
        platform: str | None = None,
    ) -> dict[str, list[str]]:
        """List available commands by platform.

        Args:
            platform: Filter by platform (None for all)

        Returns:
            Dictionary mapping platform to list of commands
        """
        result = {}

        # Add custom commands
        for plt, cmds in self._custom_cache.items():
            if platform is None or plt == platform:
                result[plt] = list(cmds.keys())

        # Add ntc-templates commands
        for plt, cmds in self._ntc_cache.items():
            if platform is None or plt == platform:
                if plt not in result:
                    result[plt] = []
                for cmd in cmds:
                    if cmd not in result[plt]:
                        result[plt].append(cmd)

        return result

    def get_whitelisted_commands(self, platform: str) -> list[str]:
        """Get commands from whitelist for a specific platform.

        Args:
            platform: Device platform

        Returns:
            List of whitelisted command strings
        """
        from config.settings import settings

        whitelist_path = Path(settings.sync.whitelist_file)
        if not whitelist_path.is_absolute():
            # Assume relative to project root
            from config.paths import PROJECT_ROOT

            whitelist_path = PROJECT_ROOT / whitelist_path

        if not whitelist_path.exists():
            logger.warning(f"Whitelist file {whitelist_path} not found")
            return []

        try:
            import yaml

            with open(whitelist_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or not isinstance(data, dict):
                return []

            return list(data.get(platform, []))

        except Exception as e:
            logger.error(f"Failed to load whitelist: {e}")
            return []

    def validate_command(
        self,
        platform: str,
        command: str,
    ) -> bool:
        """Check if a command is valid for a platform.

        Args:
            platform: Device platform
            command: Command to validate

        Returns:
            True if command/template exists
        """
        return self.get_template(platform, command) is not None


# =============================================================================
# Singleton Instance
# =============================================================================

_registry: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    """Get the global Command Registry instance.

    Returns:
        Command Registry singleton
    """
    global _registry

    if _registry is None:
        _registry = CommandRegistry()

    return _registry


def reload_command_registry() -> None:
    """Reload the command registry (useful after saving new templates).
    
    Forces re-initialization of template indices from disk.
    Call this after adding new templates programmatically.
    """
    global _registry
    logger.info("🔄 Reloading command registry...")
    _registry = CommandRegistry()
    logger.info("✓ Command registry reloaded")


# =============================================================================
# Convenience Functions
# =============================================================================


def parse_command_output(
    platform: str,
    command: str,
    output: str,
) -> list[dict[str, Any]] | None:
    """Convenience function to parse command output.

    Args:
        platform: Device platform
        command: Command name
        output: Raw command output

    Returns:
        Parsed data or None
    """
    registry = get_command_registry()
    return registry.parse(platform, command, output)


def get_template_path(
    platform: str,
    command: str,
) -> Path | None:
    """Convenience function to get template path.

    Args:
        platform: Device platform
        command: Command name

    Returns:
        Path to template or None
    """
    registry = get_command_registry()
    return registry.get_template(platform, command)
