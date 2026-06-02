#!/usr/bin/env python3
"""
Fuzzy Schema Mapping Tool - Normalize multi-vendor output to Cisco baseline.

This tool uses LLM to translate vendor-specific JSON keys to Cisco standard keys,
then caches the mapping in the schema_mappings table for future use.

Usage:
    fuzzy_map_schema(vendor="huawei", command="display bgp peer", raw_data={...})
"""

import json
import logging
import sys
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Locate project root."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import duckdb

from olav.core.config import MAIN_DB_PATH
from olav.core.llm import LLMFactory

# CISCO_BASELINE_SCHEMAS removed - now loaded from config/baselines.yaml

def _get_skill_root() -> Path:
    """Locate the root of this skill."""
    return Path(__file__).resolve().parent.parent

def _load_baselines() -> dict:
    """Load baseline schemas from the skill's config directory."""
    import yaml
    config_path = _get_skill_root() / "config" / "normalization_strategy.yaml"
    if not config_path.exists():
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Failed to load baselines.yaml: %s", e)
        return {}

def _get_standard_command(vendor_command: str, standard_platform: str) -> str:
    """Use LLM to translate a vendor command to its standard platform equivalent."""
    llm = LLMFactory.get_chat_model(temperature=0)
    prompt = f"""
    Translate the following network CLI command to its equivalent on the standard platform.
    
    Vendor Command: {vendor_command}
    Standard Platform: {standard_platform}
    
    Respond only with the command string. No explanation.
    Example: "display bgp peer" -> "show ip bgp neighbors"
    """
    from langchain_core.messages import HumanMessage
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip().strip('"').strip("'")
    except Exception:
        return vendor_command

def _get_standard_sample(platform: str, command: str) -> dict | None:
    """Attempt to find a sample of parsed data for a standard platform/command."""
    try:
        with duckdb.connect(str(MAIN_DB_PATH)) as conn:
            # Join with devices to find data belonging to the baseline platform
            sql = """
                SELECT p.parsed_data
                FROM netops.parsed_outputs p
                JOIN netops.devices d ON p.device_name = d.hostname
                WHERE d.platform = ? AND p.command = ?
                ORDER BY p.ingested_at DESC
                LIMIT 1
            """
            result = conn.execute(sql, [platform, command]).fetchone()
            if result:
                # parsed_data is JSON in DuckDB
                data = json.loads(result[0]) if isinstance(result[0], str) else result[0]
                return data[0] if isinstance(data, list) and data else data
    except Exception as e:
        logger.debug("Failed to fetch standard sample: %s", e)
    return None

def _get_db_schema(table_name: str) -> dict | None:
    """Discover schema dynamically from DuckDB."""
    try:
        with duckdb.connect(str(MAIN_DB_PATH)) as conn:
            # Check if table exists
            table_exists = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
                [table_name]
            ).fetchone()[0]

            if not table_exists:
                return None

            result = conn.execute(f"DESCRIBE {table_name}").fetchall()
            fields = {row[0]: str(row[1]) for row in result}

            return {
                "description": f"Target table structure from '{table_name}'",
                "fields": fields
            }
    except Exception:
        return None

class FuzzyMapInput(BaseModel):
    """Input for fuzzy schema mapping."""

    vendor: str = Field(..., description="Vendor name (e.g., huawei, juniper, arista)")
    platform: str | None = Field(default=None, description="Specific platform (e.g., cisco_ios, cisco_asa)")
    command: str = Field(..., description="CLI command that produced the data")
    raw_data: list[dict] = Field(..., description="Raw parsed JSON data from vendor")
    table_name: str = Field(..., description="Target table name")

class FuzzyMapOutput(BaseModel):
    """Output from fuzzy schema mapping."""

    status: str = Field(..., description="success | error | cached")
    mappings: list[dict] = Field(default_factory=list, description="Key mappings applied")
    normalized_data: list[dict] | None = Field(default=None, description="Normalized data")
    message: str | None = Field(default=None, description="Additional information")
    error: str | None = Field(default=None, description="Error message if status=error")


def _ensure_schema_mappings_table():
    """Create schema_mappings table if it doesn't exist."""
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_mappings (
                vendor VARCHAR NOT NULL,
                command VARCHAR NOT NULL,
                raw_key VARCHAR NOT NULL,
                cisco_key VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(vendor, command, raw_key)
            )
        """)


def _check_cache(vendor: str, command: str) -> list[dict] | None:
    """Check if mapping exists in cache."""
    _ensure_schema_mappings_table()

    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        try:
            result = conn.execute(
                """
                SELECT raw_key, cisco_key 
                FROM schema_mappings 
                WHERE vendor = ? AND command = ?
            """,
                [vendor, command],
            ).fetchall()

            if result:
                return [{"raw_key": r[0], "cisco_key": r[1]} for r in result]
        except Exception:
            pass

    return None


def _save_mappings(vendor: str, command: str, mappings: list[dict]):
    """Save mappings to cache."""
    _ensure_schema_mappings_table()

    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        for mapping in mappings:
            conn.execute(
                """
                INSERT OR REPLACE INTO schema_mappings (vendor, command, raw_key, cisco_key)
                VALUES (?, ?, ?, ?)
            """,
                [vendor, command, mapping["raw_key"], mapping["cisco_key"]],
            )


def _call_llm_for_mapping(
    vendor: str, command: str, raw_sample: dict, standard_schema: dict, standard_platform: str
) -> list[dict]:
    """Call LLM to generate key mappings."""
    llm = LLMFactory.get_chat_model(temperature=0.1)

    prompt = f"""You are a network automation expert. Map the {vendor} JSON keys to the standard platform ({standard_platform}) keys.

{vendor} command: {command}

