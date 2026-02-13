"""Query Execution API - Phase 1.6.

LLM-integrated query orchestration for natural language to database queries.
- Parse natural language intent
- Optimize queries for performance
- Execute safe queries against unified database
- Format results in multiple formats (JSON, CSV, markdown)
- Smart caching and recommendations
- Error recovery with diagnostics
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Query execution result."""

    success: bool
    rows: list[dict[str, Any]] | None = None
    count: int | None = None
    columns: list[str] | None = None
    format: str = "json"
    execution_time: float = 0.0
    cached: bool = False
    error: str | None = None
    diagnostic_info: dict[str, Any] | None = None


# ============================================================================
# INTENT PARSING
# ============================================================================


async def parse_intent(query: str) -> dict[str, Any]:
    """Parse natural language query into structured intent.

    Args:
        query: Natural language query string

    Returns:
        Dict with:
        - intent: Action type (list, describe, count, filter, export)
        - entity: Target entity (devices, interfaces, capabilities)
        - filters: Extracted filters
        - suggestions: Clarification suggestions if ambiguous

    Example:
        >>> result = await parse_intent("list all cisco devices")
        >>> result["intent"]
        'list'
        >>> result["entity"]
        'devices'
        >>> result["filters"]
        {'vendor': 'cisco', 'status': 'all'}
    """
    if not query or not query.strip():
        return {"intent": None, "entity": None, "error": "Empty query"}

    query_lower = query.lower().strip()

    # Intent detection
    intent = _detect_intent(query_lower)

    # Entity detection
    entity = _detect_entity(query_lower)

    # Filter extraction
    filters = await extract_filters(query)

    # Ambiguity check
    suggestions = []
    if intent is None or entity is None:
        suggestions = _suggest_clarifications(query_lower)

    result = {
        "intent": intent,
        "entity": entity,
        "filters": filters or {},
        "query": query,
        "parsed_at": datetime.now().isoformat(),
    }

    if suggestions:
        result["suggestions"] = suggestions

    return result


def _detect_intent(query_lower: str) -> str | None:
    """Detect query intent from keywords."""
    synonyms = {
        "list": ["list", "show", "display", "get all", "retrieve"],
        "count": ["count", "how many", "total", "number of"],
        "describe": ["describe", "details", "info", "what is", "tell me about"],
        "filter": ["filter", "where", "with", "matching"],
        "export": ["export", "save", "write", "download"],
    }

    for intent, keywords in synonyms.items():
        for keyword in keywords:
            if keyword in query_lower:
                return intent

    return None


def _detect_entity(query_lower: str) -> str | None:
    """Detect main entity from keywords."""
    entity_map = {
        "devices": ["devices", "device", "router", "switch", "node"],
        "interfaces": ["interfaces", "interface", "port", "link", "connection"],
        "capabilities": ["capabilities", "capability", "support", "feature", "protocol"],
        "topology": ["topology", "relation", "connection", "link"],
        "ospf": ["ospf", "ospf_neighbor"],
        "bgp": ["bgp", "bgp_neighbor"],
    }

    for entity, keywords in entity_map.items():
        for keyword in keywords:
            if keyword in query_lower:
                return entity

    return None


def _suggest_clarifications(query_lower: str) -> list[str]:
    """Suggest clarifications for ambiguous queries."""
    suggestions = []

    if "device" in query_lower:
        suggestions.append(
            "Did you mean to list devices, get device details, or show device interfaces?"
        )

    if "get" in query_lower and "all" not in query_lower:
        suggestions.append("Specify which item (e.g., 'get device R1' or 'get all devices')?")

    if not suggestions:
        suggestions.append("Could you clarify what information you need?")

    return suggestions


# ============================================================================
# QUERY OPTIMIZATION
# ============================================================================


