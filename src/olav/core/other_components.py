"""
Other Components Enhancements

Provides improvements to core components:
- InputParser advanced parsing and validation
- NetworkExecutor timeout and error handling
- Storage persistence and recovery
- APIClient retry logic and resilience
"""

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ParseStrategy(Enum):
    """Parsing strategies for input."""

    STRICT = "strict"
    LENIENT = "lenient"
    INTELLIGENT = "intelligent"


class RetryStrategy(Enum):
    """Retry strategy for API calls."""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIBONACCI = "fibonacci"


@dataclass
class ParseResult:
    """Result of input parsing."""

    success: bool
    command: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    raw_input: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if parse was successful."""
        return self.success and len(self.errors) == 0


class InputParser:
    """Advanced input parsing with multiple strategies."""

    def __init__(
        self,
        strategy: ParseStrategy = ParseStrategy.INTELLIGENT,
        max_args: int = 10,
        max_arg_length: int = 1000,
    ):
        """Initialize parser."""
        self.strategy = strategy
        self.max_args = max_args
        self.max_arg_length = max_arg_length
        self._command_registry: dict[str, dict[str, Any]] = {}

    def register_command(
        self,
        name: str,
        min_args: int = 0,
        max_args: int | None = None,
        arg_types: list[str] | None = None,
    ) -> None:
        """
        Register a command with argument requirements.

        Args:
            name: Command name
            min_args: Minimum number of arguments
            max_args: Maximum number of arguments
            arg_types: Expected argument types
        """
        self._command_registry[name] = {
            "min_args": min_args,
            "max_args": max_args or self.max_args,
            "arg_types": arg_types or [],
        }

    def parse(self, user_input: str) -> ParseResult:
        """
        Parse user input based on configured strategy.

        Args:
            user_input: Raw user input string

        Returns:
            ParseResult with parsed components
        """
        result = ParseResult(success=False, raw_input=user_input)

        if not user_input or not isinstance(user_input, str):
            result.errors.append("Input must be a non-empty string")
            return result

        # Choose parsing strategy
        if self.strategy == ParseStrategy.STRICT:
            return self._parse_strict(user_input)
        elif self.strategy == ParseStrategy.LENIENT:
            return self._parse_lenient(user_input)
        else:
            return self._parse_intelligent(user_input)

    def _parse_strict(self, user_input: str) -> ParseResult:
        """
        Strict parsing - exact format required.
        Format: command arg1=value1 arg2=value2 --flag1 --flag2
        """
        result = ParseResult(success=False, raw_input=user_input)
        parts = user_input.split()

        if not parts:
            result.errors.append("No command provided")
            return result

        result.command = parts[0]

        # Check if command is registered
        if result.command not in self._command_registry:
            result.warnings.append(f"Command '{result.command}' not registered")

        # Parse arguments and flags
        for part in parts[1:]:
            if part.startswith("--"):
                result.flags.append(part[2:])
            elif "=" in part:
                key, value = part.split("=", 1)
                result.arguments[key] = self._parse_value(value)
            else:
                result.errors.append(f"Invalid argument format: {part}")

        result.success = len(result.errors) == 0
        return result

    def _parse_lenient(self, user_input: str) -> ParseResult:
        """
        Lenient parsing - flexible format, best effort.
        """
        result = ParseResult(success=False, raw_input=user_input)
        parts = user_input.split()

        if not parts:
            result.errors.append("No command provided")
            return result

        result.command = parts[0]

        # Flexible argument parsing
        i = 1
        while i < len(parts):
            part = parts[i]

            if part.startswith("--"):
                result.flags.append(part[2:])
            elif part.startswith("-"):
                # Short flag or key
                if "=" in part:
                    key, value = part[1:].split("=", 1)
                    result.arguments[key] = self._parse_value(value)
                else:
                    result.flags.append(part[1:])
            elif "=" in part:
                key, value = part.split("=", 1)
                result.arguments[key] = self._parse_value(value)
            elif i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                # Positional argument
                result.arguments[f"arg_{i - 1}"] = self._parse_value(part)
            else:
                result.arguments[f"arg_{i - 1}"] = self._parse_value(part)

            i += 1

        # Validation
        if result.command in self._command_registry:
            registry = self._command_registry[result.command]
            arg_count = len(result.arguments)

            if arg_count < registry["min_args"]:
                result.warnings.append(
                    f"Command expects at least {registry['min_args']} arguments, got {arg_count}"
                )
            elif arg_count > registry["max_args"]:
                result.warnings.append(
                    f"Command expects at most {registry['max_args']} arguments, got {arg_count}"
                )

        result.success = True
        return result

    def _parse_intelligent(self, user_input: str) -> ParseResult:
        """
        Intelligent parsing - auto-detect format and parse accordingly.
        """
        # Try strict first
        strict_result = self._parse_strict(user_input)
        if strict_result.errors:
            # Fall back to lenient
            return self._parse_lenient(user_input)

        return strict_result

    @staticmethod
    def _parse_value(value: str) -> Any:
        """Parse a value string to appropriate type."""
        # Try integer
        try:
            return int(value)
        except ValueError:
            pass

        # Try float
        try:
            return float(value)
        except ValueError:
            pass

        # Try boolean
        if value.lower() in ("true", "yes", "on"):
            return True
        elif value.lower() in ("false", "no", "off"):
            return False

        # Return as string
        return value


@dataclass
class NetworkRequest:
    """Represents a network request with timeout."""

    url: str
    method: str = "GET"
    timeout: float = 30.0
    max_retries: int = 3
    retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    headers: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] | None = None

    def validate(self) -> tuple[bool, list[str]]:
        """Validate request configuration."""
        errors = []

        if not self.url:
            errors.append("URL cannot be empty")

        if self.timeout <= 0:
            errors.append("Timeout must be positive")

        if self.max_retries < 0:
            errors.append("Max retries cannot be negative")

        if self.method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            errors.append(f"Invalid HTTP method: {self.method}")

        return len(errors) == 0, errors


class NetworkExecutor:
    """Executes network operations with timeout and retry logic."""

    def __init__(self, max_workers: int = 5, default_timeout: float = 30.0):
        """Initialize executor."""
        self.max_workers = max_workers
        self.default_timeout = default_timeout
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._request_cache: dict[str, tuple[Any, datetime]] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "retry_count": 0,
        }
        self._stats_lock = threading.RLock()

    def execute(self, request: NetworkRequest) -> tuple[bool, Any | None, str | None]:
        """
        Execute network request with timeout and retries.

        Args:
            request: NetworkRequest to execute

        Returns:
            Tuple of (success, response, error_message)
        """
        # Validate request
        is_valid, errors = request.validate()
        if not is_valid:
            return False, None, "; ".join(errors)

        # Check cache
        cache_key = self._get_cache_key(request)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return True, cached, None

        # Execute with retries
        retry_count = 0
        last_error = None

        for attempt in range(request.max_retries):
            try:
                # Calculate timeout for this attempt
                timeout = request.timeout * (1 if attempt == 0 else 2)

                # Simulate network execution
                result = self._execute_request(request, timeout)

                with self._stats_lock:
                    self._stats["total_requests"] += 1
                    self._stats["successful_requests"] += 1

                # Cache successful result
                self._cache_result(cache_key, result)

                return True, result, None

            except TimeoutError as e:
                last_error = str(e)
                retry_count += 1
                if attempt < request.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt, request.retry_strategy)
                    time.sleep(wait_time)

            except Exception as e:
                last_error = str(e)
                retry_count += 1
                if attempt < request.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt, request.retry_strategy)
                    time.sleep(wait_time)

        with self._stats_lock:
            self._stats["total_requests"] += 1
            self._stats["failed_requests"] += 1
            self._stats["retry_count"] += retry_count

        return False, None, last_error

    @staticmethod
    def _execute_request(request: NetworkRequest, timeout: float) -> dict[str, Any]:
        """
        Execute a network request.

        Args:
            request: NetworkRequest
            timeout: Timeout in seconds

        Returns:
            Response data
        """
        # Simulate request execution
        return {
            "status": 200,
            "url": request.url,
            "method": request.method,
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def _calculate_backoff(attempt: int, strategy: RetryStrategy) -> float:
        """Calculate backoff time based on strategy."""
        if strategy == RetryStrategy.EXPONENTIAL:
            return min(2**attempt, 32)
        elif strategy == RetryStrategy.LINEAR:
            return attempt + 1
        elif strategy == RetryStrategy.FIBONACCI:
            a, b = 0, 1
            for _ in range(attempt):
                a, b = b, a + b
            return float(b)

        return 1.0

    def _get_cache_key(self, request: NetworkRequest) -> str:
        """Generate cache key for request."""
        key_str = f"{request.method}:{request.url}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Any | None:
        """Get cached response if valid."""
        if cache_key in self._request_cache:
            response, timestamp = self._request_cache[cache_key]
            if datetime.now() - timestamp < self._cache_ttl:
                return response
            else:
                del self._request_cache[cache_key]

        return None

    def _cache_result(self, cache_key: str, result: Any) -> None:
        """Cache a successful result."""
        self._request_cache[cache_key] = (result, datetime.now())

    def get_stats(self) -> dict[str, int]:
        """Get execution statistics."""
        with self._stats_lock:
            return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset execution statistics."""
        with self._stats_lock:
            self._stats = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "retry_count": 0,
            }

    def shutdown(self) -> None:
        """Shutdown executor."""
        self._executor.shutdown(wait=True)


