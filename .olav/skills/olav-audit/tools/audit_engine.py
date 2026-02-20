"""audit_engine.py — Config-driven Rule Engine for olav-audit skill.

Core of the "Code as Service" architecture. Loads audit.yaml, validates with
Pydantic, then evaluates configurable rules against SQL rows from DuckDB.

Field discovery is *schema-aware*: instead of hardcoded field name lists,
audit_engine delegates to schema_inspector.py which reads actual parsed_output
JSON keys at runtime and scores them against semantic hint words.

Flow:
    config = load_audit_config("AUDIT_HEALTH")           # load + validate YAML
    report = run_audit_reduce(sql_rows, config)           # pure Reduce phase
        └─ _evaluate_rule                                 #  rule evaluation
               └─ schema_inspector.discover_*            #   runtime field discovery
                      └─ parsed_outputs JSON keys        #    real data, real fields

This module is intentionally framework-independent (no @tool decorators) —
it is imported by audit_runner.py and audit_designer.py.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

# schema_inspector: runtime field discovery from parsed_outputs
# (imported lazily to allow the module to load without a DB connection)
_schema_inspector: Any = None


def _get_schema_inspector() -> Any:
    """Lazy import of schema_inspector — same tools/ directory."""
    global _schema_inspector
    if _schema_inspector is None:
        import sys
        _tools_dir = str(Path(__file__).resolve().parent)
        if _tools_dir not in sys.path:
            sys.path.insert(0, _tools_dir)
        import schema_inspector as _si
        _schema_inspector = _si
    return _schema_inspector

logger = logging.getLogger(__name__)

_SKILL_DIR = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _SKILL_DIR / "config"
_PROJECT_ROOT = _SKILL_DIR.parent.parent.parent   # /home/yhvh/Olav/
_SNAPSHOTS_DIR = _PROJECT_ROOT / "exports" / "snapshots"

# ---------------------------------------------------------------------------
# Pydantic schemas (lazy-import so the module loads even without pydantic)
# ---------------------------------------------------------------------------

def _build_models():
    """Build and return Pydantic model classes."""
    from pydantic import BaseModel

    class RuleFilter(BaseModel):
        exclude_pattern: str | None = None
        include_pattern: str | None = None

    class AuditRule(BaseModel):
        name: str
        target: str
        condition: Literal[
            "greater_than", "less_than",
            "not_equals", "equals",
            "is_empty", "not_empty",
            "in_set", "not_in_set",
            "matches_pattern", "not_matches_pattern",
            "consistent_across_devices",
            # Raw output conditions — no NTC template required.
            # Set 'command' to the CLI command whose raw output to search.
            # Set 'pattern' to a regex.  Violation = pattern absent (raw_contains)
            # or pattern present (raw_not_contains).
            "raw_contains",     # FAIL if pattern NOT found in raw output
            "raw_not_contains", # FAIL if pattern IS found in raw output
        ]
        warning: float | None = None
        critical: float | None = None
        expected: str | None = None
        allowed: list[str] | None = None
        forbidden: list[str] | None = None
        pattern: str | None = None
        scope: str | None = None
        severity: Literal["info", "warning", "critical"] = "warning"
        unit: str | None = None
        recommendation: str = ""
        analysis_hint: str = ""   # domain knowledge passed to LLM during Analyze phase
        target_type: str | None = None           # explicit override: "scalar"|"per_row"|"computed_ratio"
        command_keywords: list[str] | None = None  # explicit command filter keywords
        field_hints: list[str] | None = None     # explicit field name hints
        command: str | None = None               # CLI command for raw_contains / raw_not_contains
        filter: RuleFilter | None = None

    class CollectConfig(BaseModel):
        intents: list[str]

    class OutputSection(BaseModel):
        type: str
        fields: list[str] | None = None
        columns: list[str] | None = None
        severity_filter: list[str] = []
        max_items: int = 20
        max_rows: int = 50

    class OutputConfig(BaseModel):
        title: str = "Audit Report"
        filename_pattern: str = "audit_{timestamp}.md"
        sections: list[OutputSection] = []

    class PerDeviceAnalysisConfig(BaseModel):
        enabled: bool = False
        instructions: str = ""

    class GlobalAnalysisConfig(BaseModel):
        enabled: bool = False
        instructions: str = ""

    class AnalysisConfig(BaseModel):
        per_device: PerDeviceAnalysisConfig = PerDeviceAnalysisConfig()
        global_analysis: GlobalAnalysisConfig = GlobalAnalysisConfig()

    class AuditConfig(BaseModel):
        name: str
        version: str = "1.0.0"
        description: str = ""
        type: Literal[
            "health_check", "consistency", "compliance", "custom"
        ] = "custom"
        created_at: str = ""
        created_by: str = "user_manual"
        collect: CollectConfig
        rules: list[AuditRule]
        output: OutputConfig
        analysis: AnalysisConfig = AnalysisConfig()

    return AuditConfig, AuditRule, CollectConfig, OutputConfig, RuleFilter


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------

@dataclass
class AuditFinding:
    """A single finding from rule evaluation."""

    audit_name: str
    rule_name: str
    device: str
    entity: str           # e.g. interface name, BGP peer, "device"
    target: str
    condition: str
    actual_value: str
    expected_value: str
    severity: str         # info | warning | critical
    recommendation: str


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_audit_config(audit_name: str) -> Any:
    """Load, parse and Pydantic-validate an audit config.

    Args:
        audit_name: Config file stem under config/ — with or without the
                    .yaml extension (e.g. "AUDIT_HEALTH" or "global_check").

    Returns:
        AuditConfig Pydantic model instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If YAML fails Pydantic validation.
    """
    stem = audit_name.removesuffix(".yaml")
    audit_yaml = _CONFIG_DIR / f"{stem}.yaml"

    if not audit_yaml.exists():
        available = sorted(
            f.stem for f in _CONFIG_DIR.glob("*.yaml")
            if not f.stem.startswith("_") and f.stem != "target_map"
        )
        raise FileNotFoundError(
            f"Audit '{stem}' not found. "
            f"Available audits: {available}"
        )

    with open(audit_yaml, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    AuditConfig, *_ = _build_models()
    try:
        return AuditConfig.model_validate(raw)
    except Exception as e:
        raise ValueError(
            f"Validation failed for '{stem}': {e}"
        ) from e


def _build_target_def(rule: Any) -> dict[str, Any]:
    """Build a target_def dict from an AuditRule without target_map.yaml.

    Type and keywords are inferred from target name conventions:
    - "." in target → per_row
    - else → scalar (computed_ratio requires explicit target_type override)

    Rule-level overrides (target_type, command_keywords, field_hints) take priority.
    """
    target: str = rule.target

    # Type inference — only the dot-notation convention is implicit;
    # computed_ratio must be declared explicitly via target_type.
    if getattr(rule, "target_type", None):
        ttype: str = rule.target_type
    elif "." in target:
        ttype = "per_row"
    else:
        ttype = "scalar"

    # Command keywords: root word only — broad enough to match any related command
    # (e.g. "bgp" matches "show bgp summary", "show bgp neighbors", etc.).
    # Users can set command_keywords explicitly on the rule for unusual cases.
    root = target.split(".")[0].split("_")[0]
    default_kws = [root]

    # Field hints from target name parts (seed words for LLM candidate ranking)
    parts = target.replace(".", " ").replace("_", " ").split()

    tdef: dict[str, Any] = {
        "type": ttype,
        "description": " ".join(parts),
        "command_keywords": getattr(rule, "command_keywords", None) or default_kws,
        "field_hints": getattr(rule, "field_hints", None) or parts,
    }
    if ttype == "per_row":
        # Row key hint: first word of target name (e.g. "interface" from "interface.status")
        tdef["row_key_hints"] = parts[:1]
    # numerator/denominator hints for computed_ratio are intentionally omitted —
    # LLM in _prewarm_ratio receives all candidate fields and selects the correct ones
    return tdef


# ---------------------------------------------------------------------------
# Raw output extraction (no-NTC path)
# ---------------------------------------------------------------------------

def _extract_raw_text(rule: Any, device: str) -> str | None:
    """Find raw CLI output for a raw_contains / raw_not_contains rule.

    Looks up today's snapshot directory:
        exports/snapshots/{today}/raw/{device}/{cmd-slug}.txt

    Naming convention: spaces → dashes, lowercase
        "show logging"       →  show-logging.txt
        "show ip bgp summary" →  show-ip-bgp-summary.txt

    Falls back to word-based glob so minor command variations still match
    (e.g. rule.command="show bgp summary" still finds "show-ip-bgp-summary.txt").

    Returns None when no matching file exists — command was never collected
    or today's snapshot hasn't run yet.
    """
    cmd = (rule.command or rule.target).strip().lower()
    cmd_slug = cmd.replace(" ", "-")

    today = datetime.now().strftime("%Y-%m-%d")
    device_raw_dir = _SNAPSHOTS_DIR / today / "raw" / device

    if not device_raw_dir.exists():
        logger.debug("_extract_raw_text: snapshot dir missing: %s", device_raw_dir)
        return None

    # Exact match
    exact = device_raw_dir / f"{cmd_slug}.txt"
    if exact.exists():
        return exact.read_text(encoding="utf-8", errors="replace")

    # Word-based fuzzy match: file stem must contain all words in the command
    words = cmd.split()
    for f in sorted(device_raw_dir.glob("*.txt")):
        if all(w in f.stem for w in words):
            logger.debug(
                "_extract_raw_text: fuzzy match '%s' for command '%s' on %s",
                f.name, cmd, device,
            )
            return f.read_text(encoding="utf-8", errors="replace")

    return None


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------

def _get_field_value(record: dict, field_names: list[str]) -> str | None:
    """Try field_names in priority order, return first non-None non-empty value."""
    for field in field_names:
        val = record.get(field)
        if val is not None and str(val).strip() not in ("", "None", "N/A", "n/a"):
            return str(val).strip()
    return None


def _apply_transform(value: str | None, transform: str | None) -> float | str | None:
    """Apply a named transform to a raw string value."""
    if value is None:
        return None
    if transform == "float_strip_percent":
        try:
            return float(value.rstrip("%"))
        except (ValueError, AttributeError):
            return None
    return value


def _extract_scalar(
    target_def: dict,
    rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
    target_name: str = "",
) -> float | None:
    """Extract a single numeric value using schema-aware field discovery.

    Delegates field name discovery to schema_inspector, which inspects the
    actual parsed_data JSON keys at runtime instead of using hardcoded lists.
    The pre-warmed LLM cache in schema_inspector is checked first.
    """
    si = _get_schema_inspector()
    target_type = target_def.get("type", "scalar")

    if target_type == "computed_ratio":
        return _extract_computed(target_def, rows, platform=platform, target_name=target_name)

    field = si.discover_scalar_field(target_def, rows, platform=platform, target_name=target_name)
    if field is None:
        return None

    # Find the field value in matching rows
    keywords = [k.lower() for k in target_def.get("command_keywords", [])]
    transform = target_def.get("transform")

    for command, parsed in rows:
        cmd_l = command.lower()
        if not any(kw in cmd_l for kw in keywords):
            continue
        if not parsed:
            continue
        record = parsed[0] if isinstance(parsed, list) else {}
        raw = record.get(field)
        if raw is not None:
            result = _apply_transform(str(raw), transform)
            if result is not None:
                return result

    return None


def _extract_computed(
    target_def: dict,
    rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
    target_name: str = "",
) -> float | None:
    """Extract a computed ratio value (e.g. memory %) via schema-aware discovery.

    Discovers numerator and denominator fields from actual parsed_data keys.
    Handles "free-only" memory mode: if denominator is None (only free-mem
    available), computes usage as 100 - free%.
    """
    si = _get_schema_inspector()
    num_field, den_field = si.discover_ratio_fields(target_def, rows, platform=platform, target_name=target_name)

    if num_field is None:
        return None

    keywords = [k.lower() for k in target_def.get("command_keywords", [])]

    for command, parsed in rows:
        cmd_l = command.lower()
        if not any(kw in cmd_l for kw in keywords):
            continue
        if not parsed:
            continue
        record = parsed[0] if isinstance(parsed, list) else {}

        if den_field is None:
            # Free-only mode: schema_inspector detected only free% available
            free_val = record.get(num_field)
            if free_val is not None:
                try:
                    return round(100.0 - float(str(free_val).rstrip("%")), 1)
                except (ValueError, TypeError):
                    continue
        else:
            num_val = record.get(num_field)
            den_val = record.get(den_field)
            if num_val and den_val:
                try:
                    ratio = float(num_val) / float(den_val) * 100
                    return round(ratio, 1)
                except (ValueError, ZeroDivisionError):
                    continue

    return None


def _extract_per_row(
    target_def: dict,
    rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
    target_name: str = "",
) -> dict[str, str]:
    """Extract per-entity values using schema-aware field discovery.

    Returns:
        Dict mapping entity identifier → value string.
        e.g. {"GigabitEthernet0/0": "up", "GigabitEthernet0/1": "down"}

    Field names (key_field, value_field) are discovered at runtime by
    schema_inspector instead of from a hardcoded list.
    """
    si = _get_schema_inspector()
    key_field, value_field = si.discover_row_fields(target_def, rows, platform=platform, target_name=target_name)

    if key_field is None or value_field is None:
        return {}

    keywords = [k.lower() for k in target_def.get("command_keywords", [])]
    result: dict[str, str] = {}

    for command, parsed in rows:
        cmd_l = command.lower()
        if not any(kw in cmd_l for kw in keywords):
            continue
        if not isinstance(parsed, list):
            continue
        for record in parsed:
            key = record.get(key_field)
            value = record.get(value_field)
            if key and value:
                key_str = str(key).strip()
                val_str = str(value).strip()
                if key_str and key_str not in result:
                    # Normalize via value_aliases / LLM cache
                    result[key_str] = si.normalize_value(val_str, target_def, target_name=target_name)

    return result


# ---------------------------------------------------------------------------
# Rule Evaluation
# ---------------------------------------------------------------------------

def _should_exclude(entity: str, rule_filter: Any | None) -> bool:
    """Check if entity should be excluded based on rule filter."""
    if rule_filter is None:
        return False
    if rule_filter.exclude_pattern:
        if re.match(rule_filter.exclude_pattern, entity, re.IGNORECASE):
            return True
    if rule_filter.include_pattern:
        if not re.match(rule_filter.include_pattern, entity, re.IGNORECASE):
            return True
    return False


def _check_condition(
    rule: Any,
    actual: str | float,
) -> tuple[bool, str, str]:
    """Evaluate rule condition against actual value.

    Returns:
        (violated: bool, severity: str, expected_str: str)
    """
    cond = rule.condition
    severity = rule.severity

    if cond == "greater_than":
        val = float(actual) if actual is not None else 0.0
        if rule.critical is not None and val > rule.critical:
            return True, "critical", f"≤{rule.critical}"
        if rule.warning is not None and val > rule.warning:
            return True, "warning", f"≤{rule.warning}"
        return False, severity, ""

    if cond == "less_than":
        val = float(actual) if actual is not None else 0.0
        if rule.critical is not None and val < rule.critical:
            return True, "critical", f"≥{rule.critical}"
        if rule.warning is not None and val < rule.warning:
            return True, "warning", f"≥{rule.warning}"
        return False, severity, ""

    if cond == "not_equals":
        expected = rule.expected or ""
        violated = str(actual).lower() != expected.lower()
        return violated, severity, expected

    if cond == "equals":
        expected = rule.expected or ""
        violated = str(actual).lower() != expected.lower()
        return violated, severity, expected

    if cond == "is_empty":
        violated = not actual or str(actual).strip() in ("", "None", "N/A")
        return violated, severity, "non-empty"

    if cond == "not_empty":
        violated = not actual or str(actual).strip() in ("", "None", "N/A")
        return not violated, severity, "empty"

    if cond == "in_set":
        allowed = rule.allowed or []
        violated = str(actual) not in allowed
        return violated, severity, str(allowed)

    if cond == "not_in_set":
        forbidden = rule.forbidden or []
        violated = str(actual) in forbidden
        return violated, severity, f"not in {forbidden}"

    if cond == "matches_pattern":
        pattern = rule.pattern or ""
        violated = not re.match(pattern, str(actual))
        return violated, severity, f"matches '{pattern}'"

    if cond == "not_matches_pattern":
        pattern = rule.pattern or ""
        violated = bool(re.match(pattern, str(actual)))
        return violated, severity, f"not matches '{pattern}'"

    if cond == "consistent_across_devices":
        # Phase 2 feature — skip for now
        logger.debug(
            "Rule '%s': consistent_across_devices not yet implemented, skipping",
            rule.name,
        )
        return False, severity, ""

    logger.warning("Unknown condition '%s' in rule '%s'", cond, rule.name)
    return False, severity, ""


def _evaluate_rule(
    rule: Any,
    audit_name: str,
    device: str,
    device_rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
) -> list[AuditFinding]:
    """Evaluate a single rule against one device's parsed data.

    Args:
        rule:         AuditRule Pydantic model.
        audit_name:   For labelling findings.
        device:       Device name.
        device_rows:  [(command_str, parsed_data_list), ...] for this device.
        platform:     Device platform string (e.g. "cisco_ios"); used by
                      schema_inspector to prefer platform-specific fields.

    Returns:
        List of AuditFinding objects (empty = no violations).
    """
    target = rule.target

    # ------------------------------------------------------------------
    # Raw output path — no NTC template needed
    # ------------------------------------------------------------------
    if rule.condition in ("raw_contains", "raw_not_contains"):
        raw_text = _extract_raw_text(rule, device)
        if raw_text is None:
            logger.warning(
                "Rule '%s': no raw snapshot file found for command '%s' on device '%s'. "
                "Ensure today's snapshot includes this command (check intents or run "
                "take_snapshot with the relevant category). If no NTC template exists, "
                "raw output is stored automatically. Use command_learner to generate a "
                "template if structured field extraction is needed.",
                rule.name, rule.command or rule.target, device,
            )
            # Return a special 'no_data' finding so the silence is visible in the report
            return [AuditFinding(
                audit_name=audit_name, rule_name=rule.name, device=device,
                entity=device, target=target, condition=rule.condition,
                actual_value="no_data", expected_value="raw snapshot file present",
                severity="warning",
                recommendation=(
                    f"Command '{rule.command or rule.target}' not found in today's snapshot. "
                    "Run take_snapshot with the relevant category/intent to collect it, "
                    "or use command_learner to add NTC template support."
                ),
            )]
        pattern = rule.pattern or ""
        found = bool(re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE))
        violated = (not found) if rule.condition == "raw_contains" else found
        if violated:
            findings: list[AuditFinding] = []
            findings.append(AuditFinding(
                audit_name=audit_name, rule_name=rule.name, device=device,
                entity=device, target=target, condition=rule.condition,
                actual_value="absent" if rule.condition == "raw_contains" else "present",
                expected_value=(
                    f"pattern '{pattern}' present"
                    if rule.condition == "raw_contains"
                    else f"pattern '{pattern}' absent"
                ),
                severity=rule.severity,
                recommendation=rule.recommendation,
            ))
            return findings
        return []

    # ------------------------------------------------------------------
    # NTC-structured path
    # ------------------------------------------------------------------
    target_def = _build_target_def(rule)

    if rule.condition == "consistent_across_devices":
        return []   # Phase 2

    findings: list[AuditFinding] = []
    target_type = target_def.get("type", "scalar")

    if target_type in ("scalar", "computed_ratio"):
        value = _extract_scalar(target_def, device_rows, platform=platform, target_name=target)
        if value is None:
            # No NTC data found — warn so the silence is visible in logs
            logger.info(
                "Rule '%s' (target='%s') on %s: no NTC data found. "
                "If no template exists for this command, use condition: raw_contains "
                "with command: '<show command>' and create a template via command_learner.",
                rule.name, target, device,
            )
            return []
        violated, eff_severity, expected_str = _check_condition(rule, value)
        if violated:
            findings.append(AuditFinding(
                audit_name=audit_name,
                rule_name=rule.name,
                device=device,
                entity=device,
                target=target,
                condition=rule.condition,
                actual_value=str(value),
                expected_value=expected_str,
                severity=eff_severity,
                recommendation=rule.recommendation,
            ))

    elif target_type == "per_row":
        entities = _extract_per_row(target_def, device_rows, platform=platform, target_name=target)
        for entity, value in entities.items():
            if _should_exclude(entity, rule.filter):
                continue
            violated, eff_severity, expected_str = _check_condition(rule, value)
            if violated:
                findings.append(AuditFinding(
                    audit_name=audit_name,
                    rule_name=rule.name,
                    device=device,
                    entity=entity,
                    target=target,
                    condition=rule.condition,
                    actual_value=value,
                    expected_value=expected_str,
                    severity=eff_severity,
                    recommendation=rule.recommendation,
                ))

    return findings


# ---------------------------------------------------------------------------
# Reduce phase
# ---------------------------------------------------------------------------

def run_audit_reduce(
    sql_rows: list[dict[str, Any]],
    config: Any,
) -> dict[str, Any]:
    """Pure Reduce phase: evaluate all rules against SQL rows.

    Schema-aware: reads device platforms from DuckDB at the start so
    schema_inspector can prefer platform-specific field names during
    runtime field discovery.

    Args:
        sql_rows: Rows from DuckDB parsed_outputs.
            Each row: {device_name, command, parsed_data, ...}
        config: AuditConfig Pydantic model from load_audit_config().

    Returns:
        Aggregated result dict compatible with generate_audit_report().
    """
    timestamp = datetime.now().isoformat()

    # --- Schema-aware: fetch device platforms from DB (best-effort) ---
    si = _get_schema_inspector()
    try:
        device_platforms: dict[str, str] = si.get_device_platforms()
        logger.debug("Loaded platforms for %d devices", len(device_platforms))
    except Exception as exc:
        logger.debug("Could not load device platforms: %s — proceeding without", exc)
        device_platforms = {}

    # Group rows by device
    per_device_rows: dict[str, list[tuple[str, list[dict]]]] = {}
    for row in sql_rows:
        device = row.get("device_name", "unknown")
        command = (row.get("command") or "").lower()
        parsed = row.get("parsed_data") or []
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except Exception:
                parsed = []

        if device not in per_device_rows:
            per_device_rows[device] = []
        per_device_rows[device].append((command, parsed))

    # Raw-only device discovery: add devices that have raw snapshot files
    # but no parsed_outputs today (e.g. pure raw_contains/raw_not_contains audits)
    has_raw_rules = any(
        r.condition in ("raw_contains", "raw_not_contains") for r in config.rules
    )
    if has_raw_rules:
        today_str = datetime.now().strftime("%Y-%m-%d")
        raw_today_dir = _SNAPSHOTS_DIR / today_str / "raw"
        if raw_today_dir.exists():
            for device_dir in sorted(raw_today_dir.iterdir()):
                if device_dir.is_dir() and device_dir.name not in per_device_rows:
                    logger.debug(
                        "run_audit_reduce: discovered raw-only device '%s' from snapshot dir",
                        device_dir.name,
                    )
                    per_device_rows[device_dir.name] = []

    # Run all rules for each device
    all_findings: list[AuditFinding] = []
    device_stats: dict[str, dict] = {}

    for device, device_rows in per_device_rows.items():
        device_findings: list[AuditFinding] = []
        command_count = len(device_rows)
        platform = device_platforms.get(device)

        for rule in config.rules:
            rule_findings = _evaluate_rule(
                rule, config.name, device, device_rows,
                platform=platform,
            )
            device_findings.extend(rule_findings)

        all_findings.extend(device_findings)

        # Calculate device health score
        score = 100.0
        for f in device_findings:
            score -= 20 if f.severity == "critical" else 5
        score = max(0.0, min(100.0, score))

        critical_count = sum(1 for f in device_findings if f.severity == "critical")
        warning_count = sum(1 for f in device_findings if f.severity == "warning")

        if critical_count > 0:
            status = "critical"
        elif warning_count > 0:
            status = "warning"
        else:
            status = "healthy"

        device_stats[device] = {
            "device": device,
            "status": status,
            "health_score": round(score, 1),
            "inspected_commands": command_count,
            "anomaly_count": len(device_findings),
        }

    # Aggregate
    total_devices = len(device_stats)
    healthy_count = sum(1 for d in device_stats.values() if d["status"] == "healthy")
    warning_count = sum(1 for d in device_stats.values() if d["status"] == "warning")
    critical_count = sum(1 for d in device_stats.values() if d["status"] == "critical")

    avg_score = (
        sum(d["health_score"] for d in device_stats.values()) / total_devices
        if total_devices else 0
    )

    if critical_count > 0:
        overall_status = "critical"
    elif warning_count > 0:
        overall_status = "warning"
    else:
        overall_status = "healthy"

    # Build recommendations
    recommendations: list[str] = []
    if critical_count > 0:
        recommendations.append(
            f"❗ CRITICAL: {critical_count} device(s) have critical findings — "
            "immediate action required."
        )
    if warning_count > 0:
        recommendations.append(
            f"⚠️ WARNING: {warning_count} device(s) have warnings — "
            "review and monitor."
        )

    seen_recs: set[str] = set()
    for f in all_findings:
        if f.recommendation and f.recommendation not in seen_recs:
            recommendations.append(f"• {f.recommendation}")
            seen_recs.add(f.recommendation)

    return {
        "audit_name": config.name,
        "audit_type": config.type,
        "audit_time": timestamp,
        "device_count": total_devices,
        "healthy_count": healthy_count,
        "warning_count": warning_count,
        "critical_count": critical_count,
        "overall_health": overall_status,
        "overall_health_score": round(avg_score, 1),
        "device_statuses": device_stats,
        "findings": [asdict(f) for f in all_findings],
        "finding_count": len(all_findings),
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# AI analysis
# ---------------------------------------------------------------------------

def run_audit_analyze(result: dict[str, Any], config: Any) -> dict[str, Any]:
    """Analyze stage: LLM per-device + global correlation analysis.

    Runs after run_audit_reduce(), before generate_audit_report().
    Attaches results under ``result['_analysis']`` and returns a copy
    so callers can choose either approach.

    Returns:
        {"per_device": {device: str, ...}, "global": str}
    """
    si = _get_schema_inspector()
    llm = si._get_llm()

    analysis_cfg = getattr(config, "analysis", None)
    output: dict[str, Any] = {"per_device": {}, "global": ""}

    if analysis_cfg is None or not llm:
        result["_analysis"] = output
        return output

    findings: list[dict[str, Any]] = result.get("findings", [])
    device_stats: dict[str, Any] = result.get("device_statuses", {})

    # Build rule_name → analysis_hint lookup
    rule_hints: dict[str, str] = {
        rule.name: rule.analysis_hint.strip()
        for rule in config.rules
        if getattr(rule, "analysis_hint", "")
    }

    # -----------------------------------------------------------------------
    # Per-device analysis
    # -----------------------------------------------------------------------
    per_device_cfg = analysis_cfg.per_device
    if per_device_cfg.enabled and llm:
        instructions = per_device_cfg.instructions.strip()

        # Group findings by device
        by_device: dict[str, list[dict[str, Any]]] = {}
        for f in findings:
            by_device.setdefault(f["device"], []).append(f)

        for device, dev_findings in by_device.items():
            stat = device_stats.get(device, {})

            findings_lines = []
            for f in dev_findings:
                line = (
                    f"  [{f['severity'].upper()}] rule={f['rule_name']} "
                    f"entity={f['entity']} "
                    f"actual={f['actual_value']} expected={f['expected_value']}"
                )
                hint = rule_hints.get(f["rule_name"])
                if hint:
                    line += f"\n    domain context: {hint}"
                findings_lines.append(line)

            prompt = (
                f"Network device: {device}\n"
                f"Status: {stat.get('status', 'unknown').upper()} "
                f"(health_score={stat.get('health_score', '?')}%, "
                f"findings={len(dev_findings)})\n\n"
                f"Findings (with domain context):\n"
                + "\n".join(findings_lines)
                + f"\n\nInstructions:\n{instructions}\n"
            )
            try:
                text = llm.invoke(prompt).content.strip()
                output["per_device"][device] = text
                logger.info(
                    "Per-device analysis generated for %s (%d chars)", device, len(text)
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Per-device analysis failed for %s: %s", device, exc)
                output["per_device"][device] = "_Analysis unavailable._"

    # -----------------------------------------------------------------------
    # Global correlation analysis
    # -----------------------------------------------------------------------
    global_cfg = analysis_cfg.global_analysis
    if global_cfg.enabled and llm:
        instructions = global_cfg.instructions.strip()

        # Build per-device summaries (include healthy devices too)
        device_summaries: list[str] = []
        for device, stat in device_stats.items():
            icon = _status_icon(stat.get("status", "unknown"))
            per_text = output["per_device"].get(device, "")
            if per_text:
                device_summaries.append(
                    f"{icon} {device} ({stat.get('status','?').upper()}, "
                    f"score={stat.get('health_score','?')}%):\n{per_text}"
                )
            else:
                device_summaries.append(
                    f"{icon} {device} ({stat.get('status','healthy').upper()}) "
                    f"— no findings."
                )

        critical_lines = "\n".join(
            f"  {f['device']} / {f['rule_name']} / {f['entity']}: {f['actual_value']}"
            for f in findings
            if f.get("severity") == "critical"
        )[:3000] or "None."

        prompt = (
            f"Audit: {config.name} ({config.type})\n"
            f"Overall: {result.get('overall_health', '?').upper()} — "
            f"score={result.get('overall_health_score', '?')}/100\n"
            f"Devices: {result.get('device_count', '?')} total, "
            f"{result.get('critical_count', 0)} critical, "
            f"{result.get('warning_count', 0)} warning\n\n"
            f"Critical findings:\n{critical_lines}\n\n"
            f"Per-device summaries:\n"
            + "\n\n".join(device_summaries)
            + f"\n\nInstructions:\n{instructions}\n"
        )
        try:
            output["global"] = llm.invoke(prompt).content.strip()
            logger.info("Global analysis generated (%d chars)", len(output["global"]))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Global analysis failed: %s", exc)
            output["global"] = "_Global analysis unavailable._"

    result["_analysis"] = output
    return output


def generate_ai_analysis(result: dict[str, Any], config: Any) -> str:
    """Return a concise LLM expert analysis of audit findings.

    Summarises the most critical issues, cross-device patterns and
    prioritised remediation steps in 3-5 plain-prose sentences.
    Returns an italics placeholder if no LLM is configured.
    """
    si = _get_schema_inspector()
    llm = si._get_llm()
    if not llm:
        return "_LLM analysis not available — no LLM configured._"

    findings: list[dict[str, Any]] = result.get("findings", [])
    device_stats: dict[str, Any] = result.get("device_statuses", {})
    overall: str = result.get("overall_health", "unknown")
    score: int | float = result.get("overall_health_score", 0)

    findings_text = "\n".join(
        f"- [{f['severity'].upper()}] {f['device']} / {f['rule_name']}: "
        f"actual={f['actual_value']}, expected={f['expected_value']}"
        for f in findings[:30]
    ) or "No findings — all rules passed."

    device_summary = "\n".join(
        f"  {d}: {s['status']} (score={s['health_score']}%, "
        f"findings={s['anomaly_count']})"
        for d, s in device_stats.items()
    )

    prompt = (
        f"You are a network operations expert. Analyse this network audit report.\n\n"
        f"Audit: {config.name} ({config.type})\n"
        f"Overall: {overall.upper()} — {score}/100\n\n"
        f"Device statuses:\n{device_summary}\n\n"
        f"Findings:\n{findings_text}\n\n"
        f"Write a concise (3-5 sentences) expert analysis that:\n"
        f"1. Identifies the most critical issues and their likely root causes\n"
        f"2. Notes any patterns across multiple devices\n"
        f"3. Prioritises what the operator should address first\n"
        f"Write in plain prose, no markdown headers, no bullet lists."
    )
    try:
        analysis: str = llm.invoke(prompt).content.strip()
        logger.info("LLM audit analysis generated (%d chars)", len(analysis))
        return analysis
    except Exception as exc:  # noqa: BLE001
        logger.debug("generate_ai_analysis error: %s", exc)
        return "_LLM analysis unavailable._"


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _status_icon(status: str) -> str:
    return {"healthy": "✅", "warning": "⚠️", "critical": "🔴"}.get(status, "❓")


def generate_audit_report(
    result: dict[str, Any],
    config: Any,  # AuditConfig
    devices_requested: list[str] | None = None,
) -> str:
    """Generate a markdown report from run_audit_reduce() output.

    Args:
        result: Output of run_audit_reduce().
        config: AuditConfig Pydantic model.
        devices_requested: Optional device filter info for scope display.

    Returns:
        Markdown string.
    """
    lines: list[str] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    audit_name = result.get("audit_name", config.name)
    overall = result.get("overall_health", "unknown")
    score = result.get("overall_health_score", 0)
    device_count = result.get("device_count", 0)
    healthy = result.get("healthy_count", 0)
    warning = result.get("warning_count", 0)
    critical = result.get("critical_count", 0)
    finding_count = result.get("finding_count", 0)
    scope = (
        ", ".join(devices_requested)
        if devices_requested else "All inventory devices"
    )

    sections_cfg = {s.type: s for s in config.output.sections}

    def _enabled(section_type: str, default: bool = True) -> bool:
        s = sections_cfg.get(section_type)
        if s is None:
            return default
        return True

    # Title
    lines.append(f"# {config.output.title}")
    lines.append("")

    # Header section
    if _enabled("header"):
        overall_bar = "█" * int(score / 4) + "░" * (25 - int(score / 4))
        lines += [
            f"**Date**: {now_str}  ",
            f"**Audit**: `{audit_name}` ({config.type})  ",
            f"**Scope**: {scope}  ",
            "",
            f"## Overall Health",
            "",
            f"**{_status_icon(overall)} {overall.upper()}** — "
            f"{score:.0f}/100  `{overall_bar}`",
            "",
            f"| Total | Healthy | Warning | Critical | Findings |",
            f"|-------|---------|---------|----------|----------|",
            f"| {device_count} | {healthy} | {warning} | {critical} | {finding_count} |",
            "",
            "---",
            "",
        ]

    # Device health table
    if _enabled("device_health_table"):
        sec = sections_cfg.get("device_health_table")
        columns = (sec.columns if sec and sec.columns else
                   ["device", "status", "health_score", "anomaly_count", "commands_inspected"])

        col_labels = {
            "device": "Device",
            "status": "Status",
            "health_score": "Health Score",
            "anomaly_count": "Findings",
            "commands_inspected": "Commands",
        }
        lines.append("## Device Summary")
        lines.append("")
        lines.append("| " + " | ".join(col_labels.get(c, c) for c in columns) + " |")
        lines.append("|" + "|".join(["--------"] * len(columns)) + "|")

        for name, info in result.get("device_statuses", {}).items():
            icon = _status_icon(info.get("status", "unknown"))
            row = {
                "device": name,
                "status": f"{icon} {info.get('status', '-')}",
                "health_score": f"{info.get('health_score', 0):.0f}%",
                "anomaly_count": str(info.get("anomaly_count", 0)),
                "commands_inspected": str(info.get("inspected_commands", 0)),
            }
            lines.append("| " + " | ".join(row.get(c, "-") for c in columns) + " |")

        lines += ["", "---", ""]

    # Findings table
    if _enabled("anomaly_table"):
        sec = sections_cfg.get("anomaly_table")
        severity_filter: list[str] = sec.severity_filter if sec else []
        max_rows: int = sec.max_rows if sec else 50

        lines.append("## Findings")
        lines.append("")

        findings = result.get("findings", [])
        if severity_filter:
            findings = [f for f in findings if f.get("severity") in severity_filter]

        if findings:
            lines += [
                "| Device | Rule | Entity | Actual | Expected | Severity |",
                "|--------|------|--------|--------|----------|----------|",
            ]
            for f in findings[:max_rows]:
                lines.append(
                    f"| {f.get('device', '-')} "
                    f"| `{f.get('rule_name', '-')}` "
                    f"| {f.get('entity', '-')} "
                    f"| {f.get('actual_value', '-')} "
                    f"| {f.get('expected_value', '-')} "
                    f"| {f.get('severity', '-')} |"
                )
            if len(findings) > max_rows:
                lines.append(
                    f"\n_... and {len(findings) - max_rows} more findings._"
                )
        else:
            lines.append("_No findings — all rules passed._")

        lines += ["", "---", ""]

    # Recommendations
    if _enabled("recommendations"):
        sec = sections_cfg.get("recommendations")
        max_items = sec.max_items if sec else 20

        lines.append("## Recommendations")
        lines.append("")
        recs = result.get("recommendations", [])
        if recs:
            for rec in recs[:max_items]:
                lines.append(rec if rec.startswith(("❗", "⚠️", "•")) else f"- {rec}")
        else:
            lines.append("_All checks passed — no recommendations._")
        lines += ["", "---", ""]

    # AI Analysis (opt-in: default=False so existing audits are unaffected)
    if _enabled("ai_analysis", default=False):
        lines.append("## \U0001f916 AI Analysis")
        lines.append("")
        lines.append(generate_ai_analysis(result, config))
        lines += ["", "---", ""]

    # Per-device holistic analysis (from run_audit_analyze)
    if _enabled("per_device_analysis", default=False):
        analyses: dict[str, str] = result.get("_analysis", {}).get("per_device", {})
        if analyses:
            lines.append("## \U0001f50d Per-Device Analysis")
            lines.append("")
            for device, text in analyses.items():
                stat = result.get("device_statuses", {}).get(device, {})
                icon = _status_icon(stat.get("status", "unknown"))
                lines.append(f"### {icon} {device}")
                lines.append("")
                lines.append(text)
                lines.append("")
            lines += ["---", ""]

    # Global correlation / cascade analysis (from run_audit_analyze)
    if _enabled("global_analysis", default=False):
        global_text: str = result.get("_analysis", {}).get("global", "")
        if global_text:
            lines.append("## \U0001f310 Global Correlation Analysis")
            lines.append("")
            lines.append(global_text)
            lines += ["", "---", ""]

    # Footer
    if _enabled("footer"):
        lines += [
            f"_Generated by OLAV Audit Agent · {now_str}_  ",
            f"_Audit: {audit_name} v{config.version} · {config.type}_",
        ]

    return "\n".join(lines)
