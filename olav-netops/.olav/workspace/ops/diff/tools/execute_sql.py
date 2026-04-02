#!/usr/bin/env python3
"""
Database Tool - Intelligent SQL query execution with auto schema exploration.

Core Features:
1. Auto schema discovery (no manual inspect_schema calls)
2. SQL generation with context
3. Error self-correction (via Agent ReAct loop)
4. DuckDB-specific optimizations
5. SchemaContext singleton caching (5 min TTL)

Usage in DeepAgents:
    from .tools import execute_sql
    agent = create_deep_agent(tools=[execute_sql.execute_sql])
"""

import json
import sys
import time
from datetime import date, datetime
from datetime import time as time_type
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential


# Add src to Python Path
def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import duckdb as _duckdb

from olav.core.config import MAIN_DB_PATH


def db_query(sql: str, params: list | None = None) -> list[dict]:
    """Execute a SQL query against the main DuckDB database."""
    with _duckdb.connect(str(MAIN_DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if cur.description:
            cols = [d[0] for d in cur.description]
            result = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
            return result
        return []




# ============================================================================
# Pydantic Models for Type-Safe Parameter Validation
# ============================================================================


class DatabaseQueryInput(BaseModel):
    """Database query input parameters - type-safe validation"""

    query: str = Field(default="", description="Natural language query")
    sql: str = Field(default="", description="Direct SQL query (optional)")
    explain_only: bool = Field(
        default=False, description="Return only schema context without executing query"
    )

    @validator("query", "sql", pre=True)
    def validate_not_none(cls, v):
        """Convert None to empty string"""
        if v is None:
            return ""
        return v


class DatabaseQueryOutput(BaseModel):
    """Database query output format - unified response"""

    data: list[dict] | None = Field(default=None, description="Query results")
    table: str | None = Field(
        default=None, description="Markdown table representation (for small results)"
    )
    schema_context: str | None = Field(default=None, description="Database schema information")
    sql: str | None = Field(default=None, description="SQL query executed")
    count: int | None = Field(default=None, description="Number of results")
    status: str = Field(..., description="success | error | needs_sql_generation")
    error: str | None = Field(default=None, description="Error message if status=error")
    error_type: str | None = Field(default=None, description="Type of error")
    message: str | None = Field(default=None, description="Additional message")
    user_query: str | None = Field(default=None, description="Original user query")
    tables: list[str] | None = Field(default=None, description="Available tables")
    attempted_sql: str | None = Field(default=None, description="SQL that failed")
    suggestions: list[str] | None = Field(default=None, description="Suggestions for retry when count=0")


class SchemaContext:
    """Context manager for auto-schema exploration with singleton caching.

    Uses singleton pattern to cache schema across multiple execute_sql calls.
    Cache TTL is 5 minutes by default.
    """

    _instance: "SchemaContext | None" = None
    _last_refresh: float = 0
    _cache_ttl: float = 300.0  # 5 minutes TTL

    def __new__(cls) -> "SchemaContext":
        """Singleton pattern - reuse instance if cache is valid."""
        now = time.time()
        if cls._instance is None or (now - cls._last_refresh) > cls._cache_ttl:
            cls._instance = super().__new__(cls)
            cls._instance._schema_cache: dict[str, Any] = {}
            cls._instance._refresh_schema()
            cls._last_refresh = now
        return cls._instance

    def __init__(self):
        """Initialize with automatic schema caching."""
        # Schema already initialized in __new__
        pass

    def _refresh_schema(self) -> None:
        """Refresh schema cache by querying INFORMATION_SCHEMA."""
        try:
            # Get all tables
            tables_result = db_query(
                """
                SELECT table_schema || '.' || table_name AS table_name, table_type
                FROM information_schema.tables
                WHERE table_schema IN ('main', 'netops')
                ORDER BY table_schema, table_name
                """
            )

            self._schema_cache["tables"] = [row["table_name"] for row in tables_result]
            self._schema_cache["table_details"] = {}

            # Get columns for each table
            for table_name in self._schema_cache["tables"]:
                try:
                    columns_result = db_query(f"DESCRIBE {table_name}")
                    self._schema_cache["table_details"][table_name] = {
                        "columns": [
                            {
                                "name": row.get("column_name", row.get("Field", "")),
                                "type": row.get("column_type", row.get("Type", "")),
                            }
                            for row in columns_result
                        ]
                    }
                except Exception:
                    # Skip tables with errors
                    pass

            # Get sample data — prefer views and devices; skip noisy catalog/JSON tables
            SKIP_SAMPLES = {"main.schema_catalog", "main.yang_leaves",
                            "netops.oc_outputs", "netops.parsed_outputs"}
            PREFER_SAMPLES = [
                "main.v_bgp_neighbors_auto", "main.v_interfaces_auto",
                "main.v_ospf_neighbors", "main.v_topo_links_clean", "netops.devices",
            ]
            self._schema_cache["samples"] = {}
            # First try preferred tables, then fill from remaining (skip noisy ones)
            candidates = PREFER_SAMPLES + [
                t for t in self._schema_cache["tables"]
                if t not in PREFER_SAMPLES and t not in SKIP_SAMPLES
            ]
            for table_name in candidates[:6]:
                try:
                    sample = db_query(f"SELECT * FROM {table_name} LIMIT 2")
                    if sample:
                        self._schema_cache["samples"][table_name] = sample
                except Exception:
                    pass

            # Query schema_catalog for parsed_outputs JSON field info
            # Enables LLM to generate: SELECT parsed_data->>'field' FROM parsed_outputs
            try:
                catalog_rows = db_query(
                    "SELECT source_name, platform, fields FROM schema_catalog "
                    "WHERE source_type = 'textfsm' ORDER BY source_name, platform"
                )
                if catalog_rows:
                    schema_catalog_info: list[str] = []
                    for row in catalog_rows:
                        fields = row.get("fields", [])
                        if isinstance(fields, str):
                            try:
                                fields = json.loads(fields)
                            except Exception:
                                fields = []
                        field_names = [f["name"] for f in (fields or []) if isinstance(f, dict)]
                        if field_names:
                            schema_catalog_info.append(
                                f"  {row['source_name']} ({row['platform']}): "
                                + ", ".join(field_names)
                            )
                    self._schema_cache["schema_catalog"] = schema_catalog_info
            except Exception:
                pass  # schema_catalog not yet populated, skip silently

        except Exception as e:
            self._schema_cache = {"error": str(e)}

    def get_schema_context(self) -> str:
        """Get formatted schema context for LLM."""
        if "error" in self._schema_cache:
            return f"Schema error: {self._schema_cache['error']}"

        context_parts = ["**Available Database Schema:**\n"]

        # CRITICAL: schema-qualified names required for netops tables
        context_parts.append(
            "⚠️  ALWAYS use schema-qualified names: `netops.devices`, `netops.parsed_outputs`, etc.\n"
            "   Views (v_*) are in main schema and can be queried unqualified.\n"
        )

        # List tables
        context_parts.append(f"Tables: {', '.join(self._schema_cache['tables'])}\n")

        # View semantic hints — help agent pick the right view immediately
        context_parts.append("**View Quick Reference (USE THESE FIRST for network queries):**")
        context_parts.append(
            "  v_interfaces_auto       → interface admin/oper status + IP address per device\n"
            "  v_bgp_neighbors_auto    → BGP neighbor state, remote-AS, prefixes received\n"
            "  v_ospf_neighbors        → OSPF neighbor state + cost (use for routing queries)\n"
            "  v_topo_links_clean      → physical topology: src/dst device + interface pairs\n"
            "  v_device_neighbors_summary → compact neighbor table (LLDP/CDP)\n"
            "  v_isis_adjacencies      → IS-IS adjacency state + level\n"
            "  v_evpn_instances        → EVPN VNI/RD per device\n"
            "  v_mpls_ldp_peers        → MPLS LDP peer state\n"
            "  netops.devices          → device inventory: hostname, platform, mgmt_ip\n"
            "  netops.parsed_outputs   → raw TextFSM rows: parsed_data (JSON), command, snapshot_id\n"
            "  netops.oc_outputs       → OC JSON per module: oc_module, oc_data, device_name\n"
            "  netops.topology_links   → raw topology link rows (src/dst device+interface)"
        )

        # Detail each table
        for table_name, details in self._schema_cache["table_details"].items():
            context_parts.append(f"\n**{table_name}:**")
            columns = [f"  - {col['name']}: {col['type']}" for col in details["columns"]]
            context_parts.append("\n".join(columns))

            # Add sample if available
            if table_name in self._schema_cache.get("samples", {}):
                sample = self._schema_cache["samples"][table_name]
                if sample:
                    context_parts.append(f"  Sample: {sample[0]}")

        # Add schema_catalog block (JSON fields for parsed_outputs)
        schema_catalog = self._schema_cache.get("schema_catalog", [])
        if schema_catalog:
            context_parts.append("\n**parsed_outputs JSON fields (via schema_catalog):**")
            context_parts.append(
                "  Query pattern: SELECT parsed_data->>'field_name' "
                "FROM parsed_outputs WHERE command='...' AND snapshot_date=CURRENT_DATE"
            )
            context_parts.extend(schema_catalog[:50])  # cap at 50 entries

        return "\n".join(context_parts)

    def query(self, sql: str) -> list[dict]:
        """Execute SQL query with error details."""
        return db_query(sql)


def _sanitize_value(val: Any) -> Any:
    """Convert non-JSON-serializable types to strings."""
    if isinstance(val, (datetime, date, time_type)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, dict):
        return {k: _sanitize_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_sanitize_value(v) for v in val]
    return val


def _sanitize_rows(rows: list[dict]) -> list[dict]:
    """Ensure all values in query results are JSON-serializable."""
    return [_sanitize_value(row) for row in rows]


def main(params: dict) -> dict:
    """Execute database query with auto schema exploration.

    Args:
        params: {
            "query": "Natural language query",
            "sql": "Optional direct SQL",
            "explain_only": Optional bool to only return schema context
        }

    Returns:
        {
            "data": [...],
            "sql": "Executed SQL",
            "schema_context": "Auto-discovered schema",
            "status": "success"|"error"
        }
    """
    # Validate parameters with Pydantic
    try:
        args = DatabaseQueryInput(**params)
    except Exception as e:
        output = DatabaseQueryOutput(
            status="error", error=f"Invalid parameters: {str(e)}", error_type="validation_error"
        )
        return output.model_dump(exclude_none=True)

    user_query = args.query
    direct_sql = args.sql
    explain_only = args.explain_only

    # Get schema context (singleton, cached for 5 min)
    context = SchemaContext()
    schema_context = context.get_schema_context()

    # If explain_only, return just schema
    if explain_only:
        output = DatabaseQueryOutput(
            schema_context=schema_context,
            tables=context._schema_cache.get("tables", []),
            status="success",
        )
        return output.model_dump(exclude_none=True)

    # If direct SQL provided (agent already generated it), execute it
    if direct_sql:
        try:
            # Execute query (LangGraph cache handles caching at framework level)
            results = context.query(direct_sql)
            results = _sanitize_rows(results)

            # Auto-export large results to CSV
            csv_path = None
            if len(results) > 50:
                import csv
                from pathlib import Path

                export_dir = Path("exports")
                export_dir.mkdir(exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path = export_dir / f"query_{timestamp}.csv"

                if results:
                    with open(csv_path, "w", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=results[0].keys())
                        writer.writeheader()
                        writer.writerows(results)

            # Check if results are empty - provide schema hints for agentic retry
            if len(results) == 0:
                # Empty results - provide schema context and suggestions for retry
                suggestions = []
                if 'IP_ADDRESS' in direct_sql.upper() or 'ip_address' in direct_sql.lower():
                    suggestions.append("JSON field names are LOWERCASE: use $.ip_address not $.IP_ADDRESS")
                    suggestions.append("Try: json_extract_string(elem, '$.ip_address') in WHERE clause")
                if 'INTERFACE' in direct_sql.upper():
                    suggestions.append("JSON field names are LOWERCASE: use $.interface not $.INTERFACE")

                output = DatabaseQueryOutput(
                    data=results,
                    sql=direct_sql,
                    count=0,
                    status="empty",
                    message="Query returned 0 results. Schema context provided for retry.",
                    schema_context=schema_context,
                    suggestions=suggestions if suggestions else None,
                )
                return output.model_dump(exclude_none=True)

            SCHEMA_HINT = (
                "Schema reminder: netops.devices(hostname,platform,ip_address,role) | "
                "netops.parsed_outputs(device_name,command,parsed_data,snapshot_id) | "
                "views(no prefix): v_interfaces_auto, v_bgp_neighbors_auto, v_ospf_neighbors, v_topo_links_clean"
            )
            msg = f"Results exported to {csv_path}" if csv_path else None
            output = DatabaseQueryOutput(
                data=results,
                sql=direct_sql,
                count=len(results),
                status="success",
                message=f"{msg} | {SCHEMA_HINT}" if msg else SCHEMA_HINT,
            )
            return output.model_dump(exclude_none=True)
        except Exception as e:
            # Return error with schema context for agent to retry
            output = DatabaseQueryOutput(
                error=str(e),
                schema_context=schema_context,
                attempted_sql=direct_sql,
                status="error",
                error_type="execution_error",
            )
            return output.model_dump(exclude_none=True)

    # If natural language query, return schema context for agent to generate SQL
    output = DatabaseQueryOutput(
        message="Schema context provided for SQL generation",
        user_query=user_query,
        schema_context=schema_context,
        status="needs_sql_generation",
    )
    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration
# ============================================================================


@tool
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def execute_sql(query: str = "", sql: str = "", explain_only: bool = False) -> dict:
    """Execute SQL query with automatic schema discovery and error correction.
    ⭐ DEFAULT TOOL for device queries. Use this FIRST before execute_cli.

    ⚠️  SCHEMA RULES (always follow):
    - netops tables REQUIRE schema prefix: netops.devices, netops.parsed_outputs,
      netops.oc_outputs, netops.topology_links
    - Views are in main and can be used WITHOUT prefix: v_interfaces_auto, v_bgp_neighbors_auto,
      v_ospf_neighbors, v_topo_links_clean, v_device_neighbors_summary
    - Column names: use `hostname` (not `name`) for netops.devices

    QUICK REFERENCE:
    - Device list/count      → SELECT hostname, platform FROM netops.devices
    - Interface + IP         → SELECT device_name, interface, ip_address FROM v_interfaces_auto
    - BGP neighbors          → SELECT * FROM v_bgp_neighbors_auto
    - OSPF neighbors         → SELECT * FROM v_ospf_neighbors
    - Topology links         → SELECT src, dst, source_interface FROM v_topo_links_clean
    - Raw TextFSM data       → SELECT parsed_data FROM netops.parsed_outputs WHERE command='...'

    Args:
        query: Natural language question about the database
        sql: Optional direct SQL query (used for executing generated SQL)
        explain_only: If True, return only schema context

    Returns:
        Status, results, or error information with schema context

    Examples:
        Example 1 - Device count and platform:
        >>> execute_sql(sql="SELECT COUNT(*) as total, platform FROM netops.devices GROUP BY platform")

        Example 2 - List all devices:
        >>> execute_sql(sql="SELECT hostname, ip_address, platform, role FROM netops.devices")

        Example 3 - BGP neighbors:
        >>> execute_sql(sql="SELECT device_name, neighbor_ip, neighbor_as, state FROM v_bgp_neighbors_auto")

        Example 4 - Get schema for SQL generation:
        >>> execute_sql(explain_only=True)
    """
    params = {"query": query, "sql": sql, "explain_only": explain_only}
    return main(params)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
    except Exception as e:
        print(
            json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(1)
