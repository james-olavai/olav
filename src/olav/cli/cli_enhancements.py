"""CLI Command Enhancements - Phase 3 Legacy (Task: CLI Commands).

Implements advanced CLI features:
1. Help command with detailed documentation
2. Shell command for system execution
3. Config command for settings management
4. Skill management commands
5. Async/await support for CLI
"""

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HelpCommand:
    """Help command handler for CLI."""

    def __init__(self, commands: dict[str, dict[str, Any]] | None = None):
        """Initialize help command.

        Args:
            commands: Dictionary of available commands with metadata
        """
        self.commands = commands or {}

    def register_command(
        self,
        name: str,
        description: str,
        usage: str | None = None,
        examples: list[str] | None = None,
    ) -> None:
        """Register a command in help system.

        Args:
            name: Command name
            description: Command description
            usage: Command usage string
            examples: List of usage examples
        """
        self.commands[name] = {
            "description": description,
            "usage": usage,
            "examples": examples or [],
        }

    def get_help(self, command: str | None = None) -> str:
        """Get help text for command or general help.

        Args:
            command: Specific command to get help for (None for general help)

        Returns:
            Help text
        """
        if command is None:
            return self._get_general_help()
        elif command in self.commands:
            return self._get_command_help(command)
        else:
            return f"Command '{command}' not found. Type 'help' for available commands."

    def _get_general_help(self) -> str:
        """Get general help for all commands."""
        lines = ["Available Commands:"]
        lines.append("")

        for cmd, info in sorted(self.commands.items()):
            lines.append(f"  {cmd:<15} - {info.get('description', '')}")

        lines.append("")
        lines.append("Type 'help <command>' for more information about a command.")

        return "\n".join(lines)

    def _get_command_help(self, command: str) -> str:
        """Get detailed help for a command."""
        info = self.commands[command]
        lines = []

        # Description
        if "description" in info:
            lines.append(f"{info['description']}\n")

        # Usage
        if "usage" in info:
            lines.append(f"Usage: {info['usage']}")

        # Examples
        if "examples" in info and info["examples"]:
            lines.append("\nExamples:")
            for example in info["examples"]:
                lines.append(f"  $ {example}")

        return "\n".join(lines)


