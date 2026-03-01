#!/usr/bin/env python3
"""
E2E Test: Command Learner → Template Generation → Snapshot Parsing

This test:
1. Uses natural language to invoke config agent's learner
2. Learns show bgp summary and show interfaces terse from R1
3. Verifies templates are generated in .olav/templates/custom/
4. Syncs command library
5. Reruns R1 snapshot to verify parsing success
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Add tools paths
sys.path.insert(0, str(PROJECT_ROOT / ".olav/workspace/config/learner/tools"))
sys.path.insert(0, str(PROJECT_ROOT / ".olav/workspace/audit/tools"))


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def run_command(cmd: str | list, shell: bool = False) -> tuple[int, str]:
    """Run shell command and return exit code + output."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=shell,
        )
        return result.returncode, result.stdout + result.stderr
    except Exception as e:
        return 1, str(e)


def verify_template_exists(command: str, platform: str = "juniper_junos") -> bool:
    """Check if custom template exists for a command."""
    template_name = f"{platform}_{command.replace(' ', '_')}.textfsm"
    template_path = PROJECT_ROOT / ".olav/templates/custom" / template_name
    
    exists = template_path.exists()
    size = template_path.stat().st_size if exists else 0
    
    print(f"  Template: {template_name}")
    print(f"  Path: {template_path}")
    print(f"  Exists: {exists}")
    print(f"  Size: {size} bytes" if exists else "  Size: N/A")
    
    return exists and size > 100  # Template should be at least 100 bytes


async def test_learner_e2e():
    """Main E2E test."""
    print_section("OLAV E2E: Learner → Snapshot")
    
    # =========================================================================
    # Step 1: Learn commands via natural language
    # =========================================================================
    print_section("Step 1: Learn Commands via Natural Language")
    
    query = "Learn TextFSM templates for Juniper show bgp summary and show interfaces terse from device R1"
    
    print(f"Query: {query}\n")
    print("Invoking: olav config 'natural language query'")
    
    # Run olav CLI with config subcommand + query
    # Correct syntax: config is a subcommand, query becomes args to that subcommand
    cmd = [
        sys.executable,
        "-m", "olav.cli.main",
        "config",
        query.strip()
    ]
    
    print(f"\nCommand: {' '.join(cmd)}\n")
    exit_code, output = run_command(cmd, shell=False)
    
    print("Output:")
    print(output[:2000] if len(output) > 2000 else output)
    
    if exit_code != 0:
        print(f"⚠️  Command returned exit code {exit_code}")
        print("Continuing anyway to check if templates were created...")
    
    # =========================================================================
    # Step 2: Verify templates were created
    # =========================================================================
    print_section("Step 2: Verify Templates Generated")
    
    templates_created = {
        "show bgp summary": verify_template_exists("show_bgp_summary"),
        "show interfaces terse": verify_template_exists("show_interfaces_terse"),
    }
    
    print(f"\nTemplates Created:")
    for cmd, exists in templates_created.items():
        status = "✅" if exists else "❌"
        print(f"  {status} {cmd}: {exists}")
    
    if not all(templates_created.values()):
        print("\n⚠️  Not all templates created. Check learner output above.")
        return False
    
    # =========================================================================
    # Step 3: Sync command library
    # =========================================================================
    print_section("Step 3: Sync Command Library")
    
    print("Invoking: olav --agent config 'sync commands'")
    
    cmd = f"""{sys.executable} -m olav.cli.main --agent config "Please sync the command library to include the newly created templates" """
    
    exit_code, output = run_command(cmd, shell=True)
    
    if exit_code == 0:
        print("✅ Command library synced")
    else:
        print(f"⚠️  Sync returned exit code {exit_code}")
        print("Output:", output[:1000])
    
    # =========================================================================
    # Step 4: Run snapshot on R1 to test parsing
    # =========================================================================
    print_section("Step 4: Test Parsing with Snapshot on R1")
    
    from take_snapshot import take_snapshot
    
    print("Running: take_snapshot(devices=['R1'], commands=[...], ...)")
    
    result = take_snapshot.func(
        devices=["R1"],
        commands=["show bgp summary", "show interfaces terse"],
        timeout=45,
        max_workers=2,
    )
    
    print("\nSnapshot Result:")
    print(json.dumps(result, indent=2, default=str)[:2000])
    
    # =========================================================================
    # Step 5: Analyze parsing quality
    # =========================================================================
    print_section("Step 5: Analyze Parsing Quality")
    
    bgp_result = next(
        (r for r in result.get("results", []) if "bgp" in r.get("command", "")),
        None
    )
    interfaces_result = next(
        (r for r in result.get("results", []) if "interfaces" in r.get("command", "")),
        None
    )
    
    print("\nParsing Results:")
    
    if bgp_result:
        print(f"\n  show bgp summary:")
        print(f"    Status: {bgp_result.get('status')}")
        print(f"    Parsed rows: {bgp_result.get('parsed_rows', 0)}")
        print(f"    Quality gap: {bgp_result.get('quality_gap', 'None')}")
        if bgp_result.get("parsed_rows", 0) > 0:
            print("    ✅ Successfully parsed!")
        else:
            print("    ⚠️  No rows parsed")
    
    if interfaces_result:
        print(f"\n  show interfaces terse:")
        print(f"    Status: {interfaces_result.get('status')}")
        print(f"    Parsed rows: {interfaces_result.get('parsed_rows', 0)}")
        print(f"    Quality gap: {interfaces_result.get('quality_gap', 'None')}")
        if interfaces_result.get("parsed_rows", 0) > 0:
            print("    ✅ Successfully parsed!")
        else:
            print("    ⚠️  No rows parsed")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print_section("Summary")
    
    bgp_parsed = (bgp_result or {}).get("parsed_rows", 0) > 0 if bgp_result else False
    interfaces_parsed = (interfaces_result or {}).get("parsed_rows", 0) > 0 if interfaces_result else False
    
    print(f"\nTemplates Created: {all(templates_created.values())}")
    print(f"BGP Summary Parsed: {bgp_parsed}")
    print(f"Interfaces Terse Parsed: {interfaces_parsed}")
    
    if all([templates_created.get(cmd) for cmd in templates_created]) and \
       (bgp_parsed or interfaces_parsed):
        print("\n✅ E2E Test PASSED!")
        return True
    else:
        print("\n❌ E2E Test FAILED")
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(test_learner_e2e())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
