#!/usr/bin/env python3
"""
Mock/Fallback Data Audit Script

Searches for:
1. Mock/test/fake device data
2. Fallback returns when database fails
3. Example/sample data returns
4. CSV-based data sources (not using database)
"""

import os
import re
from pathlib import Path

ROOT = Path("/home/yhvh/Olav")
SRC_PATH = ROOT / "src"

# Patterns to search for
PATTERNS = {
    "mock_devices": r"(mock_devices|test_devices|sample_devices|example_devices|fake_devices)\s*=",
    "hardcoded_list": r"return\s*\[\s*\{.*device.*\}",
    "csv_read": r"(pd\.read_csv|csv\.DictReader|open.*csv)",
    "fallback_return": r"except.*:\s*(?:return\s*\[|return\s*{}|return\s*None)",
    "csv_export": r"(exports_dir|EXPORTS_DIR|exports/)",
    "devices_var": r"devices\s*=\s*\[",
}

def scan_file(filepath):
    """Scan a file for problematic patterns."""
    try:
        content = filepath.read_text()
        issues = {}
        
        for pattern_name, pattern in PATTERNS.items():
            matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
            for match in matches:
                # Count lines up to match
                line_no = content[:match.start()].count('\n') + 1
                if pattern_name not in issues:
                    issues[pattern_name] = []
                issues[pattern_name].append({
                    'line': line_no,
                    'match': match.group(0)[:80],  # First 80 chars
                })
        
        return issues if issues else None
    except Exception as e:
        return None

def main():
    """Audit all Python files for mock data."""
    
    print("🔍 MOCK/FALLBACK DATA AUDIT")
    print("=" * 80)
    
    suspicious_files = []
    
    for py_file in SRC_PATH.rglob("*.py"):
        rel_path = py_file.relative_to(ROOT)
        issues = scan_file(py_file)
        
        if issues:
            print(f"\n⚠️  {rel_path}")
            for pattern_name, matches in issues.items():
                print(f"   [{pattern_name}]:")
                for match_info in matches[:3]:  # Show first 3
                    print(f"      Line {match_info['line']}: {match_info['match'][:70]}...")
            suspicious_files.append(str(rel_path))
    
    print("\n" + "=" * 80)
    print(f"🔴 Found {len(suspicious_files)} potentially suspicious files")
    
    # Additional checks
    print("\n📋 SPECIFIC CHECKS:")
    
    # Check for "_nornir_instance" - maybe it's failing silently
    nornir_files = list(SRC_PATH.rglob("network_executor.py"))
    if nornir_files:
        print(f"✓ Found Nornir executor: {nornir_files[0].relative_to(ROOT)}")
    
    # Check for CSV data loading in skills
    skills_path = ROOT / ".olav" / "skills"
    csv_tools = list(skills_path.rglob("*.py"))
    if csv_tools:
        print(f"✓ Found {len(csv_tools)} skill tools")
        for tool in csv_tools:
            content = tool.read_text()
            if "read_csv" in content or "load_csv" in content:
                print(f"  ⚠️  {tool.name} reads CSV!")
    
    # Check for example data in __main__ blocks
    print("\n💾 Checking for hardcoded example data...")
    for py_file in SRC_PATH.rglob("*.py"):
        content = py_file.read_text()
        if "__main__" in content and ("device" in content.lower() or "host" in content.lower()):
            # Check if it has device data
            if re.search(r'"hostname".*"192\.168|"name".*"R[0-9]|"device_id"', content):
                print(f"  ⚠️  {py_file.relative_to(ROOT)} has example device data in __main__")
    
    return len(suspicious_files) > 0

if __name__ == "__main__":
    exit(main())
