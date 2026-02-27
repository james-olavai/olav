"""schema_inspector.py — Runtime field discovery for olav-audit.

Replaces the static field lists that were in target_map.yaml with
dynamic discovery: inspects actual parsed_outputs JSON keys from DuckDB,
scores them against semantic hint words, and returns the best matching
field name per (target, device, platform) combination.

Design principle (olav-ops style):
  Instead of hardcoding:
    cpu_percent.fields = [cpu_5_sec, five_sec_cpu, cpu_util]   ← design-time guesses
  We do:
    1. READ  devices.platform for this device
    2. SCAN  parsed_outputs.parsed_data JSON keys for matching commands
    3. SCORE field names against hint words (cpu, util, percent, ...)
    4. PICK  highest-scoring field (or fall back to platform_overrides)

The caller (audit_engine.py) passes pre-loaded device_rows and target_def;
this module is stateless and DB-connection-optional (rows are passed in).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatLM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM-assisted field resolution
# ---------------------------------------------------------------------------

# CONFIDENCE_THRESHOLD — used ONLY in the runtime discover_*() cache-miss
# fallback path (when prewarm was not called).  During prewarm, LLM is always
# the primary judge; scoring is only used to rank candidates for the LLM prompt.
CONFIDENCE_THRESHOLD: float = 0.5

# Module-level caches — populated by prewarm_resolution_cache() before Reduce.
# Key: (target_name, platform, frozenset(field_names))
_field_resolution_cache: dict[tuple, str | None] = {}
# Key: (target_name, raw_value_lower)
_value_normalization_cache: dict[tuple, str] = {}

_llm_instance: BaseChatLM | None = None


def _get_llm() -> BaseChatLM | None:
    """Lazy-load the workspace LLM (same model the Agent uses).

    Returns None silently if settings are unavailable — callers fall back
    to pure scoring.
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    try:
        from langchain_openai import ChatOpenAI

        from olav.core.config import get_settings

        s = get_settings()
        _llm_instance = ChatOpenAI(model=s.llm.model_name, temperature=0.0)
        return _llm_instance
    except Exception as exc:
        logger.debug("_get_llm: cannot load LLM (%s), using scoring fallback", exc)
        return None


def _make_field_cache_key(
    target_name: str,
    platform: str | None,
    field_names: list[str],
) -> tuple:
    """Stable cache key: (target_name, platform, frozenset(fields))."""
    return (target_name, platform or "", frozenset(field_names))


def _llm_pick_field(
    candidates: list[tuple[str, float]],
    target_name: str,
    target_description: str,
    platform: str | None,
    llm: Any,
) -> str | None:
    """Ask LLM to choose the best field from low-confidence candidates.

    The LLM chooses from actual field names present in parsed device output,
    which is a semantic reasoning task unsuited to pure string-scoring.
    Falls back to the highest-scoring candidate on any error.
    """
    if not candidates:
        return None

    candidate_lines = "\n".join(
        f"  - {name}  (similarity score: {score:.2f})" for name, score in candidates[:15]
    )
    prompt = (
        f"You are analyzing parsed output fields from a network device command.\n\n"
        f"I need the field representing: **{target_description}**\n"
        f"Metric name: {target_name}\n"
        f"Device platform: {platform or 'unknown'}\n\n"
        f"Available field names found in the device output:\n{candidate_lines}\n\n"
        f"Which field name best represents '{target_description}'?\n"
        f"Reply with ONLY the exact field name from the list, "
        f"or 'none' if no field is relevant."
    )
    try:
        response = llm.invoke(prompt).content.strip()
        candidate_names = [name for name, _ in candidates]
        if response in candidate_names:
            logger.info(
                "LLM field pick: '%s' → '%s' (platform=%s)",
                target_name,
                response,
                platform,
            )
            return response
        cleaned = response.strip("'\"` ")
        if cleaned in candidate_names:
            return cleaned
        if cleaned.lower() == "none":
            return None
        # LLM returned something outside the candidate list — use top scorer
        logger.debug(
            "LLM returned '%s' not in candidates for '%s', using top scorer '%s'",
            response,
            target_name,
            candidates[0][0],
        )
        return candidates[0][0]
    except Exception as exc:
        logger.debug("_llm_pick_field error: %s", exc)
        return candidates[0][0] if candidates else None


