#!/usr/bin/env python3
"""
Generate OpenConfig YANG paths for unmapped schema_catalog fields using LLM.

This script:
1. Loads unmapped fields from schema_catalog
2. For each gap field (platform + command + field_name), generates OpenConfig path suggestions
3. Writes high-confidence mappings to mapping_rules table
4. Outputs detailed feedback (JSON) for review and validation

Design principle: Schema-to-schema matching via LLM (YANG leaf ↔ TextFSM field).
Reference: dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md § OC-13
"""

import json
import logging
import copy
from typing import Any, Optional, TypedDict, List, Dict
from dataclasses import dataclass, asdict
from datetime import datetime

import duckdb

# Import LLM factory from olav framework
try:
    from olav.core.llm import LLMFactory
except ImportError as e:
    print(f"ERROR: Cannot import LLMFactory: {e}")
    print("Make sure you're in the OLAV project root and dependencies are installed: uv pip install -e .")
    raise

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@dataclass
class MappingCandidate:
    """Result of LLM-generated OpenConfig path candidate."""

    platform: str
    source_name: str  # command
    src_field: str
    openconfig_path: str
    confidence: float  # 0.0-1.0
    reasoning: str
    attempt_number: int = 1


class GapField(TypedDict):
    """Structure of gap field from schema_catalog."""

    platform: str
    source_name: str
    field_name: str
    field_type: str


def _load_gap_fields(db_path: str, limit: Optional[int] = None) -> List[GapField]:
    """Load unmapped fields from schema_catalog.

    Priority: start with top gap commands (most critical for gate).
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        # Load raw data and filter in Python for better control
        query = "SELECT platform, source_name, fields FROM schema_catalog ORDER BY platform, source_name"
        
        rows = con.execute(query).fetchall()
        gaps: List[GapField] = []
        
        for platform, source_name, fields_json in rows:
            try:
                # Parse fields JSON
                if isinstance(fields_json, str):
                    fields_list = json.loads(fields_json)
                else:
                    fields_list = fields_json
                
                # Check each field in the array
                if isinstance(fields_list, list):
                    for field_obj_raw in fields_list:
                        # Type cast for proper typing
                        field_obj: Dict[str, Any] = field_obj_raw if isinstance(field_obj_raw, dict) else {}
                        field_name = field_obj.get("name")
                        field_type = field_obj.get("type", "unknown")
                        openconfig_path = field_obj.get("openconfig_path")
                        
                        # Only include unmapped fields
                        if field_name and (not openconfig_path or openconfig_path == ""):
                            gap: GapField = {
                                "platform": str(platform),
                                "source_name": str(source_name),
                                "field_name": str(field_name),
                                "field_type": str(field_type),
                            }
                            gaps.append(gap)
                            
                            if limit and len(gaps) >= limit:
                                logging.info(f"Reached limit of {limit} gap fields")
                                con.close()
                                return gaps
                                
            except (json.JSONDecodeError, TypeError) as e:
                logging.warning(f"Failed to parse fields for {platform}/{source_name}: {e}")
                continue
        
        logging.info(f"Loaded {len(gaps)} gap fields from schema_catalog")
        return gaps

    finally:
        con.close()


def _build_prompt(gap: GapField, context: str = "") -> str:
    """Build LLM prompt for mapping generation.

    Provide:
    - Source field name, type, platform, command
    - Domain context (e.g., routing, interfaces, BGP)
    - OpenConfig YANG hierarchy hints
    """

    platform = gap["platform"]
    command = gap["source_name"]
    field = gap["field_name"]
    field_type = gap["field_type"]

    # Infer domain from command name
    domain = _infer_domain(command)

    prompt = f"""You are an expert in network device data mapping and OpenConfig YANG models.

Your task: Suggest the most likely OpenConfig YANG path for a TextFSM field.

**Input:**
- Platform: {platform}
- Command: {command}
- Field name: {field}
- Field type: {field_type}
- Domain: {domain}
{context}

**Output Format:**
Respond ONLY with a JSON object:
{{
    "openconfig_path": "/openconfig-interfaces:interfaces/interface[name='eth0']/config/...",
    "confidence": 0.85,
    "reasoning": "Field 'mtu' on interfaces typically maps to MTU config in openconfig-interfaces."
}}

