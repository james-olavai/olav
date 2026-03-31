"""SRL Config Renderer.

Two rendering paths:

  Primary — LLM-driven (render_device_srl_config_via_llm):
      Raw OC fields + iface_map + SRL syntax reference → LLM → set /... commands.
      No Python-level translation logic. The LLM:
        - knows OpenConfig semantics (from training + syntax reference)
        - knows SRL CLI syntax (from training + syntax reference)
        - resolves interface names using the provided iface_map
        - skips read-only state paths, loopbacks, unapplicable fields
        - handles every protocol (BGP, OSPF, ISIS, EVPN, VRF, policy, ...)
      Adding a new protocol = update srl-cli-syntax.md only.

  Fallback — deterministic (render_device_srl_config):
      Used when no LLM is available (unit tests, offline mode).
      Table-driven rules for BGP + interface basics only.
      Not a replacement for the LLM path — coverage is intentionally limited.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_LAB_SCRIPTS = _Path(__file__).parent.resolve()
if str(_LAB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_LAB_SCRIPTS))

import json as _json
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SRL_SYNTAX_REF_PATH = _LAB_SCRIPTS.parent / "references" / "srl-cli-syntax.md"


# ---------------------------------------------------------------------------
# LLM-driven renderer (primary path)
# ---------------------------------------------------------------------------


def _load_syntax_ref() -> str:
    try:
        return _SRL_SYNTAX_REF_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("srl_config_renderer: cannot load syntax reference: %s", exc)
        return ""


def render_device_srl_config_via_llm(
    device: str,
    oc_fields: list[dict],
    iface_map: dict[str, str],
    llm_fn: Callable[[str], str],
    syntax_ref: str | None = None,
) -> str:
    """Generate SRL config via LLM — no Python translation logic.

    The LLM receives the full OpenConfig field data, the interface name mapping,
    and the SRL CLI syntax reference. It produces all required ``set /...`` commands
    for every protocol present in the data.

    Args:
        device:     Device name (for prompt context and logging).
        oc_fields:  OC field list from extract_oc_fields_from_snapshot —
                    [{openconfig_path, value, [interface], [neighbor-address], ...}]
        iface_map:  {vendor_iface: srl_ethernet} mapping from topology (LLDP).
                    The LLM uses this to translate interface names.
        llm_fn:     (prompt: str) -> str  callable that invokes the LLM.
        syntax_ref: SRL CLI syntax reference text. Loaded from srl-cli-syntax.md if None.

    Returns:
        Newline-joined ``set /...`` commands from the LLM, or a comment if none produced.
    """
    if not oc_fields:
        return f"# no OC fields for {device}\n"

    if syntax_ref is None:
        syntax_ref = _load_syntax_ref()

    prompt = f"""You are generating SR Linux (SRL) startup configuration for a ContainerLab digital twin.

Device: {device}

Interface name mapping (vendor name → SRL physical port name):
{_json.dumps(iface_map, indent=2) if iface_map else "{}  (no topology mapping — use names as-is)"}

OpenConfig fields extracted from the production network snapshot for this device:
{_json.dumps(oc_fields, indent=2)}

SR Linux CLI syntax reference:
{syntax_ref}

Generate the complete SRL configuration as `set /...` commands.

Rules:
1. Translate vendor interface names to SRL names using the interface mapping above.
2. Loopback interfaces (Loopback*, lo*, lo0*) are NOT physical SRL ports — skip them.
   Router-id is set via BGP global config, not via a loopback interface command.
3. Read-only state fields (session-state, adjacency-state, oper-status) — skip them.
4. Paths containing `/state/` are read-only snapshots — use their `/config/` equivalent
   when generating the set command (e.g. state/admin-status → admin-state enable/disable).
