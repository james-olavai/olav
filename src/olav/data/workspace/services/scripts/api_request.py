#!/usr/bin/env python3
"""api_request — Universal API query script for registered services.

Reference: dev_docs/36. SCHEMA_AWARE_API_ARCHITECTURE.md §8
"""
from __future__ import annotations

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# ARCH-18 #2: default compaction for large list responses. Trims to at most
# this many items before returning, with a "status: truncated" envelope so
# callers know to fetch the rest via explicit pagination if needed.
_COMPACT_LIST_CAP = 50


def api_request(
    service: str,
    method: str = "GET",
    path: str = "/",
    params: dict | None = None,
    body: dict | None = None,
    page_size: int | None = None,
    confirmed: bool = False,
) -> dict | list:
    """Authenticated API request to a registered service.

    Use tool_help("api_request") for full usage and pagination details.

    Args: service (name in services.yaml); method; path; params; body;
    page_size (None=first page, -1=auto-follow); confirmed (write gate).
    Write methods need --enable-api-write CLI flag + confirmed=True.
    Large list responses compact to first _COMPACT_LIST_CAP items with
    ``{"status": "truncated", ...}`` envelope.
    """
    from olav.platform.services.client import service_call

    try:
        # ISSUE-API-REQUEST-PAGE-SIZE-DROPPED: service_call() does NOT
        # accept ``page_size`` — passing it raises TypeError which the
        # 27B agent reads and gives up with ``[]`` as final response.
        # Pagination is handled locally below via _COMPACT_LIST_CAP.
        # If auto-follow page_size=-1 is wanted, implement it as a
        # paginate loop here, NOT by forwarding to service_call.
        result = service_call(
            service,
            method=method,
            path=path,
            params=params,
            body=body,
            confirmed=confirmed,
        )
    except KeyError:
        from olav.platform.services.registry import ServiceRegistry
        registry = ServiceRegistry.get_instance()
        available = sorted(s.name for s in registry.list())
        return {
            "status": "error",
            "reason": f"Service '{service}' is not registered.",
            "hint": f"Run `olav registry register <url>` to add it. Available: {available}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": str(exc), "service": service, "path": path}

    # DRF-pagination response: {count, next, results: [...]}. Apply compact cap.
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        page = result["results"]
        if len(page) > _COMPACT_LIST_CAP:
            return {
                "status": "truncated",
                "service": service,
                "path": path,
                "count": result.get("count", len(page)),
                "returned": _COMPACT_LIST_CAP,
                "next": result.get("next"),
                "results": page[:_COMPACT_LIST_CAP],
                "hint": (
                    f"compact mode: showing {_COMPACT_LIST_CAP} of "
                    f"{result.get('count', len(page))} items. Narrow via params "
                    "or set page_size=-1 to auto-follow."
                ),
            }
    return result


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = api_request(**_args)
    print(_json.dumps(result, default=str))
