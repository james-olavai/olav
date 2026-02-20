"""sync_commands — Sync the command capability registry from templates.

Builds the in-process CommandRegistry by scanning TextFSM templates AND
persists results to DuckDB:
  - commands table      : command whitelist/blacklist per platform
  - schema_catalog table: JSON field structure for parsed_outputs queries

Command registry location (in-process, not persisted to DB):
  src/olav/core/command_registry.py  — CommandRegistry singleton
  Sources scanned (priority order):
    1. .olav/config/textfsm/     project-level overrides
    2. .olav/templates/custom/   user custom templates
    3. .olav/templates/          user templates
    4. NTC-templates package     community templates (lowest priority)

Also reloads:
  .olav/templates/config/allowed_commands.yaml   command whitelist
  .olav/templates/config/blacklisted_commands.yaml command blacklist

Call this after adding or modifying .textfsm files so that take_snapshot()
picks up the new commands without restarting the process.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


def _parse_textfsm_fields(template_path: str) -> list[dict]:
    """Extract Value field names from a TextFSM template file."""
    fields = []
    try:
        with open(template_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.match(
                    r'^Value\s+(?:List\s+|Filldown\s+|Required\s+|Fillup\s+)*(\w+)',
                    line.strip()
                )
                if m:
                    fields.append({"name": m.group(1).lower(), "type": "str"})
    except Exception as exc:
        logger.debug("textfsm parse error %s: %s", template_path, exc)
    return fields


def _stem_to_command(stem: str, platform: str) -> str:
    """Convert template filename stem to CLI command string.

    e.g. 'cisco_ios_show_ip_ospf_neighbor' → 'show ip ospf neighbor'
    """
    prefix = f"{platform}_"
    if stem.startswith(prefix):
        return stem[len(prefix):].replace("_", " ")
    return stem.replace("_", " ")


def _template_to_category(command: str) -> str:
    """Infer category from command string."""
    cmd = command.lower()
    if any(k in cmd for k in ("ospf", "bgp", "eigrp", "rip", "route", "routing")):
        return "routing"
    if any(k in cmd for k in ("interface", "port", "counters")):
        return "interfaces"
    if any(k in cmd for k in ("cdp", "lldp", "neighbor")):
        return "topology"
    if any(k in cmd for k in ("version", "inventory", "license", "platform")):
        return "system"
    if any(k in cmd for k in ("running", "startup", "config")):
        return "configs"
    if any(k in cmd for k in ("vlan", "spanning", "stp")):
        return "switching"
    if any(k in cmd for k in ("process", "cpu", "memory")):
        return "performance"
    return "general"


def _load_allowed_commands(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Load allowed_commands.yaml → {command_name: {platforms, pipe_allowed}}."""
    result: dict[str, dict[str, Any]] = {}
    yaml_path = config_dir / "allowed_commands.yaml"
    if not yaml_path.exists():
        return result
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            entries = yaml.safe_load(f) or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cmd = entry.get("command", "").strip().lower()
            if not cmd:
                continue
            result[cmd] = {
                "platforms": entry.get("platforms", ["*"]),
                "pipe_allowed": bool(entry.get("pipe_allowed", False)),
            }
    except Exception as exc:
        logger.warning("Failed to load allowed_commands.yaml: %s", exc)
    return result


def _load_blacklisted_commands(config_dir: Path) -> set[str]:
    """Load blacklisted_commands.yaml → set of lowercased command names."""
    result: set[str] = set()
    yaml_path = config_dir / "blacklisted_commands.yaml"
    if not yaml_path.exists():
        return result
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            entries = yaml.safe_load(f) or []
        for entry in entries:
            if isinstance(entry, dict):
                cmd = entry.get("command", "").strip().lower()
            elif isinstance(entry, str):
                cmd = entry.strip().lower()
            else:
                continue
            if cmd:
                result.add(cmd)
    except Exception as exc:
        logger.warning("Failed to load blacklisted_commands.yaml: %s", exc)
    return result


def _scan_templates() -> list[dict]:
    """Scan all template directories and return list of template records.

    Returns list of dicts with keys:
      command_name, platform, template_path, fields
    """
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (command, platform)

    # Scan user template directories first (highest priority)
    user_dirs = [
        PROJECT_ROOT / ".olav" / "templates" / "custom",
        PROJECT_ROOT / ".olav" / "templates",
    ]
    for user_dir in user_dirs:
        if not user_dir.is_dir():
            continue
        for tpl in sorted(user_dir.glob("*.textfsm")):
            stem = tpl.stem
            # Determine platform from filename prefix
            parts = stem.split("_", 2)
            if len(parts) < 2:
                continue
            platform = "_".join(parts[:2])  # e.g. cisco_ios
            command = _stem_to_command(stem, platform)
            key = (command.lower(), platform.lower())
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "command_name": command,
                "platform": platform,
                "template_path": str(tpl),
                "fields": _parse_textfsm_fields(str(tpl)),
            })

    # Augment with NTC templates (lower priority)
    try:
        import ntc_templates as _ntc
        ntc_dir = Path(_ntc.__file__).parent / "templates"
        for tpl in sorted(ntc_dir.glob("*.textfsm")):
            stem = tpl.stem
            parts = stem.split("_", 2)
            if len(parts) < 2:
                continue
            platform = "_".join(parts[:2])
            command = _stem_to_command(stem, platform)
            key = (command.lower(), platform.lower())
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "command_name": command,
                "platform": platform,
                "template_path": str(tpl),
                "fields": _parse_textfsm_fields(str(tpl)),
            })
    except Exception:
        pass

    return records


