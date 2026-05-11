"""R-AGENT-HIERARCHY Phase C — deterministic TCF writer.

The 2026-05-09 CAB experiments showed gemma4:31b nothink can't reliably
construct emit_tcf args (10+ fields with cross-constraints + nested CLI
JSON-in-string) — three attempts to fix at the LLM layer (thin tool,
plan template, more guides) all failed.

The diagnosis: TCF is the wrong shape for an LLM to author directly.
LLMs are best at prose; structured nested formats compete with the
analytical thinking budget.

This module is the **deterministic translation layer**:
* sim sub-agent outputs prose change plan with `## Change Summary` block
* `render_tcf_from_change_plan(plan_text)` extracts the summary, queries
  DB for facts (ASN, loopback, platform), renders CLI from per-intent +
  per-platform templates, and writes the TCF YAML

Pure Python — no LLM call.  Hallucination becomes impossible because
the LLM never authors ASNs / loopbacks / CLI fragments.

See ``dev_docs/73. AGENT_HIERARCHY_REFACTOR.md`` (Phase C).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .intf_picker import pick_free_interfaces
from .lab_subnet_pool import allocate_lab_subnet
from .prod_cli import (
    ebgp_subnet_assignments,
    generate_ios_ebgp_config,
    generate_ios_ebgp_rollback,
    generate_junos_ebgp_config,
    generate_junos_ebgp_rollback,
)
from .tcf_sim import tcf_emit_from_sim


_SUMMARY_HEADER_RE = re.compile(
    r"^##\s+Change\s+Summary\s*$", re.MULTILINE | re.IGNORECASE
)
# Match either a fenced YAML block or a bare YAML body until next `##`
_FENCED_YAML_RE = re.compile(
    r"```(?:yaml|yml)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE
)


# ────────────────────────────────────────────────────────────────────
# Summary block extraction
# ────────────────────────────────────────────────────────────────────


def _extract_summary(plan_text: str) -> dict[str, Any]:
    """Find `## Change Summary` and parse YAML body inside.

    Accepts either ```yaml fenced or bare YAML lines until next ## header.
    Returns {} if no block found (caller decides error).
    """
    match = _SUMMARY_HEADER_RE.search(plan_text)
    if not match:
        return {}
    tail = plan_text[match.end():]
    # Try fenced first
    fenced = _FENCED_YAML_RE.search(tail)
    body: str
    if fenced:
        body = fenced.group(1)
    else:
        # Bare body: take lines until next `##` header or EOF
        lines: list[str] = []
        for line in tail.splitlines():
            if line.startswith("##"):
                break
            lines.append(line)
        body = "\n".join(lines).strip()
    if not body:
        return {}
    try:
        parsed = yaml.safe_load(body)
    except yaml.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


# ────────────────────────────────────────────────────────────────────
# DB grounding
# ────────────────────────────────────────────────────────────────────


