
import os
import sys
import duckdb
from pathlib import Path
from unittest.mock import patch

# Mock user for testing
TEST_USER = "test_user_v9"
os.environ["USER"] = TEST_USER

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from config.paths import USER_CACHE_PATH
from olav.core.unified_database import UnifiedDatabase
from olav.cli.memory import AgentMemory

def test_user_isolation():
    print(f"Testing User Isolation for: {TEST_USER}")
    
    # 1. Verify Path Resolution
    print(f"Resolved Cache Path: {USER_CACHE_PATH}")
    assert f"cache_{TEST_USER}.duckdb" in str(USER_CACHE_PATH)
    
    # Clean previous run
    if USER_CACHE_PATH.exists():
        USER_CACHE_PATH.unlink()
        
    # 2. Initialize Memory (should create DB and schema)
    print("Initializing AgentMemory...")
    memory = AgentMemory()
    
    # 3. Add message
    print("Adding test message...")
    memory.add("user", "Hello User Cache")
    
    # 4. Verify Persistence via Direct DuckDB
    print("Verifying persistence...")
    conn = duckdb.connect(str(USER_CACHE_PATH))
    result = conn.execute("SELECT content FROM main.session_history").fetchall()
    conn.close() # CRITICAL: Release lock before next step
    
    assert len(result) == 1
    assert result[0][0] == "Hello User Cache"
    print("✅ Persistence Verified!")
    
    # 5. Verify UnifiedDatabase access
    print("Verifying UnifiedDatabase access...")
    with UnifiedDatabase() as db:
        res = db.query("SELECT count(*) FROM commands.main.session_history")
        assert res[0][0] == 1
    print("✅ UnifiedDatabase Access Verified!")

if __name__ == "__main__":
    try:
        test_user_isolation()
        print("\nSUCCESS: User-Local Architecture Verified")
    except Exception as e:
        print(f"\nFAILURE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
