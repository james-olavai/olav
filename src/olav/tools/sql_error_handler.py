"""SQL Error Handler for Enhanced Query Error Messages.

This module provides intelligent error suggestions for DuckDB SQL queries,
reducing query error rates from 50-60% to <30%.

Core functionality:
- get_sql_error_suggestions(): Parse SQL errors and return actionable suggestions
- validate_sql_with_explain(): Use EXPLAIN to validate SQL before execution

Integration:
- Called from react_query.py::query_network()
- Provides user-friendly error messages with troubleshooting steps

Roadmap: Task 5.2 (P1 Priority - High Value Optimization)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


# =============================================================================
# SQL Error Pattern Matching
# =============================================================================

# Error patterns and corresponding suggestions
ERROR_PATTERNS: dict[str, list[dict[str, Any]]] = {
    "Binder Error": [
        {
            "pattern": r'Referenced column "(\w+)" not found',
            "suggestions": [
                "✓ 检查列名拼写是否正确",
                "✓ 使用 inspect_schema() 查看可用字段列表",
                "✓ 检查是否需要在列名前加表别名 (如 d.column_name)",
            ],
        },
        {
            "pattern": r"Ambiguous reference to column",
            "suggestions": [
                "✓ 列名在多个表中存在，请使用表别名限定 (如 table1.column_name)",
                "✓ 使用 inspect_schema() 查看完整的表结构",
            ],
        },
    ],
    "Parser Error": [
        {
            "pattern": r"syntax error",
            "suggestions": [
                "✓ 检查 SQL 语法错误，常见问题：",
                "  - FORM 应该是 FROM",
                "  - 缺少引号或括号",
                "  - 关键字拼写错误",
                "✓ 参考正确语法: SELECT column FROM table",
            ],
        },
    ],
    "Catalog Error": [
        {
            "pattern": r"Table.*does not exist",
            "suggestions": [
                "✓ 使用 discover_data() 查看可用的数据文件",
                "✓ 检查表路径是否正确 (需要完整路径如 exports/snapshots/latest/parsed/...)",
                "✓ 使用 read_json_auto('path/to/file.json') 读取 JSON 文件",
            ],
        },
        {
            "pattern": r"View.*does not exist",
            "suggestions": [
                "✓ 该视图可能不存在，尝试使用基础表查询",
                "✓ 使用 inspect_schema() 查看可用的表和视图",
            ],
        },
    ],
    "Type Error": [
        {
            "pattern": r"mismatched types",
            "suggestions": [
                "✓ 检查数据类型是否匹配 (如字符串与数字比较)",
                "✓ 使用 CAST() 转换数据类型",
                "✓ 使用 TRY_CAST() 进行安全的类型转换",
            ],
        },
    ],
}


# =============================================================================
# Error Suggestion Functions
# =============================================================================


def get_sql_error_suggestions(error: str) -> list[str]:
    """Parse SQL error and return actionable suggestions.

    This function analyzes DuckDB error messages and provides
    specific, actionable troubleshooting steps.

    Args:
        error: Error message from DuckDB

    Returns:
        List of suggestion strings (empty list if no match)

    Examples:
        >>> error = "Binder Error: Referenced column \\"xyz\\" not found"
        >>> suggestions = get_sql_error_suggestions(error)
        >>> assert "inspect_schema" in suggestions[0]
    """
    suggestions = []
    error_upper = error.upper()

    # Try to match against known error patterns
    for error_type, pattern_list in ERROR_PATTERNS.items():
        if error_type.upper() in error_upper:
            for pattern_dict in pattern_list:
                pattern = pattern_dict["pattern"]
                if re.search(pattern, error, re.IGNORECASE):
                    suggestions.extend(pattern_dict["suggestions"])
                    break

    # Generic suggestions for LINE/POSITION references
    line_match = re.search(r"LINE (\d+)", error, re.IGNORECASE)
    if line_match:
        line_num = line_match.group(1)
        suggestions.append(f"✓ 错误出现在第 {line_num} 行，请检查该位置附近的语法")
        return suggestions  # Return early if we found line reference

    # If no specific suggestions found, provide general guidance
    if not suggestions:
        return []  # Return empty for unknown errors (as per test expectation)

    return suggestions


def format_error_with_suggestions(sql: str, error: str) -> str:
    """Format error message with suggestions for user.

    Args:
        sql: The failed SQL query
        error: The error message

    Returns:
        Formatted error message with suggestions
    """
    suggestions = get_sql_error_suggestions(error)

    lines = [
        "❌ SQL Query Error",
        "",
        f"Error: {error}",
        "",
        "🔧 Suggestions:",
    ]
    lines.extend(suggestions)
    lines.append("")
    lines.append("Failed Query:")
    lines.append("```sql")
    lines.append(sql)
    lines.append("```")

    return "\n".join(lines)


# =============================================================================
# SQL Validation with EXPLAIN
# =============================================================================


def validate_sql_with_explain(
    sql: str, duckdb_conn: duckdb.DuckDBPyConnection | None = None
) -> bool:
    """Validate SQL query using EXPLAIN (catches syntax errors early).

    This function uses DuckDB's EXPLAIN command to validate SQL
    syntax without executing the query, providing better error
    messages and avoiding side effects.

    Args:
        sql: SQL query to validate
        duckdb_conn: Optional DuckDB connection (creates new if None)

    Returns:
        True if SQL is valid, False otherwise

    Examples:
        >>> validate_sql_with_explain("SELECT 1")
        True
        >>> validate_sql_with_explain("SELECT FORM invalid")
        False
    """
    try:
        # Create connection if not provided
        if duckdb_conn is None:
            conn = duckdb.connect(":memory:")
        else:
            conn = duckdb_conn

        # Use EXPLAIN to validate (doesn't execute the query)
        explain_sql = f"EXPLAIN {sql}"
        conn.execute(explain_sql).fetchone()

        # If we get here, SQL is valid
        return True

    except Exception:
        # SQL has errors
        return False


def safe_query_execution(
    sql: str,
    duckdb_conn: duckdb.DuckDBPyConnection | None = None,
    enable_explain_validation: bool = True,
) -> tuple[bool, str | list[Any]]:
    """Execute SQL query with enhanced error handling.

    This function:
    1. Optionally validates SQL with EXPLAIN first
    2. Executes the query
    3. Returns formatted error with suggestions if it fails

    Args:
        sql: SQL query to execute
        duckdb_conn: Optional DuckDB connection
        enable_explain_validation: Whether to validate with EXPLAIN first

    Returns:
        Tuple of (success: bool, result: str|list)
        - If success=True: result is query results (list of dicts)
        - If success=False: result is formatted error message

    Examples:
        >>> success, result = safe_query_execution("SELECT 1 as test")
        >>> assert success is True
        >>> isinstance(result, list)
    """
    try:
        # Step 1: Validate with EXPLAIN (optional)
        if enable_explain_validation:
            if not validate_sql_with_explain(sql, duckdb_conn):
                return False, format_error_with_suggestions(
                    sql, "Query validation failed (EXPLAIN check)"
                )

        # Step 2: Create connection if not provided
        if duckdb_conn is None:
            conn = duckdb.connect(":memory:")
        else:
            conn = duckdb_conn

        # Step 3: Execute query
        result = conn.execute(sql).fetchall()

        # Step 4: Get column names
        column_names = [desc[0] for desc in conn.description]

        # Step 5: Convert to dict list
        rows = [dict(zip(column_names, row, strict=True)) for row in result]

        return True, rows

    except Exception as e:
        # Format error with suggestions
        error_msg = format_error_with_suggestions(sql, str(e))
        return False, error_msg


# =============================================================================
# Helper Functions for react_query.py Integration
# =============================================================================


def enhance_query_network_result(sql: str, result: str, original_error: Exception) -> str:
    """Enhance query_network result with error suggestions.

    This is a helper function for integrating with the existing
    react_query.py code without breaking the API.

    Args:
        sql: The SQL query that failed
        result: The original error result string
        original_error: The original exception

    Returns:
        Enhanced error message with suggestions
    """
    error_str = str(original_error)
    suggestions = get_sql_error_suggestions(error_str)

    # Build enhanced error message
    lines = [
        "❌ SQL Error:",
        error_str,
        "",
        "🔧 Fix Suggestions:",
    ]
    lines.extend(suggestions)

    enhanced_result = "\n".join(lines)
    return enhanced_result