def _upsert_to_db(
    records: list[dict],
    allowed: dict[str, dict[str, Any]],
    blacklisted: set[str],
) -> tuple[int, int]:
    """Upsert records into commands + schema_catalog tables.

    Returns: (commands_upserted, schema_catalog_upserted)
    """
    try:
        from olav.core.database import get_database
    except ImportError:
        logger.warning("get_database not available — skipping DB upsert")
        return 0, 0

    try:
        db = get_database()
    except Exception as exc:
        logger.warning("DB connection failed — skipping DB upsert: %s", exc)
        return 0, 0

    cmd_count = 0
    sc_count = 0
    now = datetime.now()

    for rec in records:
        cmd = rec["command_name"]
        platform = rec["platform"]
        cmd_lower = cmd.lower()
        tpl_path = rec["template_path"]
        fields = rec["fields"]
        category = _template_to_category(cmd)

        # Determine allowed/blacklisted/pipe_allowed
        is_blacklisted = cmd_lower in blacklisted
        allowed_entry = allowed.get(cmd_lower)
        if allowed_entry is None:
            # Wildcard match
            for allowed_cmd, allowed_data in allowed.items():
                if cmd_lower.startswith(allowed_cmd.lower()):
                    allowed_entry = allowed_data
                    break

        is_allowed = True  # default: allowed unless explicitly blacklisted
        pipe_allowed = False
        if allowed_entry:
            platforms = allowed_entry.get("platforms", ["*"])
            if platforms != ["*"] and platform not in platforms:
                is_allowed = False  # not listed for this platform
            else:
                pipe_allowed = allowed_entry.get("pipe_allowed", False)

        try:
            db.conn.execute("""
                INSERT INTO commands
                    (command_name, platform, category, template_path, has_template,
                     allowed, blacklisted, pipe_allowed, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (command_name, platform) DO UPDATE SET
                    category      = excluded.category,
                    template_path = excluded.template_path,
                    has_template  = excluded.has_template,
                    allowed       = excluded.allowed,
                    blacklisted   = excluded.blacklisted,
                    pipe_allowed  = excluded.pipe_allowed,
                    updated_at    = excluded.updated_at
            """, [cmd, platform, category, tpl_path, True,
                  is_allowed, is_blacklisted, pipe_allowed, now])
            cmd_count += 1
        except Exception as exc:
            logger.debug("commands upsert failed (%s/%s): %s", cmd, platform, exc)

        if not fields:
            continue

        try:
            db.conn.execute("""
                INSERT INTO schema_catalog
                    (source_type, source_name, platform, fields, description, updated_at)
                VALUES ('textfsm', ?, ?, ?, ?, ?)
                ON CONFLICT (source_name, platform, source_type) DO UPDATE SET
                    fields      = excluded.fields,
                    description = excluded.description,
                    updated_at  = excluded.updated_at
            """, [cmd, platform, json.dumps(fields),
                  f"TextFSM template: {Path(tpl_path).name}", now])
            sc_count += 1
        except Exception as exc:
            logger.debug("schema_catalog upsert failed (%s/%s): %s", cmd, platform, exc)

    try:
        db.conn.commit()
    except Exception as exc:
        logger.warning("DB commit failed: %s", exc)

    return cmd_count, sc_count


@tool
def sync_commands() -> dict:
    """Sync command capability registry from TextFSM templates.

    1. Scans template directories (user templates → NTC templates)
       and rebuilds in-process CommandRegistry.
    2. Persists results to DuckDB:
       - commands table:       per-platform command whitelist/blacklist
       - schema_catalog table: JSON field names for parsed_outputs queries

    Control files (optional):
      .olav/templates/config/allowed_commands.yaml   — mark commands allowed + pipe_allowed
      .olav/templates/config/blacklisted_commands.yaml — permanently block commands

    After running this, olav-ops SchemaContext will pick up JSON field names
    on next refresh, enabling LLM to generate correct parsed_data->>'field' queries.

    Returns:
        {
            "status":              "success" | "error",
            "templates_scanned":   int,
            "commands_upserted":   int,
            "schema_catalog_upserted": int,
            "whitelisted_commands": int,
            "blacklisted_patterns": int,
            "new_templates":       list[str],
        }
    """
    try:
        # Step 1: Rebuild in-process CommandRegistry
        from olav.core.command_registry import CommandRegistry
        registry_result = CommandRegistry.reload()
    except Exception as e:
        logger.warning(f"CommandRegistry.reload() failed: {e}")
        registry_result = {"reloaded": {"templates": 0,
                                        "whitelisted_commands": 0,
                                        "blacklisted_patterns": 0},
                           "new_templates": []}

    # Step 2: Scan templates for DB write
    records = _scan_templates()

    # Step 3: Load control files
    config_dir = PROJECT_ROOT / ".olav" / "templates" / "config"
    allowed = _load_allowed_commands(config_dir)
    blacklisted = _load_blacklisted_commands(config_dir)

    # Step 4: Upsert into DB
    cmd_count, sc_count = _upsert_to_db(records, allowed, blacklisted)

    return {
        "status": "success",
        "templates_scanned":      len(records),
        "commands_upserted":      cmd_count,
        "schema_catalog_upserted": sc_count,
        "whitelisted_commands":   registry_result["reloaded"]["whitelisted_commands"],
        "blacklisted_patterns":   registry_result["reloaded"]["blacklisted_patterns"],
        "new_templates":          registry_result.get("new_templates", []),
    }

