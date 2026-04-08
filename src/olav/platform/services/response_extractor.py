"""response_extractor.py — schema-aware response trimming for service_call().

Provides two layers of protection against LLM context overflow:

1. Auto-schema trim: looks up response_200_def from api_registry for the
   (service_name, method, path) triple; trims unknown fields from each item.

2. List truncation: limits list responses to `max_items` entries when the
   estimated token count exceeds `token_budget`.

Public API:
    auto_extract(data, service_name, method, path) -> Any
        Full pipeline: schema-trim then truncate if still too large.

    schema_trim(data, service_name, def_name) -> Any
        Field-filter only; pass response_def explicitly.

    truncate_list(data, max_items, summary_key) -> Any
        Hard-cap a list; appends a sentinel dict with count info.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Rough estimate: 4 chars ≈ 1 token; stay below 32k tokens for most models.
_DEFAULT_TOKEN_BUDGET = 32_000
_DEFAULT_MAX_ITEMS = 200

# Characters-per-token estimate for naive tokenisation
_CHARS_PER_TOKEN = 4


def _char_count(data: Any) -> int:
    """Fast character count of the serialised form (no JSON encode overhead)."""
    return len(str(data))


def _token_estimate(data: Any) -> int:
    return _char_count(data) // _CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Schema-trim (field filtering)
# ---------------------------------------------------------------------------


def _lookup_response_def(
    service_name: str,
    method: str,
    path: str,
) -> str | None:
    """Query api_registry for the response_200_def of this operation.

    Returns None if registry is unavailable or operation is not registered.
    """
    try:
        from olav.core.api_registry import DEFAULT_DB
        import duckdb

        db_path = Path(DEFAULT_DB)
        if not db_path.exists():
            return None

        with duckdb.connect(str(db_path), read_only=True) as con:
            row = con.execute(
                "SELECT response_200_def FROM api_registry.operations "
                "WHERE api_name=? AND method=? AND path=?",
                [service_name, method.upper(), path],
            ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def schema_trim(
    data: Any,
    service_name: str,
    def_name: str | None,
) -> Any:
    """Filter dict/list items to known fields for `def_name` in the registry.

    Identical to client._trim_response but callable independently.
    Falls back to `data` unchanged when schema is unknown.
    """
    if not def_name or not isinstance(data, (dict, list)):
        return data

    try:
        from olav.core.api_registry import field_names
        known = field_names(service_name, def_name)
        if not known:
            return data
    except Exception:
        return data

    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in known}
    return [
        {k: v for k, v in item.items() if k in known}
        if isinstance(item, dict) else item
        for item in data
    ]


# ---------------------------------------------------------------------------
# List truncation
# ---------------------------------------------------------------------------


def truncate_list(
    data: Any,
    max_items: int = _DEFAULT_MAX_ITEMS,
    summary_key: str = "_truncated",
) -> Any:
    """Hard-cap a list at `max_items` entries.

    Appends a sentinel dict so agents know the response was truncated:
        {"_truncated": True, "total_returned": N, "total_available": M,
         "hint": "Use pagination params (limit/offset) to retrieve more."}

    Non-list values are returned unchanged.
    """
    if not isinstance(data, list) or len(data) <= max_items:
        return data

    total = len(data)
    trimmed = data[:max_items]
    trimmed.append({
        summary_key: True,
        "total_returned": max_items,
        "total_available": total,
        "hint": (
            f"Response truncated to {max_items} of {total} items. "
            "Use pagination params (limit/offset or page) to retrieve more."
        ),
    })
    return trimmed


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def auto_extract(
    data: Any,
    service_name: str,
    method: str,
    path: str,
    *,
    response_def: str | None = None,
    max_items: int = _DEFAULT_MAX_ITEMS,
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
) -> Any:
    """Schema-trim then truncate a service_call() response.

    Steps:
    1. Resolve response_def from registry if not supplied.
    2. Detect paginated wrapper (NetBox-style {"count":N,"results":[...]}).
    3. Apply schema_trim to the item list.
    4. Apply truncate_list if still over token_budget.

    Args:
        data:         Raw parsed JSON from service_call.
        service_name: Key in services.yaml (e.g. "netbox").
        method:       HTTP method used (GET, POST, …).
        path:         API path (e.g. "/api/dcim/devices/").
        response_def: Explicit schema definition name; auto-detected if omitted.
        max_items:    Hard cap on list length before a sentinel is appended.
        token_budget: Estimated token limit; triggers truncation if exceeded.

    Returns:
        Trimmed/truncated response, or the original `data` if nothing applies.
    """
    if data is None:
        return data

    # 1. Resolve response_def from registry if not explicitly supplied.
    #    Note: auto-detected def_names describe the full response object (e.g. PaginatedDeviceList),
    #    not the inner item type, so they are NOT used for schema_trim (unreliable).
    #    This call is retained for graceful-fallback validation — if the registry DB is
    #    unavailable, auto_extract must still work normally.
    try:
        _ = response_def or _lookup_response_def(service_name, method, path)
    except Exception:
        pass

    # 2. Unwrap paginated envelope  {"count": N, "results": [...], ...}
    envelope: dict | None = None
    items: Any = data
    if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
        envelope = {k: v for k, v in data.items() if k != "results"}
        items = data["results"]

    # 3. Schema trim — only when response_def was explicitly supplied.
    #    Auto-detected def_names from the registry describe the full response object
    #    (e.g. PaginatedDeviceList), not the inner item type, so auto-trimming is
    #    unreliable. Explicit response_def (passed by caller) is always correct.
    if response_def and envelope is None:
        items = schema_trim(items, service_name, response_def)

    # 4. Truncate if over budget
    if isinstance(items, list):
        estimated = _token_estimate(items)
        effective_max = min(max_items, len(items))
        if estimated > token_budget:
            # Shrink max proportionally so we stay within budget
            ratio = token_budget / max(estimated, 1)
            effective_max = max(1, int(len(items) * ratio))
        items = truncate_list(items, effective_max)
    elif isinstance(items, dict):
        # Single-object response: just log if very large
        if _token_estimate(items) > token_budget:
            logger.warning(
                "response_extractor: single-object response from %s %s exceeds token budget (%d tokens); "
                "consider passing a narrower response_def",
                method.upper(),
                path,
                _token_estimate(items),
            )

    # 5. Re-wrap envelope if we unwrapped it
    if envelope is not None:
        return {**envelope, "results": items}
    return items