def _db_facts(device_names: list[str]) -> dict[str, dict[str, Any]]:
    """Pull platform / ASN / loopback per device from main.duckdb.

    Returns a dict keyed by hostname with keys
    ``platform``, ``loopback``, ``local_as``.  Missing values are
    ``None`` (caller decides).
    """
    facts: dict[str, dict[str, Any]] = {
        d: {"platform": None, "loopback": None, "local_as": None}
        for d in device_names
    }
    if not device_names:
        return facts

    try:
        import duckdb

        from olav.core.config import MAIN_DB_PATH

        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        try:
            placeholders = ",".join("?" for _ in device_names)
            # Platform + metadata.loopback_ip
            for hostname, platform, metadata in con.execute(
                f"SELECT hostname, platform, metadata FROM netops.devices "
                f"WHERE hostname IN ({placeholders})",
                device_names,
            ).fetchall():
                if hostname not in facts:
                    continue
                facts[hostname]["platform"] = platform
                if metadata:
                    try:
                        md = (
                            json.loads(metadata)
                            if isinstance(metadata, str)
                            else metadata
                        )
                        if isinstance(md, dict) and md.get("loopback_ip"):
                            facts[hostname]["loopback"] = md["loopback_ip"]
                    except (json.JSONDecodeError, TypeError):
                        pass
            # ASN + router_id (loopback fallback) from BGP summary view
            for hostname, router_id, local_as in con.execute(
                f"SELECT device_name, router_id, local_as "
                f"FROM netops.v_show_ip_bgp_summary_auto "
                f"WHERE device_name IN ({placeholders})",
                device_names,
            ).fetchall():
                if hostname not in facts:
                    continue
                if facts[hostname]["local_as"] is None and local_as is not None:
                    try:
                        facts[hostname]["local_as"] = int(local_as)
                    except (TypeError, ValueError):
                        pass
                if facts[hostname]["loopback"] is None and router_id:
                    facts[hostname]["loopback"] = router_id
            # Cross-resolve: Junos devices often don't show in the
            # Cisco-style v_show_ip_bgp_summary_auto, but show up as
            # neighbors of Cisco peers.  Match by loopback IP.
            known_loopbacks = {
                f["loopback"]: name
                for name, f in facts.items()
                if f.get("loopback")
            }
            if known_loopbacks:
                for _, neighbor, neighbor_as in con.execute(
                    "SELECT device_name, bgp_neighbor, neighbor_as "
                    "FROM netops.v_show_ip_bgp_summary_auto"
                ).fetchall():
                    if neighbor in known_loopbacks:
                        target = known_loopbacks[neighbor]
                        if facts[target]["local_as"] is None:
                            try:
                                facts[target]["local_as"] = int(neighbor_as)
                            except (TypeError, ValueError):
                                pass
            # Heuristic for missing loopback: if peer device knows
            # exactly one neighbor with the expected ASN, take that
            # neighbor IP as our loopback.  Used when target device
            # is Junos (no own row in Cisco-style summary view).
            for target in device_names:
                if facts[target]["loopback"] is not None and facts[target]["local_as"] is not None:
                    continue
                others = [d for d in device_names if d != target]
                for other in others:
                    if facts[other]["local_as"] is None:
                        continue
                    rows = con.execute(
                        "SELECT bgp_neighbor, neighbor_as "
                        "FROM netops.v_show_ip_bgp_summary_auto "
                        "WHERE device_name = ?",
                        [other],
                    ).fetchall()
                    if len(rows) == 1:
                        n, na = rows[0]
                        if facts[target]["loopback"] is None and n:
                            facts[target]["loopback"] = n
                        if facts[target]["local_as"] is None:
                            try:
                                facts[target]["local_as"] = int(na)
                            except (TypeError, ValueError):
                                pass
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — best-effort grounding
        pass
    return facts


# ────────────────────────────────────────────────────────────────────
# Per-intent rendering
# ────────────────────────────────────────────────────────────────────