@dataclass
class StorageItem:
    """Item stored in persistent storage."""

    key: str
    value: Any
    timestamp: datetime = field(default_factory=datetime.now)
    ttl: int | None = None  # seconds

    def is_expired(self) -> bool:
        """Check if item has expired."""
        if self.ttl is None:
            return False

        age = (datetime.now() - self.timestamp).total_seconds()
        return age > self.ttl


class PersistentStorage:
    """Thread-safe persistent storage with TTL support."""

    def __init__(self, storage_dir: Path | None = None):
        """Initialize storage."""
        self.storage_dir = Path(storage_dir or Path.home() / ".olav" / "storage")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, StorageItem] = {}
        self._lock = threading.RLock()
        self._load_from_disk()

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """
        Store a value with optional TTL.

        Args:
            key: Storage key
            value: Value to store
            ttl: Time to live in seconds

        Returns:
            True if stored successfully
        """
        try:
            item = StorageItem(key=key, value=value, ttl=ttl)

            with self._lock:
                self._memory_cache[key] = item

            # Persist to disk
            self._save_item(item)
            logger.debug(f"Stored item: {key}")
            return True

        except Exception as e:
            logger.error(f"Error storing item {key}: {e}")
            return False

    def get(self, key: str) -> Any | None:
        """
        Retrieve a value.

        Args:
            key: Storage key

        Returns:
            Value if found and not expired, None otherwise
        """
        with self._lock:
            if key not in self._memory_cache:
                return None

            item = self._memory_cache[key]

            if item.is_expired():
                del self._memory_cache[key]
                self._delete_item(item)
                return None

            return item.value

    def delete(self, key: str) -> bool:
        """Delete a stored value."""
        with self._lock:
            if key in self._memory_cache:
                item = self._memory_cache[key]
                del self._memory_cache[key]
                self._delete_item(item)
                return True

        return False

    def clear(self) -> None:
        """Clear all storage."""
        with self._lock:
            self._memory_cache.clear()

        # Delete all files
        for file in self.storage_dir.glob("*.json"):
            try:
                file.unlink()
            except Exception as e:
                logger.error(f"Error deleting {file}: {e}")

    def _save_item(self, item: StorageItem) -> None:
        """Save an item to disk."""
        file_path = self.storage_dir / f"{item.key}.json"

        try:
            data = {
                "key": item.key,
                "value": item.value,
                "timestamp": item.timestamp.isoformat(),
                "ttl": item.ttl,
            }

            file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        except Exception as e:
            logger.error(f"Error saving item to disk: {e}")

    def _delete_item(self, item: StorageItem) -> None:
        """Delete an item from disk."""
        file_path = self.storage_dir / f"{item.key}.json"

        try:
            if file_path.exists():
                file_path.unlink()

        except Exception as e:
            logger.error(f"Error deleting item from disk: {e}")

    def _load_from_disk(self) -> None:
        """Load all items from disk."""
        if not self.storage_dir.exists():
            return

        for file in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))

                item = StorageItem(
                    key=data["key"],
                    value=data["value"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    ttl=data.get("ttl"),
                )

                # Skip expired items
                if not item.is_expired():
                    self._memory_cache[item.key] = item
                else:
                    file.unlink()

            except Exception as e:
                logger.error(f"Error loading {file}: {e}")


@dataclass
class APIRequest:
    """API request configuration."""

    endpoint: str
    method: str = "GET"
    timeout: float = 30.0
    payload: dict[str, Any] | None = None
    auth_token: str | None = None
    max_retries: int = 3

    def validate(self) -> tuple[bool, list[str]]:
        """Validate request."""
        errors = []

        if not self.endpoint:
            errors.append("Endpoint cannot be empty")

        if self.timeout <= 0:
            errors.append("Timeout must be positive")

        if self.max_retries < 0:
            errors.append("Max retries cannot be negative")

        return len(errors) == 0, errors


class APIClient:
    """API client with retry logic and error handling."""

    def __init__(self, base_url: str = "", max_retries: int = 3):
        """Initialize client."""
        self.base_url = base_url
        self.max_retries = max_retries
        self._session_headers: dict[str, str] = {}
        self._request_history: list[dict[str, Any]] = []
        self._history_lock = threading.RLock()

    def set_auth(self, token: str) -> None:
        """Set authentication token."""
        self._session_headers["Authorization"] = f"Bearer {token}"

    def set_header(self, key: str, value: str) -> None:
        """Set custom header."""
        self._session_headers[key] = value

    def request(self, api_req: APIRequest) -> tuple[bool, dict[str, Any] | None, str | None]:
        """
        Execute API request with automatic retries.

        Args:
            api_req: API request configuration

        Returns:
            Tuple of (success, response, error_message)
        """
        # Validate request
        is_valid, errors = api_req.validate()
        if not is_valid:
            return False, None, "; ".join(errors)

        url = self._build_url(api_req.endpoint)
        last_error = None

        for attempt in range(api_req.max_retries):
            try:
                # Simulate request
                response = self._execute_request(
                    url, api_req.method, api_req.payload, api_req.timeout
                )

                # Record in history
                self._record_request(url, api_req.method, True, None)

                return True, response, None

            except TimeoutError as e:
                last_error = f"Timeout: {e}"

                if attempt < api_req.max_retries - 1:
                    wait_time = self._calculate_wait_time(attempt)
                    time.sleep(wait_time)

            except Exception as e:
                last_error = str(e)

                if attempt < api_req.max_retries - 1:
                    wait_time = self._calculate_wait_time(attempt)
                    time.sleep(wait_time)

        # Record final failure
        self._record_request(url, api_req.method, False, last_error)

        return False, None, last_error

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from base and endpoint."""
        if self.base_url:
            return f"{self.base_url}/{endpoint.lstrip('/')}"
        return endpoint

    @staticmethod
    def _execute_request(
        url: str, method: str, payload: dict[str, Any] | None, timeout: float
    ) -> dict[str, Any]:
        """Execute HTTP request."""
        return {
            "status": 200,
            "url": url,
            "method": method,
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def _calculate_wait_time(attempt: int) -> float:
        """Calculate exponential backoff."""
        return min(2**attempt, 32)

    def _record_request(self, url: str, method: str, success: bool, error: str | None) -> None:
        """Record request in history."""
        with self._history_lock:
            self._request_history.append(
                {
                    "url": url,
                    "method": method,
                    "success": success,
                    "error": error,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Keep only last 100 requests
            if len(self._request_history) > 100:
                self._request_history = self._request_history[-100:]

    def get_request_history(self) -> list[dict[str, Any]]:
        """Get request history."""
        with self._history_lock:
            return list(self._request_history)

    def clear_history(self) -> None:
        """Clear request history."""
        with self._history_lock:
            self._request_history.clear()
