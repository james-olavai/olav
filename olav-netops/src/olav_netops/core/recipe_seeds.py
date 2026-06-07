"""ARCH-06 — hand-curated view_recipes loader.

Pre-populates the ``view_recipes`` table with vendor-aware mappings for
the most common show-commands so the audit / learner pipeline has a
baseline even before the LLM discovery pass runs.

The loader is idempotent: repeated calls update ``discovered_at`` and
the mapping / filter fields but never create duplicate rows. Rows are
upserted on the ``(command, concept, vendor_hint)`` natural key.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Concepts shipped in builtin seeds. Listing them here is advisory — a
# WARN is logged when a recipe uses a non-builtin concept so schema drift
# is visible, but the row is still loaded. User-defined concepts
# (firewall_rules, ipsec_tunnels, bfd_sessions, …) are first-class and go
# through the same ``_custom_branch`` path in view_builder.
_BUILTIN_CONCEPTS = frozenset({
    "interfaces",
    "bgp_neighbors",
    "ospf_neighbors",
    "topology_l2",
    "routes",
    "arp",
})

import re as _re
_CONCEPT_PATTERN = _re.compile(r"^[a-z][a-z0-9_]*$")


_REQUIRED_FIELDS = frozenset({"command", "concept", "field_mappings"})
_DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "view_recipes_seed.yaml"


def _ensure_table(conn: Any) -> None:
    """Create ``view_recipes`` if absent (matches the learner's expected shape)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS view_recipes (
            command       VARCHAR NOT NULL,
            concept       VARCHAR NOT NULL,
            vendor_hint   VARCHAR,
            field_mappings JSON NOT NULL,
            filter_expr   VARCHAR,
            discovered_at TIMESTAMP,
            PRIMARY KEY (command, concept, vendor_hint)
        )
        """
    )


def _validate_entry(entry: dict[str, Any], index: int) -> None:
    missing = _REQUIRED_FIELDS - set(entry)
    if missing:
        raise ValueError(
            f"recipe seed #{index} missing required fields: {sorted(missing)}"
        )
    concept = entry["concept"]
    if not isinstance(concept, str) or not _CONCEPT_PATTERN.match(concept):
        raise ValueError(
            f"recipe seed #{index} has invalid concept {concept!r}; "
            f"must match [a-z][a-z0-9_]*"
        )
    if concept not in _BUILTIN_CONCEPTS:
        logger.info(
            "recipe seed #%d uses user-defined concept %r (not a builtin) — loaded",
            index, concept,
        )
    # ARCH-28: commands starting with "@" are special-case directives
    # (e.g. "@topology_links" means view_builder projects directly from
    # the topology_links table, not from parsed_outputs JSON). Empty
    # field_mappings are legitimate for these.
    command = entry.get("command", "")
    allow_empty = isinstance(command, str) and command.startswith("@")
    if not isinstance(entry["field_mappings"], dict):
        raise ValueError(
            f"recipe seed #{index} has non-dict field_mappings"
        )
    if not entry["field_mappings"] and not allow_empty:
        raise ValueError(
            f"recipe seed #{index} has empty field_mappings (non-@-directive)"
        )


def _builtin_recipes_dir() -> Path:
    """Resolve the shipped builtin recipes directory.

    ARCH-29: per-protocol YAML files live under
    ``olav-netops/.olav/workspace/topology/recipes/builtin/``. When
    olav-netops is installed as a wheel, the workspace is copied into
    ``.olav/workspace/topology/`` at ``olav skill install`` time.
    """
    # Try package-relative path first (works for wheel installs that
    # include the workspace under .olav/workspace/ at deploy time).
    # At runtime the user's OLAV project has the workspace under
    # ``.olav/workspace/topology/`` — resolve via paths config.
    try:
        from olav.core.config import get_paths_config
        base = Path(get_paths_config().agent_dir) / "workspace" / "topology" / "recipes" / "builtin"
        if base.exists():
            return base
    except Exception:
        pass
    # Fallback: hunt relative to this file for dev checkouts.
    here = Path(__file__).resolve().parent
    for candidate in [
        here.parent.parent.parent / ".olav" / "workspace" / "netops" / "topology" / "recipes" / "builtin",
        here.parent.parent.parent / ".olav" / "workspace" / "topology" / "recipes" / "builtin",
        here.parent.parent / "data" / "recipes" / "builtin",
    ]:
        if candidate.exists():
            return candidate
    return Path("")  # empty Path — caller treats as missing


def _user_recipes_dir() -> Path:
    """Resolve ``~/.olav/config/recipes/user/`` — agent-drafted / user-written."""
    try:
        from olav.core.config import get_paths_config
        return Path(get_paths_config().config_dir) / "recipes" / "user"
    except Exception:
        return Path.home() / ".olav" / "config" / "recipes" / "user"


def _load_yaml_file(path: Path) -> list[dict[str, Any]]:
    """Parse a recipe YAML file; tolerate single-entry or list-of-entries."""
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    raise ValueError(f"recipe file {path} must be a dict or list of dicts")


def load_recipe_seeds(
    conn: Any,
    *,
    seed_path: Path | None = None,
    include_user: bool = True,
) -> dict[str, Any]:
    """Upsert view_recipes from builtin + user YAML directories.

    ARCH-29 layout:
    * Builtin: ``olav-netops/.olav/workspace/topology/recipes/builtin/*.yaml``
    * User:    ``~/.olav/config/recipes/user/*.yaml``

    Args:
        conn: open DuckDB connection (read-write).
        seed_path: override the builtin dir (legacy, accepts dir OR single file).
        include_user: if True (default), also scan user recipes dir.

    Returns ``{"total": N, "inserted_or_updated": M, "source_files": [...]}``.
    """
    _ensure_table(conn)

    # Resolve paths.
    if seed_path is None:
        builtin_dir = _builtin_recipes_dir()
    else:
        seed_path = Path(seed_path)
        builtin_dir = seed_path if seed_path.is_dir() else seed_path.parent
    user_dir = _user_recipes_dir() if include_user else None

    sources: list[Path] = []
    if builtin_dir and builtin_dir.exists():
        sources.extend(sorted(builtin_dir.glob("*.yaml")))
    else:
        logger.warning("recipe_seeds: builtin dir %s missing", builtin_dir)
    if user_dir and user_dir.exists():
        sources.extend(sorted(user_dir.glob("*.yaml")))

    # Single-file fallback (back-compat for `seed_path=<file.yaml>` callers).
    if seed_path is not None and seed_path.is_file():
        sources = [seed_path]

    if not sources:
        logger.info("recipe_seeds: no recipe YAML files found")
        return {"total": 0, "inserted_or_updated": 0, "source_files": []}

    now = datetime.now(UTC)
    written = 0
    total = 0
    for source in sources:
        try:
            entries = _load_yaml_file(source)
        except Exception as exc:
            logger.warning("recipe_seeds: skip %s (parse error: %s)", source, exc)
            continue
        for i, entry in enumerate(entries):
            try:
                _validate_entry(entry, i)
            except ValueError as exc:
                logger.warning("recipe_seeds: invalid entry in %s: %s", source, exc)
                continue
            total += 1
            command = entry["command"]
            concept = entry["concept"]
            vendor_hint = entry.get("vendor_hint") or "universal"
            field_mappings = json.dumps(entry["field_mappings"])
            filter_expr = entry.get("filter_expr")
            conn.execute(
                """
                INSERT INTO view_recipes
                    (command, concept, vendor_hint, field_mappings, filter_expr, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (command, concept, vendor_hint) DO UPDATE SET
                    field_mappings = EXCLUDED.field_mappings,
                    filter_expr = EXCLUDED.filter_expr,
                    discovered_at = EXCLUDED.discovered_at
                """,
                [command, concept, vendor_hint, field_mappings, filter_expr, now],
            )
            written += 1

    logger.info(
        "recipe_seeds: upserted %d row(s) from %d file(s)",
        written, len(sources),
    )
    return {
        "total": total,
        "inserted_or_updated": written,
        "source_files": [str(s) for s in sources],
    }
