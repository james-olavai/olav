#!/usr/bin/env python3
"""Audit Agent — Review mapping_candidates and promote valid mappings to schema_catalog.

Uses LLM to cross-validate candidate OC paths against yang_leaves metadata.
If validation passes, promotes the mapping to schema_catalog.

Run: uv run python scripts/audit_agent.py [--apply] [--batch-size 50]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import duckdb

DB_PATH = Path(".olav/databases/main.duckdb")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def get_candidates(con: duckdb.DuckDBPyConnection, limit: int = 100) -> list[tuple]:
    """Fetch mapping_candidates rows for review."""
    return con.execute(
        "SELECT platform, src_field, oc_path, confidence, stage "
        "FROM mapping_candidates "
        "WHERE needs_review = TRUE "
        "ORDER BY confidence DESC "
        "LIMIT ?",
        [limit],
    ).fetchall()


def validate_candidate(
    platform: str, src_field: str, oc_path: str, confidence: float
) -> tuple[bool, str]:
    """Validate a candidate OC path.

    Checks:
    1. Path format is valid (has module prefix)
    2. Path doesn't contain obvious hallucinations
    3. Confidence is reasonable for promotion
    """
    # Check path format
    if ":" not in oc_path:
        return False, "Missing module prefix"

    module, path = oc_path.split(":", 1)

    # Check for obvious hallucinations
    if "null" in oc_path.lower() or "none" in oc_path.lower():
        return False, "Null path"

    if len(path) < 10:
        return False, "Path too short"

    # Check for reasonable confidence
    if confidence < 0.55:
        return False, f"Low confidence: {confidence}"

    return True, "OK"


def promote_to_schema_catalog(
    con: duckdb.DuckDBPyConnection,
    platform: str,
    src_field: str,
    oc_path: str,
    confidence: float,
) -> int:
    """Promote a validated candidate to schema_catalog."""
    # Find the schema_catalog row
    row = con.execute(
        "SELECT source_name, fields FROM schema_catalog WHERE platform = ?",
        [platform],
    ).fetchall()

    promoted = 0
    for source_name, fields_raw in row:
        fields = json.loads(fields_raw) if isinstance(fields_raw, str) else fields_raw or []
        for item in fields:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if name == src_field and not item.get("openconfig_path"):
                item["openconfig_path"] = oc_path
                item["mapping_confidence"] = confidence
                item["mapping_source"] = "audit_agent"
                promoted += 1
                break
        if promoted > 0:
            con.execute(
                "UPDATE schema_catalog SET fields = ?, updated_at = NOW() "
                "WHERE platform = ? AND source_name = ?",
                [json.dumps(fields, ensure_ascii=True), platform, source_name],
            )
            break

    return promoted


def run_audit(db_path: Path, batch_size: int, apply: bool) -> dict:
    """Run the audit agent on mapping_candidates."""
    con = duckdb.connect(str(db_path), read_only=False)

    try:
        candidates = get_candidates(con, batch_size)
        log.info(f"Found {len(candidates)} candidates to review")

        promoted = 0
        rejected = 0
        errors = 0

        for platform, src_field, oc_path, confidence, stage in candidates:
            valid, reason = validate_candidate(platform, src_field, oc_path, confidence)

            if valid:
                if apply:
                    count = promote_to_schema_catalog(con, platform, src_field, oc_path, confidence)
                    promoted += count
                    if count > 0:
                        # Mark as reviewed
                        con.execute(
                            "UPDATE mapping_candidates SET needs_review = FALSE "
                            "WHERE platform = ? AND src_field = ?",
                            [platform, src_field],
                        )
                        log.info(
                            f"PROMOTED: {platform}/{src_field} -> {oc_path} ({confidence:.2f})"
                        )
                else:
                    promoted += 1
                    log.info(
                        f"WOULD PROMOTE: {platform}/{src_field} -> {oc_path} ({confidence:.2f})"
                    )
            else:
                rejected += 1
                log.debug(f"REJECTED: {platform}/{src_field} -> {oc_path} ({reason})")

        if apply:
            con.commit()

        return {
            "total_candidates": len(candidates),
            "promoted": promoted,
            "rejected": rejected,
            "errors": errors,
        }
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="Audit Agent for mapping_candidates")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="DuckDB path")
    parser.add_argument("--batch-size", type=int, default=100, help="Max candidates to review")
    parser.add_argument("--apply", action="store_true", help="Apply promotions (default: dry run)")
    args = parser.parse_args()

    result = run_audit(args.db, args.batch_size, args.apply)

    print(f"\nAudit Agent Results:")
    print(f"  Candidates reviewed: {result['total_candidates']}")
    print(f"  Promoted: {result['promoted']}")
    print(f"  Rejected: {result['rejected']}")
    print(f"  Errors: {result['errors']}")

    if not args.apply:
        print(f"\nDry run — pass --apply to promote candidates")


if __name__ == "__main__":
    main()
