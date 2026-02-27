#!/usr/bin/env python3
"""analyze_logs.py - Structured log analysis for self-learning and audit.

Data Sources:
- .olav/databases/llm_cache.sqlite - LLM request/response history
- .olav/databases/checkpoints.sqlite - LangGraph execution traces (if enabled)
- .olav/logs/olav.json - Structured app events (if enabled)
"""

import json
import sqlite3
from datetime import datetime, timedelta

from langchain_core.tools import tool

from olav.core.config import DATABASES_DIR as _DB_DIR
from olav.core.config import LOGS_DIR as _LOGS_DIR


def _query_llm_cache(query_type: str, keyword: str | None, hours: int | None, limit: int) -> dict:
    db_path = _DB_DIR / "llm_cache.sqlite"
    if not db_path.exists():
        return {"status": "error", "message": "llm_cache.sqlite not found"}

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        if query_type == "stats":
            total = cursor.execute("SELECT COUNT(*) FROM full_llm_cache").fetchone()[0]
            llm_counts = cursor.execute(
                "SELECT llm, COUNT(*) as cnt FROM full_llm_cache GROUP BY llm ORDER BY cnt DESC"
            ).fetchall()
            return {
                "status": "success",
                "total_entries": total,
                "by_model": [{"model": r[0], "count": r[1]} for r in llm_counts],
            }

        elif query_type == "recent":
            results = cursor.execute(
                "SELECT idx, llm, prompt, response FROM full_llm_cache ORDER BY idx DESC LIMIT ?",
                (limit,),
            ).fetchall()
            entries = []
            for r in results:
                prompt_preview = r[2][:200] + "..." if len(r[2]) > 200 else r[2]
                response_preview = r[3][:300] + "..." if len(r[3]) > 300 else r[3]
                entries.append(
                    {
                        "idx": r[0],
                        "model": r[1],
                        "prompt_preview": prompt_preview,
                        "response_preview": response_preview,
                    }
                )
            return {"status": "success", "entries": entries, "count": len(entries)}

        elif query_type == "search" and keyword:
            pattern = f"%{keyword}%"
            results = cursor.execute(
                "SELECT idx, llm, prompt, response FROM full_llm_cache WHERE prompt LIKE ? OR response LIKE ? ORDER BY idx DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
            entries = []
            for r in results:
                prompt_preview = r[2][:200] + "..." if len(r[2]) > 200 else r[2]
                response_preview = r[3][:300] + "..." if len(r[3]) > 300 else r[3]
                entries.append(
                    {
                        "idx": r[0],
                        "model": r[1],
                        "prompt_preview": prompt_preview,
                        "response_preview": response_preview,
                    }
                )
            return {
                "status": "success",
                "keyword": keyword,
                "entries": entries,
                "count": len(entries),
            }

        elif query_type == "tool_usage":
            tool_pattern = '%"name": "execute_sql"%'
            tool_pattern2 = '%"name": "take_snapshot"%'
            tool_pattern3 = '%"name": "execute_cli"%'

            sql_count = cursor.execute(
                "SELECT COUNT(*) FROM full_llm_cache WHERE response LIKE ?", (tool_pattern,)
            ).fetchone()[0]
            snapshot_count = cursor.execute(
                "SELECT COUNT(*) FROM full_llm_cache WHERE response LIKE ?", (tool_pattern2,)
            ).fetchone()[0]
            cli_count = cursor.execute(
                "SELECT COUNT(*) FROM full_llm_cache WHERE response LIKE ?", (tool_pattern3,)
            ).fetchone()[0]

            return {
                "status": "success",
                "tool_usage": {
                    "execute_sql": sql_count,
                    "take_snapshot": snapshot_count,
                    "execute_cli": cli_count,
                },
            }

        else:
            return {"status": "error", "message": f"Unknown query_type: {query_type}"}

    finally:
        conn.close()


def _query_checkpoints(query_type: str, keyword: str | None, hours: int | None, limit: int) -> dict:
    db_path = _DB_DIR / "checkpoints.sqlite"
    if not db_path.exists() or db_path.stat().st_size == 0:
        return {
            "status": "error",
            "message": "checkpoints.sqlite not found or empty (checkpointer not enabled)",
        }

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]

        if "checkpoints" not in table_names:
            return {
                "status": "error",
                "message": "checkpoints table not found",
                "tables": table_names,
            }

        if query_type == "stats":
            total = cursor.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            threads = cursor.execute(
                "SELECT COUNT(DISTINCT thread_id) FROM checkpoints"
            ).fetchone()[0]
            return {"status": "success", "total_checkpoints": total, "unique_threads": threads}

        elif query_type == "recent":
            results = cursor.execute(
                "SELECT thread_id, step, checkpoint FROM checkpoints ORDER BY step DESC LIMIT ?",
                (limit,),
            ).fetchall()
            entries = []
            for r in results:
                cp_preview = str(r[2])[:300] + "..." if len(str(r[2])) > 300 else str(r[2])
                entries.append({"thread_id": r[0], "step": r[1], "checkpoint_preview": cp_preview})
            return {"status": "success", "entries": entries, "count": len(entries)}

        elif query_type == "search" and keyword:
            pattern = f"%{keyword}%"
            results = cursor.execute(
                "SELECT thread_id, step, checkpoint FROM checkpoints WHERE checkpoint LIKE ? LIMIT ?",
                (pattern, limit),
            ).fetchall()
            entries = []
            for r in results:
                cp_preview = str(r[2])[:300] + "..." if len(str(r[2])) > 300 else str(r[2])
                entries.append({"thread_id": r[0], "step": r[1], "checkpoint_preview": cp_preview})
            return {
                "status": "success",
                "keyword": keyword,
                "entries": entries,
                "count": len(entries),
            }

        else:
            return {"status": "error", "message": f"Unknown query_type: {query_type}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def _query_app_logs(query_type: str, keyword: str | None, hours: int | None, limit: int) -> dict:
    log_path = _LOGS_DIR / "olav.json"
    if not log_path.exists():
        return {"status": "error", "message": ".olav/logs/olav.json not found (JSON logging not enabled)"}

    try:
        with open(log_path) as f:
            lines = f.readlines()

        entries = []
        cutoff = datetime.now() - timedelta(hours=hours) if hours else None

        for line in lines[-limit * 10 :]:
            try:
                entry = json.loads(line.strip())
                if keyword and keyword.lower() not in json.dumps(entry).lower():
                    continue
                if cutoff and "timestamp" in entry:
                    ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
                    if ts.replace(tzinfo=None) < cutoff:
                        continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

        return {"status": "success", "entries": entries[:limit], "count": len(entries[:limit])}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def _analyze_logs_impl(
    source: str = "llm_cache",
    query: str = "stats",
    keyword: str = "",
    hours: int = 24,
    limit: int = 10,
) -> dict:
    source = source.lower()
    query = query.lower()
    keyword = keyword.strip() if keyword else ""

    if source == "all":
        return {
            "status": "success",
            "sources": {
                "llm_cache": _query_llm_cache("stats", None, hours, limit),
                "checkpoints": _query_checkpoints("stats", None, hours, limit),
                "app_logs": _query_app_logs("stats", None, hours, limit),
            },
        }

    elif source == "llm_cache":
        return _query_llm_cache(query, keyword if keyword else None, hours, limit)

    elif source == "checkpoints":
        return _query_checkpoints(query, keyword if keyword else None, hours, limit)

    elif source == "app_logs":
        return _query_app_logs(query, keyword if keyword else None, hours, limit)

    else:
        return {
            "status": "error",
            "message": f"Unknown source: {source}. Use llm_cache, checkpoints, app_logs, or all",
        }


@tool
def analyze_logs(
    source: str = "llm_cache",
    query: str = "stats",
    keyword: str = "",
    hours: int = 24,
    limit: int = 10,
) -> dict:
    """Analyze OLAV execution logs for self-learning and audit.

    Queries structured data from execution history databases without loading
    raw logs into LLM context. Use this to identify patterns, failures, and
    improvement opportunities.

    Args:
        source: Data source to query
            - "llm_cache": LLM request/response history
            - "checkpoints": LangGraph execution traces
            - "app_logs": Structured app events (.olav/logs/olav.json)
            - "all": Query all sources (summary only)

        query: Query type
            - "stats": Summary statistics (default)
            - "recent": Most recent entries
            - "search": Search by keyword (requires keyword param)
            - "tool_usage": Tool call statistics (llm_cache only)

        keyword: Search keyword (used with query="search")
        hours: Time window in hours (default: 24, 0 = all time)
        limit: Max entries to return (default: 10)

    Returns:
        Structured dict with status and results.
    """
    return _analyze_logs_impl(source, query, keyword, hours, limit)


if __name__ == "__main__":
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else "all"
    query = sys.argv[2] if len(sys.argv) > 2 else "stats"
    keyword = sys.argv[3] if len(sys.argv) > 3 else ""

    result = _analyze_logs_impl(source=source, query=query, keyword=keyword)
    print(json.dumps(result, indent=2))