5. If an interface name is not in the mapping and the mapping is non-empty, skip that interface.
6. Output ONLY `set /...` commands, one per line. No explanation, no comments, no blank lines.
"""

    response = llm_fn(prompt)

    lines = [
        line.strip()
        for line in response.splitlines()
        if line.strip().startswith("set /")
    ]

    if not lines:
        logger.warning(
            "render_device_srl_config_via_llm [%s]: LLM returned no set/ commands", device
        )
        return f"# LLM returned no commands for {device}\n"

    logger.debug(
        "render_device_srl_config_via_llm [%s]: %d commands from LLM", device, len(lines)
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Deterministic fallback (no LLM — unit tests / offline)
# ---------------------------------------------------------------------------

_LOOPBACK_RE = re.compile(r"^(loopback|lo)\d*$", re.IGNORECASE)

_SRL_TRANSLATIONS: list[dict[str, Any]] = [
    {
        "oc_path_suffix": "config/admin-status",
        "oc_path_anchor": "interfaces/interface",
        "srl_template":   "set / interface {interface} admin-state {value}",
        "value_map":      {"up": "enable", "true": "enable", "1": "enable", "enabled": "enable",
                           "down": "disable", "false": "disable", "0": "disable", "disabled": "disable"},
        "context_key":    "interface",
    },
    {
        "oc_path_suffix": "config/mtu",
        "oc_path_anchor": "interfaces/interface",
        "srl_template":   "set / interface {interface} mtu {value}",
        "value_map":      None,
        "context_key":    "interface",
    },
    {
        "oc_path_suffix": "config/ip",
        "oc_path_anchor": "subinterfaces/subinterface",
        "srl_template":   "set / interface {interface} subinterface 0 ipv4 address {value} primary",
        "value_map":      None,
        "context_key":    "interface",
    },
    {
        "oc_path_suffix": "config/peer-as",
        "oc_path_anchor": "bgp/neighbors/neighbor",
        "srl_template":   "set / network-instance default protocols bgp neighbor {neighbor-address} peer-as {value}",
        "value_map":      None,
        "context_key":    "neighbor-address",
    },
    {
        "oc_path_suffix": "config/enabled",
        "oc_path_anchor": "bgp/neighbors/neighbor",
        "srl_template":   "set / network-instance default protocols bgp neighbor {neighbor-address} admin-state {value}",
        "value_map":      {"true": "enable", "1": "enable", "enabled": "enable", "up": "enable",
                           "false": "disable", "0": "disable", "disabled": "disable", "down": "disable"},
        "context_key":    "neighbor-address",
    },
    {
        "oc_path_suffix": "config/as",
        "oc_path_anchor": "bgp/global",
        "srl_template":   "set / network-instance default protocols bgp autonomous-system {value}",
        "value_map":      None,
        "context_key":    None,
    },
    {
        "oc_path_suffix": "config/router-id",
        "oc_path_anchor": "bgp/global",
        "srl_template":   "set / network-instance default protocols bgp router-id {value}",
        "value_map":      None,
        "context_key":    None,
    },
]


def _resolve_iface(raw: str, iface_map: dict[str, str]) -> str | None:
    if _LOOPBACK_RE.match(raw.strip()):
        return None
    if raw in iface_map:
        return iface_map[raw]
    return None if iface_map else raw


def oc_leaf_to_srl_cli(
    oc_path: str,
    value: Any,
    context: dict[str, Any],
    iface_map: dict[str, str],
    translations: list[dict[str, Any]] | None = None,
) -> str | None:
    if not oc_path:
        return None
    rules = _SRL_TRANSLATIONS if translations is None else translations
    path = oc_path.lower()

    for rule in rules:
        if not path.endswith(rule["oc_path_suffix"].lower()):
            continue
        anchor = rule.get("oc_path_anchor")
        if anchor and anchor.lower() not in path:
            continue
        req = rule.get("context_key")
        if req and req not in context:
            return None

        render_ctx = dict(context)
        if "interface" in render_ctx:
            resolved = _resolve_iface(render_ctx["interface"], iface_map)
            if resolved is None:
                return None
            render_ctx["interface"] = resolved

        vm = rule.get("value_map")
        mapped = vm.get(str(value).lower(), value) if vm else value
        if "primary" in rule["srl_template"] and "/" not in str(mapped):
            return None

        try:
            return rule["srl_template"].format_map({**render_ctx, "value": mapped})
        except KeyError:
            return None

    return None


def render_device_srl_config(
    device: str,
    oc_fields: list[dict],
    iface_map: dict[str, str],
    db_path: str | None = None,
) -> str:
    """Deterministic fallback — covers BGP + interface basics without an LLM."""
    lines: list[str] = []
    seen: set[str] = set()

    for field in oc_fields:
        raw_path = field.get("openconfig_path", "")
        # state→config flip
        parts = raw_path.split("/")
        config_path = "/".join("config" if p == "state" else p for p in parts)
        value = field.get("value")
        context = {k: v for k, v in field.items() if k not in ("openconfig_path", "value", "leaf_type")}

        cmd = oc_leaf_to_srl_cli(config_path, value, context, iface_map)
        if cmd and cmd not in seen:
            seen.add(cmd)
            lines.append(cmd)

    return ("\n".join(lines) + "\n") if lines else f"# no renderable OC fields for {device}\n"


# ---------------------------------------------------------------------------
# DB seeding (for agent SQL introspection)
# ---------------------------------------------------------------------------

SRL_TRANSLATIONS_DDL = """
CREATE TABLE IF NOT EXISTS srl_translations (
    id INTEGER PRIMARY KEY, priority INTEGER NOT NULL DEFAULT 100,
    oc_path_suffix VARCHAR NOT NULL, oc_path_anchor VARCHAR,
    srl_template VARCHAR NOT NULL, value_map JSON, context_key VARCHAR, notes VARCHAR
)
"""

SRL_TRANSLATIONS_SEED: list[tuple] = [
    (1, 10, "config/admin-status", "interfaces/interface",
     "set / interface {interface} admin-state {value}",
     '{"up":"enable","true":"enable","1":"enable","enabled":"enable","down":"disable","false":"disable","0":"disable","disabled":"disable"}',
     "interface", "Interface admin up/down"),
    (2, 20, "config/mtu", "interfaces/interface",
     "set / interface {interface} mtu {value}", None, "interface", "Interface MTU"),
    (3, 30, "config/ip", "subinterfaces/subinterface",
     "set / interface {interface} subinterface 0 ipv4 address {value} primary",
     None, "interface", "Interface IPv4 address (CIDR)"),
    (4, 40, "config/peer-as", "bgp/neighbors/neighbor",
     "set / network-instance default protocols bgp neighbor {neighbor-address} peer-as {value}",
     None, "neighbor-address", "BGP neighbor peer AS"),
    (5, 50, "config/enabled", "bgp/neighbors/neighbor",
     "set / network-instance default protocols bgp neighbor {neighbor-address} admin-state {value}",
     '{"true":"enable","1":"enable","enabled":"enable","up":"enable","false":"disable","0":"disable","disabled":"disable","down":"disable"}',
     "neighbor-address", "BGP neighbor admin-state"),
    (6, 60, "config/as", "bgp/global",
     "set / network-instance default protocols bgp autonomous-system {value}",
     None, None, "BGP global autonomous-system"),
    (7, 70, "config/router-id", "bgp/global",
     "set / network-instance default protocols bgp router-id {value}",
     None, None, "BGP global router-id"),
]


def ensure_srl_translations(con: Any) -> None:
    con.execute(SRL_TRANSLATIONS_DDL)
    for row in SRL_TRANSLATIONS_SEED:
        con.execute(
            """INSERT INTO srl_translations (id,priority,oc_path_suffix,oc_path_anchor,
               srl_template,value_map,context_key,notes)
               SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS
               (SELECT 1 FROM srl_translations WHERE id=?)""",
            [*row, row[0]],
        )
