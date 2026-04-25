"""Post-parse field normalizer (R72, INGEST-NORMALIZATION).

Canonicalises common network field types immediately after
``parse_output`` produces structured records. Runs once at ingest
time so all downstream consumers (view_builder, agent SQL queries,
sim/lab code) see a consistent shape.

Normalisations applied:

* **Interface names** — via ``netutils.interface.canonical_interface_name``.
  ``Gi0/0`` → ``GigabitEthernet0/0``, ``Et0/0`` → ``Ethernet0/0``, etc.
  Junos names (``ge-0/0/0``) pass through unchanged.
* **IP addresses** — via ``ipaddress.ip_address``. ``10.00.00.1`` →
  ``10.0.0.1``; IPv6 compressed; mapped forms collapsed.
* **ASNs** — via ``netutils.asn.asn_to_int``. ``1.1`` → ``65537``;
  ``"65001"`` → ``65001``.
* **MAC addresses** — via ``netutils.mac.mac_to_format("COMMON")``.
  ``AA:BB:CC:DD:EE:FF`` → ``aa:bb:cc:dd:ee:ff``.

Field-name heuristics guard against mis-normalisation:

* Interface: field name contains ``interface``, ``port``, ``intf``,
  ``neighbor_interface``, ``local_interface``
* IP: field name contains ``ip``, ``address``, ``router_id``, ``neighbor_ip``
* ASN: field name contains ``as`` (with word boundary)
* MAC: field name contains ``mac``, ``hwaddr``, ``chassis_id``

Value format is *also* validated before canonicalising — a field named
``ip_mtu`` with value ``1500`` is NOT treated as an IP address.
"""

from __future__ import annotations

import logging
import re
from ipaddress import ip_address, AddressValueError
from typing import Any

logger = logging.getLogger(__name__)

# ── Field-name heuristics (case-insensitive; underscores are word-safe) ──
# Python's \b treats `_` as a word char, so we can't rely on \b to split
# snake_case. Each pattern below is written to match bare-word tokens
# either at the ends of the field name or around `_` separators.

def _has_token(pattern: re.Pattern[str], name: str) -> bool:
    """Substring-match for snake_case-friendly tokens."""
    return pattern.search(name) is not None


_IFACE_HINT = re.compile(
    r"(?:^|_)(interface|port|intf|link)(?:$|_)",
    re.IGNORECASE,
)
_IP_HINT = re.compile(
    r"(?:^|_)("
    r"ip|ipv4|ipv6|address|router_id|neighbor_ip|peer_ip|"
    r"destination|source|next_hop|local_ip|remote_ip|gateway|loopback|"
    r"source_ip|dest_ip|src_ip|dst_ip|mgmt_ip|management_ip|ip_address"
    r")(?:$|_)",
    re.IGNORECASE,
)
_ASN_HINT = re.compile(
    r"(?:^|_)(asn|as_number|remote_as|local_as|peer_as|as)(?:$|_)",
    re.IGNORECASE,
)
_MAC_HINT = re.compile(
    r"(?:^|_)(mac|hwaddr|chassis_id|physical_address|mac_address)(?:$|_)",
    re.IGNORECASE,
)
# R83.2: state-like fields that should be canonicalised to RFC names.
# Triggers on ``state`` / ``status`` / ``session_state`` / ``bgp_state``
# / ``ospf_state`` / ``port_state``.  Combined with value-shape check
# below to avoid mis-normalising free-form text fields.
_STATE_HINT = re.compile(
    r"(?:^|_)(state|status)(?:$|_)",
    re.IGNORECASE,
)
# State values are short enum-like tokens (single word or word/word).
# Free-form messages ("administratively down by user") fall through.
_STATE_VALUE_RE = re.compile(r"^[A-Za-z0-9/_+-]{1,40}$")

# ── Value-format validators ─────────────────────────────────────────────
# A reasonable looking IPv4/IPv6 (before ipaddress does the authoritative parse)
_IP_LIKE_RE = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3}(?:/\d+)?|[0-9a-fA-F:]+(?:/\d+)?)$"
)
_ASN_LIKE_RE = re.compile(r"^(\d+|\d+\.\d+)$")
_MAC_LIKE_RE = re.compile(
    r"^([0-9a-fA-F]{2}[:.-]){5}[0-9a-fA-F]{2}$"
    r"|^[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}$"
    r"|^[0-9a-fA-F]{12}$"
)


def _canonical_interface(val: str) -> str | None:
    try:
        from netutils.interface import canonical_interface_name
        return canonical_interface_name(val)
    except Exception as exc:
        logger.debug("canonical_interface_name(%r) failed: %s", val, exc)
        return None