def _render_ebgp_direct(
    devices: list[str],
    facts: dict[str, dict[str, Any]],
    lab_subnet: str,
) -> dict[str, Any]:
    """Build implementation/rollback/post_check/tvt for ebgp_direct.

    Uses prod_cli.generate_*_ebgp_config helpers (already used by
    derive_prod_cli_from_tcf).  Lab subnet drives the per-device IPs.
    """
    if len(devices) != 2:
        raise ValueError(
            f"ebgp_direct requires exactly 2 devices; got {len(devices)}"
        )

    a, b = devices
    fa, fb = facts[a], facts[b]
    plat_a = (fa.get("platform") or "").lower()
    plat_b = (fb.get("platform") or "").lower()
    asn_a = fa.get("local_as")
    asn_b = fb.get("local_as")
    loop_a = fa.get("loopback")
    loop_b = fb.get("loopback")

    # IP allocation via shared helper — prefixlen flows from lab_subnet,
    # not hardcoded /30 (ARCH-37). For /30 the helper gives the same
    # ".1 / .2" result as the previous string arithmetic, but for /29
    # /28 etc. it stays internally consistent.
    intf_ips = ebgp_subnet_assignments(lab_subnet, [a, b])
    a_ip_cidr, b_ip_cidr = intf_ips[a], intf_ips[b]
    a_ip = a_ip_cidr.split("/", 1)[0]
    b_ip = b_ip_cidr.split("/", 1)[0]

    # ARCH-32: discover free interface per device from netops.topology_links
    # instead of hardcoding GigabitEthernet0/1 / ge-0/0/1 (which is
    # almost always already in use in real prod). Falls back to the
    # legacy hardcoded names ONLY when the DB has no topology data
    # (fresh deployment), with a warning surfaced to the caller.
    picked = pick_free_interfaces(
        [a, b],
        {a: fa.get("platform"), b: fb.get("platform")},
    )
    a_intf = picked.get(a) or ("ge-0/0/1" if "junos" in plat_a else "GigabitEthernet0/1")
    b_intf = picked.get(b) or ("ge-0/0/1" if "junos" in plat_b else "GigabitEthernet0/1")

    impl: list[dict[str, Any]] = []
    rollback: list[dict[str, Any]] = []

    def _cli_for(self_name, self_facts, peer_name, peer_facts,
                 self_intf, self_ip_cidr, peer_ip):
        plat = (self_facts.get("platform") or "").lower()
        loop = self_facts.get("loopback") or "0.0.0.0"
        peer_loop = peer_facts.get("loopback") or "0.0.0.0"
        local_as = self_facts.get("local_as") or 0
        peer_as = peer_facts.get("local_as") or 0
        group = f"EBGP-{peer_name}"
        if "junos" in plat:
            cli = generate_junos_ebgp_config(
                prod_intf=self_intf,
                prod_intf_ip=self_ip_cidr,
                prod_loopback=str(loop),
                local_asn=int(local_as),
                neighbor_ip=peer_ip,
                neighbor_loopback=str(peer_loop),
                peer_asn=int(peer_as),
                group_name=group,
            )
            rb = generate_junos_ebgp_rollback(
                prod_intf=self_intf, group_name=group,
            )
        else:
            cli = generate_ios_ebgp_config(
                prod_intf=self_intf,
                prod_intf_ip=self_ip_cidr,
                prod_loopback=str(loop),
                local_asn=int(local_as),
                neighbor_ip=peer_ip,
                peer_asn=int(peer_as),
            )
            rb = generate_ios_ebgp_rollback(
                local_asn=int(local_as),
                prod_intf=self_intf,
                neighbor_ip=peer_ip,
                neighbor_asn=int(peer_as),
                prod_loopback=str(loop),
            )
        return cli, rb

    cli_a, rb_a = _cli_for(a, fa, b, fb, a_intf, a_ip_cidr, b_ip)
    cli_b, rb_b = _cli_for(b, fb, a, fa, b_intf, b_ip_cidr, a_ip)
    impl = [
        {"device": a, "phase": 1, "action": "configure", "cli": cli_a},
        {"device": b, "phase": 1, "action": "configure", "cli": cli_b},
    ]
    rollback = [
        {"device": a, "phase": 1, "action": "configure", "cli": rb_a},
        {"device": b, "phase": 1, "action": "configure", "cli": rb_b},
    ]

    # ARCH-34: pre_check verifies preconditions BEFORE implementation
    # pushes config.  Two checks per device:
    #   1. Lab subnet not already routed (catches subnet collision)
    #   2. Picked interface not already configured with an IP (catches
    #      stale topology DB, race with another change)
    # Failure semantics: any pre_check failure => HITL must intervene,
    # implementation is BLOCKED.
    def _pre_check_rows(self_name, peer_ip_str, self_intf, plat):
        is_junos = "junos" in plat
        # Subnet-not-routed check: cross-platform "show ip route" works
        # on Cisco IOS; Junos uses "show route".
        subnet_cmd = (
            f"show route {lab_subnet}" if is_junos
            else f"show ip route {lab_subnet}"
        )
        # IOS prints "% Network not in table" / "% Subnet not in table"
        # for absent routes.  Junos prints no `inet.0` entry => the
        # default Junos response has no specific match line.
        # must_match=False with an empty pattern is unwieldy; instead
        # we look for a pattern that's ONLY present when a route EXISTS
        # ("via" appears in any active route line) and require its
        # absence.
        subnet_absent_pattern = "via "
        # Interface-IP-empty check: cross-platform "show ip interface
        # brief" on Cisco; Junos "show interfaces terse".
        intf_cmd = (
            f"show interfaces {self_intf} terse" if is_junos
            else f"show ip interface brief {self_intf}"
        )
        # IOS "unassigned" appears when the interface has no IP.
        # Junos terse line shows the interface but no inet column when
        # unconfigured; "inet" presence indicates configured.
        intf_free_pattern = "unassigned" if not is_junos else "inet"
        intf_must_match = not is_junos  # IOS: pattern present; Junos: absent

        return [
            {
                "device": self_name,
                "check_id": f"PR-{self_name}-subnet-clear",
                "description": (
                    f"Lab subnet {lab_subnet} must not be present in "
                    f"the routing table before deploy"
                ),
                "command": subnet_cmd,
                "expected_pattern": subnet_absent_pattern,
                "must_match": False,  # absence proves the subnet is free
            },
            {
                "device": self_name,
                "check_id": f"PR-{self_name}-intf-free",
                "description": (
                    f"Interface {self_intf} must not have an IP "
                    f"configured before deploy"
                ),
                "command": intf_cmd,
                "expected_pattern": intf_free_pattern,
                "must_match": intf_must_match,
            },
        ]

    pre_check = (
        _pre_check_rows(a, b_ip, a_intf, plat_a)
        + _pre_check_rows(b, a_ip, b_intf, plat_b)
    )

    post_check = [
        {
            "device": a, "check_id": f"PC-{a}-bgp",
            "description": f"BGP session to {b} ({b_ip}) Established",
            "command": "show bgp summary"
                if "junos" in plat_a else "show ip bgp summary",
            "expected_pattern": str(b_ip),
        },
        {
            "device": b, "check_id": f"PC-{b}-bgp",
            "description": f"BGP session to {a} ({a_ip}) Established",
            "command": "show bgp summary"
                if "junos" in plat_b else "show ip bgp summary",
            "expected_pattern": str(a_ip),
        },
    ]
    tvt = [
        {
            "test_id": f"TC-bgp-{a}-{b}",
            "description": f"BGP session {a}↔{b} reaches Established within 60s",
            "expected": "session-up",
            "evidence_check_ids": [f"PC-{a}-bgp", f"PC-{b}-bgp"],
        },
    ]
    return {
        "implementation": impl,
        "rollback": rollback,
        "pre_check": pre_check,
        "post_check": post_check,
        "tvt": tvt,
        "lab_ips": {a: a_ip, b: b_ip},
    }


