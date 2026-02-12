"""
Validation functions for Admin Agent parameters.

Provides centralized validation logic for all parameter types.
"""

import ipaddress
import re
from typing import Optional

from .exceptions import ValidationError


def validate_device_name(name: Optional[str]) -> None:
    """
    Validate device name.

    Requirements:
      - Not empty
      - 1-64 characters
      - Only alphanumeric, dash, underscore
      - Must start with letter

    Args:
        name: Device name to validate

    Raises:
        ValidationError: If validation fails
    """
    if not name:
        raise ValidationError("Device name cannot be empty")

    if len(name) > 64:
        raise ValidationError(f"Device name too long (max 64 chars): {name}")

    # Must start with letter
    if not re.match(r"^[a-zA-Z]", name):
        raise ValidationError(f"Device name must start with letter: {name}")

    # Only alphanumeric, dash, underscore
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise ValidationError(f"Device name contains invalid characters: {name}")


def validate_device_ip(ip: Optional[str]) -> None:
    """
    Validate device IP address.

    Requirements:
      - Valid IPv4 address
      - Not a reserved IP

    Args:
        ip: IP address to validate

    Raises:
        ValidationError: If validation fails
    """
    if not ip:
        raise ValidationError("IP address cannot be empty")

    try:
        ip_obj = ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        raise ValidationError(f"Invalid IP address format: {ip}")

    # Check for reserved IPs
    if ip_obj.is_loopback:
        raise ValidationError(f"Cannot use loopback IP: {ip}")

    if ip_obj.is_reserved:
        raise ValidationError(f"Cannot use reserved IP: {ip}")

    if str(ip_obj) == "0.0.0.0":
        raise ValidationError("Cannot use 0.0.0.0")


def validate_username(username: Optional[str]) -> None:
    """
    Validate username.

    Requirements:
      - Not empty
      - 1-32 characters
      - Only alphanumeric, dash, underscore

    Args:
        username: Username to validate

    Raises:
        ValidationError: If validation fails
    """
    if not username:
        raise ValidationError("Username cannot be empty")

    if len(username) > 32:
        raise ValidationError(f"Username too long (max 32 chars): {username}")

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise ValidationError(f"Username contains invalid characters: {username}")


def validate_file_path(path: Optional[str], allowed_dirs: list) -> None:
    """
    Validate that file path is in allowed directories.

    Args:
        path: File path to validate
        allowed_dirs: List of allowed directory prefixes

    Raises:
        ValidationError: If path is invalid or not in allowed directories
    """
    if not path:
        raise ValidationError("File path cannot be empty")

    # Check for path traversal
    if ".." in path:
        raise ValidationError("Path traversal not allowed")

    if path.startswith("/"):
        raise ValidationError("Absolute paths not allowed")

    # Check if in allowed directories
    is_allowed = False
    for allowed_dir in allowed_dirs:
        if path.startswith(allowed_dir):
            is_allowed = True
            break

    if not is_allowed:
        raise ValidationError(f"Path {path} not in allowed directories: {allowed_dirs}")


def validate_cron_schedule(schedule: Optional[str]) -> None:
    """
    Validate cron schedule expression.

    Accepts standard cron format: minute hour day month weekday

    Args:
        schedule: Cron expression to validate

    Raises:
        ValidationError: If format is invalid
    """
    if not schedule:
        raise ValidationError("Cron schedule cannot be empty")

    parts = schedule.split()
    if len(parts) != 5:
        raise ValidationError(f"Cron expression must have 5 fields: {schedule}")

    # Basic validation - no need for full cron parsing here
    # Just ensure each part is either * or contains numbers/ranges
    valid_chars = set("0123456789*,/-")
    for i, part in enumerate(parts):
        if not all(c in valid_chars for c in part):
            raise ValidationError(f"Invalid characters in cron field {i}: {part}")


def validate_knowledge_topic(topic: Optional[str]) -> None:
    """
    Validate knowledge topic name.

    Args:
        topic: Topic name to validate

    Raises:
        ValidationError: If validation fails
    """
    if not topic:
        raise ValidationError("Knowledge topic cannot be empty")

    if len(topic) > 128:
        raise ValidationError(f"Topic name too long (max 128 chars): {topic}")

    # Allow more characters for topic than device name
    if not re.match(r"^[a-zA-Z0-9\s_\-\.（）()]+$", topic):
        raise ValidationError(f"Topic contains invalid characters: {topic}")


def validate_not_empty(value: Optional[str], field_name: str) -> None:
    """
    Generic validator for non-empty strings.

    Args:
        value: Value to check
        field_name: Name of field (for error messages)

    Raises:
        ValidationError: If value is empty
    """
    if not value or not str(value).strip():
        raise ValidationError(f"{field_name} cannot be empty")
