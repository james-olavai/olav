"""Command Validator - Flexible command validation with multiple modes.

This module provides flexible command validation supporting:
- Blacklist mode: Allow all show/display commands, only block dangerous ones
- Whitelist mode: Only allow predefined commands (strict but limited)
- Hybrid mode: Smart validation with best-effort TextFSM parsing

Processing Flow:
1. Guard blacklist check (always) - Guard rules from guard_rules.yaml
2. Command prefix check (mode-dependent) - show/display/get/list/describe
3. TextFSM template check (optional in hybrid/blacklist mode)

Usage:
    from olav.core.command_validator import get_command_validator

    validator = get_command_validator()
    result = validator.validate_command(platform="cisco_ios", command="show ip ospf interface brief")
    if result.allowed:
        # Execute command
        pass
    else:
        # Handle rejection
        print(f"Command blocked: {result.reason}")
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from config.settings import settings

if TYPE_CHECKING:
    from olav.core.registry import CommandRegistry

logger = logging.getLogger(__name__)


class CommandMode(str, Enum):
    """Command validation modes."""

    BLACKLIST = "blacklist"  # Allow all show/display, block dangerous
    WHITELIST = "whitelist"  # Only allow predefined commands
    HYBRID = "hybrid"  # Smart validation with best-effort parsing


class ValidationResult(BaseModel):
    """Result of command validation.

    Attributes:
        allowed: Whether command is allowed to execute
        reason: Reason for rejection (if not allowed)
        mode: Validation mode used
        has_template: Whether TextFSM template exists
        raw_fallback: Whether to use raw output if no template
    """

    allowed: bool
    reason: str | None = None
    mode: CommandMode | None = None
    has_template: bool = False
    raw_fallback: bool = False


class CommandValidator:
    """Flexible command validator with multiple modes.

    Attributes:
        mode: Current validation mode
        config: Command mode configuration
        registry: CommandRegistry instance
    """

    def __init__(self, mode: str | None = None, config_path: str | None = None) -> None:
        """Initialize Command Validator.

        Args:
            mode: Validation mode (blacklist/whitelist/hybrid). If None, uses settings.sync.command_mode
            config_path: Path to command_mode.yaml config file
        """

        # Determine mode
        if mode is None:
            mode = settings.sync.command_mode

        self.mode = CommandMode(mode)

        # Load config
        self.config = self._load_config(config_path or settings.sync.command_mode_config)

        # Initialize registry
        from olav.core.registry import get_command_registry

        self.registry: CommandRegistry = get_command_registry()

        logger.info(f"CommandValidator initialized with mode: {self.mode.value}")

    def _load_config(self, config_path: str) -> dict:
        """Load command mode configuration.

        Args:
            config_path: Path to command_mode.yaml

        Returns:
            Configuration dictionary
        """
        from config.paths import PROJECT_ROOT

        path = Path(config_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / config_path

        if not path.exists():
            logger.warning(f"Command mode config not found: {path}, using defaults")
            return self._get_default_config()

        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                return self._get_default_config()

            return data

        except Exception as e:
            logger.error(f"Failed to load command mode config: {e}, using defaults")
            return self._get_default_config()

    def _get_default_config(self) -> dict:
        """Get default configuration for current mode.

        Returns:
            Default configuration dictionary
        """
        if self.mode == CommandMode.WHITELIST:
            return {"modes": {"whitelist": {"require_template": True, "allow_pipe": False}}}
        elif self.mode == CommandMode.BLACKLIST:
            return {
                "modes": {
                    "blacklist": {
                        "allowed_prefixes": ["show", "display", "get", "list", "describe"],
                        "require_template": False,
                        "allow_pipe": True,
                    }
                }
            }
        else:  # HYBRID
            return {
                "modes": {
                    "hybrid": {
                        "allowed_prefixes": ["show", "display", "get", "list", "describe"],
                        "require_template": False,
                        "allow_pipe": True,
                        "no_template_fallback": "raw_output",
                    }
                }
            }

    def _get_mode_config(self) -> dict:
        """Get configuration for current mode.

        Returns:
            Mode-specific configuration
        """
        return self.config.get("modes", {}).get(self.mode.value, {})

    def _check_command_prefix(self, command: str) -> bool:
        """Check if command starts with allowed prefix.

        Args:
            command: Command string

        Returns:
            True if command starts with allowed prefix
        """
        mode_config = self._get_mode_config()
        allowed_prefixes = mode_config.get("allowed_prefixes", ["show", "display"])

        command_lower = command.strip().lower()
        for prefix in allowed_prefixes:
            if command_lower.startswith(prefix.lower()):
                return True

        return False

    def _check_pipe_allowed(self, command: str) -> bool:
        """Check if pipe operators are allowed in command.

        Args:
            command: Command string

        Returns:
            True if pipes are allowed
        """
        mode_config = self._get_mode_config()
        allow_pipe = mode_config.get("allow_pipe", False)

        if not allow_pipe and "|" in command:
            return False

        # Check max pipes
        max_pipes = mode_config.get("max_pipes", 3)
        pipe_count = command.count("|")
        if pipe_count > max_pipes:
            logger.warning(f"Command has {pipe_count} pipes, max allowed: {max_pipes}")
            return False

        return True

    def _has_textfsm_template(self, platform: str, command: str) -> bool:
        """Check if TextFSM template exists for command.

        Args:
            platform: Device platform
            command: Command string

        Returns:
            True if template exists
        """
        return self.registry.get_template(platform, command) is not None

    def validate_command(
        self,
        platform: str,
        command: str,
    ) -> ValidationResult:
        """Validate if command is allowed to execute.

        Args:
            platform: Device platform (e.g., "cisco_ios")
            command: Command string to validate

        Returns:
            ValidationResult with allowed status and reason
        """
        # Trim command
        command = command.strip()
        mode_config = self._get_mode_config()

        # Mode-specific validation
        if self.mode == CommandMode.WHITELIST:
            return self._validate_whitelist(platform, command, mode_config)
        elif self.mode == CommandMode.BLACKLIST:
            return self._validate_blacklist(platform, command, mode_config)
        else:  # HYBRID
            return self._validate_hybrid(platform, command, mode_config)

    def _validate_whitelist(
        self, platform: str, command: str, mode_config: dict
    ) -> ValidationResult:
        """Validate in whitelist mode (strict).

        Only allows commands with TextFSM templates.
        """
        # Check if template exists
        has_template = self._has_textfsm_template(platform, command)

        if not has_template:
            return ValidationResult(
                allowed=False,
                reason=f"Command not in whitelist (no TextFSM template found for {platform})",
                mode=self.mode,
                has_template=False,
            )

        return ValidationResult(
            allowed=True,
            mode=self.mode,
            has_template=True,
        )

    def _validate_blacklist(
        self, platform: str, command: str, mode_config: dict
    ) -> ValidationResult:
        """Validate in blacklist mode (permissive).

        Allows all show/display commands, checks templates optionally.
        """
        # Check command prefix
        if not self._check_command_prefix(command):
            return ValidationResult(
                allowed=False,
                reason=f"Command must start with one of: {mode_config.get('allowed_prefixes', ['show'])}",
                mode=self.mode,
                has_template=False,
            )

        # Check pipes
        if not self._check_pipe_allowed(command):
            return ValidationResult(
                allowed=False,
                reason="Pipe operators not allowed in whitelist mode",
                mode=self.mode,
                has_template=False,
            )

        # Template check (optional in blacklist mode)
        has_template = self._has_textfsm_template(platform, command)
        raw_fallback = not has_template

        return ValidationResult(
            allowed=True,
            mode=self.mode,
            has_template=has_template,
            raw_fallback=raw_fallback,
        )

    def _validate_hybrid(self, platform: str, command: str, mode_config: dict) -> ValidationResult:
        """Validate in hybrid mode (smart).

        Combines blacklist and whitelist approaches.
        """
        # Check command prefix
        if not self._check_command_prefix(command):
            return ValidationResult(
                allowed=False,
                reason=f"Command must start with one of: {mode_config.get('allowed_prefixes', ['show'])}",
                mode=self.mode,
                has_template=False,
            )

        # Check pipes
        if not self._check_pipe_allowed(command):
            return ValidationResult(
                allowed=False,
                reason="Too many pipe operators or pipes not allowed",
                mode=self.mode,
                has_template=False,
            )

        # Template check (prefer template but allow without)
        has_template = self._has_textfsm_template(platform, command)
        fallback_behavior = mode_config.get("no_template_fallback", "raw_output")

        raw_fallback = not has_template and fallback_behavior == "raw_output"

        return ValidationResult(
            allowed=True,
            mode=self.mode,
            has_template=has_template,
            raw_fallback=raw_fallback,
        )


# =============================================================================
# Singleton Instance
# =============================================================================

_validator: CommandValidator | None = None


def get_command_validator() -> CommandValidator:
    """Get the global Command Validator instance.

    Returns:
        Command Validator singleton
    """
    global _validator

    if _validator is None:
        _validator = CommandValidator()

    return _validator


def reset_command_validator() -> None:
    """Reset the global Command Validator instance (mainly for testing)."""
    global _validator
    _validator = None
