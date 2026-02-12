"""
Admin File Manager - Unified file operations for Admin Agent

Handles all file I/O operations:
- YAML/JSON configuration file operations
- Knowledge base file management
- Path safety checks
- Metadata management
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .exceptions import OperationError, PathError, ValidationError

logger = logging.getLogger(__name__)


class AdminFileManager:
    """
    Unified file manager for Admin operations.
    
    Handles:
    - Configuration files (YAML/JSON)
    - Knowledge base entries (Markdown with metadata)
    - Path validation and security
    """

    ALLOWED_DIRS = [
        ".olav/config",
        ".olav/knowledge",
    ]

    # ====== Path Management ======

    @staticmethod
    def _validate_path(path: str) -> Path:
        """
        Validate and normalize file path.

        Prevents path traversal attacks and ensures files are in allowed directories.

        Args:
            path: File path to validate

        Returns:
            Validated Path object

        Raises:
            PathError: If path is invalid or outside allowed directories
        """
        try:
            file_path = Path(path).resolve()
        except Exception as e:
            raise PathError(f"Invalid path: {path}") from e

        # Check for path traversal attacks
        if ".." in str(path):
            raise PathError("Path traversal not allowed")

        # Check if in allowed directories
        is_allowed = False
        for allowed_dir in AdminFileManager.ALLOWED_DIRS:
            allowed_path = Path(allowed_dir).resolve()
            try:
                file_path.relative_to(allowed_path)
                is_allowed = True
                break
            except ValueError:
                continue

        if not is_allowed:
            raise PathError(f"Path {path} is not in allowed directories: {AdminFileManager.ALLOWED_DIRS}")

        return file_path

    # ====== YAML Operations ======

    @staticmethod
    def load_yaml(path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Args:
            path: Path to YAML file

        Returns:
            Dictionary containing parsed YAML content

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be read
            ValidationError: If YAML is invalid
        """
        file_path = AdminFileManager._validate_path(path)

        try:
            if not file_path.exists():
                logger.warning(f"Config file not found: {path}, returning empty dict")
                return {}

            with open(file_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                return content if content is not None else {}

        except yaml.YAMLError as e:
            raise ValidationError(f"Invalid YAML format in {path}: {e}") from e
        except IOError as e:
            raise OperationError(f"Failed to read config file {path}: {e}") from e
        except Exception as e:
            raise OperationError(f"Unexpected error reading {path}: {e}") from e

    @staticmethod
    def save_yaml(path: str, data: Dict[str, Any]) -> None:
        """
        Save configuration to YAML file.

        Args:
            path: Path to YAML file
            data: Dictionary to save as YAML

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be written
        """
        file_path = AdminFileManager._validate_path(path)

        try:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)

            logger.info(f"Config saved to {path}")

        except Exception as e:
            raise OperationError(f"Failed to save config file {path}: {e}") from e

    # ====== JSON Operations ======

    @staticmethod
    def load_json(path: str) -> Dict[str, Any]:
        """
        Load configuration from JSON file.

        Args:
            path: Path to JSON file

        Returns:
            Dictionary containing parsed JSON content

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be read
            ValidationError: If JSON is invalid
        """
        file_path = AdminFileManager._validate_path(path)

        try:
            if not file_path.exists():
                logger.warning(f"Config file not found: {path}, returning empty dict")
                return {}

            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                return content if content is not None else {}

        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON format in {path}: {e}") from e
        except IOError as e:
            raise OperationError(f"Failed to read config file {path}: {e}") from e
        except Exception as e:
            raise OperationError(f"Unexpected error reading {path}: {e}") from e

    @staticmethod
    def save_json(path: str, data: Dict[str, Any]) -> None:
        """
        Save configuration to JSON file.

        Args:
            path: Path to JSON file
            data: Dictionary to save as JSON

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be written
        """
        file_path = AdminFileManager._validate_path(path)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Config saved to {path}")

        except Exception as e:
            raise OperationError(f"Failed to save config file {path}: {e}") from e

    # ====== Markdown Operations (for Knowledge Base) ======

    async def read_markdown(self, path: str) -> str:
        """
        Read raw markdown file content.

        Args:
            path: Path to markdown file

        Returns:
            File content

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be read
        """
        file_path = self._validate_path(path)

        try:
            if not file_path.exists():
                raise OperationError(f"File not found: {path}")

            return file_path.read_text(encoding="utf-8")

        except Exception as e:
            raise OperationError(f"Failed to read markdown file {path}: {e}") from e

    async def write_markdown(self, path: str, content: str) -> None:
        """
        Write markdown file content.

        Args:
            path: Path to markdown file
            content: Content to write

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be written
        """
        file_path = self._validate_path(path)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            logger.info(f"Markdown saved to {path}")

        except Exception as e:
            raise OperationError(f"Failed to write markdown file {path}: {e}") from e

    async def delete_file(self, path: str) -> None:
        """
        Delete a file.

        Args:
            path: Path to file to delete

        Raises:
            PathError: If path is invalid
            OperationError: If file cannot be deleted
        """
        file_path = self._validate_path(path)

        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"File deleted: {path}")
            else:
                raise OperationError(f"File not found: {path}")

        except Exception as e:
            raise OperationError(f"Failed to delete file {path}: {e}") from e

    # ====== Validation ======

    @staticmethod
    def validate_yaml(data: Dict[str, Any], required_keys: Optional[List[str]] = None) -> bool:
        """
        Validate YAML data structure.

        Args:
            data: Dictionary to validate
            required_keys: List of required keys

        Returns:
            True if valid

        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(data, dict):
            raise ValidationError(f"Expected dict, got {type(data)}")

        if required_keys:
            missing_keys = [k for k in required_keys if k not in data]
            if missing_keys:
                raise ValidationError(f"Missing required keys: {missing_keys}")

        return True

    @staticmethod
    def merge_yaml(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two YAML dictionaries.

        Updates take precedence over base values.

        Args:
            base: Base configuration
            updates: Updates to merge

        Returns:
            Merged configuration dictionary
        """
        result = base.copy()

        for key, value in updates.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = AdminFileManager.merge_yaml(result[key], value)
            else:
                result[key] = value

        return result
