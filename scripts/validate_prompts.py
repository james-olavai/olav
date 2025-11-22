"""Prompt schema validator.

Validates agent prompt YAML files under config/prompts/agents/ for required
semantic sections to keep LLM alignment consistent.

Required semantic blocks (case-insensitive substring match in file text):
  principles
  operations
  workflow
  output

Usage:
  uv run python scripts/validate_prompts.py
  uv run python scripts/validate_prompts.py --fail-on-missing

Exit codes:
  0 - All prompts valid (or missing tolerated)
  1 - Missing sections (when --fail-on-missing provided)
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import List, Dict

REQUIRED_SECTIONS = ["principles", "operations", "workflow", "output"]
AGENTS_DIR = pathlib.Path("config/prompts/agents")


def scan_file(path: pathlib.Path) -> Dict[str, bool]:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    return {section: (section in lower) for section in REQUIRED_SECTIONS}


def validate_prompts(fail_on_missing: bool = False) -> int:
    if not AGENTS_DIR.exists():
        print(f"[WARN] Agents directory not found: {AGENTS_DIR}")
        return 0

    failures: List[str] = []
    print("Validating agent prompt files...\n")
    for file in sorted(AGENTS_DIR.glob("*_agent.yaml")):
        result = scan_file(file)
        missing = [k for k, present in result.items() if not present]
        if missing:
            print(f"[FAIL] {file.name}: missing -> {', '.join(missing)}")
            failures.append(file.name)
        else:
            print(f"[OK]   {file.name}")
    print("\nSummary:")
    if failures:
        print(f" - Invalid: {len(failures)} -> {', '.join(failures)}")
    else:
        print(" - All prompt files contain required sections")

    if failures and fail_on_missing:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate agent prompt YAML structure")
    parser.add_argument("--fail-on-missing", action="store_true", help="Return non-zero if sections missing")
    args = parser.parse_args()
    exit_code = validate_prompts(fail_on_missing=args.fail_on_missing)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
