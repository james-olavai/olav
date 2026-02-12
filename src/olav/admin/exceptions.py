"""
Exception definitions for Admin Agent.

Provides structured exception hierarchy for error handling and reporting.
"""


class AdminException(Exception):
    """Base exception for all Admin Agent errors."""

    def __init__(self, message: str, code: str = "ADMIN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(f"[{code}] {message}")


class ValidationError(AdminException):
    """Raised when parameter validation fails."""

    def __init__(self, message: str):
        super().__init__(message, "VALIDATION_ERROR")


class OperationError(AdminException):
    """Raised when an operation fails during execution."""

    def __init__(self, message: str):
        super().__init__(message, "OPERATION_ERROR")


class PathError(AdminException):
    """Raised when file path is invalid or not allowed."""

    def __init__(self, message: str):
        super().__init__(message, "PATH_ERROR")


class PermissionError(AdminException):
    """Raised when operation is not permitted (security policy)."""

    def __init__(self, message: str):
        super().__init__(message, "PERMISSION_ERROR")


class IntentError(AdminException):
    """Raised when intent cannot be identified or is not supported."""

    def __init__(self, message: str):
        super().__init__(message, "INTENT_ERROR")
