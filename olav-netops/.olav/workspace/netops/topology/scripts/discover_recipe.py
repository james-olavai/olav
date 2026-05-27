#!/usr/bin/env python3
"""discover_recipe — LLM-drafts a recipe YAML for a new (protocol, vendor).

ARCH-29: when a user adds a new protocol to ``~/.olav/config/topology.yaml``,
the topology agent uses this tool to produce a candidate recipe YAML by:

1. Scanning ``netops.raw_output_store`` for commands matching the protocol
   keyword (e.g. ``%bfd%``) on the target vendor's devices
2. Sampling the first parsed entry to see the available JSON field names
3. Prompting the LLM to produce a YAML recipe matching the contract in
   ``references/RECIPE_FORMAT.md``

The output is a YAML string to be reviewed/saved via ``save_recipe``.
This function does NOT write to DB or disk — that's ``save_recipe``'s job.

**No sandbox, no Python code generation** — LLM emits YAML only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


_PROTOCOL_KEYWORDS = {
    # Built-in — used as fallback hints; user may override.
    "bgp": ["bgp summary"],
    "ospf": ["ospf neighbor"],
    "cdp_lldp": ["cdp neighbor", "lldp neighbor"],
    # Common extensions
    "bfd": ["bfd neighbor", "bfd session"],
    "isis": ["isis neighbor", "isis adjacency"],
    "hsrp": ["hsrp"],
    "vrrp": ["vrrp"],
    "ldp": ["ldp neighbor", "mpls ldp"],
}


def _sample_parsed_entry(con, command: str, vendor: str) -> dict | None:
    """Pick a device of ``vendor`` and return one parsed_data entry."""
    try:
        row = con.execute(
            """
            SELECT parsed_data
            FROM netops.parsed_outputs
            WHERE command = ?
              AND device_name IN (SELECT hostname FROM netops.devices WHERE platform = ?)
              AND parsed_data IS NOT NULL
            LIMIT 1
            """,
            [command, vendor],
        ).fetchone()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception:
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def _candidate_commands(con, protocol: str, vendor: str) -> list[str]:
    """Find commands in raw_output_store that look relevant to this protocol."""
    keywords = _PROTOCOL_KEYWORDS.get(protocol.lower(), [protocol.lower()])
    like_clauses = " OR ".join(["command ILIKE ?"] * len(keywords))
    params = [f"%{k}%" for k in keywords]
    try:
        rows = con.execute(
            f"""
            SELECT DISTINCT command FROM netops.raw_output_store
            WHERE ({like_clauses})
              AND device_name IN (SELECT hostname FROM netops.devices WHERE platform = ?)
            """,
            params + [vendor],
        ).fetchall()
    except Exception:
        return []
    return [r[0] for r in rows if r[0]]


def _canonical_field_hints(protocol: str) -> str:
    """Return a prompt fragment listing canonical target-field names."""
    hints = {
        "bgp": (
            "Target canonical fields (BGPSession Pydantic model):\n"
            "  - neighbor_ip (IP of the peer, required)\n"
            "  - neighbor_as (int, peer AS)\n"
            "  - local_as (int, optional)\n"
            "  - router_id (str, optional)\n"
            "  - state (Literal: Established/Active/Idle/Connect/OpenSent/OpenConfirm/Down)\n"
            "  - uptime (str, optional)"
        ),
        "ospf": (
            "Target canonical fields (OSPFAdjacency Pydantic model):\n"
            "  - neighbor_id (required, router-id of peer)\n"
            "  - neighbor_ip (optional, IP of peer)\n"
            "  - interface (required)\n"
            "  - state (Literal: Full/FULL/DR/FULL/BDR/FULL/DROTHER/2-Way/Init/ExStart/Exchange/Loading/Down)\n"
            "  - area (optional)\n"
            "  - dead_time (optional)"
        ),
    }
    return hints.get(protocol.lower(), (
        "Target canonical fields (custom concept — choose snake_case names "
        "that match the semantic fields in the parsed entry):\n"
        "  - neighbor_ip (if the concept has peer IP)\n"
        "  - state (if the concept has a state field)\n"
        "  - interface (if concept has an interface binding)"
    ))


def _render_prompt(
    protocol: str,
    vendor: str,
    commands: list[str],
    sample: dict,
    protocol_concept: str,
) -> str:
    sample_json = json.dumps(sample, indent=2, ensure_ascii=False)[:2500]
    cmds_list = "\n".join(f"  - {c!r}" for c in commands[:5])
    hints = _canonical_field_hints(protocol)
    return (
        f"Draft a YAML recipe for the `{protocol_concept}` concept on "
        f"vendor `{vendor}`. Pick ONE command from the candidates below "
        f"that best represents '{protocol}' session/adjacency data.\n\n"
        f"## Candidate commands present in raw_output_store:\n{cmds_list}\n\n"
        f"## Sample parsed_data entry (first record from one device):\n"
        f"```json\n{sample_json}\n```\n\n"
        f"## {hints}\n\n"
        f"## Output contract — emit ONLY YAML (no markdown fences, no prose):\n"
        f"- command: <exact CLI string>\n"
        f"  concept: {protocol_concept}\n"
        f"  vendor_hint: {vendor}\n"
        f"  field_mappings:\n"
        f"    <canonical_name>: <source_json_key_from_sample_above>\n"
        f"    ... (one line per mapping)\n\n"
        f"Rules:\n"
        f"1. `field_mappings` values MUST be keys that exist in the sample.\n"
        f"2. `state` source field is often literally named 'state' or 'state_pfxrcd'.\n"
        f"3. If a canonical field has no good source, OMIT it (don't invent).\n"
        f"4. No Python code, no comments in YAML output.\n"
    )


def discover_recipe(protocol: str, vendor: str) -> dict[str, Any]:
    """Draft a recipe YAML for a ``(protocol, vendor)`` pair using LLM.

    Args:
        protocol: User-declared protocol keyword (``bfd``, ``hsrp``, etc.).
        vendor: Target platform (``cisco_ios``, ``juniper_junos``, ``arista_eos``).

    Returns:
        ``{ok, yaml, diagnostics}``. On success ``yaml`` is the candidate
        recipe string (pass to ``save_recipe``). On failure ``ok=False``
        with ``error`` explaining why (no matching command, no parsed
        data, LLM unavailable, etc.).
    """
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    from olav_netops.core.topology_intent import intent_to_concept

    concept = intent_to_concept(protocol)

    con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    try:
        commands = _candidate_commands(con, protocol, vendor)
        if not commands:
            return {
                "ok": False,
                "error": (
                    f"no raw_output_store commands matching {protocol!r} keywords "
                    f"on vendor {vendor!r}; run netops_init first or extend "
                    f"_PROTOCOL_KEYWORDS"
                ),
                "diagnostics": {"commands_found": []},
            }

        # Try each candidate until we find one with non-empty parsed_data
        sample = None
        chosen_cmd = None
        for cmd in commands:
            s = _sample_parsed_entry(con, cmd, vendor)
            if s:
                sample = s
                chosen_cmd = cmd
                break
        if sample is None:
            return {
                "ok": False,
                "error": (
                    f"found commands {commands} but none have parsed_data on "
                    f"{vendor!r} devices; parse layer (ntc-templates or "
                    f"ARCH-25 PaC) needs to succeed first"
                ),
                "diagnostics": {"commands_found": commands, "sample": None},
            }
    finally:
        con.close()

    # LLM call — prompt is YAML-only, no Python, no sandbox
    try:
        from olav.core.llm import LLMFactory
        llm = LLMFactory.get_chat_model()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"LLM unavailable: {exc}",
            "diagnostics": {"commands_found": commands, "chosen_cmd": chosen_cmd},
        }

    prompt = _render_prompt(protocol, vendor, commands, sample, concept)
    try:
        response = llm.invoke(prompt)
        yaml_text = (
            response.content if hasattr(response, "content") else str(response)
        ).strip()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"LLM invoke failed: {exc}",
            "diagnostics": {"commands_found": commands, "chosen_cmd": chosen_cmd},
        }

    # Strip markdown fences if any (the prompt asks not to include them but LLM
    # sometimes does anyway)
    if yaml_text.startswith("```"):
        yaml_text = yaml_text.split("\n", 1)[1] if "\n" in yaml_text else ""
    if yaml_text.endswith("```"):
        yaml_text = yaml_text.rsplit("```", 1)[0].rstrip()

    # Fast YAML parse sanity (save_recipe will re-validate)
    try:
        import yaml
        parsed = yaml.safe_load(yaml_text)
        entries = parsed if isinstance(parsed, list) else [parsed]
    except Exception as exc:
        return {
            "ok": False,
            "error": f"LLM output is not valid YAML: {exc}",
            "diagnostics": {"raw": yaml_text[:500]},
        }

    return {
        "ok": True,
        "yaml": yaml_text,
        "diagnostics": {
            "protocol": protocol,
            "vendor": vendor,
            "concept": concept,
            "chosen_cmd": chosen_cmd,
            "sample_keys": sorted(sample.keys())[:15],
            "entries": len(entries),
        },
    }


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = discover_recipe(**_args)
    print(_json.dumps(result, default=str))