# ────────────────────────────────────────────────────────────────────
# Main entry
# ────────────────────────────────────────────────────────────────────


def _render_freeform_cli(
    devices: list[str],
    facts: dict[str, dict[str, Any]],
    lab_subnet: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Build TCF blocks from sim-supplied CLI lines + checks.

    Unlike ebgp_direct, this renderer does not synthesize CLI from
    DB facts and per-platform templates — sim provides the CLI
    directly via typed slots in submit_change_plan, grounded in
    inspector-tool outputs.  The renderer wraps these into the TCF
    block structure (auto-assigning check_ids and standard
    phase/action fields), preserving pre_check/rollback/post_check
    gates.

    Required summary keys (from sim's submit_change_plan call):
        cli_per_device:      dict[device_name, list[str]]
        rollback_per_device: dict[device_name, list[str]]
        pre_checks:          list[{device, command, expected_pattern,
                                   must_match, description}]
        post_checks:         list[{device, command, expected_pattern,
                                   description}]

    The lab_subnet param is unused for freeform_cli (sim's CLI is
    expected to encode any IP/subnet plumbing it needs) but accepted
    for renderer-signature compatibility with ebgp_direct.
    """
    _ = lab_subnet  # accepted but unused
    _ = facts       # facts available for sanity but not consumed

    cli_per_device = summary.get("cli_per_device") or {}
    rollback_per_device = summary.get("rollback_per_device") or {}
    pre_checks_in = summary.get("pre_checks") or []
    post_checks_in = summary.get("post_checks") or []

    if not isinstance(cli_per_device, dict) or not cli_per_device:
        raise ValueError(
            "freeform_cli requires non-empty cli_per_device "
            "dict (device → CLI lines)"
        )
    if not isinstance(rollback_per_device, dict) or not rollback_per_device:
        raise ValueError(
            "freeform_cli requires non-empty rollback_per_device "
            "dict — every change must have a rollback path"
        )
    if not isinstance(post_checks_in, list) or not post_checks_in:
        raise ValueError(
            "freeform_cli requires at least one post_check — TVT "
            "needs evidence to reference"
        )

    impl: list[dict[str, Any]] = []
    rollback: list[dict[str, Any]] = []
    for d in devices:
        d_cli = cli_per_device.get(d)
        d_rb = rollback_per_device.get(d)
        if not d_cli:
            raise ValueError(
                f"freeform_cli: cli_per_device missing entry for "
                f"device {d!r}"
            )
        if not d_rb:
            raise ValueError(
                f"freeform_cli: rollback_per_device missing entry "
                f"for device {d!r}"
            )
        # CliBlock.cli is list[str] — preserve list form; if sim sent
        # a single string, split on newlines.
        d_cli_list = d_cli if isinstance(d_cli, list) else str(d_cli).splitlines()
        d_rb_list = d_rb if isinstance(d_rb, list) else str(d_rb).splitlines()
        impl.append({"device": d, "phase": 1, "action": "configure", "cli": d_cli_list})
        rollback.append({"device": d, "phase": 1, "action": "configure", "cli": d_rb_list})

    pre_check: list[dict[str, Any]] = []
    for i, pc in enumerate(pre_checks_in, start=1):
        if not isinstance(pc, dict):
            continue
        dev = pc.get("device")
        if dev not in devices:
            continue
        pre_check.append({
            "device": dev,
            "check_id": pc.get("check_id") or f"PR-{dev}-{i:02d}",
            "description": pc.get("description") or "(no description)",
            "command": pc["command"],
            "expected_pattern": pc.get("expected_pattern", ""),
            "must_match": bool(pc.get("must_match", True)),
        })

    post_check: list[dict[str, Any]] = []
    for i, pc in enumerate(post_checks_in, start=1):
        if not isinstance(pc, dict):
            continue
        dev = pc.get("device")
        if dev not in devices:
            continue
        post_check.append({
            "device": dev,
            "check_id": pc.get("check_id") or f"PC-{dev}-{i:02d}",
            "description": pc.get("description") or "(no description)",
            "command": pc["command"],
            "expected_pattern": pc.get("expected_pattern", ""),
        })

    if not post_check:
        raise ValueError(
            "freeform_cli: post_checks did not match any provided "
            "device — every device named in post_checks must be in "
            "the devices list"
        )

    tvt = [{
        "test_id": "TC-freeform-verify",
        "description": (
            f"All post_check evidence must match expected patterns "
            f"({len(post_check)} check{'s' if len(post_check) != 1 else ''})"
        ),
        "expected": "all-post-checks-pass",
        "evidence_check_ids": [pc["check_id"] for pc in post_check],
    }]

    return {
        "implementation": impl,
        "rollback": rollback,
        "pre_check": pre_check,
        "post_check": post_check,
        "tvt": tvt,
    }


_INTENT_RENDERERS = {
    "ebgp_direct": _render_ebgp_direct,
    "freeform_cli": _render_freeform_cli,
}


def render_tcf_from_change_plan(
    plan_text: str,
    output_dir: str | Path = "exports/cab",
    *,
    lab_subnet: str | None = None,
    risk_class: str = "medium",
    created_by: str = "sim",
) -> dict[str, Any]:
    """Parse prose change plan + ground from DB + render TCF YAML.

    The plan must contain a ``## Change Summary`` section with a YAML
    block carrying these required fields:

        change_id: r1-r3-ebgp
        title: Add eBGP between R1 and R3
        intent_type: ebgp_direct
        devices: [R1, R3]

    Optional summary fields:
        feasibility: BLOCKED        # any non-OK value blocks emission
        feasibility_reason: "..."   # surfaced in error envelope

    Returns:
        On success:
            {"status": "success", "spec_path": "<path>", "facts": {...},
             "warnings": [...]}
        On error (no spec written):
            {"status": "error", "error": "<reason>", "blockers": [...]}
    """
    summary = _extract_summary(plan_text)
    if not summary:
        return {
            "status": "error",
            "error": (
                "no `## Change Summary` block found in plan_text "
                "(or block has no parseable YAML body)"
            ),
        }

    required = {"change_id", "title", "intent_type", "devices"}
    missing = required - set(summary.keys())
    if missing:
        return {
            "status": "error",
            "error": f"Change Summary missing required fields: {sorted(missing)}",
            "got_fields": sorted(summary.keys()),
        }

    # ARCH-36: allocate from RFC 5737 pool, idempotent on change_id.
    # Prevents concurrent CABs from colliding on the legacy default
    # 172.16.99.0/30 and prevents overlap with real prod RFC 1918 space.
    if lab_subnet is None:
        lab_subnet = allocate_lab_subnet(summary["change_id"])

    intent_type = summary["intent_type"]

    # rev 271 Phase F integration: when an `intent_schemas/<intent>.intent.yaml`
    # exists, route through the generic config-driven handler. Hand-coded
    # entries in _INTENT_RENDERERS remain canonical for intents not yet ported
    # (currently ebgp_direct, freeform_cli) — schema lookup is checked first.
    try:
        from olav.core.cab.generic_intent_handler import _schemas_dir as _gh_schemas_dir
        _yaml_schema_exists = (_gh_schemas_dir() / f"{intent_type}.intent.yaml").exists()
    except Exception:
        _yaml_schema_exists = False

    if intent_type not in _INTENT_RENDERERS and not _yaml_schema_exists:
        available = sorted(_INTENT_RENDERERS.keys())
        try:
            from olav.core.cab.generic_intent_handler import list_intents as _gh_list
            schema_intents = _gh_list()
            if schema_intents:
                available = sorted({*available, *schema_intents})
        except Exception:
            pass
        return {
            "status": "error",
            "error": (
                f"intent_type {intent_type!r} not supported by tcf_writer. "
                f"Supported: {available}.  "
                "Either add a renderer or have sim escalate to a human."
            ),
        }

    devices = summary["devices"]
    if not isinstance(devices, list) or not devices:
        return {
            "status": "error",
            "error": f"`devices` must be a non-empty list; got {devices!r}",
        }

    # Honour explicit feasibility flag.  OK and OK_HITL_ONLY both
    # render the spec; only BLOCKED stops emission (per ADR-0011 §5).
    feasibility = str(summary.get("feasibility", "OK")).upper()
    if feasibility not in ("OK", "OK_HITL_ONLY"):
        return {
            "status": "error",
            "error": (
                f"sim flagged feasibility={feasibility}. "
                "TCF not emitted; address the blocker first."
            ),
            "blockers": [summary.get("feasibility_reason", feasibility)],
        }

    # Ground facts from DB
    facts = _db_facts(devices)
    warnings: list[str] = []
    for d in devices:
        f = facts[d]
        miss = [k for k in ("platform", "loopback", "local_as") if f[k] is None]
        if miss:
            warnings.append(
                f"DB gap for {d}: {miss} not in netops.devices / "
                f"v_show_ip_bgp_summary_auto.  Spec will use placeholders; "
                "review before lab apply."
            )

    # Implicit feasibility: same-AS eBGP is impossible
    if intent_type == "ebgp_direct" and len(devices) == 2:
        a, b = devices
        asn_a, asn_b = facts[a]["local_as"], facts[b]["local_as"]
        if asn_a is not None and asn_b is not None and asn_a == asn_b:
            return {
                "status": "error",
                "error": (
                    f"⚠ eBGP feasibility BLOCKED by DB grounding: "
                    f"{a} and {b} are both in AS {asn_a}.  "
                    "eBGP requires different ASNs.  "
                    "Phase 0 prerequisite: renumber one device, OR change "
                    "intent_type to ibgp_direct."
                ),
                "blockers": [
                    f"{a}.local_as = {asn_a} == {b}.local_as = {asn_b}"
                ],
                "facts": facts,
            }

    # Render per-intent CLI blocks. Three dispatch paths:
    #   (a) YAML schema match (rev 271 Phase F): config-driven via
    #       generic_intent_handler — preferred for new intents.
    #   (b) freeform_cli: hand-coded, takes parsed summary (sim
    #       supplies cli_per_device etc.).
    #   (c) Other hand-coded entries (ebgp_direct): take only
    #       devices / facts / lab_subnet.
    try:
        if _yaml_schema_exists:
            from olav.core.cab.generic_intent_handler import (
                render_intent_to_tcf_blocks as _gh_render,
            )
            import duckdb
            try:
                from olav.core.config import MAIN_DB_PATH
                _db_conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
            except Exception as _db_exc:
                return {
                    "status": "error",
                    "error": f"generic_intent_handler: DB open failed: {_db_exc}",
                    "facts": facts,
                }
            try:
                intent_args = summary.get("intent_args") or {}
                if not intent_args:
                    return {
                        "status": "error",
                        "error": (
                            f"intent {intent_type!r} uses YAML schema; "
                            "summary YAML must include `intent_args:` block "
                            "with per-intent fields. See "
                            "src/olav/data/intent_schemas/<intent>.intent.yaml "
                            "for required args."
                        ),
                    }
                rendered = _gh_render(intent_type, intent_args, _db_conn)
            finally:
                try:
                    _db_conn.close()
                except Exception:
                    pass
        elif intent_type == "freeform_cli":
            renderer = _INTENT_RENDERERS[intent_type]
            rendered = renderer(devices, facts, lab_subnet, summary)
        else:
            renderer = _INTENT_RENDERERS[intent_type]
            rendered = renderer(devices, facts, lab_subnet)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error": f"renderer for {intent_type!r} failed: {exc}",
            "facts": facts,
        }

    # Compose tcf_emit_from_sim args
    result = tcf_emit_from_sim(
        change_id=summary["change_id"],
        title=summary["title"],
        intent_type=intent_type,
        device_names=devices,
        device_platforms=[facts[d]["platform"] or "unknown" for d in devices],
        device_loopbacks=[facts[d]["loopback"] or "0.0.0.0" for d in devices],
        device_asns=[facts[d]["local_as"] or 0 for d in devices],
        implementation_json=json.dumps(rendered["implementation"]),
        rollback_json=json.dumps(rendered["rollback"]),
        pre_check_json=json.dumps(rendered.get("pre_check", [])),
        post_check_json=json.dumps(rendered["post_check"]),
        tvt_json=json.dumps(rendered["tvt"]),
        required_test_ids=[r["test_id"] for r in rendered["tvt"]],
        optional_test_ids=[],
        lab_subnet=lab_subnet,
        risk_class=risk_class,
        output_dir=str(output_dir),
        created_by=created_by,
    )

    if isinstance(result, dict):
        result.setdefault("warnings", [])
        result["warnings"].extend(warnings)
        result["facts"] = facts
    return result
