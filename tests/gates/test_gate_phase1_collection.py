"""Phase 1 gate: collected data is complete and internally consistent.

Rewritten 2026-08-06. The previous version asserted against one developer's
lab — `EXPECTED_DEVICES = {"R1", "R2", "R3", "R4", "SW1", "SW2"}` and a
hardcoded freshness date — and skipped entirely whenever `main.duckdb` was
empty, which in CI is always. It therefore ran zero times in CI and could not
have passed anywhere but on the machine it was written on: the demo dataset has
339 devices named `alpha-core-6807v…`, not R1.

The assertions here are invariants over whatever data is present, not equality
with a roster. "Every device in `devices` has parsed output" is true of a
4-device fixture, a 339-device import and a lab that has not been built yet;
"the devices are R1..SW2" was true of exactly one machine on exactly one day.

Data comes from `conftest.netops_db`, whose views are built by the product's
own `finalise_ingest` (see fixture_db).
"""

from __future__ import annotations

import pytest

MIN_COMMANDS_PER_DEVICE = 5


class TestEveryDeviceWasCollected:
    def test_every_device_has_parsed_output(self, con):
        """A device row with no collected output is a collection failure that
        looks like success — the inventory says the device is known."""
        orphans = con.execute("""
            SELECT d.hostname FROM netops.devices d
            WHERE NOT EXISTS (
                SELECT 1 FROM netops.parsed_outputs p
                WHERE p.device_name = d.hostname
            )
            ORDER BY 1
        """).fetchall()
        assert not orphans, (
            f"devices with no parsed_outputs: {[r[0] for r in orphans]}"
        )

    def test_no_output_references_an_unknown_device(self, con):
        """The other direction: output attributed to a device the inventory
        has never heard of means the two tables disagree about reality."""
        strays = con.execute("""
            SELECT DISTINCT p.device_name FROM netops.parsed_outputs p
            WHERE NOT EXISTS (
                SELECT 1 FROM netops.devices d WHERE d.hostname = p.device_name
            )
            ORDER BY 1
        """).fetchall()
        assert not strays, (
            f"parsed_outputs references devices absent from the inventory: "
            f"{[r[0] for r in strays]}"
        )

    def test_each_device_has_minimum_command_coverage(self, con):
        """One command per device is a connection test, not a collection."""
        thin = con.execute(f"""
            SELECT device_name, COUNT(DISTINCT command) AS n
            FROM netops.parsed_outputs
            GROUP BY device_name
            HAVING n < {MIN_COMMANDS_PER_DEVICE}
            ORDER BY 1
        """).fetchall()
        assert not thin, (
            f"devices below {MIN_COMMANDS_PER_DEVICE} distinct commands: "
            f"{[(r[0], r[1]) for r in thin]}"
        )


class TestSnapshotsAreCoherent:
    def test_more_than_one_snapshot_is_distinguishable(self, con):
        """Snapshot ids must order — every 'latest wins' query depends on it."""
        snaps = [r[0] for r in con.execute(
            "SELECT DISTINCT snapshot_id FROM netops.parsed_outputs ORDER BY 1"
        ).fetchall()]
        assert snaps, "no snapshots at all"
        assert snaps == sorted(snaps), "snapshot ids do not sort chronologically"
        assert len(snaps) == len(set(snaps))

    def test_the_latest_snapshot_covers_every_device(self, con):
        """A device present only in an older snapshot silently disappears from
        any query that filters to the newest one."""
        missing = con.execute("""
            WITH latest AS (SELECT MAX(snapshot_id) AS s FROM netops.parsed_outputs)
            SELECT d.hostname FROM netops.devices d
            WHERE NOT EXISTS (
                SELECT 1 FROM netops.parsed_outputs p, latest
                WHERE p.device_name = d.hostname AND p.snapshot_id = latest.s
            )
            ORDER BY 1
        """).fetchall()
        assert not missing, (
            f"devices absent from the newest snapshot: {[r[0] for r in missing]}"
        )

    def test_parsed_data_is_valid_json(self, con):
        """`parsed_data` is queried with JSON functions downstream; a row that
        is not valid JSON fails there, far from the cause."""
        bad = con.execute("""
            SELECT device_name, command FROM netops.parsed_outputs
            WHERE TRY_CAST(parsed_data AS JSON) IS NULL
            ORDER BY 1, 2
        """).fetchall()
        assert not bad, f"rows whose parsed_data is not JSON: {bad}"


class TestTopologyWasDiscovered:
    def test_topology_links_are_populated(self, con):
        n = con.execute("SELECT COUNT(*) FROM netops.topology_links").fetchone()[0]
        assert n > 0, "neighbour discovery produced nothing"

    def test_every_link_endpoint_is_a_known_device(self, con):
        """A link to a device the inventory does not contain is either a parse
        error or an incomplete import; both are worth failing on."""
        unknown = con.execute("""
            SELECT DISTINCT endpoint FROM (
                SELECT source_device AS endpoint FROM netops.topology_links
                UNION
                SELECT destination_device FROM netops.topology_links
            )
            WHERE endpoint NOT IN (SELECT hostname FROM netops.devices)
            ORDER BY 1
        """).fetchall()
        assert not unknown, (
            f"link endpoints absent from the inventory: {[r[0] for r in unknown]}"
        )


class TestTheFixtureIsNotVacuous:
    """Every assertion above is of the form "no bad rows". All of them pass
    against an empty database, so the suite would go green having checked
    nothing. These pin that there is data to check."""

    def test_there_are_devices_and_outputs_and_links(self, con):
        counts = {
            t: con.execute(f"SELECT COUNT(*) FROM netops.{t}").fetchone()[0]
            for t in ("devices", "parsed_outputs", "topology_links")
        }
        assert all(v > 0 for v in counts.values()), f"empty tables: {counts}"

    def test_a_device_without_neighbours_is_present(self, con):
        """The fixture deliberately includes one; if it disappears, the
        endpoint gates above stop being able to tell 'no links' from 'links for
        everyone'."""
        n = con.execute("""
            SELECT COUNT(*) FROM netops.devices d
            WHERE d.hostname NOT IN (
                SELECT source_device FROM netops.topology_links
                UNION SELECT destination_device FROM netops.topology_links
            )
        """).fetchone()[0]
        assert n >= 1, "fixture no longer contains an isolated device"