**Constraints:**
1. Use standard OpenConfig YANG paths (e.g., /openconfig-interfaces, /openconfig-bgp, /openconfig-system)
2. Confidence 0.0-1.0: higher if field name clearly matches YANG leaf names
3. Avoid guessing: if uncertain, return confidence < 0.5
4. Do NOT include list indices in the path template (use [name='*'] or [*] for placeholders)
5. Prefer shallow paths (avoid deeply nested structures unless field name suggests it)

**Examples:**
- Field "mtu" on interfaces → "/openconfig-interfaces:interfaces/interface[name='*']/config/mtu" (confidence 0.95)
- Field "uptime" on BGP neighbors → "/openconfig-bgp:bgp/neighbors/neighbor[neighbor-address='*']/state/uptime" (confidence 0.9)
- Field "serial_number" (ambiguous) → "/openconfig-system:system/state/serial-number" (confidence 0.6)
- Field "vendor_specific_token" → {{no reasonable mapping}} (confidence 0.0)

**Field: {field}**

Now generate the mapping:
"""

    return prompt


def _infer_domain(command: str) -> str:
    """Infer domain (routing, interfaces, BGP, etc.) from command name."""
    cmd_lower = command.lower()

    domain_keywords = {
        "routing": ["route", "routing", "ospf", "isis", "bgp", "rip"],
        "interfaces": ["interface", "port", "ethernet", "vlan"],
        "bgp": ["bgp"],
        "ospf": ["ospf"],
        "system": ["system", "chassis", "hardware"],
        "vlan": ["vlan", "switchport"],
        "access_control": ["acl", "access-list"],
        "qos": ["qos", "queue", "police", "shape"],
    }

    for domain, keywords in domain_keywords.items():
        if any(kw in cmd_lower for kw in keywords):
            return domain

    return "general"


def _parse_llm_response(response: str) -> Optional[Dict[str, Any]]:
    """Parse LLM response and validate the mapping."""
    try:
        # Extract JSON from response (may contain extra text)
        json_start = response.find("{")
        json_end = response.rfind("}") + 1

        if json_start < 0 or json_end <= json_start:
            logging.warning(f"No JSON found in LLM response: {response[:100]}")
            return None

        json_str = response[json_start:json_end]
        data = json.loads(json_str)

        # Validate required fields
        for required in ["openconfig_path", "confidence", "reasoning"]:
            if required not in data:
                logging.warning(f"Missing required field {required} in LLM response")
                return None

        # Validate path format (basic check)
        path = data["openconfig_path"]
        if not path.startswith("/"):
            logging.warning(f"Invalid path format (must start with /): {path}")
            return None

        # Validate confidence range
        confidence = float(data["confidence"])
        if not (0.0 <= confidence <= 1.0):
            logging.warning(f"Confidence out of range [0.0, 1.0]: {confidence}")
            return None

        return {
            "openconfig_path": path,
            "confidence": confidence,
            "reasoning": data["reasoning"],
        }

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logging.warning(f"Failed to parse LLM response: {e}")
        return None


def generate_mappings(
    db_path: str,
    limit: Optional[int] = None,
    confidence_threshold: float = 0.7,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Generate mappings for gap fields.

    Args:
        db_path: Path to DuckDB database
        limit: Max number of gap fields to process (None = all)
        confidence_threshold: Only save mappings with confidence >= threshold
        dry_run: If True, don't write to DB

    Returns:
        Summary dict with statistics
    """

    logging.info(f"Starting mapping generation (limit={limit}, threshold={confidence_threshold})")

    # Load gap fields
    gaps = _load_gap_fields(db_path, limit=limit)

    if not gaps:
        logging.warning("No gap fields found")
        return {
            "total_gaps": 0,
            "generated": 0,
            "high_confidence": 0,
            "low_confidence": 0,
            "failed": 0,
            "candidates": [],
        }

    # Initialize LLM
    try:
        llm = LLMFactory.get_chat_model(temperature=0.3, agent_id="mapping_generator")
        logging.info(f"LLM initialized: {type(llm).__name__}")
    except Exception as e:
        logging.error(f"Failed to initialize LLM: {e}")
        raise

    high_confidence_candidates: List[MappingCandidate] = []
    low_confidence_candidates: List[MappingCandidate] = []
    failed_gaps: List[GapField] = []

    # Process each gap
    for i, gap in enumerate(gaps):
        try:
            if (i + 1) % 10 == 0:
                logging.info(f"Processing gap {i + 1}/{len(gaps)}")

            # Build prompt
            prompt = _build_prompt(gap)

            # Call LLM
            try:
                response = llm.invoke([{"role": "user", "content": prompt}])
                # Ensure response_text is a string
                if hasattr(response, 'content'):
                    response_text = str(response.content)
                else:
                    response_text = str(response)
            except Exception as e:
                logging.warning(f"LLM call failed for {gap['platform']}/{gap['source_name']}/{gap['field_name']}: {e}")
                failed_gaps.append(gap)
                continue

            # Parse response
            mapping = _parse_llm_response(response_text)
            if not mapping:
                failed_gaps.append(gap)
                continue

            # Build candidate (with proper type casting for dict access)
            mapping_dict: Dict[str, Any] = mapping
            candidate = MappingCandidate(
                platform=gap["platform"],
                source_name=gap["source_name"],
                src_field=gap["field_name"],
                openconfig_path=str(mapping_dict.get("openconfig_path", "")),
                confidence=float(mapping_dict.get("confidence", 0.0)),
                reasoning=str(mapping_dict.get("reasoning", "")),
            )

            # Categorize by confidence
            if candidate.confidence >= confidence_threshold:
                high_confidence_candidates.append(candidate)
            else:
                low_confidence_candidates.append(candidate)

        except Exception as e:
            logging.error(f"Error processing gap {gap}: {e}")
            failed_gaps.append(gap)

    logging.info(
        f"Generated {len(high_confidence_candidates)} high-confidence + "
        f"{len(low_confidence_candidates)} low-confidence mappings, "
        f"{len(failed_gaps)} failed"
    )

    # Write high-confidence mappings to mapping_rules
    if high_confidence_candidates and not dry_run:
        logging.info(f"Writing {len(high_confidence_candidates)} mappings to mapping_rules...")
        con = duckdb.connect(db_path)
        try:
            for candidate in high_confidence_candidates:
                con.execute(
                    """
                    INSERT OR REPLACE INTO mapping_rules 
                    (vendor, command, src_field, oc_path, confidence, reasoning)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        candidate.platform,
                        candidate.source_name,
                        candidate.src_field,
                        candidate.openconfig_path,
                        candidate.confidence,
                        candidate.reasoning,
                    ],
                )
            con.commit()
            logging.info("Mappings written successfully")
        except Exception as e:
            logging.error(f"Failed to write mappings: {e}")
            con.close()
            raise
        finally:
            con.close()
    elif dry_run:
        logging.info("DRY RUN: skipping DB write")

    # Prepare summary
    summary: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "db_path": db_path,
        "total_gaps": len(gaps),
        "generated": len(high_confidence_candidates) + len(low_confidence_candidates),
        "high_confidence": len(high_confidence_candidates),
        "low_confidence": len(low_confidence_candidates),
        "failed": len(failed_gaps),
        "confidence_threshold": confidence_threshold,
        "dry_run": dry_run,
        "candidates": {
            "high_confidence": [asdict(c) for c in high_confidence_candidates[:20]],  # Sample
            "low_confidence": [asdict(c) for c in low_confidence_candidates[:10]],  # Sample
        },
    }

    return summary


if __name__ == "__main__":
    import sys

    # Parse arguments
    db_path = ".olav/databases/main.duckdb"
    limit = 50  # Start with small batch for validation
    dry_run = "--apply" not in sys.argv
    confidence_threshold = 0.7

    if "--help" in sys.argv:
        print(__doc__)
        print("Usage: uv run python scripts/generate_openconfig_mappings_with_llm.py [--apply] [--limit N]")
        sys.exit(0)

    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    print(f"Generate OpenConfig Mappings via LLM")
    print(f"  Database: {db_path}")
    print(f"  Limit: {limit}")
    print(f"  Confidence threshold: {confidence_threshold}")
    print(f"  Mode: {'apply' if not dry_run else 'dry-run'}")
    print()

    # Run mapping generation
    result = generate_mappings(db_path, limit=limit, confidence_threshold=confidence_threshold, dry_run=dry_run)

    # Output summary
    output_file = f"tmp/openconfig_mapping_generation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    print(f"\nResults saved to: {output_file}")

    # Exit with success/fail
    total_gaps = result["total_gaps"]
    sys.exit(0 if result["failed"] < (total_gaps * 0.5 if total_gaps > 0 else 1) else 1)
