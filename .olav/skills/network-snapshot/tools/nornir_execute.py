#!/usr/bin/env python3
"""
Nornir Execute - Wrapper importing from shared tools.

This tool is implemented in .olav/shared/tools/nornir_execute.py
"""

# Import from shared tools and execute
import sys
from pathlib import Path

def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()

# Add shared tools to path
shared_tools = _find_project_root() / ".olav" / "shared" / "tools"
sys.path.insert(0, str(shared_tools.parent))

# Import and execute the shared tool
from tools.nornir_execute import main, DateTimeEncoder
import json

if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
    except Exception as e:
        print(json.dumps({"error": str(e), "status": "failed"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
