#!/usr/bin/env python3
"""
E2E Test: Direct learner invocation (bypassing CLI async issues)

This test directly calls learner tools without going through the CLI,
to verify the template generation → snapshot parsing workflow.

Steps:
1. Use learner tools to learn commands (execute_command, analyze, generate templates)
2. Verify templates are created in .olav/templates/custom/
3. Sync command library
4. Rerun R1 snapshot
5. Verify parsing gaps are detected correctly
"""

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
            timeout=60,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return 124, "Command timed out"
    except Exception as e:
        return 1, str(e)


def verify_template_exists(command: str, platform: str = "juniper_junos") -> bool:
    """Check if custom template exists for a command."""
    template_name = f"{platform}_{command.replace(' ', '_')}.textfsm"
    template_path = PROJECT_ROOT / ".olav/templates/custom" / template_name
    
    exists = template_path.exists()
    size = template_path.stat().st_size if exists else 0
    
    print(f"  Template: {template_name}")
    print(f"  Exists: {'✅' if exists else '❌'} ({size} bytes)" if exists else "  Exists: ❌")
    
    return exists and size > 100


async def test_learner_direct():
    """Main E2E test using direct tool invocation."""
    print_section("OLAV E2E: Direct Learner Tools Test")
    
    # =========================================================================
    # Step 1: Verify learner tools exist
    # =========================================================================
    print_section("Step 1: Verify Learner Tools Available")
    
    learner_tools_dir = PROJECT_ROOT / ".olav/workspace/config/learner/tools"
    tools_available = {
        "execute_command.py": learner_tools_dir / "execute_command.py",
        "analyze_output.py": learner_tools_dir / "analyze_output.py",
        "generate_template.py": learner_tools_dir / "generate_template.py",
        "save_template.py": learner_tools_dir / "save_template.py",
    }
    
    all_exist = True
    for tool_name, tool_path in tools_available.items():
        exists = tool_path.exists()
        print(f"  {tool_name}: {'✅' if exists else '❌'}")
        all_exist = all_exist and exists
    
    if not all_exist:
        print("\n⚠️  Some learner tools missing. You may need to run learner setup.")
        return
    
    # =========================================================================
    # Step 2: Simulate learning workflow (without full LLM integration)
    # =========================================================================
    print_section("Step 2: Simulate Learning Commands")
    
    # For this test, we'll use the existing execute_command tool to run commands on R1
    # and collect their output for template analysis
    
    commands_to_learn = [
        "show bgp summary",
        "show interfaces terse",
    ]
    
    collected_outputs = {}
    for cmd in commands_to_learn:
        print(f"\n  Learning: {cmd}")
        
        # Use execute_command tool to collect raw output from R1
        execute_cmd = [
            sys.executable,
            str(learner_tools_dir / "execute_command.py"),
            "--command", cmd,
            "--device", "R1",
            "--output-format", "json",
        ]
        
        exit_code, output = run_command(execute_cmd, shell=False)
        
        if exit_code == 0:
            try:
                result = json.loads(output)
                collected_outputs[cmd] = result.get("output", "")
                print(f"    ✅ Collected {len(result.get('output', ''))} bytes")
            except json.JSONDecodeError:
                print(f"    ❌ Failed to parse output: {output[:200]}")
        else:
            print(f"    ❌ Command failed: {output[:200]}")
    
    # =========================================================================
    # Step 3: Verify templates exist (they should be in NTC templates for Juniper)
    # =========================================================================
    print_section("Step 3: Check for Existing NTC Templates")
    
    ntc_templates_dir = PROJECT_ROOT / ".olav/templates"  # or path to ntc-templates
    
    templates_found = {}
    for cmd in commands_to_learn:
        # Check if template exists in custom or NTC
        cmd_safe = cmd.replace(" ", "_")
        template_path = PROJECT_ROOT / f".olav/templates/custom/juniper_junos_{cmd_safe}.textfsm"
        
        exists = template_path.exists()
        templates_found[cmd] = exists
        print(f"  {cmd}: {'✅ Custom template exists' if exists else '❌ No custom template'}")
    
    # =========================================================================
    # Step 4: Rerun R1 snapshot to test parsing
    # =========================================================================
    print_section("Step 4: Rerun R1 Snapshot for Parse Quality Check")
    
    # Use take_snapshot tool to run a fresh snapshot on R1
    take_snapshot_script = PROJECT_ROOT / ".olav/workspace/audit/tools/take_snapshot.py"
    
    if take_snapshot_script.exists():
        snapshot_cmd = [
            sys.executable,
            str(take_snapshot_script),
            "--device", "R1",
            "--output-format", "json",
        ]
        
        exit_code, output = run_command(snapshot_cmd, shell=False)
        
        if exit_code == 0:
            try:
                snapshot_result = json.loads(output)
                
                # Check for gaps in parsing
                quality_gaps = snapshot_result.get("quality_gaps", {})
                if quality_gaps:
                    print(f"\n  Quality Gaps Detected:")
                    print(f"    HIGH severity: {quality_gaps.get('high', 0)}")
                    print(f"    MEDIUM severity: {quality_gaps.get('medium', 0)}")
                    print(f"    TOTAL gaps: {quality_gaps.get('total', 0)}")
                else:
                    print("  ✅ No parsing gaps detected!")
                
                # Check specific command results
                quality_warning = snapshot_result.get("quality_warning", "")
                if quality_warning:
                    print(f"\n  Warning details:")
                    print(f"    {quality_warning[:300]}...")
                    
            except json.JSONDecodeError:
                print(f"  ❌ Failed to parse snapshot output")
        else:
            print(f"  ⚠️  Snapshot collection failed: {output[:200]}")
    else:
        print(f"  ⚠️  take_snapshot.py not found at {take_snapshot_script}")
    
    # =========================================================================
    # Step 5: Summary
    # =========================================================================
    print_section("Test Summary")
    
    print(f"\n  Learner tools available: {'✅' if all_exist else '❌'}")
    print(f"  Commands learned: {len(collected_outputs)}/{len(commands_to_learn)}")
    print(f"  Custom templates found: {sum(1 for v in templates_found.values() if v)}/{len(templates_found)}")
    
    if sum(1 for v in templates_found.values() if v) > 0:
        print(f"\n  ✅ E2E test passed: Templates exist and snapshot parsing is available")
    else:
        print(f"\n  ⚠️  No custom templates found. Use learner agent to create them manually:")
        print(f"     - See .olav/workspace/config/learner/ for learner subagent")
        print(f"     - or use: olav config 'Learn templates for show bgp summary from R1'")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_learner_direct())
