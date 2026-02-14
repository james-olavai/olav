"""Query Orchestrator - Synchronous Query Execution (v0.11.1)

Separated from orchestrator.py as part of code simplification refactor (Phase 2.1).

Responsibilities:
- Execute database queries through LLM routing
- Parse LLM responses to SQL
- Handle query execution with error recovery
- Format and return query results
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def orchestrate_query_sync(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Synchronous orchestrator for database queries (v0.11.1).

    **Why Synchronous?** DeepAgents ainvoke() hangs with non-standard OpenAI APIs
    (OpenRouter, Groq, etc.) due to async middleware issues. This sync version
    bypasses those issues and provides ~3-5s query execution.

    **Architecture**: Direct LLM + Database Query approach
    1. Check cache for previous results (NEW in v0.11.2)
    2. Get database schema
    3. Send query + schema to LLM
    4. Parse LLM response for SQL
    5. Execute SQL and cache results

    **Important**: This is NOT a limitation - it's often BETTER than async due to:
    - Simpler error handling
    - No async/await deadlocks
    - Better for short-running queries (which most DB queries are)
    - Cleaner code path for debugging

    Args:
        user_query: Natural language query from user
        user_id: User ID for audit/security (optional)
        thread_id: Thread ID for conversation context (optional)
        use_cache: Whether to use cached results (default True)

    Returns:
        Query result dict with:
            - 'success' (bool)
            - 'result' (list of dicts) - Query results
            - 'query' (str) - Executed SQL query
            - 'execution_time' (float) - Query execution time in seconds
            - 'cached' (bool) - Whether result was from cache
            - 'error' (str) - Error message if failed
    """
    import time
    import re

    from olav.core.database import get_database
    from olav.core.llm import LLMFactory
    from olav.core.query_cache import QueryCache
    from olav.core.skill_loader import get_skill_loader

    execution_start = time.time()
    logger.info(f"[QueryOrchestrator] Processing query: {user_query[:100]}...")
    
    # ✅ Phase 3.1: Detect export request from user query
    export_requested = False
    export_format = "csv"
    export_filename = None
    
    # Simple export detection (Guard will do deeper detection, this is backup)
    query_lower = user_query.lower()
    if any(kw in query_lower for kw in ["export", "save", "csv", "导出", "保存", "输出"]):
        export_requested = True
        if "json" in query_lower:
            export_format = "json"
        elif "markdown" in query_lower:
            export_format = "markdown"
        # Try to extract filename from query
        filename_match = re.search(r"(?:to|as|named?|called?|filename)\s+['\"]?(\w+)", query_lower)
        if filename_match:
            export_filename = filename_match.group(1)
    
    logger.debug(f"[QueryOrchestrator] Export detection: requested={export_requested}, format={export_format}")

    # Initialize cache (NEW in v0.11.2)
    cache = None
    if use_cache:
        cache = QueryCache()
        cached_result = cache.get(user_query)
        if cached_result is not None:
            execution_time = time.time() - execution_start
            cached_result["execution_time"] = execution_time
            cached_result["cached"] = True
            # ✅ Preserve export flags from original detection
            cached_result["export_requested"] = export_requested
            cached_result["export_format"] = export_format
            cached_result["export_filename"] = export_filename
            return cached_result

    try:
        # 1. Get database connection and schema
        logger.debug("[QueryOrchestrator] Fetching database connection...")
        db = get_database()
        conn = db.conn
        
        # Get schema from DuckDB (information_schema.columns)
        schema_query = """
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            ORDER BY table_name, ordinal_position
        """
        schema_result = conn.execute(schema_query).fetchall()
        
        # Format into readable schema with column descriptions
        db_schema = "/* Database Tables and Columns - Dynamically Generated */\n"
        
        # Get table row counts
        table_counts = {}
        try:
            tables_result = conn.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
            """).fetchall()
            for (table_name,) in tables_result:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    table_counts[table_name] = count
                except:
                    pass
        except:
            pass
        
        # Column descriptions to help LLM understand data relationships
        column_descriptions = {
            # parsed_outputs table
            ("parsed_outputs", "device_name"): "Device name (e.g., 'R1', 'R3') - use for filtering by specific device",
            ("parsed_outputs", "command"): "CLI command that was executed (e.g., 'show interfaces', 'show arp')",
            ("parsed_outputs", "parsed_data"): "JSON array containing parsed command output - use json_extract() for access",
            ("parsed_outputs", "snapshot_date"): "Date/time when command was executed",
            # devices table
            ("devices", "id"): "Device unique identifier (e.g., 'R3') - use for matching with device_name",
            ("devices", "name"): "Device name (e.g., 'R3', 'R1', 'SW1')",
            ("devices", "ip"): "Management IP address",
            # topology_links table
            ("topology_links", "source_device"): "Local device name",
            ("topology_links", "source_interface"): "Local interface name",
            ("topology_links", "destination_device"): "Remote device name",
            ("topology_links", "destination_interface"): "Remote interface name",
        }
        
        current_table = None
        for table_name, column_name, data_type in schema_result:
            if table_name != current_table:
                row_count = table_counts.get(table_name, "?")
                db_schema += f"\n{table_name}: ({row_count} rows)\n"
                current_table = table_name
            
            # Add description if available
            desc = column_descriptions.get((table_name, column_name))
            if desc:
                db_schema += f"  - {column_name}: {data_type}  # {desc}\n"
            else:
                db_schema += f"  - {column_name}: {data_type}\n"

        if not db_schema or len(db_schema) < 50:
            logger.warning("[QueryOrchestrator] Database schema is empty")
            db_schema = "/* No tables found in database */"

        logger.debug(f"[QueryOrchestrator] Got schema ({len(db_schema)} chars)")

        # 2. Load system prompt from SKILL (no hardcoding!) - v0.12.0+
        llm = LLMFactory.get_chat_model()
        
        # Detect which tables are "empty" (0 rows) for warning
        empty_tables = []
        for table_name, count in table_counts.items():
            if count == 0:
                empty_tables.append(table_name)
        
        empty_tables_warning = ""
        if empty_tables:
            empty_tables_warning = f"WARNING - These tables are EMPTY (DO NOT QUERY):\n"
            for table_name in empty_tables:
                empty_tables_warning += f"  ❌ {table_name} - 0 rows\n"
            empty_tables_warning += "ALWAYS prefer tables with data:\n"
            populated_tables = [t for t in table_counts if table_counts[t] > 0]
            for table_name in populated_tables:
                empty_tables_warning += f"  ✅ {table_name} - {table_counts[table_name]} rows\n"

        # 🆕 v0.12.1: Dynamically extract JSON field mappings from actual data
        # This ensures the system prompt always has current field names
        json_reference = ""
        try:
            from olav.core.json_metadata import analyze_database_json_schema, generate_json_field_reference
            command_fields = analyze_database_json_schema(conn)
            if command_fields:
                json_reference = generate_json_field_reference(command_fields)
                logger.debug(f"[QueryOrchestrator] Generated JSON field reference ({len(json_reference)} chars)")
        except Exception as e:
            logger.warning(f"[QueryOrchestrator] Failed to generate JSON reference: {e}")

        # Load system prompt from .olav/skills/network-query/SKILL.md
        # This respects the Olav principle: "All configuration flows from SKILL.md"
        skill_loader = get_skill_loader()
        skill_loader.load_all()  # Ensure skills are indexed
        
        system_prompt = skill_loader.load_system_prompt(
            "network-query",
            prompt_key="sql_generator",  # Use sql_generator for direct SQL generation (v0.12.0+)
            template_vars={
                "schema": db_schema,
                "warnings": empty_tables_warning,
                "query": user_query,
            }
        )
        
        # 🆕 v0.12.1: Inject dynamic JSON field reference into prompt
        # This ensures the LLM knows the actual field names in the database
        if json_reference:
            insertion_point = "## SQL Best Practices"
            if insertion_point in system_prompt:
                system_prompt = system_prompt.replace(
                    insertion_point,
                    json_reference + "\n\n" + insertion_point
                )
        
        if not system_prompt:
            logger.warning("[QueryOrchestrator] Failed to load prompt from SKILL, using fallback")
            system_prompt = f"You are a SQL query generator. Schema:\n{db_schema}\n{empty_tables_warning}\n\nUser Query: {user_query}\n\nGenerate SQL:"

        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
        ]

        logger.debug("[QueryOrchestrator] Sending query to LLM...")

        # 3. Get SQL from LLM (synchronous call)
        response = llm.invoke(messages)

        # Extract SQL from response
        sql_query = response.content.strip() if hasattr(response, "content") else str(response).strip()

        # Enhanced SQL extraction - handle various markdown formats
        import re
        
        # Pattern 1: Extract from ```sql ... ``` code blocks
        sql_block_match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", sql_query, re.DOTALL | re.IGNORECASE)
        if sql_block_match:
            sql_query = sql_block_match.group(1).strip()
        
        # Pattern 2: Remove markdown headers (## SQL Query, etc.)
        sql_query = re.sub(r"^##[^\n]*\n", "", sql_query, flags=re.MULTILINE)
        
        # Pattern 3: Extract only the SELECT/WITH/INSERT/UPDATE/DELETE statement
        # Stop at common explanation markers
        sql_match = re.search(
            r"((?:SELECT|WITH|INSERT|UPDATE|DELETE|CREATE)\b.*?)(?:\n\n|##|\*\*|$)",
            sql_query,
            re.DOTALL | re.IGNORECASE
        )
        if sql_match:
            sql_query = sql_match.group(1).strip()
        
        # Final cleanup
        sql_query = sql_query.strip()
        
        # Remove trailing explanation text (fallback)
        if "\n\n" in sql_query:
            sql_query = sql_query.split("\n\n")[0].strip()

        logger.info(f"[QueryOrchestrator] Generated SQL: {sql_query[:100]}...")
        
        # 4. Execute query
        logger.debug("[QueryOrchestrator] Executing SQL query...")
        logger.debug(f"[QueryOrchestrator] Full SQL: {sql_query}")
        logger.debug(f"[QueryOrchestrator] Database conn: {conn is not None}")
        
        try:
            query_start = time.time()
            exec_result = conn.execute(sql_query)
            if exec_result is None:
                logger.error(f"[QueryOrchestrator] DuckDB execute() returned None for query: {sql_query}")
                raise ValueError(f"DuckDB execute failed: returned None for query: {sql_query}")
            result = exec_result.fetchall()
        except Exception as e:
            logger.error(f"[QueryOrchestrator] Execute error: {type(e).__name__}: {str(e)}")
            logger.error(f"[QueryOrchestrator] Query was: {sql_query}")
            raise
        query_duration = time.time() - query_start

        # Convert to list of dicts
        if result:
            columns = [description[0] for description in conn.execute(sql_query).description]
            result_dicts = [dict(zip(columns, row)) for row in result]
            
            # 🔧 FIX: Replace None with "N/A" to prevent LLM hallucinations
            # When LLM sees None/null values (e.g., vendor=None, model=None),
            # it may fill them with "reasonable" example data like "ISR4321" or "Catalyst 3750".
            # This explicit "N/A" marker prevents such hallucinations.
            cleaned_dicts = []
            for row_dict in result_dicts:
                cleaned_row = {}
                for key, value in row_dict.items():
                    if value is None:
                        cleaned_row[key] = "N/A"  # Explicit missing data marker
                    else:
                        cleaned_row[key] = value
                cleaned_dicts.append(cleaned_row)
            
            result_dicts = cleaned_dicts
        else:
            result_dicts = []

        execution_time = time.time() - execution_start
        logger.info(
            f"[QueryOrchestrator] ✅ Query successful ({len(result_dicts)} rows, {query_duration:.2f}s)"
        )

        # ✅ TODO #7: Data integrity protection
        # Generate hash of raw data to detect tampering
        import hashlib
        data_json = json.dumps(result_dicts, sort_keys=True, default=str)
        data_hash = hashlib.sha256(data_json.encode()).hexdigest()[:16]

        result_dict = {
            "success": True,
            "result": result_dicts,
            "query": sql_query,
            "execution_time": execution_time,
            "rows_returned": len(result_dicts),
            "format": "table",  # Hint for CLI: render as table directly (skip LLM prettification)
            "cached": False,
            # ✅ TODO #7: Data integrity metadata
            "data_hash": data_hash,  # SHA256 hash for integrity verification
            "data_protected": True,  # Flag indicating raw data should not be modified
            # ✅ Phase 3.1: Export metadata
            "export_requested": export_requested,
            "export_format": export_format,
            "export_filename": export_filename,
        }
        
        # 🆕 Generate markdown summary for analysis
        # Provide both table (for CLI) and markdown (for integration)
        try:
            from olav.core.result_analyzer import analyze_results
            markdown_summary = analyze_results(result_dicts, user_query, sql_query)
            result_dict["final_answer"] = markdown_summary
        except Exception as e:
            logger.debug(f"[QueryOrchestrator] Failed to generate markdown: {e}")
            result_dict["final_answer"] = ""
        
        # Cache result for future queries (NEW in v0.11.2)
        if use_cache:
            try:
                cache.set(user_query, result_dict)
            except Exception as e:
                logger.debug(f"[QueryOrchestrator] Cache write failed: {e}")
        
        return result_dict

    except Exception as e:
        execution_time = time.time() - execution_start
        logger.error(
            f"[QueryOrchestrator] ✗ Query failed: {type(e).__name__}: {str(e)[:100]}",
            exc_info=True,
        )

        return {
            "success": False,
            "error": f"{type(e).__name__}: {str(e)}",
            "query": user_query,
            "execution_time": execution_time,
        }


async def orchestrate_query(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Async wrapper around orchestrate_query_sync (v0.11.1).

    **Note**: This is an async wrapper that delegates to the sync version.
    This avoids DeepAgents async/await deadlocks while maintaining API compatibility.

    Args:
        user_query: Natural language query from user
        user_id: User ID for audit/security (optional)
        thread_id: Thread ID for conversation context (optional)

    Returns:
        Query result dict (same as orchestrate_query_sync)
    """
    import asyncio

    # Run sync version in executor to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        orchestrate_query_sync,
        user_query,
        user_id,
        thread_id,
    )

    return result


