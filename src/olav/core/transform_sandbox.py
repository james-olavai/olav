"""Value Transform — Named Transformers (GAP-06, §3.4).

Stage 4 LLM outputs a transformer **name** (not code). This module executes
predefined transformers from the BUILTIN_TRANSFORMERS dict. No AST sandbox,
no RestrictedPython — LLM cannot generate arbitrary code.

Usage:
    from olav.core.transform_sandbox import apply_transform

    result = apply_transform("bytes_to_bps", "1000000")  # → 8000000
    result = apply_transform("bool_up_down", "up")        # → "UP"
    result = apply_transform(None, "1500")                 # → "1500" (passthrough)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _to_int(v: Any) -> int | None:
    """Safely convert to int, returning None on failure."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    """Safely convert to float, returning None on failure."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


BUILTIN_TRANSFORMERS: dict[str, Callable[[Any], Any]] = {
    # Unit conversions
    "bytes_to_bps": lambda v: _to_int(v) * 8 if _to_int(v) is not None else v,
    "kbps_to_bps": lambda v: _to_int(v) * 1_000 if _to_int(v) is not None else v,
    "mbps_to_bps": lambda v: _to_int(v) * 1_000_000 if _to_int(v) is not None else v,
    "gbps_to_bps": lambda v: _to_int(v) * 1_000_000_000 if _to_int(v) is not None else v,
    "ms_to_ns": lambda v: _to_int(v) * 1_000_000 if _to_int(v) is not None else v,
    "us_to_ns": lambda v: _to_int(v) * 1_000 if _to_int(v) is not None else v,
    "seconds_to_ms": lambda v: _to_int(v) * 1_000 if _to_int(v) is not None else v,
    # Boolean / state normalizers
    "bool_up_down": lambda v: "UP" if str(v).lower() in ("up", "true", "1", "active") else "DOWN",
    "bool_enabled_disabled": lambda v: (
        "ENABLED" if str(v).lower() in ("up", "true", "1", "enabled", "active") else "DISABLED"
    ),
    "bool_yes_no": lambda v: "YES" if str(v).lower() in ("yes", "true", "1", "up") else "NO",
    # String normalizers
    "lower": lambda v: str(v).lower() if v is not None else v,
    "upper": lambda v: str(v).upper() if v is not None else v,
    "strip": lambda v: str(v).strip() if v is not None else v,
    # Type casts
    "to_int": lambda v: _to_int(v) if v is not None else v,
    "to_float": lambda v: _to_float(v) if v is not None else v,
    "to_str": lambda v: str(v) if v is not None else v,
}


# List of available transformer names for LLM prompt
AVAILABLE_TRANSFORMERS: list[str] = sorted(BUILTIN_TRANSFORMERS.keys())


def apply_transform(name: str | None, value: Any) -> Any:
    """Apply a named transformer to a value.

    Args:
        name: Transformer name from BUILTIN_TRANSFORMERS, or None for passthrough.
        value: Input value to transform.

    Returns:
        Transformed result, or original value if name is None/unknown.
    """
    if name is None or not name or name == "null":
        return value

    fn = BUILTIN_TRANSFORMERS.get(name)
    if fn is None:
        logger.debug("Unknown transformer %r, returning original value", name)
        return value

    try:
        return fn(value)
    except (TypeError, ValueError, AttributeError) as exc:
        logger.debug("Transformer %r failed for value %r: %s", name, value, exc)
        return value
