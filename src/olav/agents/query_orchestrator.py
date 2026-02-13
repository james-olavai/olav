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

    from olav.core.database import get_database
    from olav.core.llm import LLMFactory
    from olav.core.query_cache import QueryCache

    execution_start = time.time()
    logger.info(f"[QueryOrchestrator] Processing query: {user_query[:100]}...")

    # Initialize cache (NEW in v0.11.2)
    cache = None
    if use_cache:
        cache = QueryCache()
        cached_result = cache.get(user_query)
        if cached_result is not None:
            execution_time = time.time() - execution_start
            cached_result["execution_time"] = execution_time
            cached_result["cached"] = True
            return cached_result

    try:
        # 1. Get database connection and schema
        logger.debug("[QueryOrchestrator] Fetching database schema...")
        db = get_database()
        conn = db.conn
        
        # Get schema from DuckDB (info_schema.tables)
        schema_query = """
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            ORDER BY table_name, ordinal_position
        """
        schema_result = conn.execute(schema_query).fetchall()
        
        # Format into readable schema
        db_schema = "/* Database Tables and Columns */\n"
        current_table = None
        for table_name, column_name, data_type in schema_result:
            if table_name != current_table:
                db_schema += f"\n{table_name}:\n"
                current_table = table_name
            db_schema += f"  - {column_name}: {data_type}\n"

        if not db_schema or len(db_schema) < 50:
            logger.warning("[QueryOrchestrator] Database schema is empty")
            db_schema = "/* No tables found in database */"

        logger.debug(f"[QueryOrchestrator] Got schema ({len(db_schema)} chars)")

        # 2. Prepare LLM prompt
        llm = LLMFactory.get_chat_model()

        system_prompt = """You are a SQL query generator for a network device inventory database.

Given a user query, generate ONLY a valid SQL query that will retrieve the requested data.

Rules:
1. Return ONLY the SQL query - no explanation
2. Use SELECT for data retrieval (not CREATE, DROP, DELETE, etc.)
3. The database contains device information (devices, interfaces, vlans, etc.)
4. If the query cannot be answered, return: SELECT 'Query not possible' AS error
5. Always use proper SQL syntax
6. Include LIMIT 1000 if no specific limit is given

Database Schema:
{schema}

User Query: {query}

Generate SQL:"""

        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt.format(schema=db_schema, query=user_query)),
        ]

        logger.debug("[QueryOrchestrator] Sending query to LLM...")

        # 3. Get SQL from LLM (synchronous call)
        response = llm.invoke(messages)

        # Extract SQL from response
        sql_query = response.content.strip() if hasattr(response, "content") else str(response).strip()

        # Remove markdown code blocks if present
        if sql_query.startswith("```"):
            sql_query = "\n".join(sql_query.split("\n")[1:-1])

        sql_query = sql_query.strip()
        logger.info(f"[QueryOrchestrator] Generated SQL: {sql_query[:100]}...")

        # 4. Execute query
        logger.debug("[QueryOrchestrator] Executing SQL query...")
        query_start = time.time()
        result = conn.execute(sql_query).fetchall()
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

        result_dict = {
            "success": True,
            "result": result_dicts,
            "query": sql_query,
            "execution_time": execution_time,
            "rows_returned": len(result_dicts),
            "format": "table",  # Hint for CLI: render as table directly (skip LLM prettification)
            "cached": False,
        }
        
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