class ShellCommand:
    """Shell command execution handler."""

    def __init__(self, timeout: float = 30.0, shell: str = "/bin/bash"):
        """Initialize shell command handler.

        Args:
            timeout: Default timeout for commands in seconds
            shell: Shell executable to use
        """
        self.timeout = timeout
        self.shell = shell

    def execute(
        self,
        command: str,
        timeout: float | None = None,
        capture_output: bool = True,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Execute shell command.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds (uses default if None)
            capture_output: Whether to capture stdout/stderr
            check: Whether to raise exception on non-zero exit

        Returns:
            CompletedProcess with results

        Raises:
            subprocess.TimeoutExpired: If command exceeds timeout
            subprocess.CalledProcessError: If check=True and command fails
        """
        timeout = timeout or self.timeout

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                check=check,
            )
            logger.debug(f"Shell command executed: {command[:50]}...")
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Shell command timed out after {timeout}s: {command}")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Shell command failed with code {e.returncode}: {command}")
            raise
        except Exception as e:
            logger.error(f"Shell command error: {e}")
            raise

    def execute_and_return_output(self, command: str, timeout: float | None = None) -> str:
        """Execute shell command and return output.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds

        Returns:
            Combined stdout and stderr

        Example:
            output = shell.execute_and_return_output("ls -la /home")
        """
        result = self.execute(command, timeout=timeout)
        return result.stdout or result.stderr


class ConfigCommand:
    """Configuration management command handler."""

    def __init__(self, config_path: Path | None = None):
        """Initialize config command.

        Args:
            config_path: Path to config file (default: ~/.olav/config.json)
        """
        if config_path is None:
            config_path = Path.home() / ".olav" / "config.json"

        self.config_path = config_path
        self._config: dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    self._config = json.load(f)
                logger.debug(f"Configuration loaded from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                self._config = {}
        else:
            self._config = {}

    def _save_config(self) -> None:
        """Save configuration to file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w") as f:
                json.dump(self._config, f, indent=2)

            logger.debug(f"Configuration saved to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        # Check environment variable override first
        env_key = f"OLAV_{key.upper()}"
        if env_key in os.environ:
            return os.environ[env_key]

        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        self._config[key] = value
        self._save_config()
        logger.info(f"Configuration updated: {key} = {value}")

    def list_all(self) -> dict[str, Any]:
        """Get all configuration values.

        Returns:
            Configuration dictionary
        """
        return self._config.copy()

    def delete(self, key: str) -> None:
        """Delete configuration key.

        Args:
            key: Configuration key to delete
        """
        if key in self._config:
            del self._config[key]
            self._save_config()
            logger.info(f"Configuration deleted: {key}")


class SkillManagementCommand:
    """Skill management command handler."""

    def __init__(self, skills_dir: Path | None = None):
        """Initialize skill management.

        Args:
            skills_dir: Directory containing skills (default: ~/.olav/skills/)
        """
        if skills_dir is None:
            skills_dir = Path.home() / ".olav" / "skills"

        self.skills_dir = skills_dir
        self._skill_registry: dict[str, dict[str, Any]] = {}
        self._load_skills()

    def _load_skills(self) -> None:
        """Load available skills."""
        if not self.skills_dir.exists():
            logger.debug(f"Skills directory not found: {self.skills_dir}")
            return

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                self._register_skill(skill_dir)

    def _register_skill(self, skill_dir: Path) -> None:
        """Register a skill from directory.

        Args:
            skill_dir: Skill directory path
        """
        skill_config_file = skill_dir / "SKILL.md"

        if not skill_config_file.exists():
            return

        try:
            skill_name = skill_dir.name
            self._skill_registry[skill_name] = {
                "path": str(skill_dir),
                "enabled": True,
                "version": self._extract_version(skill_config_file),
            }
            logger.debug(f"Skill registered: {skill_name}")
        except Exception as e:
            logger.error(f"Failed to register skill {skill_dir.name}: {e}")

    @staticmethod
    def _extract_version(config_file: Path) -> str:
        """Extract version from skill config.

        Args:
            config_file: Skill configuration file

        Returns:
            Version string (default "1.0.0")
        """
        try:
            with open(config_file) as f:
                content = f.read()
                # Simple version extraction from markdown frontmatter
                for line in content.split("\n"):
                    if "version:" in line.lower():
                        return line.split(":", 1)[1].strip()
            return "1.0.0"
        except Exception:
            return "1.0.0"

    def list_skills(self) -> list[dict[str, Any]]:
        """List all available skills.

        Returns:
            List of skill information dictionaries
        """
        return [
            {
                "name": name,
                "enabled": info["enabled"],
                "version": info["version"],
            }
            for name, info in self._skill_registry.items()
        ]

    def get_skill_info(self, skill_name: str) -> dict[str, Any] | None:
        """Get information about a skill.

        Args:
            skill_name: Name of the skill

        Returns:
            Skill information dictionary or None if not found
        """
        return self._skill_registry.get(skill_name)

    def enable_skill(self, skill_name: str) -> bool:
        """Enable a skill.

        Args:
            skill_name: Name of the skill to enable

        Returns:
            True if successful, False otherwise
        """
        if skill_name in self._skill_registry:
            self._skill_registry[skill_name]["enabled"] = True
            logger.info(f"Skill enabled: {skill_name}")
            return True
        return False

    def disable_skill(self, skill_name: str) -> bool:
        """Disable a skill.

        Args:
            skill_name: Name of the skill to disable

        Returns:
            True if successful, False otherwise
        """
        if skill_name in self._skill_registry:
            self._skill_registry[skill_name]["enabled"] = False
            logger.info(f"Skill disabled: {skill_name}")
            return True
        return False

    def is_compatible(self, skill_name: str, required_version: str) -> bool:
        """Check if skill version meets requirement.

        Args:
            skill_name: Name of the skill
            required_version: Required version string (e.g., "1.0.0")

        Returns:
            True if skill meets version requirement
        """
        if skill_name not in self._skill_registry:
            return False

        skill_version = self._skill_registry[skill_name]["version"]
        return self._compare_versions(skill_version, required_version) >= 0

    @staticmethod
    def _compare_versions(version1: str, version2: str) -> int:
        """Compare two version strings.

        Args:
            version1: First version
            version2: Second version

        Returns:
            > 0 if version1 > version2
            = 0 if version1 == version2
            < 0 if version1 < version2
        """
        try:
            v1_parts = [int(x) for x in version1.split(".")]
            v2_parts = [int(x) for x in version2.split(".")]

            for v1, v2 in zip(v1_parts, v2_parts):
                if v1 > v2:
                    return 1
                elif v1 < v2:
                    return -1

            if len(v1_parts) > len(v2_parts):
                return 1
            elif len(v1_parts) < len(v2_parts):
                return -1

            return 0
        except Exception:
            return 0


class InputValidator:
    """Input validation for CLI commands."""

    @staticmethod
    def validate_command_name(name: str) -> bool:
        """Validate command name format.

        Args:
            name: Command name to validate

        Returns:
            True if valid
        """
        if not name:
            return False
        return name.replace("_", "").isalnum() and name[0].isalpha()

    @staticmethod
    def validate_argument_count(args: list[str], required: int, optional: int = 0) -> bool:
        """Validate argument count.

        Args:
            args: Actual arguments provided
            required: Required number of arguments
            optional: Maximum number of optional arguments

        Returns:
            True if argument count is valid
        """
        arg_count = len(args)
        return required <= arg_count <= (required + optional)

    @staticmethod
    def validate_numeric(value: str) -> bool:
        """Validate numeric input.

        Args:
            value: Value to validate

        Returns:
            True if value is numeric
        """
        try:
            float(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def validate_enum(value: str, allowed: list[str]) -> bool:
        """Validate enum input.

        Args:
            value: Value to validate
            allowed: List of allowed values

        Returns:
            True if value is in allowed list
        """
        return value in allowed

    @staticmethod
    def validate_path(path: str, must_exist: bool = False) -> bool:
        """Validate file path.

        Args:
            path: File path to validate
            must_exist: Whether path must exist

        Returns:
            True if path is valid
        """
        try:
            p = Path(path).expanduser()
            if must_exist:
                return p.exists()
            return True
        except Exception:
            return False


class AsyncCLISupport:
    """Async/await support for CLI operations."""

    @staticmethod
    async def run_async_command(
        coro: Any,
        timeout: float | None = None,
    ) -> Any:
        """Run async command with optional timeout.

        Args:
            coro: Coroutine to execute
            timeout: Timeout in seconds (optional)

        Returns:
            Command result

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            Exception: Any exception raised by command

        Example:
            result = await AsyncCLISupport.run_async_command(some_coroutine(), timeout=30)
        """
        try:
            if timeout:
                return await asyncio.wait_for(coro, timeout=timeout)
            else:
                return await coro
        except TimeoutError:
            logger.error(f"Async command timed out after {timeout}s")
            raise

    @staticmethod
    async def run_multiple_async_commands(
        coros: list[Any],
        return_exceptions: bool = False,
    ) -> list[Any]:
        """Run multiple async commands in parallel.

        Args:
            coros: List of coroutines to execute
            return_exceptions: Whether to return exceptions as results

        Returns:
            List of results

        Example:
            results = await AsyncCLISupport.run_multiple_async_commands([coro1, coro2, coro3])
        """
        try:
            return await asyncio.gather(*coros, return_exceptions=return_exceptions)
        except Exception as e:
            logger.error(f"Error running multiple async commands: {e}")
            raise

    @staticmethod
    def create_async_task(coro: Any) -> asyncio.Task:
        """Create async task from coroutine.

        Args:
            coro: Coroutine to create task for

        Returns:
            Async task

        Example:
            task = AsyncCLISupport.create_async_task(long_running_coro())
            # Later...
            result = await task
        """
        return asyncio.create_task(coro)

    @staticmethod
    async def cancel_async_task(task: asyncio.Task) -> None:
        """Cancel an async task.

        Args:
            task: Task to cancel

        Example:
            task = AsyncCLISupport.create_async_task(long_running_coro())
            # After some time...
            await AsyncCLISupport.cancel_async_task(task)
        """
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Task cancelled successfully")


class CommandTimeout:
    """Command timeout management."""

    def __init__(self, timeout_seconds: float = 30.0):
        """Initialize command timeout.

        Args:
            timeout_seconds: Default timeout in seconds
        """
        self.timeout = timeout_seconds
        self._start_time: float | None = None

    def start(self) -> None:
        """Mark command start time."""
        import time

        self._start_time = time.time()

    def check(self) -> bool:
        """Check if timeout exceeded.

        Returns:
            True if timeout exceeded
        """
        if self._start_time is None:
            return False

        import time

        return (time.time() - self._start_time) > self.timeout

    def remaining(self) -> float:
        """Get remaining time before timeout.

        Returns:
            Remaining seconds (0 if timed out)
        """
        if self._start_time is None:
            return self.timeout

        import time

        remaining = self.timeout - (time.time() - self._start_time)
        return max(0.0, remaining)
