"""NL query runner: translates natural language to SQL and executes against DuckDB.

Used by P4-1 e2e acceptance tests. Requires a real LLM API key (NL_QUERY_ENABLED=1).
"""

import logging
import re
from collections.abc import Mapping
from collections.abc import Sequence
from typing import cast

import duckdb
from langchain_core.messages import HumanMessage, SystemMessage

from olav.core.config import MAIN_DB_PATH
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)

def _get_schema_context() -> str:
    from olav.core.workspace import resolve_workspace_path
    schema_ref = resolve_workspace_path("core", "references") / "SCHEMA_REFERENCE.md"
    if not schema_ref.exists():
        raise FileNotFoundError(f"Schema reference not found: {schema_ref}")
    return schema_ref.read_text(encoding="utf-8")


def _build_messages(schema_context: str, question: str) -> tuple[str, str]:
    system_msg = (
        "You are a DuckDB SQL expert for a network operations database. "
        "CRITICAL RULES:\n"
        "0. Contract priority: semantic views first; parsed_outputs is explicit raw-snapshot path only. mapping_rules is a COMPAT TABLE — never query it directly; prefer schema_catalog or semantic views.\n"
        "1. ALWAYS use v_interfaces (not interfaces) for interface/IP queries. For loopback inventory, return one primary loopback per device.\n"
        "2. ALWAYS use v_bgp_neighbors (not bgp_neighbors) for BGP queries.\n"
        "3. ALWAYS prefer v_l2_topology_summary for topology summaries and v_device_neighbors_summary for per-device neighbor queries. Use v_topo_links_clean only when interface-level detail is explicitly required.\n"
        "4. SNAPSHOT FILTER: Always filter to latest data. When using snapshot_id, "
        "use (SELECT MAX(snapshot_id) FROM <same_table>) — each table has its OWN max. "
        "Do NOT use MAX(snapshot_id) FROM parsed_outputs for other tables.\n"
        "5. Simpler is better: prefer DISTINCT without snapshot filter if there is any doubt.\n"
        "6. Respond with ONLY a single valid DuckDB SQL query wrapped in ```sql\n...\n``` fences. No explanation."
    )
    user_msg = (
        f"Schema:\n{schema_context}\n\n"
        "REMINDER: Use semantic views first (v_interfaces, v_bgp_neighbors, v_l2_topology_summary, v_device_neighbors_summary). "
        "Use parsed_outputs only when raw snapshot inspection is explicitly required, and mapping_rules is a COMPAT TABLE — never query it directly. "
        "Snapshot filter: MAX(snapshot_id) from the SAME table, not from parsed_outputs. For loopback inventory, return one primary loopback per device. For L2 topology questions, prefer v_l2_topology_summary. For per-device neighbor questions, prefer v_device_neighbors_summary.\n\n"
        f"Question: {question}\n\nReturn a single DuckDB SQL query."
    )
    return system_msg, user_msg


def _extract_sql(text: str) -> str:
    """Extract the first SQL query from an LLM response."""
    m = re.search(r"```(?:sql)?\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"((?:WITH|SELECT)\s+.+?)(?:;|$)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


def _normalize_llm_content(content: object) -> str:
    """Normalize LLM response content into plain text for SQL extraction."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        content_items = cast(list[object], content)
        parts: list[str] = []
        for item in content_items:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, Mapping):
                item_map = cast(Mapping[str, object], item)
                text = item_map.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)

    return str(cast(object, content))


def _has_unquoted_internal_semicolon(sql: str) -> bool:
    """Return True when SQL contains an internal semicolon outside quotes."""
    text = sql.strip()
    if not text:
        return False

    # A single trailing semicolon is allowed.
    scan_text = text[:-1] if text.endswith(";") else text

    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(scan_text)

    while i < n:
        ch = scan_text[i]
        nxt = scan_text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if not in_single and not in_double:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

        if ch == "'" and not in_double:
            if in_single and i + 1 < n and scan_text[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if ch == '"' and not in_single:
            if in_double and i + 1 < n and scan_text[i + 1] == '"':
                i += 2
                continue
            in_double = not in_double
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            return True

        i += 1

    return False


def _contains_forbidden_sql_keyword(sql: str) -> bool:
    """Return True when SQL includes non-read-only keywords outside quotes/comments."""
    forbidden = {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "MERGE",
        "REPLACE",
        "GRANT",
        "REVOKE",
        "COPY",
        "CALL",
        "VACUUM",
        "ANALYZE",
        "ATTACH",
        "DETACH",
    }

    text = sql.strip()
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    token: list[str] = []
    i = 0
    n = len(text)

    def flush_token() -> bool:
        if not token:
            return False
        word = "".join(token).upper()
        token.clear()
        return word in forbidden

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if not in_single and not in_double:
            if ch == "-" and nxt == "-":
                if flush_token():
                    return True
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                if flush_token():
                    return True
                in_block_comment = True
                i += 2
                continue

        if ch == "'" and not in_double:
            if in_single and i + 1 < n and text[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if ch == '"' and not in_single:
            if in_double and i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            in_double = not in_double
            i += 1
            continue

        if in_single or in_double:
            i += 1
            continue

        if ch.isalpha() or (ch == "_" and token):
            token.append(ch)
            i += 1
            continue

        if flush_token():
            return True
        i += 1

    return flush_token()


def _format_result(
    rows: Sequence[Sequence[object]], description: Sequence[Sequence[object]]
) -> str:
    """Format DuckDB result rows as a human-readable string."""
    if not rows:
        return "(no results)"
    cols = [str(d[0]) for d in description]
    if not cols:
        raise ValueError("Missing column description for non-empty rows")
    lines: list[str] = []
    for row in rows:
        if len(row) != len(cols):
            raise ValueError(
                f"Row/column length mismatch: row has {len(row)} values, header has {len(cols)} columns"
            )
        pairs = zip(cols, row, strict=False)
        rendered = ", ".join(str(value) for _, value in pairs)
        lines.append(rendered)
    header = " | ".join(cols)
    return header + "\n" + "\n".join(lines)


def _execute_sql(sql: str) -> str:
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        try:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return _format_result(rows, cur.description or [])
        except Exception as e:
            logger.warning("SQL error: %s\nSQL: %s", e, sql)
            return f"SQL error: {e}\nSQL: {sql}"


def run_nl_query(question: str) -> str:
    """Translate a natural language question to SQL, execute it, and return results.

    Args:
        question: Natural language query (Chinese or English).

    Returns:
        Human-readable string containing query results.
        On SQL error, returns an error message string (never raises).
    """
    try:
        schema_context = _get_schema_context()
    except FileNotFoundError as e:
        logger.error("Schema reference missing: %s", e)
        return f"Schema error: {e}"
    system_msg, user_msg = _build_messages(schema_context, question)

    llm = LLMFactory.get_chat_model(temperature=0, agent_id="query_runner")

    try:
        response = llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
        raw_content = cast(object, getattr(response, "content", ""))
        content_text = _normalize_llm_content(raw_content)
        sql = _extract_sql(content_text)
        if not sql:
            return "LLM error: empty SQL response"
        if _has_unquoted_internal_semicolon(sql):
            return "LLM error: multiple SQL statements not allowed"
        if re.match(r"^(WITH|SELECT)\b", sql, re.IGNORECASE) is None:
            return "LLM error: invalid SQL response"
        if _contains_forbidden_sql_keyword(sql):
            return "LLM error: non-read-only SQL response"
        logger.debug("Generated SQL for %r: %s", question, sql)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return f"LLM error: {e}"

    return _execute_sql(sql)