Sample {vendor} data:
{json.dumps(raw_sample, indent=2)}

Standard baseline schema for {standard_schema["description"]}:
{json.dumps(standard_schema["fields"], indent=2)}

Respond with a JSON array of mappings in this format:
[
  {{"raw_key": "<vendor_key>", "cisco_key": "<standard_key>"}},
  ...
]

Keep the target key name as "cisco_key" in the JSON structure for database compatibility, but map it to the {standard_platform} equivalent field name.
Only include mappings where the keys are actually different. If a key is the same in both, don't include it.
"""

    from langchain_core.messages import HumanMessage

    response = llm.invoke([HumanMessage(content=prompt)])

    # Parse JSON from response
    try:
        # Try to extract JSON from response
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        mappings = json.loads(content.strip())
        return mappings
    except Exception as e:
        raise ValueError(f"Failed to parse LLM response: {e}")


def _apply_mappings(data: list[dict], mappings: list[dict]) -> list[dict]:
    """Apply key mappings to data."""
    # Create lookup dict
    key_map = {m["raw_key"]: m["cisco_key"] for m in mappings}

    normalized = []
    for row in data:
        new_row = {}
        for key, value in row.items():
            new_key = key_map.get(key, key)  # Use mapped key or original
            new_row[new_key] = value
        normalized.append(new_row)

    return normalized


def main(params: dict) -> dict:
    """Perform fuzzy schema mapping."""
    try:
        args = FuzzyMapInput(**params)
    except Exception as e:
        return FuzzyMapOutput(status="error", error=f"Invalid parameters: {str(e)}").model_dump(
            exclude_none=True
        )

    vendor = args.vendor.lower()
    platform = args.platform.lower() if args.platform else None
    command = args.command
    raw_data = args.raw_data
    table_name = args.table_name

    # 1. Load Strategy
    strategy = _load_baselines()
    categories = strategy.get("device_categories", {})

    # 2. Determine Category and Standard Platform
    standard_platform = "cisco_ios" # Default fallback

    for cat, details in categories.items():
        if platform in details.get("platforms", []) or vendor in details.get("platforms", []):
            standard_platform = details.get("standard_platform", standard_platform)
            break

    # 3. Discover Baseline Schema
    baseline_schema = {}

    # Priority 1: Direct Table Schema from DuckDB (Static Truth)
    db_schema = _get_db_schema(table_name)
    if db_schema:
        baseline_schema = db_schema

    # Priority 2: Auto-discover from Standard Platform's parsed data (Dynamic Truth)
    # We ask LLM "What is the equivalent command on Cisco?"
    standard_command = _get_standard_command(command, standard_platform)

    if standard_command:
        sample = _get_standard_sample(standard_platform, standard_command)
        if sample:
            sample_fields = {k: "str" for k in sample.keys()}
            if baseline_schema:
                # Merge: favor table schema but expand with fields from samples
                baseline_schema["fields"].update(sample_fields)
                baseline_schema["description"] += f" (Augmented with {standard_platform} sample)"
            else:
                baseline_schema = {
                    "description": f"Auto-discovered from {standard_platform} '{standard_command}'",
                    "fields": sample_fields
                }

    if not baseline_schema:
        return FuzzyMapOutput(
            status="error",
            error=f"Discovery failed: No baseline table '{table_name}' and no sample data for "
                  f"platform '{standard_platform}' found in database.",
        ).model_dump(exclude_none=True)

    # Check cache first
    cached_mappings = _check_cache(vendor, command)

    if cached_mappings:
        # Use cached mappings
        normalized = _apply_mappings(raw_data, cached_mappings)
        return FuzzyMapOutput(
            status="cached",
            mappings=cached_mappings,
            normalized_data=normalized,
            message="Used cached schema mappings",
        ).model_dump(exclude_none=True)

    # Need to call LLM for mapping
    if not raw_data:
        return FuzzyMapOutput(status="error", error="No raw data provided").model_dump(
            exclude_none=True
        )

    try:
        # Use first row as sample for mapping
        mappings = _call_llm_for_mapping(vendor, command, raw_data[0], baseline_schema, standard_platform)

        # Save mappings to cache
        _save_mappings(vendor, command, mappings)

        # Apply mappings
        normalized = _apply_mappings(raw_data, mappings)

        return FuzzyMapOutput(
            status="success",
            mappings=mappings,
            normalized_data=normalized,
            message=f"Generated {len(mappings)} key mappings via LLM",
        ).model_dump(exclude_none=True)

    except Exception as e:
        return FuzzyMapOutput(status="error", error=str(e)).model_dump(exclude_none=True)


# =============================================================================
# LangChain Tool Registration
# =============================================================================


@tool
def fuzzy_map_schema(
    vendor: str,
    command: str,
    raw_data: list[dict],
    table_name: str = "interfaces",
    platform: str | None = None,
) -> dict:
    """Normalize multi-vendor parsed output to a standard schema.

    Uses LLM to translate vendor-specific JSON keys to standard keys (e.g., Cisco IOS baseline),
    then caches the mapping for future use. Baselines are classified by device category 
    (routing, firewall, wireless) in configuration.

    Args:
        vendor: Vendor name (huawei, juniper, arista, etc.)
        command: CLI command that produced the data
        raw_data: Raw parsed JSON data from vendor
        table_name: Target baseline table (interfaces, bgp_neighbors, ospf_neighbors, routes, etc.)
        platform: Optional specific platform (cisco_ios, cisco_asa) for better classification

    Returns:
        Dictionary with mappings applied and normalized data
    """
    return main(
        {
            "vendor": vendor,
            "command": command,
            "raw_data": raw_data,
            "table_name": table_name,
            "platform": platform,
        }
    )


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
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)