def _llm_normalize_value(
    raw_value: str,
    target_name: str,
    target_description: str,
    expected_values: list[str],
    llm: Any,
) -> str:
    """Ask LLM to normalise an unrecognised status string.

    Example: BGP state \"Established/2d\" → \"established\".
    Falls back to raw_value unchanged on any error.
    """
    if not expected_values or llm is None:
        return raw_value

    prompt = (
        f"Network device status normalisation.\n\n"
        f'Raw value from device output: "{raw_value}"\n'
        f"Metric: {target_name} ({target_description})\n"
        f"Valid normalised values: {expected_values}\n\n"
        f'Which normalised value does "{raw_value}" correspond to?\n'
        f"Reply with ONLY one of: {', '.join(expected_values)}, "
        f"or 'unknown' if you cannot determine."
    )
    try:
        response = llm.invoke(prompt).content.strip().strip("'\"` ").lower()
        expected_lower = {v.lower(): v for v in expected_values}
        result = expected_lower.get(response, raw_value)
        logger.info(
            "LLM value normalise: '%s' '%s' → '%s'",
            target_name,
            raw_value,
            result,
        )
        return result
    except Exception as exc:
        logger.debug("_llm_normalize_value error: %s", exc)
        return raw_value


# ---------------------------------------------------------------------------
# DB helpers — used at agent startup to cache platform info
# ---------------------------------------------------------------------------


