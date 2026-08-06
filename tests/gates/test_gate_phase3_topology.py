"""Phase 3 gate: discovered topology is well-formed.

Rewritten 2026-08-06, for two reasons the previous version could not survive.

It hardcoded one lab — `LAB_DEVICES = {"R1"…"SW2"}` and a `KNOWN_LINKS` table of
specific adjacencies — so it asserted facts true of a single machine on a single
day. And it queried `v_l2_topology_summary`, `v_topo_links_clean` and
`v_device_neighbors_summary`, none of which exist on a production install: a
real machine's netops schema holds eleven views and all of them are `v_*_auto`.
No commit in the repo's history ever created the others, so these tests could
not have passed even with a full lab attached — they were written against
hand-made recipe views on a developer's box.

What survives is the part that was always about the product: the invariants a
discovered topology must satisfy regardless of which devices are in it. Where a
view is needed, it is `v_l2_links_auto`, which `finalise_ingest` really does
build — so the assertion lands on shipped SQL.
"""

from __future__ import annotations

import pytest

# The protocols the collector is allowed to record. A value outside this set
# means a parser invented one, which downstream taxonomy logic will mishandle.
ALLOWED_PROTOCOLS = {"lldp", "cdp"}
ALLOWED_LINK_TYPES = {"l2", "l3", "unknown"}


class TestTheLinkTableIsWellFormed:
    def test_topology_links_exists_and_has_rows(self, con):
        n = con.execute("SELECT COUNT(*) FROM netops.topology_links").fetchone()[0]
        assert n > 0, "neighbour discovery produced no links"

    def test_no_link_points_at_itself(self, con):
        """A self-loop is always a parse error — a device does not neighbour
        itself — and it corrupts any degree or path computation downstream."""
        loops = con.execute("""
            SELECT source_device, source_interface, destination_interface
            FROM netops.topology_links
            WHERE source_device = destination_device
            ORDER BY 1, 2
        """).fetchall()
        assert not loops, f"self-loops in topology_links: {loops}"

    def test_both_endpoints_are_fully_specified(self, con):
        """A link missing an interface cannot be drawn or verified; it is a
        half-parsed row that looks like data."""
        incomplete = con.execute("""
            SELECT link_id FROM netops.topology_links
            WHERE source_device IS NULL OR destination_device IS NULL
               OR source_interface IS NULL OR destination_interface IS NULL
               OR TRIM(source_interface) = '' OR TRIM(destination_interface) = ''
            ORDER BY 1
        """).fetchall()
        assert not incomplete, f"links with missing endpoints: {incomplete}"

    def test_link_ids_are_unique_within_a_snapshot(self, con):
        """Duplicate ids make 'the' link ambiguous and silently double any
        count that groups by it."""
        dupes = con.execute("""
            SELECT link_id, snapshot_id, COUNT(*) AS n
            FROM netops.topology_links
            GROUP BY link_id, snapshot_id
            HAVING n > 1
            ORDER BY 1
        """).fetchall()
        assert not dupes, f"duplicate link_id within a snapshot: {dupes}"


class TestControlledVocabularies:
    def test_discovery_protocol_values_are_controlled(self, con):
        found = {r[0] for r in con.execute(
            "SELECT DISTINCT discovery_protocol FROM netops.topology_links"
        ).fetchall()}
        unexpected = found - ALLOWED_PROTOCOLS
        assert not unexpected, (
            f"unrecognised discovery protocols: {sorted(unexpected)} — a parser "
            f"is emitting a value the taxonomy does not handle"
        )
        assert found, "no protocol recorded on any link"

    def test_link_type_values_are_controlled(self, con):
        found = {r[0] for r in con.execute(
            "SELECT DISTINCT link_type FROM netops.topology_links WHERE link_type IS NOT NULL"
        ).fetchall()}
        unexpected = found - ALLOWED_LINK_TYPES
        assert not unexpected, f"unrecognised link types: {sorted(unexpected)}"

    def test_l2_discovery_protocols_produce_l2_links(self, con):
        """The taxonomy rule that actually matters: LLDP and CDP are layer-2
        discovery, so their links must not be recorded as layer 3."""
        wrong = con.execute("""
            SELECT link_id, discovery_protocol, link_type
            FROM netops.topology_links
            WHERE discovery_protocol IN ('lldp', 'cdp') AND link_type = 'l3'
            ORDER BY 1
        """).fetchall()
        assert not wrong, f"L2 discovery recorded as an L3 link: {wrong}"


class TestSnapshotSemantics:
    def test_every_link_carries_a_snapshot(self, con):
        n = con.execute(
            "SELECT COUNT(*) FROM netops.topology_links WHERE snapshot_id IS NULL"
        ).fetchone()[0]
        assert n == 0, f"{n} links have no snapshot_id — they belong to no point in time"

    def test_the_latest_snapshot_has_links(self, con):
        """Every topology query filters to the newest snapshot; if discovery
        wrote only to an older one the map silently empties."""
        n = con.execute("""
            SELECT COUNT(*) FROM netops.topology_links
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM netops.topology_links)
        """).fetchone()[0]
        assert n > 0, "the newest snapshot contains no links"


class TestTheProductsOwnView:
    """`v_l2_links_auto` is built by `finalise_ingest` — the same call
    `/netops_init` and `take_snapshot` make. These assert on shipped SQL."""

    def test_the_view_exists(self, con):
        views = {r[0] for r in con.execute(
            "SELECT view_name FROM duckdb_views() WHERE schema_name='netops'"
        ).fetchall()}
        assert "v_l2_links_auto" in views, (
            f"finalise_ingest did not build v_l2_links_auto; it has {sorted(views)}"
        )

    def test_the_view_exposes_every_link(self, con):
        """It is documented as a pure column-rename projection, so dropping
        rows would mean a filter crept into it."""
        base = con.execute("SELECT COUNT(*) FROM netops.topology_links").fetchone()[0]
        view = con.execute("SELECT COUNT(*) FROM netops.v_l2_links_auto").fetchone()[0]
        assert view == base, (
            f"v_l2_links_auto exposes {view} of {base} links — the projection "
            f"is filtering rows it should not"
        )

    def test_the_view_carries_a_snapshot_column(self, con):
        """Consumers filter it to the latest snapshot; without the column that
        filter fails at query time rather than here."""
        cols = {r[1] for r in con.execute("PRAGMA table_info('netops.v_l2_links_auto')").fetchall()}
        assert "snapshot_id" in cols, f"v_l2_links_auto columns: {sorted(cols)}"


class TestTheFixtureIsNotVacuous:
    """The invariants above are all "no bad rows", which an empty table
    satisfies. These pin that the fixture presents something to check —
    including the awkward cases the invariants exist for."""

    def test_both_discovery_protocols_are_represented(self, con):
        found = {r[0] for r in con.execute(
            "SELECT DISTINCT discovery_protocol FROM netops.topology_links"
        ).fetchall()}
        assert found >= {"lldp", "cdp"}, (
            f"fixture no longer exercises both protocols (has {sorted(found)}), "
            f"so the vocabulary gates cannot fail"
        )

    def test_more_than_one_snapshot_exists(self, con):
        n = con.execute(
            "SELECT COUNT(DISTINCT snapshot_id) FROM netops.topology_links"
        ).fetchone()[0]
        assert n >= 2, "snapshot gates need at least two snapshots to mean anything"