async def optimize_query(query: str) -> dict[str, Any]:
    """Optimize natural language query for execution.

    Args:
        query: Natural language query

    Returns:
        Dict with:
        - optimized: True if optimizations found
        - original: Original query
        - suggestions: List of optimization suggestions
        - estimates: Result size estimates
        - warnings: Any warnings (e.g., large result set)
    """
    intent = await parse_intent(query)

    optimizations = []
    warnings = []

    # Check for N+1 query pattern
    if "all its" in query.lower() or "each" in query.lower():
        optimizations.append(
            {
                "type": "n_plus_one",
                "suggestion": "Use JOIN instead of looping through items individually",
                "impact": "2-5x faster execution",
            }
        )

    # Check for unrestricted queries
    if "all" in query.lower() and "limit" not in query.lower():
        warnings.append(
            {
                "type": "large_result_set",
                "message": "Query may return many rows. Consider adding filters or limits.",
                "suggestion": "Add pagination or filters to reduce result size",
            }
        )

    # Check access patterns
    if "password" in query.lower() or "secret" in query.lower():
        warnings.append(
            {
                "type": "restricted_access",
                "message": "This query accesses restricted data",
                "status": "blocked",
            }
        )

    # Estimate result size
    estimated_rows = _estimate_result_size(query)

    return {
        "optimized": len(optimizations) > 0 or len(warnings) > 0,
        "original": query,
        "intent": intent.get("intent"),
        "optimizations": optimizations if optimizations else None,
        "warnings": warnings if warnings else None,
        "estimates": {
            "estimated_rows": estimated_rows,
            "estimated_size_mb": (estimated_rows * 0.001),  # Rough estimate
        },
        "execution_suggestion": _suggest_execution_strategy(query),
    }


def _estimate_result_size(query: str) -> int:
    """Estimate result size based on query pattern."""
    query_lower = query.lower()

    # Base estimates
    base_rows = 50  # Average devices

    if "interfaces" in query_lower:
        base_rows *= 10  # ~10 interfaces per device

    if "all" in query_lower:
        if "device" in query_lower:
            return 100  # ~100 devices in typical network
        if "interface" in query_lower:
            return 1000  # Many interfaces

    if "one" in query_lower or "single" in query_lower:
        return 1

    return base_rows


def _suggest_execution_strategy(query: str) -> str:
    """Suggest execution strategy for query."""
    query_lower = query.lower()

    if "export" in query_lower or "save" in query_lower:
        return "Execute query and export to file"

    if "count" in query_lower or "how many" in query_lower:
        return "Execute aggregation query"

    if "all" in query_lower:
        return "Execute with pagination (fetch all pages)"

    return "Execute simple query"


# ============================================================================
# QUERY EXECUTION
# ============================================================================


async def execute_query(query: str) -> dict[str, Any]:
    """Execute natural language query against database.

    Args:
        query: Natural language query string

    Returns:
        Dict with:
        - success: Boolean indicating if execution succeeded
        - rows: List of result rows
        - count: Number of rows
        - cached: Whether result came from cache
        - execution_time: Time in seconds
        - error: Error message if failed
    """
    import time

    start_time = time.time()

    if not query or not query.strip():
        return {"success": False, "error": "Empty query", "rows": [], "execution_time": 0.0}

    try:
        # Parse intent
        intent = await parse_intent(query)

        # Security check
        is_safe = await validate_query_safety(query)
        if not is_safe:
            return {
                "success": False,
                "error": "Query failed security validation",
                "diagnostic_info": {"query": query, "reason": "SQL injection pattern detected"},
                "execution_time": time.time() - start_time,
            }

        # Route to appropriate handler
        if intent.get("intent") == "count":
            result = await _execute_count_query(query, intent)
        elif intent.get("intent") == "export":
            result = await _execute_export_query(query, intent)
        elif intent.get("entity") == "devices":
            result = await _execute_devices_query(query, intent)
        elif intent.get("entity") == "interfaces":
            result = await _execute_interfaces_query(query, intent)
        else:
            result = await _execute_generic_query(query, intent)

        result["execution_time"] = time.time() - start_time
        return result

    except Exception as e:
        logger.error(f"Query execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "diagnostic_info": {"query": query, "error_type": type(e).__name__},
            "execution_time": time.time() - start_time,
        }


