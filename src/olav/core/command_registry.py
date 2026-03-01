#!/usr/bin/env python3
"""
Command Registry - Hot-reload mechanism for templates and commands

Provides singleton registry for TextFSM templates and command definitions.
Supports hot-reload without restarting the process.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CommandRegistry:
    """Global registry for commands and templates.

    Singleton pattern for managing:
    - TextFSM templates
    - Whitelisted commands
    - Blacklisted commands

    Supports hot-reload via reload() method.
    """

    _instance = None
    _templates: dict[str, Path] = {}
    _whitelist: set[str] = set()
    _blacklist: list[str] = []
    _template_index: dict[str, dict] = {}
    _commands_by_platform: dict[str, list[str]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_all()
        return cls._instance

    def _load_all(self) -> None:
        """Load all registry data."""
        self._load_templates()
        self._load_whitelist()
        self._load_blacklist()
        self._load_platform_commands()

    def _load_templates(self) -> None:
        """Load TextFSM templates from .olav/templates/."""
        self._templates.clear()
        self._template_index.clear()

        # Priority 1: Custom config directory
        custom_config_dir = Path(".olav/config/textfsm")
        if custom_config_dir.exists():
            self._scan_templates(custom_config_dir, priority=1)

        # Priority 2: Command learner custom directory
        custom_dir = Path(".olav/templates/custom")
        if custom_dir.exists():
            self._scan_templates(custom_dir, priority=2)

        # Priority 3: Default templates directory
        templates_dir = Path(".olav/templates")
        if templates_dir.exists():
            self._scan_templates(templates_dir, priority=3)

        # Priority 4: NTC templates (if installed)
        self._load_ntc_templates()

        logger.info(f"Loaded {len(self._templates)} TextFSM templates")

    def _load_ntc_templates(self) -> None:
        """Load templates from ntc-templates package if available."""
        try:
            import ntc_templates

            ntc_dir = Path(ntc_templates.__file__).parent / "ntc_templates"
            if ntc_dir.exists():
                self._scan_templates(ntc_dir, priority=4)
                logger.info(f"Loaded {len(self._templates)} total templates including NTC")
        except ImportError:
            logger.debug("ntc-templates not installed")
        except Exception as e:
            logger.warning(f"Failed to load NTC templates: {e}")

    def _scan_templates(self, directory: Path, priority: int) -> None:
        """Scan directory for TextFSM templates."""
        for template_path in directory.glob("*.textfsm"):
            template_name = template_path.name
            # Only add if not already registered (higher priority wins)
            if template_name not in self._templates:
                self._templates[template_name] = template_path
                self._template_index[template_name] = {
                    "path": str(template_path),
                    "priority": priority,
                    "size": template_path.stat().st_size,
                }

    def _load_whitelist(self) -> None:
        """Load whitelisted commands from config."""
        self._whitelist.clear()

        whitelist_path = Path(".olav/config/allowed_commands.json")
        if whitelist_path.exists():
            try:
                import json

                data = json.loads(whitelist_path.read_text())
                commands = data.get("commands", [])
                self._whitelist.update(commands)
                logger.info(f"Loaded {len(self._whitelist)} whitelisted commands")
            except Exception as e:
                logger.error(f"Failed to load whitelist: {e}")

    def _load_blacklist(self) -> None:
        """Load blacklisted commands from config."""
        self._blacklist.clear()

        blacklist_path = Path(".olav/config/blacklisted_commands.json")
        if blacklist_path.exists():
            try:
                import json

                data = json.loads(blacklist_path.read_text())
                patterns = data.get("patterns", [])
                self._blacklist.extend(patterns)
                logger.info(f"Loaded {len(self._blacklist)} blacklisted patterns")
            except Exception as e:
                logger.error(f"Failed to load blacklist: {e}")

    def _load_platform_commands(self) -> None:
        """Load commands grouped by platform from templates."""
        self._commands_by_platform.clear()

        # Map platform names to template file patterns
        # NTC templates use format: {platform}_{command}.textfsm
        platform_commands: dict[str, set[str]] = {}

        for template_name in self._templates.keys():
            # Parse platform from filename (e.g., "cisco_ios_show_version.textfsm")
            parts = template_name.replace(".textfsm", "").split("_")
            if len(parts) >= 3:
                # First two parts form the platform (e.g., "cisco_ios", "juniper_junos")
                platform = "_".join(parts[:2])
                command = "_".join(parts[2:])

                if platform not in platform_commands:
                    platform_commands[platform] = set()
                platform_commands[platform].add(command)

        # Convert sets to sorted lists
        for platform, commands in platform_commands.items():
            self._commands_by_platform[platform] = sorted(list(commands))

        logger.info(f"Loaded commands for {len(self._commands_by_platform)} platforms")

    @classmethod
    def get_platform_commands(cls, platform: str) -> list[str]:
        """Get commands for a specific platform by merging local and NTC templates.

        This function:
        1. Gets platform-specific commands from NTC templates
        2. Gets generic commands that work across platforms
        3. Merges them, removing duplicates

        Args:
            platform: Network platform (e.g., "cisco_ios", "juniper_junos", "arista_eos")

        Returns:
            List of command names suitable for the platform
        """
        if cls._instance is None:
            cls._instance = cls()

        # Check with underscore variations (cisco_ios vs cisco-ios)
        platform_variants = [
            platform,
            platform.replace("_", "-"),
            platform.replace("-", "_"),
        ]

        all_cmds = set()
        for variant in platform_variants:
            if variant in cls._instance._commands_by_platform:
                all_cmds.update(cls._instance._commands_by_platform[variant])

        # Add generic commands that work across platforms
        generic_commands = [
            "show version",
            "show running-config",
            "show interfaces",
            "show ip interface brief",
            "show clock",
        ]

        # Check if these generic commands exist in any form
        for cmd in generic_commands:
            cmd_underscore = cmd.replace(" ", "_")
            for template_name in cls._instance._templates:
                template_cmd = template_name.replace(".textfsm", "")
                if cmd_underscore in template_cmd or cmd in template_cmd:
                    all_cmds.add(cmd)

        return sorted(list(all_cmds))

    @classmethod
    def reload(cls) -> dict[str, Any]:
        """Hot-reload all command definitions.

        Reloads:
        1. TextFSM templates (.olav/templates/*)
        2. Command whitelist (.olav/config/allowed_commands.json)
        3. Command blacklist (.olav/config/blacklisted_commands.json)

        Returns:
            dict: {
                "reloaded": {
                    "templates": int,
                    "whitelisted_commands": int,
                    "blacklisted_patterns": int
                },
                "new_templates": list[str],
                "errors": list[str]
            }
        """
        if cls._instance is None:
            cls._instance = cls()

        # Track changes
        old_templates = set(cls._instance._templates.keys())

        # Reload all
        try:
            cls._instance._load_all()

            # Detect new templates
            new_templates = list(set(cls._instance._templates.keys()) - old_templates)

            logger.info(
                f"✅ Reloaded: {len(cls._instance._templates)} templates, "
                f"{len(cls._instance._whitelist)} commands, "
                f"{len(cls._instance._blacklist)} blacklist patterns"
            )

            return {
                "reloaded": {
                    "templates": len(cls._instance._templates),
                    "whitelisted_commands": len(cls._instance._whitelist),
                    "blacklisted_patterns": len(cls._instance._blacklist),
                },
                "new_templates": new_templates,
                "errors": [],
            }

        except Exception as e:
            logger.error(f"Failed to reload: {e}")
            return {
                "reloaded": {"templates": 0, "whitelisted_commands": 0, "blacklisted_patterns": 0},
                "new_templates": [],
                "errors": [str(e)],
            }

    @classmethod
    def get_template_path(cls, template_name: str) -> Path | None:
        """Get path for a template by name."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance._templates.get(template_name)

    @classmethod
    def is_command_allowed(cls, command: str) -> bool:
        """Check if command is whitelisted."""
        if cls._instance is None:
            cls._instance = cls()
        return command in cls._instance._whitelist

    @classmethod
    def is_command_blacklisted(cls, command: str) -> bool:
        """Check if command matches blacklist pattern."""
        if cls._instance is None:
            cls._instance = cls()

        import re

        for pattern in cls._instance._blacklist:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    @classmethod
    def get_all_templates(cls) -> dict[str, dict]:
        """Get all registered templates."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance._template_index


# Create singleton instance on module import
_registry = CommandRegistry()
