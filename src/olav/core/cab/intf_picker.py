"""Free-interface picker for CAB prod CLI rendering (ARCH-32).

Previously ``tcf_writer._render_ebgp_direct`` hardcoded ``GigabitEthernet0/1``
/ ``ge-0/0/1`` for the new eBGP link. In real prod, the lowest-numbered
interface is almost always already in use — pushing the change overwrites
that link's IP and breaks the existing peering.

This module reads ``netops.topology_links`` to discover which interfaces
are already in use on each device, then picks the lowest-numbered FREE
interface following the platform's naming convention.

Public:
    * ``pick_free_interfaces(device_names, platforms_by_name)`` — bulk
      per-device picker. Returns ``dict[device, intf]``. Raises on
      unknown platform; returns ``None`` for the device when topology
      data is missing entirely.

When the DB has no topology data at all (e.g. fresh deployment, no
collect run yet), returns ``None`` per device — caller decides whether
to fail loud or fall back. ``tcf_writer`` falls back with a warning
so existing tests + bootstrapping flows keep working.
"""
from __future__ import annotations

import re
from typing import Iterable

# Platform → (regex matching its interface naming, name template, max N)
# Templates use {n} for the slot index. Cisco IOS uses module/port pairs
# (Gi0/N) — we only ever pick port within module 0 to keep behavior
# predictable; for chassis with multiple modules sim should pass an
# explicit override.
# Cisco IOS unifies the slot/port for any common interface family on
# module 0 (Gi0/N, Et0/N, Fa0/N) — IOL boxes use Ethernet0/N,
# router platforms use GigabitEthernet0/N, but the slot/port number
# space is the same. We match ANY recognised family so that a port
# occupied as Et0/0 isn't picked as Gi0/0 (real-data bug surfaced on
# demo7 — IOL Ethernet0/0 occupied, picker returned Gi0/1 collision).
# When picking, follow the convention dominant on the device's
# occupied set (fall back to GigabitEthernet0/N when no precedent).
_CISCO_IOS_RE = re.compile(
    r"^(?:Gi|GigabitEthernet|Et|Ethernet|Fa|FastEthernet)0/(\d+)$",
    re.I,
)
_CISCO_IOS_FAMILY_RE = re.compile(
    r"^(Gi|GigabitEthernet|Et|Ethernet|Fa|FastEthernet)0/\d+$",
    re.I,
)
_CISCO_IOS_FAMILY_NORMALISED = {
    "gi": "GigabitEthernet",
    "gigabitethernet": "GigabitEthernet",
    "et": "Ethernet",
    "ethernet": "Ethernet",
    "fa": "FastEthernet",
    "fastethernet": "FastEthernet",
}

_PLATFORM_TEMPLATES = {
    "cisco_ios":     {"re": _CISCO_IOS_RE, "tmpl": "GigabitEthernet0/{n}", "max_n": 48,
                      "family_aware": True},
    "cisco_iosxe":   {"re": _CISCO_IOS_RE, "tmpl": "GigabitEthernet0/{n}", "max_n": 48,
                      "family_aware": True},
    "cisco_nxos":    {"re": re.compile(r"^Ethernet1/(\d+)$",  re.I), "tmpl": "Ethernet1/{n}", "max_n": 48},
    "juniper_junos": {"re": re.compile(r"^ge-0/0/(\d+)$",     re.I), "tmpl": "ge-0/0/{n}",    "max_n": 48},
    "arista_eos":    {"re": re.compile(r"^Ethernet(\d+)$",    re.I), "tmpl": "Ethernet{n}",   "max_n": 48},
}


