#!/usr/bin/env python3
"""Direct DuckDB database verification."""

import os

import duckdb


def check_devices():
    """Check devices in network.duckdb database."""
    print("=" * 70)
    print("Database Device Inventory Check")
    print("=" * 70)

    db_path = os.path.expanduser("~/.olav/data/network.duckdb")

    print(f"\n📁 Database: {db_path}")
    print(f"✅ Exists: {os.path.exists(db_path)}")
    print(f"📏 Size: {os.path.getsize(db_path) / 1024:.1f} KB")

    try:
        conn = duckdb.connect(db_path, read_only=True)

        # List all tables
        print("\n📋 Tables in database:")
        tables_result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()

        if not tables_result:
            print("  ❌ No tables found!")
            return

        tables = [t[0] for t in tables_result]
        for table_name in tables:
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"  - {table_name}: {row_count} rows")

        # Check snapshots table specifically
        if "snapshots" in tables:
            print("\n🖥️  Devices in snapshots table:")
            devices = conn.execute(
                "SELECT DISTINCT device_name FROM snapshots ORDER BY device_name"
            ).fetchall()

            if not devices:
                print("  ❌ No devices found in snapshots!")
            else:
                print(f"  Found {len(devices)} device(s):")
                for (device,) in devices:
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM snapshots WHERE device_name = '{device}'"
                    ).fetchone()[0]
                    print(f"    - {device}: {count} snapshot records")

            # Check expected devices
            expected = {"R1", "R2", "R3", "SW1"}
            found = {d[0] for d in devices}
            missing = expected - found

            print("\n📊 Completeness Check:")
            print(f"  Expected: {expected}")
            print(f"  Found: {found}")

            if not missing:
                print("  ✅ All expected devices present!")
            else:
                print(f"  ⚠️  Missing: {missing}")
                print("\n  To collect missing device data, run:")
                for device in missing:
                    print(f"    olav snapshot collect --device {device}")
        else:
            print("\n⚠️  'snapshots' table not found!")
            print("  Available tables:", tables)

        conn.close()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    check_devices()
