#!/usr/bin/env python3
"""快速从 test_network.duckdb 复制数据到 olav.duckdb"""
import duckdb
from pathlib import Path

test_db = Path(".olav/db/test_network.duckdb")
prod_db = Path(".olav/db/olav.duckdb")

print(f"📥 复制数据从 {test_db.name} 到 {prod_db.name}...")

# 读取 test database (DuckDB format)
test_conn = duckdb.connect(str(test_db), read_only=True)

# 创建 production database
prod_conn = duckdb.connect(str(prod_db))

# 获取所有表
tables = test_conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()

if not tables:
    # Fallback: use PRAGMA table_info
    tables = test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

for (table_name,) in tables:
    try:
        print(f"  复制 {table_name}...", end=" ")
        
        # 使用 ATTACH DATABASE 直接复制
        prod_conn.execute(f"ATTACH DATABASE '{test_db}' AS test_db;")
        
        # 创建表结构
        prod_conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM test_db.{table_name} WHERE FALSE")
        
        # 复制数据
        prod_conn.execute(f"INSERT INTO {table_name} SELECT * FROM test_db.{table_name}")
        
        # 计算行数
        count = prod_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"✅ {count:,} 行")
        
        prod_conn.execute(f"DETACH DATABASE test_db;")
    except Exception as e:
        print(f"⚠️  Error: {e}")

prod_conn.commit()
test_conn.close()
prod_conn.close()

print("\n✅ 数据复制完成！")
print(f"   Production DB: {prod_db}")