def get_device_platforms(conn: Any = None) -> dict[str, str]:
    """Return {device_name: platform} from the devices table.

    Args:
        conn: DuckDB connection (optional). If None, opens main.duckdb directly.

    Returns:
        Dict mapping device name → platform string (e.g. "cisco_ios").
        Returns empty dict on error (caller falls back to platform_overrides=None).
    """
    try:
        if conn is None:
            conn = _get_db_conn()
        rows = conn.execute(
            "SELECT name, platform FROM devices WHERE platform IS NOT NULL AND platform != ''"
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception as exc:
        logger.debug("get_device_platforms failed: %s", exc)
        return {}


def _get_db_conn() -> Any:
    """Open main DuckDB connection — fallback when no conn is injected."""
    # Try the framework layer first
    try:
        from olav.core.database import get_database

        return get_database().conn
    except Exception as exc:
        logger.debug("Failed to get DB from framework: %s", exc)

    # Direct open — walk up to find project root
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            break
        p = p.parent

    import duckdb

    for candidate in [
        p / ".olav" / "db" / "main.duckdb",
        p / ".olav" / "databases" / "main.duckdb",
    ]:
        if candidate.exists():
            import duckdb
            return duckdb.connect(str(candidate), read_only=False)

    raise FileNotFoundError("Cannot locate main.duckdb")


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------


def _score_field(field_name: str, hint_words: list[str]) -> float:
    """Score a field name against a list of hint words.

    Scoring rules (higher = better match):
      1.0  — exact equality with a hint word
      0.8  — field starts with or ends with a hint word
      0.5  — field contains a hint word as a whole token (underscore-separated)
      0.3  — field contains a hint word as a substring
      0.0  — no match

    Earlier hints in the list carry a small positional bonus (recency bias),
    so hint_words should be ordered from most-preferred to least-preferred.
    """
    fn = field_name.lower()
    fn_tokens = set(re.split(r"[_\-\.]", fn))

    best = 0.0
    for rank, hint in enumerate(hint_words):
        h = hint.lower()
        position_bonus = max(0.0, 0.05 * (len(hint_words) - rank) / len(hint_words))

        if fn == h:
            return 1.0 + position_bonus  # exact — return immediately
        if fn.startswith(h) or fn.endswith(h):
            score = 0.8 + position_bonus
        elif h in fn_tokens:
            score = 0.5 + position_bonus
        elif h in fn:
            score = 0.3 + position_bonus
        else:
            score = 0.0

        if score > best:
            best = score

    return best


def _all_field_names(records: list[dict]) -> list[str]:
    """Extract unique field names from a list of parsed_data records."""
    seen: dict[str, float] = {}
    for rec in records:
        for key in rec.keys():
            if key not in seen:
                seen[key] = 0.0
    return list(seen.keys())


# ---------------------------------------------------------------------------
# Public API — field discovery per target type
# ---------------------------------------------------------------------------


def discover_scalar_field(
    target_def: dict[str, Any],
    device_rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
    target_name: str = "",
) -> str | None:
    """Find the best scalar field name for a target (e.g. cpu_percent).

    Resolution order:
      1. Pre-warmed cache (populated by prewarm_resolution_cache with LLM).
      2. Platform override → if platform matches and field exists in data, use it.
      3. Score all actual field names against field_hints:
         a. score ≥ CONFIDENCE_THRESHOLD → return directly.
         b. score < threshold but > 0 → return best guess (low confidence).
      4. Numeric fallback: first field with a numeric value.

    Args:
        target_def:  Dict from target_map.yaml for this target.
        device_rows: [(command_str, [row_dict, ...]), ...] for one device.
        platform:    Device platform string (e.g. "cisco_ios"), or None.
        target_name: Target name for cache keying (e.g. "cpu_percent").

    Returns:
        Field name string, or None if no matching data found.
    """
    cmd_kws = [k.lower() for k in target_def.get("command_keywords", [])]
    field_hints = target_def.get("field_hints", [])
    platform_overrides = target_def.get("platform_overrides", {})

    # Collect records from commands matching ANY of the intent keywords
    # (OR logic — "cpu" OR "processes" matches "show processes top")
    matching_records: list[dict] = []
    for cmd, records in device_rows:
        cmd_l = cmd.lower()
        if any(kw in cmd_l for kw in cmd_kws):
            matching_records.extend(records)

    if not matching_records:
        return None

    # Platform override (always high-confidence — skip cache/scoring)
    if platform and platform in platform_overrides:
        override_field = platform_overrides[platform]
        if isinstance(override_field, str):
            for rec in matching_records:
                if override_field in rec and _has_value(rec[override_field]):
                    logger.debug(
                        "scalar discover: platform_override '%s' → field '%s'",
                        platform,
                        override_field,
                    )
                    return override_field

    all_fields = _all_field_names(matching_records)
    if not all_fields:
        return None

    # Check pre-warmed LLM cache (populated before Reduce by audit_runner)
    cache_key = _make_field_cache_key(target_name, platform, all_fields)
    if cache_key in _field_resolution_cache:
        cached = _field_resolution_cache[cache_key]
        logger.debug(
            "scalar discover: cache hit '%s' → '%s' (platform=%s)",
            target_name,
            cached,
            platform,
        )
        return cached

    # Score all actual field names
    scored_list = sorted(
        [(f, _score_field(f, field_hints)) for f in all_fields],
        key=lambda x: -x[1],
    )
    best_field, best_score = scored_list[0] if scored_list else (None, 0.0)

    if best_score >= CONFIDENCE_THRESHOLD:
        logger.debug(
            "scalar discover: '%s' score=%.2f (≥%.1f threshold) from %d candidates",
            best_field,
            best_score,
            CONFIDENCE_THRESHOLD,
            len(all_fields),
        )
        _field_resolution_cache[cache_key] = best_field
        return best_field

    if best_score > 0.0:
        logger.debug(
            "scalar discover: low-confidence '%s' score=%.2f — "
            "call prewarm_resolution_cache(llm=...) for better results",
            best_field,
            best_score,
        )
        _field_resolution_cache[cache_key] = best_field
        return best_field

    # Numeric fallback
    for field in all_fields:
        for rec in matching_records:
            val = rec.get(field, "")
            if val and _is_numeric_str(str(val)):
                _field_resolution_cache[cache_key] = field
                return field

    _field_resolution_cache[cache_key] = None
    return None


def discover_ratio_fields(
    target_def: dict[str, Any],
    device_rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
    target_name: str = "",
) -> tuple[str | None, str | None]:
    """Find (numerator_field, denominator_field) for computed_ratio targets.

    Checks the pre-warmed LLM cache (keys: target_name+/num, target_name+/den)
    before falling back to pure scoring.

    Returns:
        (numerator_field, denominator_field) — either may be None if not found.
    """
    cmd_kws = [k.lower() for k in target_def.get("command_keywords", [])]
    numerator_hints = target_def.get("numerator_hints", [])
    denominator_hints = target_def.get("denominator_hints", [])

    matching_records: list[dict] = []
    for cmd, records in device_rows:
        cmd_l = cmd.lower()
        if any(kw in cmd_l for kw in cmd_kws):
            matching_records.extend(records)

    if not matching_records:
        return None, None

    all_fields = _all_field_names(matching_records)

    def best_match(hints: list[str], suffix: str) -> str | None:
        cache_key = _make_field_cache_key(target_name + suffix, platform, all_fields)
        if cache_key in _field_resolution_cache:
            return _field_resolution_cache[cache_key]
        scored = {f: _score_field(f, hints) for f in all_fields}
        top = max(scored, key=lambda f: scored[f])
        result = top if scored[top] > 0.0 else None
        _field_resolution_cache[cache_key] = result
        return result

    num_field = best_match(numerator_hints, "/num")
    den_field = best_match(denominator_hints, "/den")

    # Edge case: only "free" memory available → adjust caller formula
    if num_field is not None and den_field is not None:
        if "free" in den_field.lower() and "total" not in den_field.lower():
            # Caller must handle: usage = 1 - (free / total)
            # Return numerator=free_field, denominator=None → caller computes 100-free%
            logger.debug(
                "ratio discover: only free-memory field available ('%s'), "
                "will compute 100 - free%%",
                den_field,
            )
            return den_field, None  # sentinel: single-field free-only mode

    logger.debug("ratio discover: numerator='%s', denominator='%s'", num_field, den_field)
    return num_field, den_field


def discover_row_fields(
    target_def: dict[str, Any],
    device_rows: list[tuple[str, list[dict]]],
    platform: str | None = None,
    target_name: str = "",
) -> tuple[str | None, str | None]:
    """Find (row_key_field, value_field) for per_row targets.

    row_key_field:  The field that names the entity (e.g. interface name, peer IP).
    value_field:    The field that holds the check value (e.g. status, state).

    Strategy:
      1. Pre-warmed cache (keys: target_name+/key, target_name+/val).
      2. Platform override → if found and fields exist in data, use directly.
      3. Score actual field names against row_key_hints → pick best key.
      4. Score actual field names against field_hints → pick best value field.

    Returns:
        (key_field, value_field) — either may be None.
    """
    cmd_kws = [k.lower() for k in target_def.get("command_keywords", [])]
    row_key_hints = target_def.get("row_key_hints", [])
    field_hints = target_def.get("field_hints", [])
    platform_overrides = target_def.get("platform_overrides", {})

    # Match commands
    matching_records: list[dict] = []
    for cmd, records in device_rows:
        cmd_l = cmd.lower()
        if any(kw in cmd_l for kw in cmd_kws):
            matching_records.extend(records)

    if not matching_records:
        return None, None

    # Platform override (always high-confidence)
    if platform and platform in platform_overrides:
        ov = platform_overrides[platform]
        if isinstance(ov, dict):
            kf = ov.get("key_field")
            vf = ov.get("value_field")
            if kf and vf:
                sample = matching_records[0]
                if kf in sample and vf in sample:
                    logger.debug(
                        "per_row discover: platform_override '%s' → key='%s', value='%s'",
                        platform,
                        kf,
                        vf,
                    )
                    return kf, vf

    all_fields = _all_field_names(matching_records)

    def best_match(hints: list[str], suffix: str) -> str | None:
        cache_key = _make_field_cache_key(target_name + suffix, platform, all_fields)
        if cache_key in _field_resolution_cache:
            return _field_resolution_cache[cache_key]
        scored = {f: _score_field(f, hints) for f in all_fields}
        top = max(scored, key=lambda f: scored[f])
        result = top if scored[top] > 0.0 else None
        _field_resolution_cache[cache_key] = result
        return result

    key_field = best_match(row_key_hints, "/key")
    value_field = best_match(field_hints, "/val")

    # Avoid key==value
    if key_field and value_field and key_field == value_field:
        # Pick second-best value field
        scored_v = sorted(
            {f: _score_field(f, field_hints) for f in all_fields}.items(),
            key=lambda x: -x[1],
        )
        for f, s in scored_v:
            if f != key_field and s > 0.0:
                value_field = f
                break
        else:
            value_field = None

    logger.debug(
        "per_row discover: key='%s', value='%s' (platform=%s)",
        key_field,
        value_field,
        platform,
    )
    return key_field, value_field


# ---------------------------------------------------------------------------
# Value normalization (uses target_def.value_aliases)
# ---------------------------------------------------------------------------


def normalize_value(raw: str, target_def: dict[str, Any], target_name: str = "") -> str:
    """Normalise a raw device status string.

    Resolution order:
      1. _value_normalization_cache — populated by prewarm with LLM.
      2. value_aliases dict (backward compat for old configs), case-insensitive.
      3. raw value unchanged.

    The primary path is always the LLM cache (populated once during prewarm).
    value_aliases in target_map.yaml is no longer required — new targets need
    only set description + supply audit rules with expected/allowed/forbidden.
    """
    # 1. LLM-pre-warmed cache (primary)
    tn = target_name or target_def.get("name", "")
    if tn:
        cached = _value_normalization_cache.get((tn, raw.lower()))
        if cached is not None:
            return cached

    # 2. Backward-compat aliases (for configs that still have value_aliases)
    aliases = target_def.get("value_aliases", {})
    if aliases:
        raw_lower = raw.lower()
        if raw_lower in aliases:
            return aliases[raw_lower]

    return raw


# ---------------------------------------------------------------------------
# Pre-warm: LLM-assisted resolution before the Reduce phase
# ---------------------------------------------------------------------------


def prewarm_resolution_cache(
    device_rows_map: dict[str, list[tuple[str, list[dict]]]],
    target_defs: dict[str, dict],
    device_platforms: dict[str, str] | None = None,
    llm: Any = None,
    audit_config: Any = None,
) -> dict[str, int]:
    """Pre-warm field and value resolution caches using LLM for low-confidence cases.

    **Call this ONCE in audit_runner.py after querying parsed_outputs and BEFORE
    calling run_audit_reduce().**  The LLM is invoked only when pure scoring is
    ambiguous (best_score < CONFIDENCE_THRESHOLD).  After this call, all
    discover_*() and normalize_value() calls become pure cache lookups.

    Args:
        device_rows_map:  {device_name: [(command, [row_dict, ...]), ...]}
        target_defs:      target definitions dict — built from audit rules via
                          _build_target_def() in audit_engine.py
        device_platforms: {device_name: platform_str} — from get_device_platforms()
        llm:              LangChain LLM instance, or None (auto-loaded from settings)
        audit_config:     AuditConfig Pydantic model — used by _prewarm_values() to
                          extract canonical state values from rules (expected/allowed/
                          forbidden), replacing hardcoded value_aliases.

    Returns:
        {"cached": N, "llm_resolved": M, "llm_skipped": K, "errors": E}

    Design principle ("use LLM capability, don't write complex logic"):
        LLM is **always** the primary judge during pre-warm — scoring only orders
        the candidate list supplied to the LLM prompt.  Scoring acts as a fallback
        only when no LLM is available (llm=None and auto-load fails).
        Cost is negligible: prewarm runs once per audit_run(), and one LLM call
        covers all (target, platform) combinations in a single batch of candidates.
    """
    if device_platforms is None:
        device_platforms = {}
    if llm is None:
        llm = _get_llm()

    stats: dict[str, int] = {
        "cached": 0,
        "llm_resolved": 0,
        "llm_skipped": 0,
        "errors": 0,
    }

    for target_name, target_def in target_defs.items():
        target_type = target_def.get("type", "scalar")
        description = target_def.get("description", target_name)
        platform_overrides = target_def.get("platform_overrides", {})
        cmd_kws = [k.lower() for k in target_def.get("command_keywords", [])]

        for device_name, device_rows in device_rows_map.items():
            platform = device_platforms.get(device_name)

            # Collect matching records
            matching_records: list[dict] = []
            for cmd, records in device_rows:
                cmd_l = cmd.lower()
                if any(kw in cmd_l for kw in cmd_kws):
                    matching_records.extend(records)

            if not matching_records:
                continue

            all_fields = _all_field_names(matching_records)
            if not all_fields:
                continue

            try:
                if target_type == "scalar":
                    _prewarm_scalar(
                        target_name,
                        target_def,
                        platform,
                        platform_overrides,
                        all_fields,
                        description,
                        llm,
                        stats,
                    )
                elif target_type == "computed_ratio":
                    _prewarm_ratio(
                        target_name,
                        target_def,
                        platform,
                        all_fields,
                        description,
                        llm,
                        stats,
                    )
                elif target_type == "per_row":
                    _prewarm_per_row(
                        target_name,
                        target_def,
                        platform,
                        platform_overrides,
                        all_fields,
                        matching_records,
                        description,
                        llm,
                        stats,
                    )
                    _prewarm_values(
                        target_name,
                        target_def,
                        matching_records,
                        all_fields,
                        description,
                        llm,
                        stats,
                        audit_config=audit_config,
                    )
            except Exception as exc:
                logger.debug(
                    "prewarm error for '%s' device '%s': %s", target_name, device_name, exc
                )
                stats["errors"] += 1

    logger.info(
        "prewarm_resolution_cache: cached=%d, llm_resolved=%d, skipped=%d, errors=%d",
        stats["cached"],
        stats["llm_resolved"],
        stats["llm_skipped"],
        stats["errors"],
    )
    return stats


def _prewarm_scalar(
    target_name: str,
    target_def: dict,
    platform: str | None,
    platform_overrides: dict,
    all_fields: list[str],
    description: str,
    llm: Any,
    stats: dict,
) -> None:
    """Pre-warm field cache for a scalar target.

    LLM is always the primary judge.  Scoring ranks the candidate list for
    the LLM prompt; platform_overrides are still used when exact.
    """
    if platform and platform in platform_overrides:
        override = platform_overrides[platform]
        if isinstance(override, str) and override in all_fields:
            cache_key = _make_field_cache_key(target_name, platform, all_fields)
            _field_resolution_cache[cache_key] = override
            stats["cached"] += 1
            return

    cache_key = _make_field_cache_key(target_name, platform, all_fields)
    if cache_key in _field_resolution_cache:
        stats["cached"] += 1
        return

    # Sort candidates by scoring (helps LLM prompt quality)
    field_hints = target_def.get("field_hints", [])
    scored = sorted(
        [(f, _score_field(f, field_hints)) for f in all_fields],
        key=lambda x: -x[1],
    )
    best_name, best_score = scored[0] if scored else (None, 0.0)

    if llm and scored:
        # LLM reads the ranked candidates and picks via semantic understanding
        resolved = _llm_pick_field(scored, target_name, description, platform, llm)
        _field_resolution_cache[cache_key] = resolved
        stats["llm_resolved"] += 1
    elif best_score > 0.0:
        # No LLM available — fall back to pure scoring
        _field_resolution_cache[cache_key] = best_name
        stats["llm_skipped"] += 1
    else:
        stats["llm_skipped"] += 1


def _prewarm_ratio(
    target_name: str,
    target_def: dict,
    platform: str | None,
    all_fields: list[str],
    description: str,
    llm: Any,
    stats: dict,
) -> None:
    """Pre-warm field cache for a computed_ratio target.

    LLM selects both numerator and denominator fields from ranked candidates.
    """
    for hint_key, suffix in [("numerator_hints", "/num"), ("denominator_hints", "/den")]:
        hints = target_def.get(hint_key, [])
        cache_key = _make_field_cache_key(target_name + suffix, platform, all_fields)
        if cache_key in _field_resolution_cache:
            stats["cached"] += 1
            continue

        scored = sorted(
            [(f, _score_field(f, hints)) for f in all_fields],
            key=lambda x: -x[1],
        )
        best_name, best_score = scored[0] if scored else (None, 0.0)
        part = "numerator" if "/num" in suffix else "denominator"
        half_desc = f"{description} ({part})"

        if llm and scored:
            resolved = _llm_pick_field(scored, target_name + suffix, half_desc, platform, llm)
            _field_resolution_cache[cache_key] = resolved
            stats["llm_resolved"] += 1
        elif best_score > 0.0:
            _field_resolution_cache[cache_key] = best_name
            stats["llm_skipped"] += 1
        else:
            stats["llm_skipped"] += 1


def _prewarm_per_row(
    target_name: str,
    target_def: dict,
    platform: str | None,
    platform_overrides: dict,
    all_fields: list[str],
    matching_records: list[dict],
    description: str,
    llm: Any,
    stats: dict,
) -> None:
    """Pre-warm field cache for a per_row target (key_field + value_field).

    LLM selects both the entity-identifier field and the status/state field
    from ranked candidates.  platform_overrides bypass LLM when exact.
    """
    if platform and platform in platform_overrides:
        ov = platform_overrides[platform]
        if isinstance(ov, dict):
            kf = ov.get("key_field")
            vf = ov.get("value_field")
            sample = matching_records[0] if matching_records else {}
            if kf and vf and kf in sample and vf in sample:
                for suffix, field in [("/key", kf), ("/val", vf)]:
                    cache_key = _make_field_cache_key(target_name + suffix, platform, all_fields)
                    _field_resolution_cache[cache_key] = field
                    stats["cached"] += 1
                return

    for hint_key, suffix in [("row_key_hints", "/key"), ("field_hints", "/val")]:
        hints = target_def.get(hint_key, [])
        cache_key = _make_field_cache_key(target_name + suffix, platform, all_fields)
        if cache_key in _field_resolution_cache:
            stats["cached"] += 1
            continue

        scored = sorted(
            [(f, _score_field(f, hints)) for f in all_fields],
            key=lambda x: -x[1],
        )
        best_name, best_score = scored[0] if scored else (None, 0.0)
        part = "key (entity identifier)" if "/key" in suffix else "value (status/state)"
        half_desc = f"{description} — {part} field"

        if llm and scored:
            resolved = _llm_pick_field(scored, target_name + suffix, half_desc, platform, llm)
            _field_resolution_cache[cache_key] = resolved
            stats["llm_resolved"] += 1
        elif best_score > 0.0:
            _field_resolution_cache[cache_key] = best_name
            stats["llm_skipped"] += 1
        else:
            stats["llm_skipped"] += 1


def map_intents_to_categories(
    intents: list[str],
    known_categories: list[str],
    llm: Any = None,
) -> list[str]:
    """Map free-text audit intents to snapshot category names using LLM.

    This replaces hardcoded ``intent → category`` dicts in audit_runner.
    The LLM understands semantic meaning (e.g. "cpu_utilization" → "system"),
    and handles arbitrary new intent names without code changes.

    Args:
        intents:          Free-text intent names from audit collect.intents.
        known_categories: Valid category keys from snapshot.CATEGORY_KEYWORDS.
        llm:              LangChain LLM, or None (auto-loaded from settings).

    Returns:
        Deduplicated list of matched category names (order preserved).
    """
    if not intents:
        return []

    # Fast path: intents that directly match known categories need no LLM
    exact = [i for i in intents if i in known_categories]
    remaining = [i for i in intents if i not in known_categories]

    if not remaining:
        return exact

    if llm is None:
        llm = _get_llm()

    if not llm:
        logger.debug("map_intents_to_categories: no LLM, returning exact matches only")
        return exact

    categories_str = "\n".join(f"  - {c}" for c in sorted(known_categories))
    intents_str = "\n".join(f"  - {i}" for i in remaining)

    prompt = (
        f"Map each network audit intent to the most relevant snapshot category.\n\n"
        f"Available snapshot categories:\n{categories_str}\n\n"
        f"Intents to map (not already matched):\n{intents_str}\n\n"
        f"Rules:\n"
        f"- Each intent maps to exactly one category\n"
        f"- Multiple intents may map to the same category\n"
        f"- Skip intents with no relevant category\n\n"
        f"Reply with ONLY valid category names from the list above, one per line, deduplicated."
    )
    try:
        response = llm.invoke(prompt).content.strip()
        llm_cats: list[str] = []
        for line in response.splitlines():
            cat = line.strip().strip("-• ").strip()
            if cat in known_categories and cat not in exact and cat not in llm_cats:
                llm_cats.append(cat)
        result = exact + llm_cats
        logger.info("LLM mapped intents %s → categories %s", intents, result)
        return result
    except Exception as exc:
        logger.debug("map_intents_to_categories LLM error: %s", exc)
        return exact


def _prewarm_values(
    target_name: str,
    target_def: dict,
    matching_records: list[dict],
    all_fields: list[str],
    description: str,
    llm: Any,
    stats: dict,
    audit_config: Any = None,
) -> None:
    """Pre-warm value normalization cache for per_row target state strings.

    Canonical values are derived from the audit config rules (expected /
    allowed / forbidden) rather than from a hardcoded value_aliases dict.
    This allows new platforms with different state strings to be handled
    without touching any config file.
    """
    if not llm:
        return

    # Collect canonical values from audit rules that reference this target
    expected_values: list[str] = []
    if audit_config:
        for rule in audit_config.rules:
            if rule.target == target_name:
                if rule.expected:
                    expected_values.append(rule.expected)
                if getattr(rule, "allowed", None):
                    expected_values.extend(rule.allowed)
                if getattr(rule, "forbidden", None):
                    # forbidden states are canonical — they're what the device
                    # should or should not be in
                    expected_values.extend(rule.forbidden)

    # Fallback: backward compat for configs that still have value_aliases
    if not expected_values:
        aliases = target_def.get("value_aliases", {})
        expected_values = list(set(aliases.values()))

    if not expected_values:
        return

    field_hints = target_def.get("field_hints", [])
    scored_fields = sorted(
        [(f, _score_field(f, field_hints)) for f in all_fields],
        key=lambda x: -x[1],
    )
    value_field = scored_fields[0][0] if scored_fields else None
    if not value_field:
        return

    raw_values: set[str] = set()
    for rec in matching_records:
        v = rec.get(value_field, "")
        if v and str(v).strip() not in ("", "None", "N/A", "n/a", "-"):
            raw_values.add(str(v).lower())

    for raw in raw_values:
        if raw in aliases:
            continue
        cache_key = (target_name, raw)
        if cache_key in _value_normalization_cache:
            continue
        resolved = _llm_normalize_value(raw, target_name, description, expected_values, llm)
        _value_normalization_cache[cache_key] = resolved
        stats["llm_resolved"] += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_value(val: Any) -> bool:
    return val is not None and str(val).strip() not in ("", "None", "N/A", "n/a", "-")


def _is_numeric_str(s: str) -> bool:
    try:
        float(s.rstrip("%"))
        return True
    except (ValueError, TypeError):
        return False
