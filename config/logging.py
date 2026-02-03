"""Logging configuration for OLAV.

Configures application-wide logging with:
- Console output for interactive use
- File output to data/logs/olav.log
- Rotating file handler to prevent log bloat
- Optional JSON structured logging (settings.log_format="json")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/olav.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    log_format: Literal["text", "json"] = "text",
) -> None:
    """Configure application logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep
        log_format: Log format ("text" or "json")
    """
    # Use JSON logging if requested
    if log_format == "json":
        from config.structured_logging import setup_structured_logging
        
        setup_structured_logging(
            log_level=log_level,
            log_file=log_file.replace(".log", ".json"),
            enable_console=True,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
        return
    
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers
    logger.handlers.clear()

    # Format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler with rotation
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not create log file {log_file}: {e}")

    # Reduce noise from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)

    # Nornir noise
    logging.getLogger("nornir").setLevel(logging.ERROR)  # High noise
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning, module="nornir")

    # Internal OLAV noise
    logging.getLogger("olav.core.registry").setLevel(logging.WARNING)
    logging.getLogger("olav.core.query_router").setLevel(logging.WARNING)
    logging.getLogger("olav.tools.schema_catalog").setLevel(logging.WARNING)
    logging.getLogger("olav.tools.raw_importer").setLevel(logging.WARNING)
    logging.getLogger("olav.agents").setLevel(logging.WARNING)
    logging.getLogger("olav.analysis").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
