"""Governance — every audit profile's SQL must reference views/tables
that exist in the canonical netops catalog.

Pre-2026-05-15: profile authors copied stale alias names like
``v_bgp_neighbors_auto`` (the canonical view is
``v_show_ip_bgp_neighbors_auto``).  At runtime DuckDB raises
``CatalogException`` and the auditor's whole pipeline crashes.

This test extracts every ``netops.<X>`` reference from each profile's
job SQL and asserts ``X`` is in the catalog snapshot below.  When you
add a new view, append it to :data:`KNOWN_NETOPS_OBJECTS`.

For non-deprecated profiles we also do a *live* execute against a
sample DB if one exists at ``$OLAV_DEMO_DIR/.olav/databases/main.duckdb``;
this catches column drift on top of name drift.  Live execution is
opt-in via env var so CI without a populated DB still passes the
name-level check.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_GLOBS = (
    "src/olav/data/workspace/audit/profiles/*.md",
    "olav-netops/.olav/workspace/audit/profiles/*.md",
)

# Canonical view + table set (2026-05-15 snapshot).
# Append when a new netops view is added to `/netops_init` view-build.
# Source of truth: query
#   SELECT table_name FROM information_schema.tables WHERE table_schema='netops'
# on a freshly-collected demo DB.
KNOWN_NETOPS_OBJECTS = frozenset({
    # tables
    "devices",
    "topology_links",
    "parsed_outputs",
    "raw_output_store",
    "commands",
    "introspection_cache",
    "oc_outputs",
    "value_profile",
    # canonical v_show_*_auto views generated from collected commands
    "v_show_access_list_auto",
    "v_show_arp_auto",
    "v_show_arp_no_resolve_auto",
    "v_show_bgp_summary_auto",
    "v_show_cdp_neighbors_auto",
    "v_show_cdp_neighbors_detail_auto",
    "v_show_chassis_firmware_auto",
    "v_show_chassis_hardware_auto",
    "v_show_clock_auto",
    "v_show_cts_pacs_auto",
    "v_show_file_systems_auto",
    "v_show_hosts_summary_auto",
    "v_show_interfaces_auto",
    "v_show_interfaces_description_auto",
    "v_show_interfaces_status_auto",
    "v_show_interfaces_switchport_auto",
    "v_show_interfaces_terse_auto",
    "v_show_ipv6_interface_brief_auto",
    "v_show_ip_access_lists_auto",
    "v_show_ip_arp_auto",
    "v_show_ip_bgp_auto",
    "v_show_ip_bgp_neighbors_auto",
    "v_show_ip_bgp_summary_auto",
    "v_show_ip_cef_auto",
    "v_show_ip_cef_detail_auto",
    "v_show_ip_http_server_status_auto",
    "v_show_ip_interface_auto",
    "v_show_ip_interface_brief_auto",
    "v_show_ip_ospf_database_auto",
    "v_show_ip_ospf_database_network_auto",
    "v_show_ip_ospf_database_router_auto",
    "v_show_ip_ospf_interface_brief_auto",
    "v_show_ip_ospf_neighbor_auto",
    "v_show_ip_route_auto",
    "v_show_ip_route_summary_auto",
    "v_show_license_status_auto",
    "v_show_lldp_neighbors_auto",
    "v_show_lldp_neighbors_detail_auto",
    "v_show_ospf_neighbor_auto",
    "v_show_route_map_auto",
    "v_show_route_summary_auto",
    "v_show_running_config_partition_access_list_auto",
    "v_show_spanning_tree_auto",
    "v_show_spanning_tree_root_auto",
    "v_show_system_configuration_database_usage_auto",
    "v_show_system_uptime_auto",
    "v_show_users_auto",
    "v_show_version_auto",
    "v_show_vlans_auto",
    "v_show_vlan_auto",
    "v_show_vtp_status_auto",
    "v_snapshots_auto",
    "v_l2_links_auto",
    "v_dir_auto",
})


def _discover_profiles() -> list[Path]:
    paths: list[Path] = []
    for pattern in PROFILE_GLOBS:
        paths.extend(REPO_ROOT.glob(pattern))
    return sorted(paths)


def _frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        pytest.fail(f"{path}: invalid YAML frontmatter — {exc}")


_REF_PAT = re.compile(r"\bnetops\.([a-zA-Z_]\w*)", re.IGNORECASE)


def _profile_refs(path: Path) -> set[str]:
    """Extract every ``netops.<obj>`` reference from the profile's job SQL."""
    fm = _frontmatter(path) or {}
    refs: set[str] = set()
    for job in fm.get("jobs", []) or []:
        sql = job.get("query") or ""
        refs.update(_REF_PAT.findall(sql))
    return refs


def _is_deprecated(path: Path) -> bool:
    fm = _frontmatter(path) or {}
    return bool(fm.get("deprecated"))


_ACTIVE_PROFILES = [p for p in _discover_profiles() if not _is_deprecated(p)]


@pytest.mark.parametrize("profile", _ACTIVE_PROFILES, ids=str)
def test_profile_sql_refs_are_in_catalog(profile: Path) -> None:
    """No active profile may reference a netops object not in the catalog."""
    refs = _profile_refs(profile)
    unknown = sorted(refs - KNOWN_NETOPS_OBJECTS)
    assert not unknown, (
        f"{profile.name}: SQL references unknown netops object(s) {unknown}.  "
        f"Either fix the SQL to use a canonical view name (e.g. "
        f"`v_show_ip_bgp_neighbors_auto`), mark the profile "
        f"`deprecated: true`, or — if a new view was actually added — "
        f"append to KNOWN_NETOPS_OBJECTS in this test."
    )


_DEMO_DB = (
    Path(os.environ.get("OLAV_DEMO_DIR", str(Path.home() / "olav-demo-2026-05-15")))
    / ".olav/databases/main.duckdb"
)


@pytest.mark.skipif(
    not _DEMO_DB.exists(),
    reason=f"No demo DB at {_DEMO_DB} — set OLAV_DEMO_DIR to enable live SQL check",
)
@pytest.mark.parametrize("profile", _ACTIVE_PROFILES, ids=str)
def test_profile_sql_executes_against_live_db(profile: Path) -> None:
    """Live-execute each job SQL to catch column drift on top of name drift."""
    import duckdb

    fm = _frontmatter(profile) or {}
    with duckdb.connect(str(_DEMO_DB), read_only=True) as conn:
        for job in fm.get("jobs", []) or []:
            sql = job.get("query") or ""
            if not sql:
                continue
            try:
                conn.execute(sql).fetchall()
            except duckdb.Error as exc:
                pytest.fail(
                    f"{profile.name} job {job.get('name')!r}: SQL error — "
                    f"{type(exc).__name__}: {exc}"
                )
