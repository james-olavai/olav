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
_PLATFORM_TEMPLATES = {
    "cisco_ios":     {"re": re.compile(r"^(?:Gi|GigabitEthernet)0/(\d+)$",  re.I),  "tmpl": "GigabitEthernet0/{n}",  "max_n": 48},
    "cisco_iosxe":   {"re": re.compile(r"^(?:Gi|GigabitEthernet)0/(\d+)$",  re.I),  "tmpl": "GigabitEthernet0/{n}",  "max_n": 48},
    "cisco_nxos":    {"re": re.compile(r"^Ethernet1/(\d+)$",                re.I),  "tmpl": "Ethernet1/{n}",         "max_n": 48},
    "juniper_junos": {"re": re.compile(r"^ge-0/0/(\d+)$",                   re.I),  "tmpl": "ge-0/0/{n}",            "max_n": 48},
    "arista_eos":    {"re": re.compile(r"^Ethernet(\d+)$",                  re.I),  "tmpl": "Ethernet{n}",           "max_n": 48},
}


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
        # Pick lowest n in [1, max_n] not in used_n
        chosen: str | None = None
        for n in range(1, spec["max_n"] + 1):
            if n not in used_n:
                chosen = spec["tmpl"].format(n=n)
                break
        result[d] = chosen
    return result


__all__ = ["pick_free_interfaces"]
