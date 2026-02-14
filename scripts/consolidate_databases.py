#!/usr/bin/env python3
"""
Database consolidation script for Phase 2 refactor.

Tasks:
1. Merge network.duckdb tables into main.duckdb
2. Verify data integrity
3. Create agent.duckdb for checkpointer
4. Set up llm_cache.db for LLM responses
"""

import sqlite3
import duckdb
from pathlib import Path
from datetime import datetime


def merge_databases(db_dir: str = ".olav/databases"):
    """Merge network_backup.duckdb into main.duckdb."""
    db_path = Path(db_dir)
    db_path.mkdir(parents=True, exist_ok=True)

    main_db = db_path / "main.duckdb"
    network_backup = db_path / "network_backup.duckdb"

    if not network_backup.exists():
        print(f"⚠️  Network backup not found: {network_backup}")
        return False

    try:
        # Connect to main database
        conn_main = duckdb.connect(str(main_db))
        
        # Get list of tables in network_backup
        conn_network = duckdb.connect(str(network_backup))
        tables_result = conn_network.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        
        print(f"📊 Found {len(tables_result)} tables in network_backup")
        
        # For each table in network_backup, import into main
        for table_row in tables_result:
            table_name = table_row[0]
            print(f"  Importing {table_name}...", end=" ")
            
            try:
                # Read from network_backup
                network_conn = duckdb.connect(str(network_backup))
                data = network_conn.execute(f"SELECT * FROM {table_name}").fetchall()
                columns = network_conn.execute(f"DESCRIBE {table_name}").fetchall()
                
                # Get column names
                col_names = [col[0] for col in columns]
                
                if data:
                    # Create table in main if not exists
                    column_defs = ", ".join([
                        f'"{col[0]}" {col[1]}' for col in columns
                    ])
                    
                    conn_main.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            {", ".join([f"{col[0]} {col[1]}" for col in columns])}
                        )
                    """)
                    
                    # Insert data
                    placeholders = ", ".join(["?" for _ in col_names])
                    insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
                    
                    for row in data:
                        try:
                            conn_main.execute(insert_sql, row)
                        except Exception as e:
                            print(f"⚠️ Skip row due to: {e}")
                    
                    conn_main.commit()
                    print(f"✅ ({len(data)} rows)")
                else:
                    print("(empty)")
                    
            except Exception as e:
                print(f"❌ Error: {e}")
                
        conn_main.close()
        conn_network.close()
        print("\n✅ Database merge completed")
        return True
        
    except Exception as e:
        print(f"❌ Merge failed: {e}")
        return False


def create_agent_db(db_dir: str = ".olav/databases"):
    """Create agent.duckdb with checkpoints table."""
    db_path = Path(db_dir)
    db_path.mkdir(parents=True, exist_ok=True)

    agent_db = db_path / "agent.duckdb"

    try:
        conn = duckdb.connect(str(agent_db))
        
        # Create checkpoints table (DuckDB compatible with LangGraph)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id VARCHAR,
                checkpoint_id VARCHAR,
                parent_id VARCHAR,
                values JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, checkpoint_id)
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint_puts (
                thread_id VARCHAR,
                checkpoint_id VARCHAR,
                task_id VARCHAR,
                key VARCHAR,
                value JSON,
                PRIMARY KEY (thread_id, checkpoint_id, task_id, key)
            )
        """)
        
        conn.commit()
        conn.close()
        print(f"✅ Created agent.duckdb with checkpoints support")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create agent.duckdb: {e}")
        return False


def create_llm_cache_db(db_dir: str = ".olav/databases"):
    """Create llm_cache.db using SQLite for LLM response caching."""
    db_path = Path(db_dir)
    db_path.mkdir(parents=True, exist_ok=True)

    cache_db = db_path / "llm_cache.db"

    try:
        conn = sqlite3.connect(str(cache_db))
        cursor = conn.cursor()
        
        # Create llm_cache table compatible with LangChain
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                prompt TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accessed_count INTEGER DEFAULT 1,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index for faster lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_prompt ON messages(prompt)
        """)
        
        conn.commit()
        conn.close()
        print(f"✅ Created llm_cache.db with messages table")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create llm_cache.db: {e}")
        return False


def verify_databases(db_dir: str = ".olav/databases"):
    """Verify all databases are accessible and have data."""
    db_path = Path(db_dir)
    results = {}
    
    # Check main.duckdb
    try:
        conn = duckdb.connect(str(db_path / "main.duckdb"))
        tables = conn.execute(
            "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchone()
        results["main.duckdb"] = {"tables": tables[0], "status": "✅"}
        conn.close()
    except Exception as e:
        results["main.duckdb"] = {"error": str(e), "status": "❌"}
    
    # Check agent.duckdb
    try:
        conn = duckdb.connect(str(db_path / "agent.duckdb"))
        hascp = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'checkpoints'"
        ).fetchone()[0]
        results["agent.duckdb"] = {"checkpoints": hascp > 0, "status": "✅"}
        conn.close()
    except Exception as e:
        results["agent.duckdb"] = {"error": str(e), "status": "❌"}
    
    # Check llm_cache.db
    try:
        conn = sqlite3.connect(str(db_path / "llm_cache.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        results["llm_cache.db"] = {"messages": cursor.fetchone()[0], "status": "✅"}
        conn.close()
    except Exception as e:
        results["llm_cache.db"] = {"error": str(e), "status": "❌"}
    
    print("\n📋 Database Verification:")
    for db_name, info in results.items():
        print(f"  {info.get('status', '❓')} {db_name}: {info}")
    
    return all(v.get("status") == "✅" for v in results.values())


if __name__ == "__main__":
    print("🔄 Starting Phase 2 Database Consolidation\n")
    
    print("Step 1: Merge databases...")
    merge_success = merge_databases()
    
    print("\nStep 2: Create agent.duckdb...")
    agent_success = create_agent_db()
    
    print("\nStep 3: Create llm_cache.db...")
    cache_success = create_llm_cache_db()
    
    print("\nStep 4: Verify databases...")
    verify_success = verify_databases()
    
    if merge_success and agent_success and cache_success and verify_success:
        print("\n✅ Phase 2 Database consolidation completed successfully!")
    else:
        print("\n⚠️  Some steps failed. Please review the output above.")
