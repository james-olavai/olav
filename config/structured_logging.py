"""JSON Structured Logging - Phase 5 Day 3-6.

Provides JSON-formatted structured logging for production environments:
- Standardized log format (JSON)
- Request/response correlation
- Performance metrics tracking
- Alert-friendly structure
"""

import json
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from config.settings import settings


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Converts Python logging records to JSON format with:
    - Standard fields (timestamp, level, logger, message)
    - Contextual fields (request_id, user_id, etc.)
    - Performance metrics (duration, cache_hit)
    - Error details (exception, traceback)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hostname = self._get_hostname()

    @staticmethod
    def _get_hostname() -> str:
        """Get system hostname."""
        try:
            import socket

            return socket.gethostname()
        except Exception:
            return "unknown"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Python logging record

        Returns:
            JSON-formatted log string
        """
        # Base fields
        log_data = {
            "@timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "hostname": self.hostname,
            "process": {
                "pid": record.process,
                "thread": record.thread,
                "thread_name": record.threadName,
            },
            "location": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Add exception information if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add custom fields from record.__dict__
        # These are added via logger.info("msg", extra={"custom_field": "value"})
        extra_fields = {}
        for key, value in record.__dict__.items():
            # Skip standard logging attributes
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
            ]:
                extra_fields[key] = value

        if extra_fields:
            log_data["extra"] = extra_fields

        return json.dumps(log_data, ensure_ascii=False, default=str)


class StructuredLogger:
    """Structured logger wrapper with convenience methods.

    Provides high-level logging methods with automatic context:
    - query_start/query_end: Query lifecycle
    - cache_hit/cache_miss: Cache events
    - error: Error events with context
    - metric: Performance metrics
    """

    def __init__(self, name: str):
        """Initialize structured logger.

        Args:
            name: Logger name (typically module name)
        """
        self.logger = logging.getLogger(name)
        self._request_id = None
        self._start_time = None

    def set_request_id(self, request_id: str):
        """Set request ID for correlation.

        Args:
            request_id: Unique request identifier
        """
        self._request_id = request_id

    def query_start(self, query: str, **kwargs):
        """Log query start event.

        Args:
            query: Query text
            **kwargs: Additional context fields
        """
        self._start_time = time.time()
        self.logger.info(
            f"Query started: {query[:100]}...",
            extra={
                "event": "query_start",
                "request_id": self._request_id,
                "query": query,
                "query_length": len(query),
                **kwargs,
            },
        )

    def query_end(self, query: str, result_size: int = 0, **kwargs):
        """Log query end event.

        Args:
            query: Query text
            result_size: Number of results returned
            **kwargs: Additional context fields
        """
        duration = time.time() - self._start_time if self._start_time else 0
        self.logger.info(
            f"Query completed: {query[:100]}... ({duration:.2f}s)",
            extra={
                "event": "query_end",
                "request_id": self._request_id,
                "query": query,
                "duration_seconds": round(duration, 3),
                "result_size": result_size,
                **kwargs,
            },
        )

    def cache_hit(self, cache_key: str, **kwargs):
        """Log cache hit event.

        Args:
            cache_key: Cache key
            **kwargs: Additional context fields
        """
        self.logger.info(
            f"Cache hit: {cache_key[:50]}...",
            extra={
                "event": "cache_hit",
                "request_id": self._request_id,
                "cache_key": cache_key,
                **kwargs,
            },
        )

    def cache_miss(self, cache_key: str, **kwargs):
        """Log cache miss event.

        Args:
            cache_key: Cache key
            **kwargs: Additional context fields
        """
        self.logger.info(
            f"Cache miss: {cache_key[:50]}...",
            extra={
                "event": "cache_miss",
                "request_id": self._request_id,
                "cache_key": cache_key,
                **kwargs,
            },
        )

    def llm_call(self, model: str, tokens: int, duration: float, **kwargs):
        """Log LLM API call event.

        Args:
            model: LLM model name
            tokens: Token count (prompt + completion)
            duration: API call duration in seconds
            **kwargs: Additional context fields
        """
        self.logger.info(
            f"LLM call: {model} ({tokens} tokens, {duration:.2f}s)",
            extra={
                "event": "llm_call",
                "request_id": self._request_id,
                "model": model,
                "tokens": tokens,
                "duration_seconds": round(duration, 3),
                **kwargs,
            },
        )

    def error(self, message: str, error: Exception | None = None, **kwargs):
        """Log error event with context.

        Args:
            message: Error message
            error: Exception object (optional)
            **kwargs: Additional context fields
        """
        extra = {
            "event": "error",
            "request_id": self._request_id,
            **kwargs,
        }

        if error:
            extra["error_type"] = type(error).__name__
            extra["error_message"] = str(error)

        self.logger.error(message, extra=extra, exc_info=error is not None)

    def metric(self, metric_name: str, value: float, unit: str = "", **kwargs):
        """Log performance metric.

        Args:
            metric_name: Metric name
            value: Metric value
            unit: Metric unit (e.g., "ms", "bytes")
            **kwargs: Additional context fields
        """
        self.logger.info(
            f"Metric: {metric_name}={value}{unit}",
            extra={
                "event": "metric",
                "request_id": self._request_id,
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                **kwargs,
            },
        )

    def info(self, message: str, **kwargs):
        """Log info message with context.

        Args:
            message: Log message
            **kwargs: Additional context fields
        """
        extra = {"request_id": self._request_id, **kwargs}
        self.logger.info(message, extra=extra)

    def warning(self, message: str, **kwargs):
        """Log warning message with context.

        Args:
            message: Log message
            **kwargs: Additional context fields
        """
        extra = {"request_id": self._request_id, **kwargs}
        self.logger.warning(message, extra=extra)

    def debug(self, message: str, **kwargs):
        """Log debug message with context.

        Args:
            message: Log message
            **kwargs: Additional context fields
        """
        extra = {"request_id": self._request_id, **kwargs}
        self.logger.debug(message, extra=extra)


def setup_structured_logging(
    log_level: str = "INFO",
    log_file: str = "logs/olav.json",
    enable_console: bool = True,
    max_bytes: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 10,
):
    """Setup JSON structured logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to JSON log file
        enable_console: Enable console logging (for development)
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers
    logger.handlers.clear()

    # JSON file handler with rotation
    try:
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not create JSON log file {log_file}: {e}")

    # Console handler (plain text for readability)
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        # Use simple format for console
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # Reduce noise from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("nornir").setLevel(logging.ERROR)


def get_structured_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name)


# Auto-setup if settings indicate JSON logging
if getattr(settings, "log_format", "text") == "json":
    setup_structured_logging(
        log_level=settings.log_level,
        log_file="logs/olav.json",
        enable_console=getattr(settings, "debug", False),
    )
