"""CAB Config Extractor — agent-driven OC config extraction.

Schema-aware OC config extraction for the CAB digital twin pipeline.
Configuration is sourced directly from the snapshot database:

    Phase A — Snapshot extraction:
        Query parsed_outputs for blast_radius devices (latest snapshot).
        Look up schema_catalog for field→OC path mappings per (platform, command).
        Apply apply_oc_mapping_cached → list of OC-nested dicts per device.

    Phase B — Flatten + render:
        Recursively flatten each OC nested dict into {openconfig_path, value, **context}.
        Context (interface name, neighbor-address) extracted from YANG list key fields.
        Render via srl_config_renderer → per-device SRL set/... commands.

Architecture note:
    - Topology YAML: derived from topology_links (LLDP) only — not used here
    - Device config: derived from parsed_outputs + schema_catalog only — no custom views
    - The "auto" semantic views (v_bgp_neighbors_auto, v_interfaces_auto) are for
      read queries (agents asking questions). Config generation goes direct to snapshot.

Usage:
    from cab_config_extractor import CABConfigExtractor

    extractor = CABConfigExtractor(db_path=".olav/databases/main.duckdb")
    node_configs = extractor.render_all_devices(
        change_intent="Adjust BGP local-preference on R1",
        blast_radius_devices=["R1", "R2", "R3"],
        iface_map={"GigabitEthernet1": "ethernet-1/1"},
    )
    # Returns {"R1": "set / ...\n...", "R2": "..."}
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_LAB_SCRIPTS = _Path(__file__).parent.resolve()
if str(_LAB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_LAB_SCRIPTS))

import json as _json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YANG list node key field specs
# ---------------------------------------------------------------------------
# For each YANG list node name: (container, leaf) that holds the list key.
# Used by _flatten_oc_record to extract context values from list items.

_YANG_LIST_KEY_FIELDS: dict[str, tuple[str, str]] = {
    "interface":    ("config", "name"),
    "neighbor":     ("config", "neighbor-address"),
    "subinterface": ("config", "index"),
    "component":    ("config", "name"),
    "area":         ("config", "identifier"),
    "protocol":     ("config", "identifier"),
}

# Maps YANG list node name → context key for srl_config_renderer
_YANG_LIST_CONTEXT_KEY: dict[str, str] = {
    "interface": "interface",
    "neighbor":  "neighbor-address",
}


# ---------------------------------------------------------------------------
# OC record flattening
# ---------------------------------------------------------------------------


def _flatten_oc_record(oc_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a nested OC dict (output of apply_oc_mapping) into field dicts.

    Traverses the nested OpenConfig dict structure and emits one dict per leaf.
    Each dict contains:
        openconfig_path: full OC path (without module prefix)
        value:           leaf value
        **context:       YANG list key values — e.g. interface="GigabitEthernet1",
                         or neighbor-address="10.0.0.2"

    The module-prefix top key (e.g. "openconfig-interfaces") is stripped.
    The "_unmapped" key is skipped.
    """
    results: list[dict[str, Any]] = []
    for module_key, module_val in oc_record.items():
        if module_key == "_unmapped":
            continue
        if not isinstance(module_val, dict):
            continue
        _flatten_recursive(module_val, path_prefix="", context={}, results=results)
    return results


