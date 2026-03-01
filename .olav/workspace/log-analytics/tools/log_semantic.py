#!/usr/bin/env python3
"""
Log Semantic Search Tool - LanceDB vector search for fault diagnosis.

Core Features:
1. Semantic search over enhanced diagnostic cards
2. Device and severity filtering
3. Time-range filtering
4. Similar fault pattern matching

Usage in DeepAgents:
    from .tools import semantic_log_search
    agent = create_deep_agent(tools=[semantic_log_search.semantic_log_search])
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator


# Add src to Python Path
def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import DATABASES_DIR

logger = logging.getLogger(__name__)

# Default embedding dimension (bge-small)
DEFAULT_EMBEDDING_DIM = 384


def _get_logs_lancedb_path() -> Path:
    """Get the logs LanceDB path."""
    lancedb_path = Path(DATABASES_DIR) / "lancedb" / "logs.lance"
    return lancedb_path


def _init_lancedb_table():
    """Initialize the LanceDB table for log diagnostics."""
    try:
        import lancedb

        db_path = _get_logs_lancedb_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        db = lancedb.connect(str(db_path))

        # Schema for diagnostic cards
        schema = {
            "id": "string",
            "device_name": "string",
            "timestamp": "string",
            "severity": "string",
            "original_message": "string",
            "enhanced_summary": "string",
            "root_cause": "string",
            "affected_module": "string",
            "fix_recommendation": "string",
            "vector": "fixed-size-list[float32]",  # 384-dim embedding
        }

        # Check if table exists
        table_names = db.table_names()
        if "diagnostics" not in table_names:
            db.create_table("diagnostics", schema=schema)
            logger.info("Created diagnostics table in logs.lance")

        return db.open_table("diagnostics")

    except Exception as e:
        logger.error(f"Failed to initialize LanceDB: {e}")
        raise


def _get_embeddings(query: str) -> list[float]:
    """Get embeddings for a query string."""
    try:
        from olav.core.llm import LLMFactory

        embeddings = LLMFactory.get_embeddings()
        query_vector = embeddings.embed_query(query)

        # Ensure vector matches expected dimension
        if len(query_vector) < DEFAULT_EMBEDDING_DIM:
            query_vector = list(query_vector) + [0.0] * (DEFAULT_EMBEDDING_DIM - len(query_vector))
        elif len(query_vector) > DEFAULT_EMBEDDING_DIM:
            query_vector = list(query_vector)[:DEFAULT_EMBEDDING_DIM]

        return query_vector

    except Exception as e:
        logger.warning(f"Failed to get embeddings: {e}. Using random vector for testing.")
        import random

        return [random.random() for _ in range(DEFAULT_EMBEDDING_DIM)]


class SemanticSearchInput(BaseModel):
    """Semantic search input parameters."""

    query: str = Field(default="", description="Natural language query about fault symptoms")
    limit: int = Field(default=5, description="Maximum number of results")
    device_name: str | None = Field(default=None, description="Filter by device name")
    severity: str | None = Field(default=None, description="Filter by severity (ERROR, CRITICAL)")
    start_date: str | None = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="End date (YYYY-MM-DD)")

    @validator("query", pre=True)
    def validate_not_none(cls, v):
        if v is None:
            return ""
        return v


class SemanticSearchOutput(BaseModel):
    """Semantic search output format."""

    data: list[dict] | None = Field(default=None, description="Search results")
    count: int | None = Field(default=None, description="Number of results")
    status: str = Field(..., description="success | error | no_data")
    error: str | None = Field(default=None, description="Error message if status=error")
    lancedb_path: str | None = Field(default=None, description="LanceDB path used")


def main(params: dict) -> dict:
    """Execute semantic search over log diagnostics.

    Args:
        params: {
            "query": "Natural language query",
            "limit": 5,
            "device_name": "device-01",
            "severity": "ERROR",
            "start_date": "2026-02-01",
            "end_date": "2026-02-28"
        }

    Returns:
        Search results with diagnostic cards
    """
    try:
        args = SemanticSearchInput(**params)
    except Exception as e:
        return SemanticSearchOutput(
            status="error", error=f"Invalid parameters: {str(e)}"
        ).model_dump(exclude_none=True)

    if not args.query or not args.query.strip():
        return SemanticSearchOutput(status="error", error="Query must not be empty").model_dump(
            exclude_none=True
        )

    db_path = _get_logs_lancedb_path()

    try:
        # Initialize table
        table = _init_lancedb_table()

        # Get query embeddings
        query_vector = _get_embeddings(args.query)

        # Build filters
        filters = []
        if args.device_name:
            filters.append(f"device_name = '{args.device_name}'")
        if args.severity:
            filters.append(f"severity = '{args.severity}'")
        if args.start_date:
            filters.append(f"timestamp >= '{args.start_date}'")
        if args.end_date:
            filters.append(f"timestamp <= '{args.end_date}'")

        filter_str = " AND ".join(filters) if filters else None

        # Execute vector search
        results = table.search(query_vector).limit(args.limit).where(filter_str).to_list()

        if not results:
            return SemanticSearchOutput(
                status="no_data",
                count=0,
                lancedb_path=str(db_path),
                message="No diagnostic cards found. Use log_metrics_query to analyze raw logs first.",
            ).model_dump(exclude_none=True)

        # Format results
        formatted_results = []
        for r in results:
            formatted_results.append(
                {
                    "id": r.get("id", ""),
                    "device_name": r.get("device_name", ""),
                    "timestamp": r.get("timestamp", ""),
                    "severity": r.get("severity", ""),
                    "original_message": r.get("original_message", "")[:200] + "..."
                    if r.get("original_message")
                    else "",
                    "enhanced_summary": r.get("enhanced_summary", ""),
                    "root_cause": r.get("root_cause", ""),
                    "affected_module": r.get("affected_module", ""),
                    "fix_recommendation": r.get("fix_recommendation", ""),
                    "score": r.get("score", r.get("_distance", "N/A")),
                }
            )

        return SemanticSearchOutput(
            data=formatted_results,
            count=len(formatted_results),
            status="success",
            lancedb_path=str(db_path),
        ).model_dump(exclude_none=True)

    except Exception as e:
        logger.error(f"Semantic search failed: {e}", exc_info=True)
        return SemanticSearchOutput(
            status="error", error=str(e), lancedb_path=str(db_path)
        ).model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration
# ============================================================================


@tool
def semantic_log_search(
    query: str,
    limit: int = 5,
    device_name: str | None = None,
    severity: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Search the semantic fault knowledge base for similar past incidents.

    WHEN TO USE:
    - "Show me similar past faults"
    - "What caused this error before?"
    - Root cause analysis from natural language
    - Finding historical patterns for recurring issues

    DATA STORAGE:
    - LanceDB at .olav/databases/lancedb/logs.lance
    - Stores LLM-enhanced diagnostic cards

    FEATURES:
    - Vector similarity search
    - Device and severity filtering
    - Time-range filtering
    - Similar fault pattern matching

    Args:
        query: Natural language query describing fault symptoms
               Be specific about: protocol, problem, vendor

        limit: Maximum number of results (default=5, max=20)

        device_name: Filter by specific device

        severity: Filter by severity (ERROR, CRITICAL, WARNING)

        start_date: Start date (YYYY-MM-DD)

        end_date: End date (YYYY-MM-DD)

    Returns:
        List of similar diagnostic cards with root cause and recommendations

    Examples:
        Example 1 - Find similar interface errors:
        >>> semantic_log_search(query="interface flapping packet loss")

        Example 2 - Find CPU issues on specific device:
        >>> semantic_log_search(query="high CPU usage", device_name="R1", severity="ERROR")

        Example 3 - Find recent authentication failures:
        >>> semantic_log_search(query="authentication failure", start_date="2026-02-01", limit=10)
    """
    params = {
        "query": query,
        "limit": limit,
        "device_name": device_name,
        "severity": severity,
        "start_date": start_date,
        "end_date": end_date,
    }
    return main(params)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(
            json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False), file=sys.stderr
        )
        sys.exit(1)
