"""audit_designer.py — Design Mode tools for olav-audit skill.

Three LangChain @tool functions for creating and managing audit configs:
  - list_audits:           Discover available audit configs
  - validate_audit_config: Pydantic schema validation
  - create_audit_config:   LLM writes audit.yaml from intent
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool

from audit_engine import _CONFIG_DIR, load_audit_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# list_audits
# ---------------------------------------------------------------------------

@tool
def list_audits() -> list[dict[str, str]]:
    """List all available audit configurations under olav-audit config/.

    Scans for *.yaml files directly in the config directory (excluding
    target_map.yaml and files starting with '_').

    Returns:
        List of dicts with keys: audit_name, type, description, created_at, created_by.

    Example:
        [
          {"audit_name": "AUDIT_HEALTH", "type": "health_check",
           "description": "CPU, memory, interface health", "created_by": "builtin"},
          ...
        ]
    """
    results: list[dict[str, str]] = []

    for f in sorted(_CONFIG_DIR.glob("*.yaml")):
        if f.stem.startswith("_") or f.stem == "target_map":
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            results.append({
                "audit_name": f.stem,
                "name": raw.get("name", f.stem),
                "type": raw.get("type", "unknown"),
                "description": raw.get("description", ""),
                "created_at": raw.get("created_at", ""),
                "created_by": raw.get("created_by", ""),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read audit '%s': %s", f.stem, exc)
            results.append({
                "audit_name": f.stem,
                "name": f.stem,
                "type": "unknown",
                "description": f"(Failed to load: {exc})",
                "created_at": "",
                "created_by": "",
            })

    return results


# ---------------------------------------------------------------------------
# validate_audit_config
# ---------------------------------------------------------------------------

@tool
def validate_audit_config(audit_name: str) -> dict[str, Any]:
    """Validate an audit config's YAML schema using Pydantic.

    Loads config/<audit_name>.yaml and checks all required fields,
    Validates YAML schema, Pydantic model, and condition logic.

    Args:
        audit_name: Config file stem under config/ (e.g. "AUDIT_HEALTH",
                    "global_check") — .yaml extension is optional.

    Returns:
        {"valid": True, "audit_name": ..., "rule_count": N, "warnings": [...]}
        or
        {"valid": False, "audit_name": ..., "errors": ["..."]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        config = load_audit_config(audit_name)
    except FileNotFoundError as e:
        return {"valid": False, "audit_name": audit_name, "errors": [str(e)]}
    except ValueError as e:
        return {"valid": False, "audit_name": audit_name, "errors": [str(e)]}

    for rule in config.rules:
        if rule.condition == "consistent_across_devices":
            warnings.append(
                f"Rule '{rule.name}': 'consistent_across_devices' is a Phase 2 feature "
                "and will be skipped during execution."
            )
        if rule.condition in ("greater_than", "less_than"):
            if rule.warning is None and rule.critical is None:
                errors.append(
                    f"Rule '{rule.name}': condition '{rule.condition}' requires "
                    "'warning' or 'critical' threshold."
                )
        if rule.condition in ("not_equals", "equals") and rule.expected is None:
            errors.append(
                f"Rule '{rule.name}': condition '{rule.condition}' requires 'expected' field."
            )
        if rule.condition == "in_set" and not rule.allowed:
            errors.append(
                f"Rule '{rule.name}': condition 'in_set' requires 'allowed' list."
            )
        if rule.condition == "not_in_set" and not rule.forbidden:
            errors.append(
                f"Rule '{rule.name}': condition 'not_in_set' requires 'forbidden' list."
            )
        if rule.condition in ("matches_pattern", "not_matches_pattern") and not rule.pattern:
            errors.append(
                f"Rule '{rule.name}': condition '{rule.condition}' requires 'pattern' field."
            )
        if rule.condition in ("raw_contains", "raw_not_contains"):
            if not rule.pattern:
                errors.append(
                    f"Rule '{rule.name}': condition '{rule.condition}' requires 'pattern' "
                    "(regex to search for in raw CLI output)."
                )
            if not rule.command:
                errors.append(
                    f"Rule '{rule.name}': condition '{rule.condition}' requires 'command' "
                    "(CLI command whose snapshot file to search, "
                    "e.g. 'show logging', 'show ntp status')."
                )
            else:
                # Helpful hint: remind user the command must have been collected
                warnings.append(
                    f"Rule '{rule.name}': uses raw snapshot file for '{rule.command}'. "
                    "Ensure today's snapshot collected this command (via take_snapshot "
                    "with the relevant intent/category). If no NTC template exists, "
                    "raw output is stored automatically as show-*.txt. "
                    "Use command_learner to generate a template for structured extraction."
                )

    if errors:
        return {
            "valid": False,
            "audit_name": audit_name,
            "errors": errors,
            "warnings": warnings,
        }

    return {
        "valid": True,
        "audit_name": audit_name,
        "audit_type": config.type,
        "rule_count": len(config.rules),
        "collect_intents": config.collect.intents,
        "warnings": warnings,
        "message": (
            f"Audit '{audit_name}' is valid: "
            f"{len(config.rules)} rules, {len(config.collect.intents)} intents."
        ),
    }


# ---------------------------------------------------------------------------
# create_audit_config
# ---------------------------------------------------------------------------

@tool
def create_audit_config(
    name: str,
    intent: str,
    audit_type: str = "health_check",
) -> dict[str, Any]:
    """Create a new audit configuration from user intent.

    Generates config/<name>.yaml using the appropriate template as a
    starting point.  The caller (LLM Agent) should customise the YAML
    with rules matching the user's intent.

    Args:
        name: Audit file stem — letters, digits, underscores and hyphens
              only (e.g. "global_check", "VLAN_audit", "ntp_compliance").
        intent: Full description of what to audit (user's goal in their words).
        audit_type: One of: health_check | consistency | compliance | custom.
                    Selects the right template.

    Returns:
        {"status": "success", "audit_name": ..., "audit_path": ..., "next_step": ...}
        or
        {"status": "error", "message": ...}
    """
    # Validate name format
    import re as _re
    if not _re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", name):
        return {
            "status": "error",
            "message": (
                f"Invalid audit name '{name}'. "
                "Use letters, digits, underscores or hyphens "
                "(e.g. 'global_check', 'VLAN_audit', 'ntp_compliance')."
            ),
        }
    if name in ("target_map",) or name.startswith("_"):
        return {
            "status": "error",
            "message": f"Reserved name '{name}'. Choose a different name.",
        }

    valid_types = {"health_check", "consistency", "compliance", "custom"}
    if audit_type not in valid_types:
        return {
            "status": "error",
            "message": f"Invalid audit_type '{audit_type}'. Must be one of: {valid_types}",
        }

    audit_yaml = _CONFIG_DIR / f"{name}.yaml"

    if audit_yaml.exists():
        return {
            "status": "error",
            "message": (
                f"Audit '{name}' already exists at {audit_yaml}. "
                "Use validate_audit_config() to check it, or delete and recreate."
            ),
        }

    # Find an existing audit of matching type as an example, else fall back to minimal template
    example_content = ""
    for _f in sorted(_CONFIG_DIR.glob("*.yaml")):
        if _f.stem.startswith("_") or _f.stem == "target_map" or _f.stem == name:
            continue
        try:
            with open(_f, encoding="utf-8") as _fh:
                _raw = yaml.safe_load(_fh)
            if isinstance(_raw, dict) and _raw.get("type") == audit_type:
                with open(_f, encoding="utf-8") as _fh:
                    example_content = _fh.read()
                logger.debug("Using '%s' as example for type '%s'", _f.name, audit_type)
                break
        except Exception:
            continue

    if not example_content:
        logger.debug("No existing '%s' audit found as example, using minimal template", audit_type)
        example_content = _minimal_template(audit_type)

    # Substitute placeholders (if minimal template is used)
    now = datetime.now().strftime("%Y-%m-%d")
    title = name.replace("_", " ").replace("-", " ").title()
    content = (
        example_content
        .replace("{{AUDIT_TITLE}}", title)
        .replace("{{AUDIT_DESCRIPTION}}", intent)
        .replace("{{AUDIT_NAME_LOWER}}", name.lower())
        .replace("{{CREATED_AT}}", now)
    )

    try:
        with open(audit_yaml, "w", encoding="utf-8") as f:
            f.write(f"# Generated by OLAV Audit Agent\n")
            f.write(f"# Intent: {intent}\n")
            f.write(f"# Created: {now}\n\n")
            f.write(content)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to write {audit_yaml}: {exc}"}

    return {
        "status": "success",
        "audit_name": name,
        "audit_path": str(audit_yaml),
        "audit_type": audit_type,
        "intent_recorded": intent,
        "next_step": (
            f"Created '{name}.yaml'. "
            f"Call validate_audit_config('{name}') to check the schema, "
            f"then run_audit('{name}') to execute."
        ),
    }


def _minimal_template(audit_type: str) -> str:
    """Minimal fallback template when _templates/ directory is missing."""
    return f"""name: "{{{{AUDIT_TITLE}}}}"
version: "1.0.0"
description: "{{{{AUDIT_DESCRIPTION}}}}"
type: {audit_type}
created_at: "{{{{CREATED_AT}}}}"
created_by: llm_generated

collect:
  intents:
    - system
    - interfaces

rules:
  - name: example_rule
    target: cpu_percent
    condition: greater_than
    warning: 70
    critical: 90
    recommendation: "Replace with rules matching your intent"

output:
  title: "{{{{AUDIT_TITLE}}}} Report"
  filename_pattern: "audit_{{{{AUDIT_NAME_LOWER}}}}_{{timestamp}}.md"
  sections:
    - type: header
      fields: [date, overall_health, scope, device_summary, anomaly_count]
    - type: device_health_table
      columns: [device, status, health_score, anomaly_count, commands_inspected]
    - type: anomaly_table
      severity_filter: []
    - type: recommendations
      max_items: 20
    - type: footer
"""
