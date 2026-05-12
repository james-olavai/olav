"""Patch M — prod→SRL translation for CAB lab post_check execution.

Analyzer (sim) writes ``post_check.command`` and ``expected_pattern``
in **production** form (e.g. Junos ``show bgp summary`` plus link IPs
from prod ``10.1.13.x``).  The lab is an SR Linux digital twin, so:

  1. ``show bgp summary`` won't run as a bare shell command on the
     SRL container — it needs ``sr_cli "show network-instance default
     protocols bgp neighbor"``.
  2. Prod link IPs (``10.1.13.x``) are not present in the lab; R89
     allocates fresh hosts under ``intent.lab_subnet`` (default
     ``172.16.99.0/30``).

Without this translator, every real-world TCF spec FAILs in the lab
even when the configuration is fundamentally correct (false-negative).
Patch L already automated the pipeline; Patch M makes the pipeline
produce a usable verdict on real specs.

Public API (all deterministic, no LLM):

    translate_command_prod_to_srl(command) -> (translated, was_translated)
    build_prod_to_lab_ip_map(tcf, r89_args) -> dict[prod_ip, lab_ip]
    translate_pattern(pattern, ip_map) -> translated_pattern
    translate_post_check(spec, ip_map) -> dict (full per-check translation)
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

# ── Command translation ──────────────────────────────────────────────────

_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:/\d{1,2})?\b")

# Ordered most-specific → least-specific so longer phrases win.
_PROD_TO_SRL_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bshow\s+(ip\s+)?bgp\s+(summary|neighbors?)\b", re.I),
        'sr_cli "show network-instance default protocols bgp neighbor"',
    ),
    (
        # 2026-05-11: SRL 24.10 needs a parametrized prefix.
        # Specific prefix form: `show ip route <PREFIX>` /
        # `show route <PREFIX>` — translate to ``prefix <PREFIX>``.
        # The prefix may be bare (``192.0.2.0``) or in CIDR
        # (``192.0.2.0/24``); SRL accepts both.
        re.compile(
            r"\bshow\s+(?:ip\s+)?route\s+"
            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)",
            re.I,
        ),
        # SRL ipv4-prefix YANG pattern requires CIDR. If the prod
        # command uses bare IP (IOS "show ip route X" form), fall
        # back to ``summary`` which lists ALL routes — pattern
        # matching against the expected_pattern (e.g. "192.0.2.0/24")
        # then works as a simple substring check across the dump.
        # This is more reliable than guessing the right prefix length.
        lambda m: (
            'sr_cli "show network-instance default route-table '
            f'ipv4-unicast prefix {m.group(1)}"'
            if "/" in m.group(1)
            else 'sr_cli "show network-instance default route-table '
                 'ipv4-unicast summary"'
        ),
    ),
    (
        # Bare ``show ip route`` (no prefix) — full summary view.
        re.compile(r"\bshow\s+(ip\s+)?route\b", re.I),
        'sr_cli "show network-instance default route-table ipv4-unicast summary"',
    ),
    (
        re.compile(r"\bshow\s+(ip\s+)?ospf\s+neighbors?\b", re.I),
        'sr_cli "show network-instance default protocols ospf neighbor"',
    ),
    (
        re.compile(r"\bshow\s+interfaces?\b", re.I),
        'sr_cli "show interface"',
    ),
    (
        re.compile(r"\bshow\s+version\b", re.I),
        'sr_cli "show version"',
    ),
    # ISSUE-CAB-FREEFORM-POSTCHECK-DESCRIPTION-FORMAT (P3, 2026-05-12):
    # `show running-config` (full) and `show running-config interface <X>`
    # → SRL `info`. The `info` output is YAML and contains description
    # strings, neighbor IPs, prefix lists, etc. verbatim, so the
    # post_check's `expected_pattern` substring check (e.g.
    # 'cab-test-link') resolves the same way as it would on IOS/Junos.
    # We don't try to translate the interface name (Eth0/0 → ethernet-1/1)
    # because the freeform_translator already renamed the interface in
    # the SRL config; `info` without an interface filter returns the
    # whole config including all interface descriptions.
    (
        re.compile(r"\bshow\s+running-config\s+interface\b", re.I),
        'sr_cli "info / interface"',
    ),
    (
        re.compile(r"\bshow\s+running-config\b", re.I),
        'sr_cli "info"',
    ),
]


def translate_command_prod_to_srl(command: str) -> tuple[str, bool]:
    """Translate a prod-form CLI show command to its SRL ``sr_cli`` form.

    Returns ``(translated, was_translated)``. Returns the input verbatim
    when it already starts with ``sr_cli`` or when no rule matches.
    """
    if not isinstance(command, str):
        return ("" if command is None else str(command), False)
    cmd = command.strip()
    if not cmd:
        return cmd, False
    # Already SRL form
    if cmd.lower().startswith("sr_cli") or cmd.startswith("bash -c"):
        return cmd, False
    for pat, replacement in _PROD_TO_SRL_RULES:
        m = pat.search(cmd)
        if m:
            # Support callable replacements that need captured groups
            # (e.g. show ip route <PREFIX> → prefix <PREFIX>).
            if callable(replacement):
                return replacement(m), True
            return replacement, True
    return cmd, False


# ── Prod→Lab IP mapping ──────────────────────────────────────────────────


def _lab_ips_from_subnet(subnet: str, count: int) -> list[str]:
    """Return ``count`` host IPs from a /30 (or larger) subnet, in order.

    R89's allocation convention: nodes[0] takes host 1, nodes[1] takes
    host 2, etc.
    """
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []
    hosts = list(net.hosts())
    return [str(h) for h in hosts[:count]]


_OWN_INTF_PATTERNS: list[re.Pattern[str]] = [
    # Junos / SRL: "family inet address <IP>/<MASK>" or "address <IP>/<MASK>"
    re.compile(
        r"\b(?:family\s+inet\s+)?address\s+(\d{1,3}(?:\.\d{1,3}){3})/\d{1,2}\b",
        re.I,
    ),
    # IOS / NX-OS: "ip address <IP> <MASK>" (mask is dotted-quad, exclude
    # by anchoring the IP capture to a non-dotted-quad followup token)
    re.compile(
        r"\bip\s+address\s+(\d{1,3}(?:\.\d{1,3}){3})\s+\d{1,3}(?:\.\d{1,3}){3}",
        re.I,
    ),
]

_NEIGHBOR_IP_PATTERN = re.compile(
    r"\bneighbor\s+(\d{1,3}(?:\.\d{1,3}){3})\b",
    re.I,
)


def _extract_own_interface_ips(cli_lines: list[str]) -> set[str]:
    """Pull **own interface** IPs out of CLI lines — addresses assigned
    to this device's interfaces (``ip address X Y`` or ``family inet
    address X/N``).  Matches deterministic CLI shapes; ignores
    addresses *referenced* in ``neighbor`` lines (those belong to
    peers).  Used as the primary source when the change includes
    interface configuration.
    """
    found: set[str] = set()
    for line in cli_lines:
        if not isinstance(line, str):
            continue
        for pat in _OWN_INTF_PATTERNS:
            for ip in pat.findall(line):
                try:
                    ipaddress.IPv4Address(ip)
                    found.add(ip)
                except ValueError:
                    continue
    return found


def _extract_neighbor_ips(cli_lines: list[str]) -> set[str]:
    """Pull **peer** IPs out of ``neighbor <IP>`` lines.  The captured
    address belongs to the *other* end of the BGP session (not the
    device whose CLI we are scanning).  Used as a fallback when the
    change CLI doesn't include interface assignments — common in
    real-world specs where interface IPs are baseline config and the
    change only adds BGP.
    """
    found: set[str] = set()
    for line in cli_lines:
        if not isinstance(line, str):
            continue
        for ip in _NEIGHBOR_IP_PATTERN.findall(line):
            try:
                ipaddress.IPv4Address(ip)
                found.add(ip)
            except ValueError:
                continue
    return found


def build_prod_to_lab_ip_map(
    tcf: Any,  # CabTcf — typed loosely to avoid circular import
    r89_args: dict[str, Any],
) -> dict[str, str]:
    """Build a flat ``prod_ip → lab_ip`` map for translating
    ``expected_pattern``.

    For each device:
      * Scan its ``implementation[*].cli`` lines for IPv4 literals.
      * Map every found IP to that device's **lab** host in
        ``r89_args["lab_subnet"]``.
      * **Skip** the device's ``prod_loopback`` — R89 reuses the prod
        loopback verbatim as ``system0``, so loopback IPs need no
        translation.

    The returned map is flat (one prod_ip → one lab_ip). When the same
    prod IP appears under two devices' CLI (rare), last writer wins;
    in real specs prod link IPs are unique per device.
    """
    nodes: list[str] = r89_args.get("nodes", [])
    lab_subnet = r89_args.get("lab_subnet", "172.16.99.0/30")
    lab_ips = _lab_ips_from_subnet(lab_subnet, len(nodes))
    if len(lab_ips) < len(nodes):
        return {}
    lab_ip_by_node = dict(zip(nodes, lab_ips, strict=True))

    loopbacks: dict[str, str] = {}
    for d in tcf.devices:
        if getattr(d, "prod_loopback", None):
            loopbacks[d.name] = d.prod_loopback

    impl_by_device: dict[str, list[str]] = {}
    for blk in tcf.implementation:
        impl_by_device.setdefault(blk.device, []).extend(blk.cli or [])

    ip_map: dict[str, str] = {}

    # Pass 1 — own-interface IPs from each device's own CLI.
    for name in nodes:
        prod_ips = _extract_own_interface_ips(impl_by_device.get(name, []))
        prod_ips.discard(loopbacks.get(name, ""))
        for prod_ip in prod_ips:
            ip_map[prod_ip] = lab_ip_by_node[name]

    # Pass 2 — for IPs that pass 1 missed (real specs often baseline
    # interface config separately and only add BGP in the change),
    # fall back to ``neighbor <IP>`` parsing: an IP referenced as a
    # neighbor in device A's CLI belongs to **another** device B.
    # Unambiguous when there is exactly one "other" device.  For
    # ebgp_direct (the only currently-supported intent) that's always
    # the case; for ≥3-device intents add explicit ``peer-as`` ↔
    # device-by-asn matching when those land.
    if len(nodes) == 2:
        a, b = nodes[0], nodes[1]
        peer_lab_ip = {a: lab_ip_by_node[b], b: lab_ip_by_node[a]}
        for name in nodes:
            for ip in _extract_neighbor_ips(impl_by_device.get(name, [])):
                if ip in ip_map:
                    continue  # already mapped from pass 1
                if ip == loopbacks.get(a) or ip == loopbacks.get(b):
                    continue  # loopback, skip
                ip_map[ip] = peer_lab_ip[name]

    return ip_map


# ── Pattern translation ──────────────────────────────────────────────────


def translate_pattern(pattern: str, ip_map: dict[str, str]) -> tuple[str, bool]:
    """Replace prod IPs in ``pattern`` with their lab counterparts.

    Handles the ``re:<regex>`` prefix transparently — strips it, runs
    substitution on the body (replacing both bare ``a.b.c.d`` and
    regex-escaped ``a\\.b\\.c\\.d``), re-prefixes.

    Returns ``(translated, was_translated)``.
    """
    if not pattern or not ip_map:
        return pattern, False
    has_re_prefix = pattern.startswith("re:")
    body = pattern[3:] if has_re_prefix else pattern
    changed = False
    for prod_ip, lab_ip in ip_map.items():
        if prod_ip in body:
            body = body.replace(prod_ip, lab_ip)
            changed = True
        # Regex-escaped form (dots backslash-escaped)
        prod_escaped = prod_ip.replace(".", r"\.")
        lab_escaped = lab_ip.replace(".", r"\.")
        if prod_escaped in body:
            body = body.replace(prod_escaped, lab_escaped)
            changed = True
    out = ("re:" + body) if has_re_prefix else body
    return out, changed


# ── Composite per-check translator ───────────────────────────────────────


def translate_post_check(
    post_check_dict: dict[str, Any],
    ip_map: dict[str, str],
) -> dict[str, Any]:
    """Return a translated copy of a single post_check spec.

    The returned dict adds:
      * ``command_translated`` (str) — what the lab actually exec's
      * ``expected_pattern_translated`` (str) — what the lab matches
      * ``translation_notes`` (list[str]) — audit trail for reviewers

    Original ``command`` and ``expected_pattern`` are preserved
    unchanged so reviewers see both the spec's contract and the
    translated lab form.
    """
    cmd_in = post_check_dict.get("command", "")
    pat_in = post_check_dict.get("expected_pattern", "")

    cmd_out, cmd_xlated = translate_command_prod_to_srl(cmd_in)
    pat_out, pat_xlated = translate_pattern(pat_in, ip_map)

    notes: list[str] = []
    if cmd_xlated:
        notes.append(f"command: {cmd_in!r} → {cmd_out!r}")
    if pat_xlated:
        notes.append(f"pattern: {pat_in!r} → {pat_out!r}")
    if not notes:
        notes.append("verbatim (no translation applied)")

    out = dict(post_check_dict)
    out["command_translated"] = cmd_out
    out["expected_pattern_translated"] = pat_out
    out["translation_notes"] = notes
    return out
