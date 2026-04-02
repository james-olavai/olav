"""sync_commands — Sync the command capability registry from templates.

Builds the in-process CommandRegistry by scanning TextFSM templates AND
persists results to DuckDB:
  - commands table      : command whitelist/blacklist per platform
  - schema_catalog table: JSON field structure for parsed_outputs queries

Command registry location (in-process, not persisted to DB):
  src/olav/core/command_registry.py  — CommandRegistry singleton
  Sources scanned (priority order):
    1. .olav/config/textfsm/     project-level overrides
    2. .olav/txtfsm_templates/custom/   user custom templates
    3. .olav/txtfsm_templates/          user templates
    4. NTC-templates package     community templates (lowest priority)

Also registers backup_only_commands entries into commands table:
  .olav/config/backup_only_commands.yaml
    type=configuration → allowed=TRUE, is_primary_config=TRUE (used by diff_engine)
    type=other         → allowed=TRUE, is_primary_config=FALSE (archived only)

Also loads:
  .olav/config/blacklisted_commands.yaml — permanently block commands

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
                    r"^Value\s+(?:List\s+|Filldown\s+|Required\s+|Fillup\s+)*(\w+)", line.strip()
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
        return stem[len(prefix) :].replace("_", " ")
    return stem.replace("_", " ")


def _load_category_strategy() -> dict:
    """Load category keywords from config."""
    import yaml

    from olav.core.config import CONFIG_DIR

    config_path = Path(CONFIG_DIR / "category_strategy.yaml")
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("categories", {})
    except Exception:
        return {}


def _template_to_category(command: str) -> str:
    """Infer category from command string using strategy config."""
    cmd = command.lower()
    categories = _load_category_strategy()

    # Sort categories to ensure consistent matching if needed,
    # but here we just return the first hit.
    for cat, keywords in categories.items():
        if any(k in cmd for k in keywords):
            return cat

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


def _upsert_backup_only_commands(config_dir: Path, blacklisted: set[str]) -> int:
    """Upsert backup_only_commands.yaml entries into the commands table.

    - type=configuration → is_primary_config=TRUE (used by diff_engine for config diff)
    - type=other         → is_primary_config=FALSE (snapshot archive only)
    - platforms field    → one row per platform (or 'all' if not specified)

    Returns number of rows upserted.
    """
    yaml_path = config_dir / "backup_only_commands.yaml"
    if not yaml_path.exists():
        logger.debug("backup_only_commands.yaml not found at %s — skipping", yaml_path)
        return 0

    try:
        import yaml as _yaml

        entries = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or []
    except Exception as exc:
        logger.warning("Failed to load backup_only_commands.yaml: %s", exc)
        return 0

    try:
        from olav.core.database import get_database

        db = get_database()
    except Exception as exc:
        logger.warning("DB connection failed for backup_only upsert: %s", exc)
        return 0

    count = 0
    now = datetime.now()

    for item in entries:
        if not isinstance(item, dict):
            continue
        cmd = item.get("command", "").strip()
        if not cmd:
            continue
        cmd_type = item.get("type", "other")
        is_primary_config = cmd_type == "configuration"
        platforms = item.get("platforms") or ["all"]
        category = "configuration" if is_primary_config else _template_to_category(cmd)
        is_blacklisted = cmd.lower() in blacklisted

        for platform in platforms:
            try:
                db.conn.execute(
                    """
                    INSERT INTO commands
                        (command_name, platform, category, template_path, has_template,
                         allowed, blacklisted, pipe_allowed, is_primary_config, updated_at)
                    VALUES (?, ?, ?, NULL, FALSE, ?, ?, ?, ?, ?)
                    ON CONFLICT (command_name, platform) DO UPDATE SET
                        category          = excluded.category,
                        is_primary_config = excluded.is_primary_config,
                        allowed           = excluded.allowed,
                        blacklisted       = excluded.blacklisted,
                        pipe_allowed      = excluded.pipe_allowed,
                        updated_at        = excluded.updated_at
                    """,
                    [
                        cmd,
                        platform,
                        category,
                        not is_blacklisted,
                        is_blacklisted,
                        not is_blacklisted,
                        is_primary_config,
                        now,
                    ],
                )
                count += 1
            except Exception as exc:
                logger.debug("backup_only upsert failed (%s/%s): %s", cmd, platform, exc)

    try:
        db.conn.commit()
    except Exception as exc:
        logger.warning("DB commit failed for backup_only upsert: %s", exc)

    logger.info("backup_only_commands: upserted %d rows (from %d entries)", count, len(entries))
    return count


def _scan_templates() -> list[dict]:
    """Scan all template directories and return list of template records.

    Returns list of dicts with keys:
      command_name, platform, template_path, fields
    """
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (command, platform)

    # Scan user template directories first (highest priority)
    from olav.core.config import TEXTFSM_TEMPLATES_DIR

    user_dirs = [
        Path(TEXTFSM_TEMPLATES_DIR),
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
            records.append(
                {
                    "command_name": command,
                    "platform": platform,
                    "template_path": str(tpl),
                    "fields": _parse_textfsm_fields(str(tpl)),
                }
            )

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
            records.append(
                {
                    "command_name": command,
                    "platform": platform,
                    "template_path": str(tpl),
                    "fields": _parse_textfsm_fields(str(tpl)),
                }
            )
    except Exception as exc:
        logger.debug("Failed to scan NTC templates: %s", exc)

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
        #
        # Design (04.workflow.md): the commands table IS the whitelist.
        # - Every scanned template is allowed=TRUE by default.
        # - pipe_allowed defaults to TRUE (fail-open) — blacklist is the only safety gate.
        # - Only blacklisted_commands.yaml can set allowed=FALSE and pipe_allowed=FALSE.
        # - allowed_commands.yaml is DEPRECATED (whitelist model too maintenance-heavy).
        is_blacklisted = cmd_lower in blacklisted
        is_allowed = not is_blacklisted  # DB in-table = whitelist; only blacklist blocks
        pipe_allowed = not is_blacklisted  # Fail-open: allow pipes unless blacklisted

        try:
            db.conn.execute(
                """
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
            """,
                [
                    cmd,
                    platform,
                    category,
                    tpl_path,
                    True,
                    is_allowed,
                    is_blacklisted,
                    pipe_allowed,
                    now,
                ],
            )
            cmd_count += 1
        except Exception as exc:
            logger.debug("commands upsert failed (%s/%s): %s", cmd, platform, exc)

        if not fields:
            continue

        try:
            db.conn.execute(
                """
                INSERT INTO schema_catalog
                    (source_type, source_name, platform, fields, description, updated_at)
                VALUES ('textfsm', ?, ?, ?, ?, ?)
                ON CONFLICT (source_name, platform, source_type) DO UPDATE SET
                    fields      = excluded.fields,
                    description = excluded.description,
                    updated_at  = excluded.updated_at
            """,
                [
                    cmd,
                    platform,
                    json.dumps(fields),
                    f"TextFSM template: {Path(tpl_path).name}",
                    now,
                ],
            )
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
      .olav/skills/olav-ops/config/allowed_commands.yaml   — mark commands allowed + pipe_allowed
      .olav/skills/olav-ops/config/blacklisted_commands.yaml — permanently block commands

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
        from olav_netops.command_registry import CommandRegistry  # type: ignore[import]

        registry_result = CommandRegistry.reload()
    except Exception as e:
        logger.warning(f"CommandRegistry.reload() failed: {e}")
        registry_result = {
            "reloaded": {"templates": 0, "whitelisted_commands": 0, "blacklisted_patterns": 0},
            "new_templates": [],
        }

    # Step 2: Scan templates for DB write
    records = _scan_templates()

    # Step 3: Load control files
    from olav.core.config import CONFIG_DIR, get_domain_config_dir

    config_dir = Path(get_domain_config_dir("netops"))
    # allowed_commands.yaml is DEPRECATED (whitelist model too maintenance-heavy for multi-platform)
    # blacklisted_commands.yaml is the only safety gate (fail-open by default)
    blacklisted = _load_blacklisted_commands(config_dir)

    # Step 4: Upsert template-derived commands into DB
    cmd_count, sc_count = _upsert_to_db(records, {}, blacklisted)

    # Step 5: Register backup_only_commands.yaml entries (commands without templates)
    #   type=configuration → is_primary_config=TRUE → used by diff_engine
    #   type=other         → archived snapshots only
    backup_count = _upsert_backup_only_commands(config_dir, blacklisted)

    return {
        "status": "success",
        "templates_scanned": len(records),
        "commands_upserted": cmd_count,
        "schema_catalog_upserted": sc_count,
        "backup_only_registered": backup_count,
        "whitelisted_commands": registry_result["reloaded"]["whitelisted_commands"],
        "blacklisted_patterns": registry_result["reloaded"]["blacklisted_patterns"],
        "new_templates": registry_result.get("new_templates", []),
    }
