"""Debug DuckDB connection state"""

from pathlib import Path

import duckdb
from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.store.duckdb import DuckDBStore

test_db = Path(".olav/test_debug.db")
test_db.parent.mkdir(parents=True, exist_ok=True)
if test_db.exists():
    test_db.unlink()

print("1. Create connection")
conn = duckdb.connect(str(test_db))

print("2. Test cursor BEFORE DuckDBSaver")
cursor = conn.cursor()
cursor.execute("SELECT 1 as v")
result = cursor.fetchone()
print(f"   Result type: {type(result)}, value: {result}")
print(f"   Can access dict-style: {type(result) == tuple}")

print("\n3. Create DuckDBSaver")
saver = DuckDBSaver(conn)
print("4. Call DuckDBSaver.setup()")
saver.setup()

print("\n5. Test cursor AFTER DuckDBSaver.setup()")
cursor2 = conn.cursor()
cursor2.execute("SELECT 1 as v")
result2 = cursor2.fetchone()
print(f"   Result type: {type(result2)}, value: {result2}")

print("\n6. Now create DuckDBStore")
store = DuckDBStore(conn)
print("7. Call DuckDBStore.setup()")
try:
    store.setup()
    print("   ✓ Success")
except TypeError as e:
    print(f"   ✗ Failed: {e}")

print("\nDone")