def _dominant_cisco_family(occupied: set[str]) -> str | None:
    """For a Cisco IOS device, pick the interface family already
    dominant on the occupied set (e.g., ``Ethernet`` on IOL boxes,
    ``GigabitEthernet`` on routers). Returns the canonical family
    name suitable for templating, or ``None`` if no occupied
    interface matches the family pattern."""
    counts: dict[str, int] = {}
    for intf in occupied:
        m = _CISCO_IOS_FAMILY_RE.match(intf)
        if m:
            family = _CISCO_IOS_FAMILY_NORMALISED.get(
                m.group(1).lower(), m.group(1)
            )
            counts[family] = counts.get(family, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _occupied_interfaces(device_names: Iterable[str]) -> dict[str, set[str]]:
    """Query ``netops.topology_links`` for occupied interfaces per device.

    Returns ``{device: {intf, intf, ...}}`` — empty set for devices with
    no rows. Returns ``{}`` (not raising) on any DB error so the caller
    can decide whether to bail or fall back.
    """
    names = list(device_names)
    if not names:
        return {}
    occupied: dict[str, set[str]] = {n: set() for n in names}
    try:
        import duckdb

        from olav.core.config import MAIN_DB_PATH

        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        try:
            placeholders = ",".join("?" for _ in names)
            rows = con.execute(
                f"SELECT source_device, source_interface, "
                f"       destination_device, destination_interface "
                f"FROM netops.topology_links "
                f"WHERE source_device IN ({placeholders}) "
                f"   OR destination_device IN ({placeholders})",
                names + names,
            ).fetchall()
        finally:
            con.close()

        for src_dev, src_intf, dst_dev, dst_intf in rows:
            if src_dev in occupied and src_intf:
                occupied[src_dev].add(src_intf)
            if dst_dev in occupied and dst_intf:
                occupied[dst_dev].add(dst_intf)
    except Exception:  # noqa: BLE001 — DB errors → empty, caller falls back
        return {}
    return occupied


def pick_free_interfaces(
    device_names: list[str],
    platforms_by_name: dict[str, str | None],
) -> dict[str, str | None]:
    """Pick the lowest-numbered free interface per device.

    Args:
        device_names: Hostnames to pick interfaces for.
        platforms_by_name: ``{hostname: platform_str_or_None}``.
            Platform string must match keys in ``_PLATFORM_TEMPLATES``;
            unknown platforms return ``None`` for that device.

    Returns:
        ``{hostname: interface_name_or_None}``. ``None`` means either:
          - the platform was unknown, or
          - the topology DB had no rows at all (caller should fall
            back / warn), or
          - all candidate interfaces up to ``max_n`` are occupied.

    Note: returns ``None`` rather than raising so callers can layer
    their own diagnostic / warning logic. tcf_writer surfaces the
    fallback in its ``warnings`` field.
    """
    occupied = _occupied_interfaces(device_names)
    if not occupied:
        return {d: None for d in device_names}

    result: dict[str, str | None] = {}
    for d in device_names:
        plat = (platforms_by_name.get(d) or "").lower()
        spec = _PLATFORM_TEMPLATES.get(plat)
        if spec is None:
            result[d] = None
            continue
        used = occupied.get(d, set())
        # Extract used port numbers matching this platform's pattern
        used_n: set[int] = set()
        for intf in used:
            m = spec["re"].match(intf)
            if m:
                try:
                    used_n.add(int(m.group(1)))
                except ValueError:
                    pass
        # Choose template — for Cisco IOS, follow the dominant interface
        # family on the device (IOL boxes use Ethernet0/N; routers use
        # GigabitEthernet0/N). Prevents picking Gi0/2 when Et0/0 + Et0/1
        # are occupied (real-data demo7 collision).
        tmpl = spec["tmpl"]
        if spec.get("family_aware"):
            dominant = _dominant_cisco_family(used)
            if dominant is not None:
                tmpl = dominant + "0/{n}"
        # Pick lowest n in [1, max_n] not in used_n
        chosen: str | None = None
        for n in range(1, spec["max_n"] + 1):
            if n not in used_n:
                chosen = tmpl.format(n=n)
                break
        result[d] = chosen
    return result


__all__ = ["pick_free_interfaces"]
