#!/usr/bin/env python3
"""
Diagnostic script to identify the backend issue.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root / "src"))

print("=" * 70)
print("DeepAgents Backend Diagnostic")
print("=" * 70)

# Test 1: Check imports
print("\n[1] Testing backend imports...")
try:
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
    print(f"    ✓ deepagents.backends imported successfully")
    print(f"    - FilesystemBackend: {FilesystemBackend}")
    print(f"    - CompositeBackend: {CompositeBackend}")
except ImportError as e:
    print(f"    ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Create a simple FilesystemBackend
print("\n[2] Testing FilesystemBackend creation...")
try:
    backend = FilesystemBackend(root_dir="/tmp")
    print(f"    ✓ FilesystemBackend created: {backend}")
    print(f"    - Type: {type(backend)}")
    print(f"    - Has aglob_info: {hasattr(backend, 'aglob_info')}")
except Exception as e:
    print(f"    ✗ Failed: {e}")

# Test 3: Check DuckDBStore issue
print("\n[3] Testing DuckDBStore (potential issue)...")
try:
    from langgraph.store.duckdb import DuckDBStore
    print(f"    ✓ DuckDBStore imported: {DuckDBStore}")
    
    # Test creating one
    store = DuckDBStore.from_conn_string("/tmp/test.db")
    print(f"    - store type: {type(store)}")
    print(f"    - Is context manager: {hasattr(store, '__enter__')}")
    
except Exception as e:
    print(f"    ⚠ DuckDBStore issue: {e}")

# Test 4: Check if store is a context manager that needs unwrapping
print("\n[4] Checking for context manager wrapping...")
try:
    from langgraph.store.duckdb import DuckDBStore
    store = DuckDBStore.from_conn_string("/tmp/test.db")
    
    if hasattr(store, '__enter__'):
        print(f"    ⚠ DuckDBStore is a context manager (needs unwrapping)")
        print(f"    - This might be causing the 'aglob_info' error")
        print(f"    - Should use: with store: backend = store")
    else:
        print(f"    ✓ DuckDBStore is NOT a context manager")
        print(f"    - Type: {type(store)}")
        
except Exception as e:
    print(f"    ! Error: {e}")

print("\n" + "=" * 70)
print("Diagnosis Complete")
print("=" * 70)
