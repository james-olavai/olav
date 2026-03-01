"""Security Policies Configuration.

This file defines the security policies for OLAV v0.12.0.
Policies are categorized by risk level and action type.

Categories:
- Destructive: Operations that delete or modify data permanently
- High Risk: Operations that affect system state significantly
- Medium Risk: Operations that require caution

Actions:
- BLOCK: Immediately block the operation
- CONFIRM: Require explicit user confirmation before proceeding
- WARN: Allow but log a warning
"""

from pathlib import Path
from typing import Any

import yaml

# Default security policies
DEFAULT_POLICIES = {
    "version": "1.0",
    "categories": {
        "destructive": {
            "description": "Operations that permanently delete or modify data",
            "action": "BLOCK",
            "patterns": [
                "delete all",
                "remove all",
                "drop database",
                "truncate table",
                "delete * from",
                "rm -rf",
                "format disk",
                "wipe all",
                "清空所有",
                "删除全部",
            ],
        },
        "high_risk": {
            "description": "Operations that significantly affect system state",
            "action": "CONFIRM",
            "patterns": [
                "shutdown",
                "restart",
                "reboot",
                "disable firewall",
                "change password",
                "modify config",
                "deploy config",
                "apply configuration",
                "批量修改",
                "推送配置",
            ],
        },
        "medium_risk": {
            "description": "Operations that require caution",
            "action": "WARN",
            "patterns": [
                "execute command",
                "run show",
                "query database",
                "export data",
                "download file",
                "执行命令",
                "查询数据库",
            ],
        },
    },
    "guardrail": {
        "enabled": True,
        "threshold": 0.85,  # Semantic similarity threshold
        "fallback_to_llm": True,
    },
}


def load_security_policies(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load security policies from config file or return defaults.

    Args:
        config_path: Path to security_policies.yaml

    Returns:
        Security policies dictionary
    """
    if config_path is None:
        # Default to .olav/config/sync/security_policies.yaml
        config_path = Path(".olav") / "config" / "sync" / "security_policies.yaml"

    config_path = Path(config_path)

    if config_path.exists():
        try:
            with open(config_path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Warning: Failed to load security policies: {e}")

    return DEFAULT_POLICIES


def get_policy_action(category: str, policies: dict | None = None) -> str:
    """Get the action for a given policy category.

    Args:
        category: Policy category (e.g., "destructive", "high_risk")
        policies: Optional policies dict (loads defaults if None)

    Returns:
        Action string: "BLOCK", "CONFIRM", or "WARN"
    """
    if policies is None:
        policies = load_security_policies()

    categories = policies.get("categories", {})
    category_data = categories.get(category, {})

    return category_data.get("action", "WARN")


def check_query_policy(query: str, policies: dict | None = None) -> dict[str, Any]:
    """Check if a query matches any security policy patterns.

    Args:
        query: User query string to check
        policies: Optional policies dict (loads defaults if None)

    Returns:
        Dict with:
        - category: Matched category or None
        - action: Action to take ("BLOCK", "CONFIRM", "WARN", "ALLOW")
        - matched_patterns: List of matched patterns
        - confidence: Similarity score (if using semantic matching)
    """
    if policies is None:
        policies = load_security_policies()

    # Check if guardrails are enabled
    guardrail = policies.get("guardrail", {})
    if not guardrail.get("enabled", True):
        return {
            "category": None,
            "action": "ALLOW",
            "matched_patterns": [],
            "confidence": 0.0,
        }

    query_lower = query.lower()
    categories = policies.get("categories", {})

    # Check each category's patterns
    for category_name, category_data in categories.items():
        patterns = category_data.get("patterns", [])

        for pattern in patterns:
            pattern_lower = pattern.lower()

            # Simple substring match first
            if pattern_lower in query_lower:
                return {
                    "category": category_name,
                    "action": category_data.get("action", "WARN"),
                    "matched_patterns": [pattern],
                    "confidence": 1.0,
                    "match_type": "exact",
                }

    # Try semantic matching if enabled
    if guardrail.get("fallback_to_llm", True):
        return _semantic_check(query, categories, guardrail.get("threshold", 0.85))

    return {
        "category": None,
        "action": "ALLOW",
        "matched_patterns": [],
        "confidence": 0.0,
    }


def _semantic_check(query: str, categories: dict, threshold: float) -> dict[str, Any]:
    """Perform semantic matching for policy patterns.

    Args:
        query: User query
        categories: Policy categories
        threshold: Similarity threshold

    Returns:
        Policy check result with semantic matching
    """
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        from olav.core.config import get_embedding_config

        # Get embeddings
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

        # Get all patterns
        all_patterns = []
        for category_name, category_data in categories.items():
            for pattern in category_data.get("patterns", []):
                all_patterns.append(
                    {
                        "pattern": pattern,
                        "category": category_name,
                        "action": category_data.get("action", "WARN"),
                    }
                )

        if not all_patterns:
            return {
                "category": None,
                "action": "ALLOW",
                "matched_patterns": [],
                "confidence": 0.0,
            }

        # Generate embeddings
        pattern_texts = [p["pattern"] for p in all_patterns]
        query_embedding = embeddings.embed_query(query)
        pattern_embeddings = embeddings.embed_documents(pattern_texts)

        # Calculate similarities
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        similarities = cosine_similarity([query_embedding], pattern_embeddings)[0]

        # Find best match
        best_idx = np.argmax(similarities)
        best_score = similarities[best_idx]

        if best_score >= threshold:
            best_match = all_patterns[best_idx]
            return {
                "category": best_match["category"],
                "action": best_match["action"],
                "matched_patterns": [best_match["pattern"]],
                "confidence": float(best_score),
                "match_type": "semantic",
            }

    except Exception as e:
        print(f"Warning: Semantic policy check failed: {e}")

    return {
        "category": None,
        "action": "ALLOW",
        "matched_patterns": [],
        "confidence": 0.0,
    }


def create_default_policy_file(config_path: str | Path) -> None:
    """Create default security_policies.yaml file.

    Args:
        config_path: Path where to create the config file
    """
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(DEFAULT_POLICIES, f, default_flow_style=False)

    print(f"Created default security policies at {config_path}")
