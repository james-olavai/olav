"""Sync Security Rules Tool.

This tool synchronizes security policies to the LanceDB vector store
for semantic matching against user queries.

Usage:
    sync_security_rules --policies .olav/config/sync/security_policies.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

import lancedb
import yaml

logger = logging.getLogger(__name__)


def sync_security_rules(
    policies_path: str | Path,
    db_path: str | Path | None = None,
) -> dict:
    """Sync security rules to LanceDB.

    Args:
        policies_path: Path to security_policies.yaml
        db_path: Optional path to LanceDB (defaults to memory.lancedb)

    Returns:
        Dict with sync status
    """
    policies_path = Path(policies_path)

    # Load policies
    if not policies_path.exists():
        return {
            "status": "error",
            "message": f"Policy file not found: {policies_path}",
        }

    with open(policies_path) as f:
        policies = yaml.safe_load(f)

    # Get categories
    categories = policies.get("categories", {})

    if not categories:
        return {
            "status": "error",
            "message": "No categories found in policy file",
        }

    # Connect to LanceDB
    if db_path is None:
        db_path = Path(".olav") / "databases" / "memory.lancedb"

    db_path = Path(db_path)
    db = lancedb.connect(str(db_path))

    # Create or open table
    try:
        table = db.open_table("security_denylist")

        # Clear existing data
        table.delete("true")
        logger.info("Cleared existing security rules")

    except Exception:
        # Create new table
        import pyarrow as pa

        schema = pa.schema(
            [
                ("vector", pa.list_(pa.float32())),
                ("pattern", pa.string()),
                ("category", pa.string()),
                ("action", pa.string()),
                ("description", pa.string()),
            ]
        )

        table = db.create_table("security_denylist", schema=schema)
        logger.info("Created security_denylist table")

    # Prepare records
    records = []

    for category_name, category_data in categories.items():
        action = category_data.get("action", "WARN")
        description = category_data.get("description", "")
        patterns = category_data.get("patterns", [])

        for pattern in patterns:
            records.append(
                {
                    "pattern": pattern,
                    "category": category_name,
                    "action": action,
                    "description": description,
                }
            )

    if not records:
        return {
            "status": "error",
            "message": "No patterns to sync",
        }

    # Generate embeddings
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        from olav.core.config import get_embedding_config

        emb_config = get_embedding_config()

        if emb_config.mode == "local":
            embeddings = HuggingFaceEmbeddings(
                model_name=emb_config.local_model,
                model_kwargs={"device": emb_config.device},
            )
        else:
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                model=emb_config.api_model,
                api_key=emb_config.api_key,
            )

        pattern_texts = [r["pattern"] for r in records]
        vectors = embeddings.embed_documents(pattern_texts)

        # Add vectors to records
        for i, record in enumerate(records):
            record["vector"] = vectors[i]

    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        return {
            "status": "error",
            "message": f"Failed to generate embeddings: {e}",
        }

    # Insert into table
    table.add(records)

    logger.info(f"Synced {len(records)} security rules to LanceDB")

    return {
        "status": "success",
        "count": len(records),
        "categories": list(categories.keys()),
    }


def check_security_violation(query: str, db_path: str | Path | None = None) -> dict:
    """Check if a query violates any security policy.

    Args:
        query: User query to check
        db_path: Optional path to LanceDB

    Returns:
        Dict with check result:
        - violation: True if query violates a BLOCK or CONFIRM policy
        - category: Matched category
        - action: Action to take
        - matched_pattern: The pattern that matched
        - confidence: Similarity score
    """
    if db_path is None:
        db_path = Path(".olav") / "databases" / "memory.lancedb"

    db_path = Path(db_path)

    try:
        db = lancedb.connect(str(db_path))
        table = db.open_table("security_denylist")
    except Exception:
        # Table doesn't exist, no security rules synced
        return {
            "violation": False,
            "category": None,
            "action": "ALLOW",
            "matched_pattern": None,
            "confidence": 0.0,
        }

    # Generate query embedding
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        from olav.core.config import get_embedding_config

        emb_config = get_embedding_config()

        if emb_config.mode == "local":
            embeddings = HuggingFaceEmbeddings(
                model_name=emb_config.local_model,
                model_kwargs={"device": emb_config.device},
            )
        else:
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                model=emb_config.api_model,
                api_key=emb_config.api_key,
            )

        query_vector = embeddings.embed_query(query)

    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        return {
            "violation": False,
            "error": str(e),
        }

    # Search
    results = table.search(query_vector, "vector").limit(1).to_list()

    if not results:
        return {
            "violation": False,
            "category": None,
            "action": "ALLOW",
            "matched_pattern": None,
            "confidence": 0.0,
        }

    best_match = results[0]
    distance = best_match.get("distance", 1.0)
    confidence = 1.0 - distance

    # Threshold for matching
    match_threshold = 0.85

    if confidence >= match_threshold:
        action = best_match.get("action", "WARN")

        return {
            "violation": action in ["BLOCK", "CONFIRM"],
            "category": best_match.get("category"),
            "action": action,
            "matched_pattern": best_match.get("pattern"),
            "confidence": confidence,
        }

    return {
        "violation": False,
        "category": None,
        "action": "ALLOW",
        "matched_pattern": None,
        "confidence": confidence,
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Sync security rules to LanceDB")
    parser.add_argument(
        "--policies",
        type=str,
        default=".olav/config/sync/security_policies.yaml",
        help="Path to security_policies.yaml",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to LanceDB database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    result = sync_security_rules(args.policies, args.db_path)

    if result["status"] == "success":
        print(f"✓ Synced {result['count']} security rules")
        print(f"  Categories: {', '.join(result['categories'])}")
        return 0
    else:
        print(f"✗ Error: {result['message']}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
