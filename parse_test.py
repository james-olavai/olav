import json
import logging
import sqlite3
import duckdb
from pathlib import Path

_DB_PATH = Path(".olav") / "databases" / "main.duckdb"

def _get_device_platform_map(con) -> dict[str, str]:
    rows = con.execute("SELECT name, platform FROM devices WHERE platform IS NOT NULL").fetchall()
    return {name: platform for name, platform in rows}

def test():
    con = duckdb.connect(str(_DB_PATH), read_only=True)
    platform_map = _get_device_platform_map(con)
    rows = con.execute("SELECT device_name, command, raw_output FROM parsed_outputs LIMIT 1").fetchall()
    print("Found rows:", len(rows))
    print("Row 0:", rows[0][0], rows[0][1], len(rows[0][2]) if rows[0][2] else 0)

if __name__ == "__main__":
    test()