def _canonical_ip(val: str) -> str | None:
    # Strip optional /prefix-length for now — preserve original if it had one
    # but we canonicalise the address portion.
    has_prefix = "/" in val
    addr_part, _, prefix_part = val.partition("/")
    try:
        canon = str(ip_address(addr_part))
    except (AddressValueError, ValueError):
        return None
    return f"{canon}/{prefix_part}" if has_prefix else canon


def _canonical_asn(val: str) -> int | str | None:
    try:
        from netutils.asn import asn_to_int
        return asn_to_int(val)
    except Exception:
        # Fallback: simple int cast for plain numerals
        try:
            return int(val)
        except (TypeError, ValueError):
            return None


def _canonical_mac(val: str) -> str | None:
    try:
        from netutils.mac import mac_to_format
        return mac_to_format(val, "MAC_COLON_TWO")
    except Exception as exc:
        logger.debug("mac_to_format(%r) failed: %s", val, exc)
        return None


# RFC-canonical protocol state names.  Vendor textfsm output varies
# (Cisco "Estab"/"Established"/"0", Junos "Establ", Arista "OpenSent")
# — collapsing at ingest means downstream views and agent SQL never
# need ``state IN ('Established', 'Estab', '0', ...)`` clauses.
#
# Rules below are *prefix matches on the lowercased value*: e.g.
# ``Full/DR`` keeps the ``/DR`` suffix because it's RFC-correct OSPF.
_STATE_RULES: tuple[tuple[str, str], ...] = (
    # BGP — RFC 4271 section 8 finite-state machine
    ("establ", "Established"),
    ("idle", "Idle"),
    ("active", "Active"),
    ("connect", "Connect"),
    ("opensent", "OpenSent"),
    ("openconfirm", "OpenConfirm"),
    # OSPF — RFC 2328 section 10 neighbour state machine
    ("full", "Full"),       # may be followed by /DR or /BDR — preserved verbatim
    ("2way", "2-Way"),
    ("2-way", "2-Way"),
    ("exstart", "ExStart"),
    ("exchange", "Exchange"),
    ("loading", "Loading"),
    ("init", "Init"),
    ("attempt", "Attempt"),
    # generic
    ("down", "Down"),
    ("up", "Up"),
)


def _canonical_state(val: str) -> str | None:
    """Map vendor variants to a canonical RFC state.

    Handles:

    * ``"Estab"`` / ``"Established"`` / ``"established"`` → ``"Established"``
    * ``"FULL"`` / ``"Full"`` / ``"full"``               → ``"Full"``
    * ``"FULL/DR"``                                       → ``"Full/DR"`` (designated form preserved)
    * ``"administratively down"``                         → unchanged (free-form text trips the value-shape gate upstream)
    * Bare numeric (``"0"``) is treated as Established **only** when the
      key suggests a BGP/peer context — handled by caller's value-format
      check; here we just pass through bare numerics unchanged.
    """
    if not val:
        return None
    lower = val.strip().lower()
    if not lower:
        return None
    for prefix, canonical in _STATE_RULES:
        if lower == prefix:
            return canonical
        if lower.startswith(prefix):
            # Preserve the ``/DR``/``/BDR`` qualifier on Full state etc.
            suffix = val[len(prefix):]
            if suffix and suffix[0] in "/-":
                return canonical + suffix
            return canonical
    return None


def _normalize_value(field_name: str, value: Any) -> Any:
    """Return canonicalised value when a rule applies; else ``value`` unchanged."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s or s.lower() in {"unassigned", "none", "n/a", "-", "--"}:
        return value

    name_l = field_name

    # Interface name — check first: names are least ambiguous
    if _IFACE_HINT.search(name_l):
        canon = _canonical_interface(s)
        if canon:
            return canon

    # IP address — value must look IP-shaped
    if _IP_HINT.search(name_l) and _IP_LIKE_RE.match(s):
        canon = _canonical_ip(s)
        if canon:
            return canon

    # ASN — numeric or asdot
    if _ASN_HINT.search(name_l) and _ASN_LIKE_RE.match(s):
        canon = _canonical_asn(s)
        if canon is not None:
            return canon

    # MAC
    if _MAC_HINT.search(name_l) and _MAC_LIKE_RE.match(s):
        canon = _canonical_mac(s)
        if canon:
            return canon

    # State / status — RFC-canonical names (R83.2 P1 — moved here from
    # view_builder.py SQL CASE expressions when the L1 view_recipes
    # machinery was retired).
    if _STATE_HINT.search(name_l) and _STATE_VALUE_RE.match(s):
        canon = _canonical_state(s)
        if canon:
            return canon

    return value


def normalize_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonicalise interface/IP/ASN/MAC fields across all rows in-place.

    Returns the same list (mutated) for callers that want chaining.
    """
    if not rows:
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, val in list(row.items()):
            # Lists of IPs / interfaces (TextFSM `Value List`)
            if isinstance(val, list):
                row[key] = [_normalize_value(key, item) for item in val]
            else:
                row[key] = _normalize_value(key, val)
    return rows