def parse_lim_response_for_sql(llm_response: str) -> str:
    """Parse LLM response to extract SQL query.

    Handles various response formats:
    - Raw SQL
    - SQL in markdown code blocks
    - SQL with explanation before/after

    Args:
        llm_response: Response from LLM

    Returns:
        Extracted SQL query
    """
    response = llm_response.strip()

    # Remove markdown code blocks
    if response.startswith("```"):
        lines = response.split("\n")
        sql_lines = []
        in_block = False

        for line in lines:
            if line.startswith("```"):
                in_block = not in_block
            elif in_block:
                sql_lines.append(line)

        response = "\n".join(sql_lines).strip()

    # Extract SELECT statement if wrapped in other text
    if "SELECT" in response.upper():
        idx = response.upper().find("SELECT")
        response = response[idx:].strip()

    return response


def format_query_result(
    result: list[dict[str, Any]],
    format: str = "json",
) -> str:
    """Format query result for display.

    Args:
        result: List of result dicts
        format: Output format - 'json', 'table', or 'csv'

    Returns:
        Formatted result string
    """
    if format == "json":
        return json.dumps(result, indent=2, default=str)
    elif format == "table":
        # Format as ASCII table
        if not result:
            return "No results"

        # Get column widths
        cols = list(result[0].keys())
        widths = {col: len(col) for col in cols}

        for row in result:
            for col in cols:
                widths[col] = max(widths[col], len(str(row.get(col, ""))))

        # Build table
        header = " | ".join(f"{col:{widths[col]}}" for col in cols)
        separator = "-+-".join("-" * widths[col] for col in cols)
        rows = [
            " | ".join(
                f"{str(row.get(col, '')):{widths[col]}}" for col in cols
            )
            for row in result
        ]

        return f"{header}\n{separator}\n" + "\n".join(rows)
    elif format == "csv":
        # Format as CSV
        if not result:
            return ""

        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=result[0].keys())
        writer.writeheader()
        writer.writerows(result)

        return output.getvalue()
    else:
        return str(result)
