"""
Skill System Enhancements

Provides comprehensive skill management, validation, and lifecycle operations.

Features:
- SkillConfig validation with schema and metadata checking
- Skill version compatibility checking and resolution
- Dynamic skill loading from configuration
- Skill tool validation and registration
"""

import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillType(Enum):
    """Enumeration of skill types."""

    QUERY = "query"
    COMMAND = "command"
    ANALYSIS = "analysis"
    INTEGRATION = "integration"
    CUSTOM = "custom"


class VersionComparison(Enum):
    """Result of version comparison."""

    COMPATIBLE = "compatible"
    WARNING = "warning"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass
class SkillVersion:
    """Represents a skill version with semantic versioning."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Return version string."""
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: "SkillVersion") -> bool:
        """Compare versions."""
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __le__(self, other: "SkillVersion") -> bool:
        """Compare versions."""
        return (self.major, self.minor, self.patch) <= (other.major, other.minor, other.patch)

    def __eq__(self, other: Any) -> bool:
        """Compare versions."""
        if not isinstance(other, SkillVersion):
            return False
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __gt__(self, other: "SkillVersion") -> bool:
        """Compare versions."""
        return (self.major, self.minor, self.patch) > (other.major, other.minor, other.patch)

    def __ge__(self, other: "SkillVersion") -> bool:
        """Compare versions."""
        return (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)


