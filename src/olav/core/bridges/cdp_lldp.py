"""CDP → openconfig-lldp bridge (OC-7).

Converts Cisco CDP TextFSM-parsed records into the ``LldpInterface``
Pydantic structure defined in :mod:`olav.core.models.openconfig`.

Each converted record carries ``_source: "cdp"`` so downstream consumers
can distinguish natively-discovered LLDP neighbors from CDP-bridged ones.
"""

from __future__ import annotations


def cdp_to_lldp(cdp_record: dict) -> dict:
    """Convert a single CDP TextFSM record to an openconfig-lldp dict.

    Parameters
    ----------
    cdp_record:
        A dictionary typically containing keys such as ``device_id``,
        ``local_interface``, ``port_id``, ``platform``, and ``ip_address``.
        Only ``device_id`` and ``local_interface`` are required.

    Returns
    -------
    dict
        An ``LldpInterface``-compatible dictionary with a ``_source``
        meta-tag set to ``"cdp"``.
    """
    state: dict[str, str | None] = {
        "system-name": cdp_record.get("device_id"),
    }

    # Optional fields — only set when present in source record
    port_id = cdp_record.get("port_id")
    if port_id is not None:
        state["port-id"] = port_id

    ip_address = cdp_record.get("ip_address")
    if ip_address is not None:
        state["management-address"] = ip_address

    platform = cdp_record.get("platform")
    if platform is not None:
        state["system-description"] = platform

    return {
        "name": cdp_record["local_interface"],
        "neighbors": [{"state": state}],
        "_source": "cdp",
    }


def cdp_batch_to_lldp(records: list[dict]) -> list[dict]:
    """Convert a batch of CDP records to openconfig-lldp dicts.

    Parameters
    ----------
    records:
        List of CDP TextFSM-parsed dictionaries.

    Returns
    -------
    list[dict]
        One ``LldpInterface``-compatible dict per input record.
    """
    return [cdp_to_lldp(r) for r in records]
