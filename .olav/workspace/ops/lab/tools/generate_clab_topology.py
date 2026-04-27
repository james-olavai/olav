"""generate_clab_topology — R88-A deterministic data-transformation tool.

Reads ``netops.v_l2_links_auto`` and emits a complete ContainerLab
topology YAML for SR Linux (SRL) digital-twin labs — including the
``links:`` section that small models routinely forget when
hand-synthesising the YAML at tool-call time.

The agent supplies a list of node names + a lab name; the tool
queries the L2 view, dedupes bidirectional links, normalises prod
interface names to SRL kernel shorthand (``e1-N``), and returns a
deploy-ready YAML string.

Companion to ``deploy_lab`` — call this first to get
``yaml_content``, then pass the result straight in.

See ``dev_docs/64. R88_DETERMINISTIC_TRANSFORM_TOOLS.md``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


_DEFAULT_IMAGE = "ghcr.io/nokia/srlinux:24.10.1"


_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:GigabitEthernet|TenGigE|TenGigabitEthernet|FortyGigE|HundredGigE|Gi|Te|Fo|Hu)(\d+)/(\d+)/(\d+)/(\d+)$", re.I), "iosxr"),
    (re.compile(r"^(?:GigabitEthernet|TenGigE|TenGigabitEthernet|Gi|Te)(\d+)/(\d+)/(\d+)$", re.I), "ios_3"),
    (re.compile(r"^(?:GigabitEthernet|FastEthernet|Ethernet|Gi|Fa|Eth)(\d+)/(\d+)$", re.I), "ios_2"),
    (re.compile(r"^(?:ge|xe|et|fe|me)-(\d+)/(\d+)/(\d+)$", re.I), "junos"),
    (re.compile(r"^ethernet-(\d+)/(\d+)$", re.I), "srl_slash"),
    (re.compile(r"^e(\d+)-(\d+)$", re.I), "srl_dash"),
]


def _normalize_iface_name(raw: str) -> tuple[str | None, str | None]:
    """Map a prod interface name to SRL kernel shorthand ``e1-N``.

    Returns ``(shorthand, warning)``. Either may be ``None``:
      - shorthand=None → unsupported pattern; warning explains why.
      - warning=None → clean conversion.

    Rule: take the LAST numeric component, add 1 (prod is usually
    0-indexed; CLAB SRL containers number ports from 1), prefix
    ``e1-``. SRL containers expose only a single line card, so
    the slot is always 1.
    """
    if not raw:
        return None, "empty interface name"

    # Strip subinterface suffix (e.g. ge-0/0/2.100 → ge-0/0/2)
    base = raw.split(".", 1)[0].strip()

    # Bundle / LAG: not representable in CLAB SRL labs
    if re.match(r"^(?:Bundle-Ether|Port-Channel|ae|ae-)", base, re.I):
        return None, f"bundle interface {raw!r} not supported in CLAB SRL labs"

    for pattern, kind in _PATTERNS:
        m = pattern.match(base)
        if not m:
            continue
        if kind == "srl_dash":
            # Already in CLAB shorthand — passthrough
            return f"e{m.group(1)}-{m.group(2)}", None
        if kind == "srl_slash":
            # SRL CLI → CLAB shorthand
            return f"e{m.group(1)}-{m.group(2)}", None
        # All other vendor patterns: take last numeric, add 1
        last = int(m.group(m.lastindex))
        return f"e1-{last + 1}", None

    return None, f"unrecognized interface pattern {raw!r}"


def _all_snapshots(con: Any) -> list[str]:
    """Return all snapshot_ids in the L2 view, newest first."""
    try:
        rows = con.execute(
            "SELECT DISTINCT snapshot_id FROM netops.v_l2_links_auto "
            "ORDER BY snapshot_id DESC"
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def _fetch_links(
    con: Any,
    nodes: list[str],
    snapshot_id: str,
) -> list[tuple[str, str, str, str]]:
    """Return rows of (src_dev, src_iface, dst_dev, dst_iface) constrained
    to links where BOTH endpoints are in ``nodes``.
    """
    if not nodes:
        return []
    placeholders = ",".join("?" for _ in nodes)
    rows = con.execute(
        f"SELECT source_device, source_interface, destination_device, "
        f"destination_interface FROM netops.v_l2_links_auto "
        f"WHERE snapshot_id = ? "
        f"  AND source_device IN ({placeholders}) "
        f"  AND destination_device IN ({placeholders}) "
        f"ORDER BY source_device, source_interface",
        [snapshot_id, *nodes, *nodes],
    ).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def _resolve_snapshot_with_links(
    con: Any,
    nodes: list[str],
    explicit: str | None,
) -> tuple[str | None, list[tuple[str, str, str, str]], list[str]]:
    """Pick a snapshot_id and return its rows.

    If ``explicit`` is provided, use it as-is (no fallback).
    Otherwise: try the newest snapshot first; if it has 0 matching
    rows, walk back through older snapshots until one yields rows.
    Returns ``(snapshot_id, rows, fallback_warnings)``.
    """
    warnings: list[str] = []
    if explicit:
        return explicit, _fetch_links(con, nodes, explicit), warnings

    snaps = _all_snapshots(con)
    if not snaps:
        return None, [], warnings
    # Try latest first
    latest = snaps[0]
    rows = _fetch_links(con, nodes, latest)
    if rows:
        return latest, rows, warnings
    # Fall back to older snapshots
    for older in snaps[1:]:
        rows = _fetch_links(con, nodes, older)
        if rows:
            warnings.append(
                f"latest snapshot {latest!r} has no links for {nodes}; "
                f"using older snapshot {older!r} (consider re-running netops_init)"
            )
            return older, rows, warnings
    # No snapshot has matching links
    warnings.append(
        f"no snapshot in netops.v_l2_links_auto contains links for {nodes}; "
        f"check device names match netops inventory"
    )
    return latest, [], warnings


def _dedupe_bidirectional(
    rows: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    """Collapse (A, ifA, B, ifB) and (B, ifB, A, ifA) to one row.

    Canonical form: (src_dev, src_iface, dst_dev, dst_iface) where
    src_dev <= dst_dev lexicographically.
    """
    seen: set[tuple[str, str, str, str]] = set()
    out: list[tuple[str, str, str, str]] = []
    for src_d, src_i, dst_d, dst_i in rows:
        if (src_d, src_i) <= (dst_d, dst_i):
            key = (src_d, src_i, dst_d, dst_i)
        else:
            key = (dst_d, dst_i, src_d, src_i)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _validate_iface(raw: str) -> str | None:
    """Return a warning if the prod interface name is unsupported in
    a CLAB SRL lab (bundle / empty / port-id-only / no alpha prefix);
    else None.

    Lab port assignment is sequential per node (e1-1, e1-2, ...) so
    we don't extract numbers from the prod name — we just need to
    know whether the prod port is a sensible physical interface.

    Rejects pure-numeric values like ``'512'`` that appear in
    LLDP-discovered topology when the remote system reports a port-id
    TLV instead of a port-name TLV.
    """
    if not raw:
        return "empty interface name"
    base = raw.split(".", 1)[0].strip()
    if re.match(r"^(?:Bundle-Ether|Port-Channel|ae|ae-)", base, re.I):
        return f"bundle interface {raw!r} not supported in CLAB SRL labs"
    if not re.search(r"[A-Za-z]", base):
        return (
            f"port-id-only value {raw!r} (no interface name); "
            f"likely an LLDP port-id TLV, not a port name"
        )
    if not re.search(r"\d", base):
        return f"non-numeric interface {raw!r}; cannot map to CLAB"
    return None


def _to_lab_name(prod_name: str) -> str:
    """Prod device names (e.g. ``R1``, ``SW2``, ``BorderRouter1``) become
    lab node names by lowercasing.

    ContainerLab is case-sensitive on container names, but the
    create_srl_links workaround calls ``docker inspect`` directly on
    the host, which fails when CLAB's internal naming differs from the
    yaml. The CAB Lab Substitution Table convention is also lowercase
    (see ``dev_docs/64``). Lowercasing here keeps the convention
    consistent end-to-end.
    """
    return prod_name.lower()


def _build_yaml(
    lab_name: str,
    nodes: list[str],
    image: str,
    links: list[tuple[str, str, str, str]],
    warnings: list[str],
    counters: dict[str, int] | None = None,
) -> str:
    """Hand-build the YAML so we control formatting (no PyYAML quirks).

    Node naming: prod → lab via ``_to_lab_name`` (lowercase). The agent
    must use the lab names (lowercase) for downstream calls to
    ``save_lab_config``, ``push_node_config``, and ``exec_on_node`` —
    the comment header makes the mapping visible.

    Lab port numbering: sequential per node, starting at e1-1, in the
    order links appear after dedup. This matches the CAB Lab
    Substitution Table convention (lab port 1 for the first link,
    independent of the prod port name).
    """
    parts: list[str] = []
    # Surface the prod→lab name mapping at the top of the body so the
    # agent can read off the lab names when constructing later calls.
    parts.append("# prod → lab node mapping:")
    for n in nodes:
        parts.append(f"#   {n} → {_to_lab_name(n)}")
    parts.append(f"name: {lab_name}")
    parts.append("topology:")
    parts.append("  nodes:")
    for n in nodes:
        lab_n = _to_lab_name(n)
        parts.append(f"    {lab_n}:")
        parts.append(f"      kind: nokia_srlinux")
        parts.append(f"      image: {image}")

    if links:
        parts.append("  links:")
        port_counter: dict[str, int] = {}
        for src_d, src_i, dst_d, dst_i in links:
            src_warn = _validate_iface(src_i)
            dst_warn = _validate_iface(dst_i)
            if src_warn:
                warnings.append(f"{src_d}:{src_i} — {src_warn}")
            if dst_warn:
                warnings.append(f"{dst_d}:{dst_i} — {dst_warn}")
            if src_warn or dst_warn:
                continue
            src_port = port_counter.get(src_d, 0) + 1
            dst_port = port_counter.get(dst_d, 0) + 1
            port_counter[src_d] = src_port
            port_counter[dst_d] = dst_port
            src_lab = _to_lab_name(src_d)
            dst_lab = _to_lab_name(dst_d)
            parts.append(
                f"    - endpoints: [{src_lab}:e1-{src_port}, {dst_lab}:e1-{dst_port}]"
            )
        if counters is not None:
            counters.update(port_counter)
    else:
        parts.append("  # NOTE: no links found in netops.v_l2_links_auto for these nodes")
        parts.append("  links: []")

    return "\n".join(parts) + "\n"


def _wrap_with_comments(
    yaml_content: str,
    snapshot_id: str | None,
    links_found: int,
    warnings: list[str],
) -> str:
    """Prepend YAML-comment metadata so warnings + snapshot are visible to
    the agent without forcing it to parse JSON. CLAB's parser ignores
    leading comments.
    """
    header: list[str] = []
    if snapshot_id:
        header.append(f"# snapshot_id: {snapshot_id}")
    header.append(f"# links_found: {links_found}")
    for w in warnings:
        header.append(f"# WARNING: {w}")
    if not header:
        return yaml_content
    return "\n".join(header) + "\n" + yaml_content


from langchain_core.tools import tool


@tool
def generate_clab_topology(
    nodes: list[str],
    lab_name: str,
    image: str = _DEFAULT_IMAGE,
    snapshot_id: str | None = None,
) -> str:
    """Generate a deploy-ready ContainerLab SRL topology YAML from netops L2 data.

    Reads ``netops.v_l2_links_auto`` for the requested nodes, dedupes
    bidirectional links, normalises prod interface names (Junos
    ``ge-0/0/2``, Cisco ``Ethernet0/0``, etc.) to SRL container
    shorthand (``e1-N``), and emits a YAML string with both ``nodes:``
    AND ``links:`` sections — feed the output straight to ``deploy_lab``.

    Use this BEFORE ``deploy_lab`` for any SRL digital-twin from the
    netops inventory. Do not hand-write the topology YAML.

    Args:
        nodes: Device names from netops inventory (e.g. ["R1", "R4"]).
            Both ends of each desired link must be in this list.
        lab_name: ContainerLab lab name (becomes ``name:`` in the YAML).
        image: SRL container image tag. Default is the pinned 24.10.1.
        snapshot_id: Specific topology snapshot to query. ``None`` = latest.

    Returns:
        Raw YAML string ready to pass straight to ``deploy_and_push_lab``
        (no JSON parsing required). Warnings and the snapshot used are
        emitted as ``# WARNING:`` / ``# snapshot_id:`` comments at the
        top — CLAB's YAML parser ignores them.

    Example:
        yaml_content = generate_clab_topology(nodes=["R1", "R4"], lab_name="cab_r1_r4_ebgp")
        deploy_and_push_lab(yaml_content=yaml_content, ...)
    """
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    if not nodes:
        return "# ERROR: nodes list is empty — must include at least 2 device names\n"
    if not lab_name:
        return "# ERROR: lab_name is required\n"

    warnings: list[str] = []

    try:
        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    except Exception as e:
        return f"# ERROR: could not open netops DB at {MAIN_DB_PATH}: {e}\n"

    try:
        snap, rows, fallback_warns = _resolve_snapshot_with_links(
            con, nodes, snapshot_id
        )
        warnings.extend(fallback_warns)
        if snap is None:
            warnings.append("no snapshots found in netops.v_l2_links_auto")
            yaml_content = _build_yaml(lab_name, nodes, image, [], warnings)
            return _wrap_with_comments(yaml_content, snap, 0, warnings)

        unique = _dedupe_bidirectional(rows)
        counters: dict[str, int] = {}
        yaml_content = _build_yaml(
            lab_name, nodes, image, unique, warnings, counters
        )
        # Count of links actually emitted in the YAML (post-validation).
        emitted = max(counters.values()) if counters else 0
        # If multiple nodes have different counters this won't be exact —
        # fall back to summing the per-node max counter / 2 for symmetric
        # topologies. For our typical 2-node case it's fine.
        emitted = sum(counters.values()) // 2 if counters else 0
        return _wrap_with_comments(yaml_content, snap, emitted, warnings)
    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(generate_clab_topology.invoke(args))