@dataclass
class SkillTool:
    """Represents a skill tool with metadata and validation."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    return_type: str = "Any"
    required: bool = False
    timeout: float = 30.0

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate tool configuration.

        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []

        if not self.name:
            errors.append("Tool name cannot be empty")

        if not self.description:
            errors.append("Tool description cannot be empty")

        if not isinstance(self.parameters, dict):
            errors.append("Tool parameters must be a dictionary")

        if self.timeout <= 0:
            errors.append("Tool timeout must be positive")

        return len(errors) == 0, errors


@dataclass
class SkillConfig:
    """Represents a skill configuration with validation."""

    name: str
    version: str
    description: str
    type: str = "custom"
    enabled: bool = True
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    min_required_version: str = "0.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Post-initialization processing."""
        self._version_obj: SkillVersion | None = None
        self._min_version_obj: SkillVersion | None = None

    @property
    def version_obj(self) -> SkillVersion:
        """Parse and cache version object."""
        if self._version_obj is None:
            self._version_obj = SkillVersion.from_string(self.version)
        return self._version_obj

    @property
    def min_version_obj(self) -> SkillVersion:
        """Parse and cache minimum version object."""
        if self._min_version_obj is None:
            self._min_version_obj = SkillVersion.from_string(self.min_required_version)
        return self._min_version_obj

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate skill configuration.

        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []

        # Name validation
        if not self.name or not isinstance(self.name, str):
            errors.append("Skill name must be a non-empty string")
        elif not re.match(r"^[a-zA-Z0-9_\-]+$", self.name):
            errors.append("Skill name must contain only alphanumeric, underscore, or hyphen")

        # Version validation
        if not self._validate_version(self.version):
            errors.append(f"Invalid version format: {self.version}")

        # Description validation
        if not self.description or not isinstance(self.description, str):
            errors.append("Skill description must be a non-empty string")

        # Type validation
        valid_types = [t.value for t in SkillType]
        if self.type not in valid_types:
            errors.append(f"Invalid skill type: {self.type}")

        # Dependencies validation
        if not isinstance(self.dependencies, list):
            errors.append("Dependencies must be a list")

        # Tools validation
        if not isinstance(self.tools, list):
            errors.append("Tools must be a list")
        else:
            for idx, tool_cfg in enumerate(self.tools):
                if not isinstance(tool_cfg, dict):
                    errors.append(f"Tool {idx} must be a dictionary")
                elif "name" not in tool_cfg:
                    errors.append(f"Tool {idx} missing required 'name' field")
                elif "description" not in tool_cfg:
                    errors.append(f"Tool {idx} missing required 'description' field")

        return len(errors) == 0, errors

    @staticmethod
    def _validate_version(version: str) -> bool:
        """Validate semantic version format."""
        pattern = r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?$"
        return bool(re.match(pattern, version))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillConfig":
        """Create SkillConfig from dictionary."""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            type=data.get("type", "custom"),
            enabled=data.get("enabled", True),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", []),
            tools=data.get("tools", []),
            min_required_version=data.get("min_required_version", "0.0.0"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SkillLoader:
    """Loads and manages skills from configuration."""

    skills_dir: Path
    max_cache_size: int = 100

    def __post_init__(self):
        """Initialize loader."""
        self.skills_dir = Path(self.skills_dir)
        self._skill_cache: dict[str, SkillConfig] = {}
        self._cache_lock = threading.RLock()
        self._load_times: dict[str, datetime] = {}

    def load_skill(self, skill_name: str) -> SkillConfig | None:
        """
        Load a skill from configuration file.

        Args:
            skill_name: Name of the skill to load

        Returns:
            SkillConfig if found and valid, None otherwise
        """
        with self._cache_lock:
            if skill_name in self._skill_cache:
                return self._skill_cache[skill_name]

        skill_path = self.skills_dir / skill_name / "SKILL.md"

        if not skill_path.exists():
            logger.warning(f"Skill file not found: {skill_path}")
            return None

        try:
            # Extract YAML frontmatter
            config_data = self._extract_frontmatter(skill_path)
            config = SkillConfig.from_dict(config_data)

            # Validate configuration
            is_valid, errors = config.validate()
            if not is_valid:
                logger.error(f"Skill {skill_name} validation failed: {errors}")
                return None

            with self._cache_lock:
                if len(self._skill_cache) >= self.max_cache_size:
                    self._evict_oldest()

                self._skill_cache[skill_name] = config
                self._load_times[skill_name] = datetime.now()

            logger.info(f"Loaded skill: {skill_name} v{config.version}")
            return config

        except Exception as e:
            logger.error(f"Error loading skill {skill_name}: {e}")
            return None

    def load_all_skills(self) -> dict[str, SkillConfig]:
        """
        Load all skills from skills directory.

        Returns:
            Dictionary of skill_name -> SkillConfig
        """
        skills = {}

        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return skills

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                config = self.load_skill(skill_dir.name)
                if config:
                    skills[skill_dir.name] = config

        return skills

    @staticmethod
    def _extract_frontmatter(file_path: Path) -> dict[str, Any]:
        """
        Extract YAML frontmatter from markdown file.

        Args:
            file_path: Path to markdown file

        Returns:
            Dictionary of configuration data
        """
        content = file_path.read_text(encoding="utf-8")

        # Find frontmatter delimiters
        if not content.startswith("---"):
            return {}

        end_idx = content.find("---", 3)
        if end_idx == -1:
            return {}

        frontmatter = content[3:end_idx].strip()

        # Simple YAML parsing
        data = {}
        for line in frontmatter.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            # Parse boolean
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False

            # Parse lists
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip("'\"") for v in value[1:-1].split(",")]

            data[key] = value

        return data

    def _evict_oldest(self) -> None:
        """Evict oldest skill from cache."""
        if not self._load_times:
            return

        oldest_skill = min(self._load_times, key=self._load_times.get)
        del self._skill_cache[oldest_skill]
        del self._load_times[oldest_skill]


@dataclass
class SkillCompatibilityChecker:
    """Checks skill version compatibility."""

    current_version: str

    def __post_init__(self):
        """Initialize checker."""
        self._current_version_obj = SkillVersion.from_string(self.current_version)

    def check_compatibility(
        self, skill_config: SkillConfig
    ) -> tuple[VersionComparison, str | None]:
        """
        Check if skill is compatible with current version.

        Args:
            skill_config: Skill configuration to check

        Returns:
            Tuple of (compatibility_status, message)
        """
        try:
            min_version = skill_config.min_version_obj

            if self._current_version_obj < min_version:
                msg = (
                    f"Skill {skill_config.name} requires version {min_version}, "
                    f"but current version is {self.current_version}"
                )
                return VersionComparison.INCOMPATIBLE, msg

            # Check if major version matches
            if self._current_version_obj.major != min_version.major:
                msg = (
                    f"Skill {skill_config.name} may have compatibility issues "
                    f"(requires {min_version.major}, current is {self._current_version_obj.major})"
                )
                return VersionComparison.WARNING, msg

            return VersionComparison.COMPATIBLE, None

        except Exception as e:
            logger.error(f"Error checking compatibility: {e}")
            return VersionComparison.UNKNOWN, str(e)

    def check_dependency_compatibility(
        self, skill_config: SkillConfig, available_skills: dict[str, SkillConfig]
    ) -> tuple[bool, list[str]]:
        """
        Check if all dependencies are available and compatible.

        Args:
            skill_config: Skill configuration
            available_skills: Dictionary of available skills

        Returns:
            Tuple of (all_compatible, missing_or_incompatible)
        """
        issues = []

        for dep in skill_config.dependencies:
            if dep not in available_skills:
                issues.append(f"Dependency '{dep}' not found")
                continue

            dep_skill = available_skills[dep]
            compat, msg = self.check_compatibility(dep_skill)

            if compat == VersionComparison.INCOMPATIBLE:
                issues.append(f"Dependency '{dep}': {msg}")

        return len(issues) == 0, issues