def _flatten_recursive(
    node: Any,
    path_prefix: str,
    context: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    if isinstance(node, dict):
        for key, val in node.items():
            new_path = f"{path_prefix}/{key}" if path_prefix else key
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        new_context = dict(context)
                        key_spec = _YANG_LIST_KEY_FIELDS.get(key)
                        if key_spec:
                            container, leaf = key_spec
                            container_val = item.get(container)
                            if isinstance(container_val, dict):
                                key_val = container_val.get(leaf)
                                if key_val is not None:
                                    ctx_key = _YANG_LIST_CONTEXT_KEY.get(key, key)
                                    new_context[ctx_key] = key_val
                        _flatten_recursive(item, new_path, new_context, results)
                    elif item is not None:
                        results.append({
                            "openconfig_path": new_path,
                            "value": item,
                            **context,
                        })
            elif isinstance(val, dict):
                _flatten_recursive(val, new_path, context, results)
            elif val is not None:
                results.append({
                    "openconfig_path": new_path,
                    "value": val,
                    **context,
                })
    elif node is not None:
        results.append({
            "openconfig_path": path_prefix,
            "value": node,
            **context,
        })


# ---------------------------------------------------------------------------
# CABConfigExtractor
# ---------------------------------------------------------------------------


class CABConfigExtractor:
    """Schema-aware OC config extractor for the CAB digital twin pipeline.

    Sources all configuration data from the snapshot database:
    - parsed_outputs: raw TextFSM records per device/command
    - schema_catalog: field→OC path mappings per (platform, command)
    - devices: platform lookup per device name

    Topology (topology_links / LLDP) is used only for building the CLAB YAML,
    not for configuration. The iface_map (vendor→SRL interface name) is derived
    externally from topology and passed in — see clab_topology_render.build_iface_map_from_spec.
    """

    def __init__(
        self,
        db_path: str,
        llm_fn: "Callable[[str], str] | None" = None,
    ) -> None:
        self.db_path = db_path
        self.llm_fn = llm_fn  # (prompt: str) -> str; when set, LLM renders SRL config
        self._oc_catalog_cache: dict[tuple[str, str], dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Schema introspection (for agent/tool use)
    # ------------------------------------------------------------------

    def get_schema_catalog(self) -> dict[str, list[str]]:
        """Return {command: [field_names]} for all entries in schema_catalog.

        Provides an overview of which fields are mapped per CLI command.
        """
        try:
            import duckdb
            con = duckdb.connect(self.db_path, read_only=True)
            rows = con.execute(
                "SELECT source_name, fields FROM schema_catalog"
            ).fetchall()
            con.close()
        except Exception as exc:
            logger.debug("get_schema_catalog: %s", exc)
            return {}

        result: dict[str, list[str]] = {}
        for command, fields_json in rows:
            if not command or not fields_json:
                continue
            try:
                fields = _json.loads(fields_json) if isinstance(fields_json, str) else fields_json
            except Exception:
                continue
            if not isinstance(fields, list):
                continue
            result[command] = [
                f.get("name", "") for f in fields
                if isinstance(f, dict) and f.get("name")
            ]
        return result

    # ------------------------------------------------------------------
    # Snapshot extraction pipeline
    # ------------------------------------------------------------------

    def _load_oc_catalog_cache(self) -> dict[tuple[str, str], dict[str, str]]:
        """Load schema_catalog into {(platform, command): {field: oc_path}} cache."""
        if self._oc_catalog_cache is not None:
            return self._oc_catalog_cache

        cache: dict[tuple[str, str], dict[str, str]] = {}
        try:
            import duckdb
            con = duckdb.connect(self.db_path, read_only=True)
            rows = con.execute(
                "SELECT platform, source_name, fields FROM schema_catalog"
            ).fetchall()
            con.close()
        except Exception as exc:
            logger.debug("_load_oc_catalog_cache: %s", exc)
            self._oc_catalog_cache = cache
            return cache

        for platform, command, fields_json in rows:
            if not platform or not command or not fields_json:
                continue
            try:
                fields = _json.loads(fields_json) if isinstance(fields_json, str) else fields_json
            except Exception:
                continue
            if not isinstance(fields, list):
                continue
            col_map: dict[str, str] = {
                f["name"]: (f.get("openconfig_path") or f.get("oc_path") or "")
                for f in fields
                if isinstance(f, dict) and f.get("name")
                and (f.get("openconfig_path") or f.get("oc_path"))
            }
            if col_map:
                cache[(platform, command)] = col_map

        self._oc_catalog_cache = cache
        return cache

    def _get_device_platforms(self, devices: list[str]) -> dict[str, str]:
        """Return {device_name: platform} for the given devices."""
        if not devices:
            return {}
        try:
            import duckdb
            placeholders = ", ".join("?" * len(devices))
            con = duckdb.connect(self.db_path, read_only=True)
            rows = con.execute(
                f"SELECT name, platform FROM devices WHERE name IN ({placeholders})",
                devices,
            ).fetchall()
            con.close()
            return {name: platform for name, platform in rows if name and platform}
        except Exception as exc:
            logger.debug("_get_device_platforms: %s", exc)
            return {}

    def _query_parsed_outputs(self, devices: list[str]) -> list[dict]:
        """Query parsed_outputs for devices at latest snapshot.

        Returns list of dicts with keys: device_name, command, parsed_data.
        """
        if not devices:
            return []
        try:
            import duckdb
            placeholders = ", ".join("?" * len(devices))
            con = duckdb.connect(self.db_path, read_only=True)
            rows = con.execute(
                f"""SELECT device_name, command, parsed_data
                    FROM parsed_outputs
                    WHERE device_name IN ({placeholders})
                      AND snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs)""",
                devices,
            ).fetchall()
            con.close()
            return [
                {"device_name": r[0], "command": r[1], "parsed_data": r[2]}
                for r in rows
            ]
        except Exception as exc:
            logger.debug("_query_parsed_outputs: %s", exc)
            return []

    def extract_oc_fields_from_snapshot(
        self,
        devices: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Extract OC field dicts from parsed_outputs snapshot for blast_radius devices.

        Pipeline:
            1. Query parsed_outputs (latest snapshot) for devices
            2. Get platform per device from devices table
            3. Load schema_catalog into oc_catalog_cache
            4. For each (device, command, records):
               a. apply_oc_mapping_cached → OC-nested dicts
               b. _flatten_oc_record  → [{openconfig_path, value, **context}]
            5. Return per-device field lists

        Returns:
            {device_name: [{openconfig_path, value, ...context_keys}]}
        """
        from olav.core.normalization import apply_oc_mapping_cached

        per_device: dict[str, list[dict[str, Any]]] = {d: [] for d in devices}

        if not devices:
            return per_device

        po_rows = self._query_parsed_outputs(devices)
        device_platforms = self._get_device_platforms(devices)
        oc_catalog_cache = self._load_oc_catalog_cache()

        for row in po_rows:
            device_name = row["device_name"]
            command = row["command"]
            parsed_data_raw = row["parsed_data"]

            if device_name not in per_device:
                continue

            platform = device_platforms.get(device_name)
            if not platform:
                logger.debug(
                    "extract_oc_fields_from_snapshot: no platform for device %r, skipping",
                    device_name,
                )
                continue

            try:
                records = (
                    _json.loads(parsed_data_raw)
                    if isinstance(parsed_data_raw, str)
                    else (parsed_data_raw or [])
                )
            except Exception as exc:
                logger.debug(
                    "extract_oc_fields_from_snapshot: JSON parse error for %r/%r: %s",
                    device_name, command, exc,
                )
                continue

            if not records or not isinstance(records, list):
                continue

            try:
                oc_records = apply_oc_mapping_cached(
                    records,
                    platform,
                    command,
                    oc_catalog_cache,
                    {},  # no mapping_rules fallback
                )
            except ValueError:
                # No mapping found for this (platform, command) — skip silently
                logger.debug(
                    "extract_oc_fields_from_snapshot: no schema_catalog entry for "
                    "platform=%r command=%r, skipping",
                    platform, command,
                )
                continue

            for oc_record in oc_records:
                fields = _flatten_oc_record(oc_record)
                per_device[device_name].extend(fields)

        return per_device

    def extract_oc_records_from_snapshot(
        self,
        devices: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Like extract_oc_fields_from_snapshot but returns nested OC records (not flattened).

        Used by the JSON import path (oc_config_builder): the nested OC dicts are
        passed directly to build_srl_config_json() without flattening.

        Returns:
            {device_name: [nested_oc_dict, ...]}  one dict per parsed_outputs row
        """
        from olav.core.normalization import apply_oc_mapping_cached

        per_device: dict[str, list[dict[str, Any]]] = {d: [] for d in devices}

        if not devices:
            return per_device

        po_rows = self._query_parsed_outputs(devices)
        device_platforms = self._get_device_platforms(devices)
        oc_catalog_cache = self._load_oc_catalog_cache()

        for row in po_rows:
            device_name = row["device_name"]
            command = row["command"]
            parsed_data_raw = row["parsed_data"]

            if device_name not in per_device:
                continue

            platform = device_platforms.get(device_name)
            if not platform:
                continue

            try:
                records = (
                    _json.loads(parsed_data_raw)
                    if isinstance(parsed_data_raw, str)
                    else (parsed_data_raw or [])
                )
            except Exception:
                continue

            if not records or not isinstance(records, list):
                continue

            try:
                oc_records = apply_oc_mapping_cached(
                    records,
                    platform,
                    command,
                    oc_catalog_cache,
                    {},
                )
            except ValueError:
                continue

            per_device[device_name].extend(oc_records)

        return per_device

    # ------------------------------------------------------------------
    # SRL rendering
    # ------------------------------------------------------------------

    def render_all_devices(
        self,
        change_intent: str,
        blast_radius_devices: list[str],
        iface_map: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Full pipeline: snapshot → OC extraction → SRL render.

        Rendering path (in priority order):
            1. LLM (if self.llm_fn is set): sends all OC fields + SRL syntax reference
               to the LLM; handles every protocol without any translation table.
            2. Deterministic fallback (no LLM): uses _SRL_TRANSLATIONS table;
               covers BGP + interface config only.

        Args:
            change_intent:         Human-readable description (used in LLM prompt).
            blast_radius_devices:  Device names to build SRL config for.
            iface_map:             {vendor_iface: srl_ethernet} mapping derived from
                                   topology (see build_iface_map_from_spec). Non-empty
                                   map acts as a whitelist — interfaces absent from it
                                   are skipped. Pass {} to disable whitelist.

        Returns:
            {device_name: srl_cli_config_string}
        """
        if not blast_radius_devices:
            return {}

        logger.debug(
            "render_all_devices: intent=%r devices=%s llm=%s",
            change_intent, blast_radius_devices, "yes" if self.llm_fn else "no",
        )

        oc_fields_by_device = self.extract_oc_fields_from_snapshot(blast_radius_devices)
        iface_map = iface_map or {}

        if self.llm_fn:
            from srl_config_renderer import render_device_srl_config_via_llm
            render_fn = lambda device, fields: render_device_srl_config_via_llm(
                device, fields, iface_map, self.llm_fn
            )
            path = "LLM"
        else:
            from srl_config_renderer import render_device_srl_config
            render_fn = lambda device, fields: render_device_srl_config(
                device, fields, iface_map
            )
            path = "deterministic"

        result: dict[str, str] = {}
        for device in blast_radius_devices:
            fields = oc_fields_by_device.get(device, [])
            cfg = render_fn(device, fields)
            result[device] = cfg
            logger.debug(
                "render_all_devices [%s] %s → %d set/ lines",
                path, device, cfg.count("set /"),
            )

        return result
