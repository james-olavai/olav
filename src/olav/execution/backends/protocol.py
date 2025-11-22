"""Backend protocol definitions for execution and storage."""

from typing import Any, Protocol


class BackendProtocol(Protocol):
    """Base backend protocol for file-like operations."""

    async def read(self, path: str) -> str:
        """Read content from a path.

        Args:
            path: Path to read from

        Returns:
            Content as string
        """
        ...

    async def write(self, path: str, content: str) -> None:
        """Write content to a path.

        Args:
            path: Path to write to
            content: Content to write
        """
        ...


class ExecutionResult:
    """Result from sandbox execution."""

    def __init__(
        self,
        success: bool,
        output: str,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize execution result.

        Args:
            success: Whether execution succeeded
            output: Standard output
            error: Error message if failed
            metadata: Additional metadata
        """
        self.success = success
        self.output = output
        self.error = error
        self.metadata = metadata or {}


class SandboxBackendProtocol(BackendProtocol, Protocol):
    """Sandbox backend for safe command execution with HITL."""

    async def execute(
        self,
        command: str,
        background: bool = False,
        requires_approval: bool = True,
    ) -> ExecutionResult:
        """Execute command in sandbox with optional approval.

        Args:
            command: Command to execute
            background: Run in background
            requires_approval: Whether to request HITL approval

        Returns:
            Execution result
        """
        ...


class StoreBackendProtocol(BackendProtocol, Protocol):
    """Storage backend for key-value operations."""

    async def put(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any],
    ) -> None:
        """Store value in namespace.

        Args:
            namespace: Storage namespace
            key: Key to store under
            value: Value to store
        """
        ...

    async def get(
        self,
        namespace: str,
        key: str,
    ) -> dict[str, Any] | None:
        """Retrieve value from namespace.

        Args:
            namespace: Storage namespace
            key: Key to retrieve

        Returns:
            Stored value or None if not found
        """
        ...