@dataclass
class SkillToolValidator:
    """Validates and manages skill tools."""

    _registered_tools: dict[str, SkillTool] = field(default_factory=dict)
    _tool_lock = threading.RLock()

    def register_tool(self, skill_name: str, tool: SkillTool) -> tuple[bool, list[str]]:
        """
        Register a tool from a skill.

        Args:
            skill_name: Name of the skill
            tool: Tool to register

        Returns:
            Tuple of (success, errors)
        """
        is_valid, errors = tool.validate()

        if not is_valid:
            return False, errors

        with self._tool_lock:
            tool_id = f"{skill_name}:{tool.name}"
            self._registered_tools[tool_id] = tool

        logger.debug(f"Registered tool: {tool_id}")
        return True, []

    def register_tools_from_skill(self, skill_config: SkillConfig) -> tuple[int, list[str]]:
        """
        Register all tools from a skill configuration.

        Args:
            skill_config: Skill configuration

        Returns:
            Tuple of (num_registered, errors)
        """
        registered = 0
        errors = []

        for tool_cfg in skill_config.tools:
            try:
                tool = SkillTool(
                    name=tool_cfg.get("name", ""),
                    description=tool_cfg.get("description", ""),
                    parameters=tool_cfg.get("parameters", {}),
                    return_type=tool_cfg.get("return_type", "Any"),
                    required=tool_cfg.get("required", False),
                    timeout=float(tool_cfg.get("timeout", 30.0)),
                )

                success, errs = self.register_tool(skill_config.name, tool)
                if success:
                    registered += 1
                else:
                    errors.extend(errs)

            except Exception as e:
                errors.append(f"Error registering tool: {e}")

        return registered, errors

    def get_tool(self, skill_name: str, tool_name: str) -> SkillTool | None:
        """
        Get a registered tool.

        Args:
            skill_name: Name of the skill
            tool_name: Name of the tool

        Returns:
            SkillTool if found, None otherwise
        """
        tool_id = f"{skill_name}:{tool_name}"
        return self._registered_tools.get(tool_id)

    def get_tools_for_skill(self, skill_name: str) -> list[SkillTool]:
        """
        Get all tools registered for a skill.

        Args:
            skill_name: Name of the skill

        Returns:
            List of registered tools
        """
        prefix = f"{skill_name}:"
        return [
            tool for tool_id, tool in self._registered_tools.items() if tool_id.startswith(prefix)
        ]

    def unregister_tool(self, skill_name: str, tool_name: str) -> bool:
        """
        Unregister a tool.

        Args:
            skill_name: Name of the skill
            tool_name: Name of the tool

        Returns:
            True if tool was removed, False otherwise
        """
        tool_id = f"{skill_name}:{tool_name}"

        with self._tool_lock:
            if tool_id in self._registered_tools:
                del self._registered_tools[tool_id]
                return True

        return False


# Add string parsing method to SkillVersion
def _parse_version(version_str: str) -> SkillVersion:
    """Parse version string into SkillVersion object."""
    parts = version_str.split(".")
    if len(parts) < 3:
        raise ValueError(f"Invalid version format: {version_str}")

    try:
        major = int(parts[0])
        minor = int(parts[1])
        # Handle patch with pre-release suffix (e.g., "5-alpha")
        patch_str = parts[2].split("-")[0]
        patch = int(patch_str)
        return SkillVersion(major, minor, patch)
    except ValueError as e:
        raise ValueError(f"Invalid version format: {version_str}") from e


SkillVersion.from_string = staticmethod(_parse_version)