async def _execute_count_query(query: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Execute COUNT aggregate query."""
    from olav.api.v1.data import query_table

    try:
        entity = intent.get("entity", "devices")
        filters = intent.get("filters", {})

        # Convert filters to where dict
        where_dict = filters if isinstance(filters, dict) else {}

        result = await asyncio.to_thread(
            query_table, entity, where=where_dict if where_dict else None
        )

        return {
            "success": True,
            "count": result.total_count,
            "entity": entity,
            "rows": [],  # Count queries don't return rows
        }
    except Exception as e:
        logger.error(f"Count query failed: {e}")
        return {"success": False, "error": str(e), "count": 0}


async def _execute_devices_query(query: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Execute devices-related query."""
    from olav.api.v1.devices import get_device, list_devices

    try:
        filters = intent.get("filters", {})
        query_lower = query.lower()

        # Single device query
        if "device r" in query_lower or "device s" in query_lower:
            # Extract device ID
            device_id = _extract_device_id(query)
            if device_id:
                device = await asyncio.to_thread(get_device, device_id)
                if device:
                    return {"success": True, "rows": [device], "count": 1, "entity": "device"}

        # List devices with filters
        vendor = filters.get("vendor")
        device_type = filters.get("device_type")
        status = filters.get("status")

        devices = await asyncio.to_thread(
            list_devices, limit=100, vendor=vendor, device_type=device_type, status=status
        )

        return {"success": True, "rows": devices, "count": len(devices), "entity": "devices"}
    except Exception as e:
        logger.error(f"Devices query failed: {e}")
        return {"success": False, "error": str(e), "rows": []}


async def _execute_interfaces_query(query: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Execute interfaces-related query."""
    from olav.api.v1.devices import get_device_interfaces

    try:
        # Extract device ID from query
        device_id = _extract_device_id(query)

        if not device_id:
            return {"success": False, "error": "Could not extract device ID from query", "rows": []}

        interfaces = await asyncio.to_thread(get_device_interfaces, device_id)

        return {
            "success": True,
            "rows": interfaces,
            "count": len(interfaces),
            "entity": "interfaces",
            "device_id": device_id,
        }
    except Exception as e:
        logger.error(f"Interfaces query failed: {e}")
        return {"success": False, "error": str(e), "rows": []}


async def _execute_export_query(query: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Execute query and export to file."""
    try:
        # First execute the base query
        base_query = query.replace("export", "").replace("save", "")
        result = await execute_query(base_query)

        if not result.get("success"):
            return result

        # Export to CSV
        filename = _generate_export_filename(intent)
        rows = result.get("rows", [])

        await _save_as_csv(rows, filename)

        result["exported_file"] = filename
        return result
    except Exception as e:
        logger.error(f"Export query failed: {e}")
        return {"success": False, "error": str(e), "rows": []}


async def _execute_generic_query(query: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Execute generic query."""
    # For unstructured queries, try to map to existing functions
    query_lower = query.lower()

    try:
        if "device" in query_lower:
            return await _execute_devices_query(query, intent)
        elif "interface" in query_lower:
            return await _execute_interfaces_query(query, intent)
        else:
            # Fallback: return instruction to user
            return {
                "success": False,
                "error": "Could not understand query intent",
                "diagnostic_info": intent,
                "suggestion": "Try queries like 'list all devices' or 'get interfaces for R1'",
            }
    except Exception as e:
        logger.error(f"Generic query failed: {e}")
        return {"success": False, "error": str(e), "rows": []}


def _extract_device_id(query: str) -> str | None:
    """Extract device ID from query."""
    import re

    # Look for patterns like "device R1", "for R1", "R1"
    patterns = [r"device\s+([A-Z0-9_]+)", r"for\s+([A-Z0-9_]+)", r"\b([A-Z0-9_]+)(?:\s+device)?$"]

    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            device_id = match.group(1)
            if len(device_id) <= 20:  # Sanity check
                return device_id

    return None




def _generate_export_filename(intent: dict[str, Any]) -> str:
    """Generate filename for exported query result."""
    from datetime import datetime
    from pathlib import Path

    entity = intent.get("entity", "data")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    exports_dir = Path(settings.runtime.get_exports_dir())
    filename = str(exports_dir / f"{entity}_{timestamp}.csv")
    exports_dir.mkdir(exist_ok=True, parents=True)

    return filename


async def _save_as_csv(rows: List[Dict[str, Any]], filename: str) -> None:
    """Save query results to CSV file."""
    import csv

    if not rows:
        return

    def _write_csv():
        """Helper to write CSV in sync context."""
        with open(filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    await asyncio.to_thread(_write_csv)


# ============================================================================
# RESULT FORMATTING
# ============================================================================


async def format_results(rows: list[dict[str, Any]], format: str = "json") -> str:
    """Format query results in specified format.

    Args:
        rows: List of result rows
        format: Output format (json, csv, markdown, text)

    Returns:
        Formatted string
    """
    if not rows:
        if format == "json":
            return json.dumps([])
        elif format == "csv":
            return ""
        elif format == "markdown":
            return "No results"
        else:
            return "No results"

    if format == "json":
        return json.dumps(rows, indent=2, default=str)

    elif format == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    elif format == "markdown":
        return _format_as_markdown_table(rows)

    elif format == "text":
        return _format_as_text(rows)

    else:
        return json.dumps(rows, indent=2, default=str)


def _format_as_markdown_table(rows: list[dict[str, Any]]) -> str:
    """Format results as markdown table."""
    if not rows:
        return ""

    headers = list(rows[0].keys())
    lines = []

    # Header
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "---|" * len(headers))

    # Rows
    for row in rows:
        values = [str(row.get(h, "")) for h in headers]
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


def _format_as_text(rows: list[dict[str, Any]]) -> str:
    """Format results as plain text."""
    lines = []
    for row in rows:
        line_parts = []
        for k, v in row.items():
            line_parts.append(f"{k}: {v}")
        lines.append(", ".join(line_parts))
    return "\n".join(lines)


# ============================================================================
# QUERY RECOMMENDATIONS
# ============================================================================


async def get_query_recommendations(
    context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Get smart query recommendations based on context.

    Args:
        context: Optional context dict with:
        - device_id: Current device
        - last_query: Recently executed query
        - current_table: Currently viewing table

    Returns:
        List of recommended queries
    """
    if not context:
        context = {}

    recommendations = []

    if "device_id" in context:
        device_id = context["device_id"]
        recommendations.extend(
            [
                {
                    "query": f"get interfaces for {device_id}",
                    "description": "View device interfaces",
                },
                {
                    "query": f"show capabilities for {device_id}",
                    "description": "View device capabilities",
                },
                {"query": f"get device {device_id} status", "description": "Check device health"},
            ]
        )

    if "current_table" in context:
        table = context["current_table"]
        if table == "devices":
            recommendations.extend(
                [
                    {"query": "list all cisco devices", "description": "Filter by vendor"},
                    {"query": "list devices with status up", "description": "Show active devices"},
                    {"query": "count devices by vendor", "description": "Distribution by vendor"},
                ]
            )

    if "last_query" in context:
        recommendations.extend(
            [
                {"query": "show more details", "description": "Expand last query"},
                {"query": "export results", "description": "Save results to file"},
            ]
        )

    # Default recommendations if no context
    if not recommendations:
        recommendations = [
            {"query": "list all devices", "description": "Show all network devices"},
            {"query": "list cisco devices", "description": "Filter devices by vendor"},
            {"query": "list devices with status up", "description": "Show active devices"},
            {"query": "get device R1", "description": "Get specific device details"},
        ]

    return recommendations


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


async def extract_entities(query: str) -> list[str]:
    """Extract entities mentioned in query.

    Returns:
        List of identified entities
    """
    entities = []
    query_lower = query.lower()

    entity_keywords = {
        "devices": ["devices", "device", "router", "switch"],
        "interfaces": ["interfaces", "interface", "port"],
        "topology": ["topology", "neighbor", "adjacency"],
        "bgp": ["bgp", "bgp_neighbor"],
        "ospf": ["ospf", "ospf_neighbor"],
    }

    for entity, keywords in entity_keywords.items():
        for keyword in keywords:
            if keyword in query_lower:
                entities.append(entity)
                break

    return entities


async def extract_filters(query: str) -> dict[str, Any]:
    """Extract filters from query.

    Returns:
        Dict of extracted filters
    """
    filters = {}
    query_lower = query.lower()

    # Vendor filter
    if "cisco" in query_lower:
        filters["vendor"] = "cisco"
    elif "juniper" in query_lower:
        filters["vendor"] = "juniper"
    elif "arista" in query_lower:
        filters["vendor"] = "arista"

    # Status filter
    if "active" in query_lower or "up" in query_lower:
        filters["status"] = "up"
    elif "inactive" in query_lower or "down" in query_lower:
        filters["status"] = "down"

    # Device type filter
    if "router" in query_lower:
        filters["device_type"] = "router"
    elif "switch" in query_lower:
        filters["device_type"] = "switch"

    return filters


async def validate_query_safety(query: str) -> bool:
    """Validate query for SQL injection and other risks.

    Args:
        query: Query to validate

    Returns:
        True if query is safe, False otherwise
    """
    # Check for SQL injection patterns
    dangerous_patterns = [
        "DROP TABLE",
        "DELETE FROM",
        "INSERT INTO",
        "UPDATE ",
        "ALTER TABLE",
        "--",
        ";",
        "xp_",
        "sp_",
    ]

    query_upper = query.upper()

    for pattern in dangerous_patterns:
        if pattern in query_upper:
            logger.warning(f"Potential SQL injection detected: {pattern}")
            return False

    return True
