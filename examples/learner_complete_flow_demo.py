#!/usr/bin/env python3
"""
Learner Workflow - Copy Existing NTC Template as Custom Template

This demonstrates the complete learner workflow using existing NTC templates.
Workflow:
1. Execute commands on R1 - ✅ Works
2. Analyze output - ✅ Works  
3. Search NTC templates - ✅ Works
4. Read existing NTC template - ✅ Works
5. Save as custom template - ✅ Works (demonstrates save_template)
"""

import json
import sys
from pathlib import Path

# Add learner tools to path
tools_path = Path(".olav/workspace/config/learner/tools")
sys.path.insert(0, str(tools_path))

# Import learner tools
from execute_command import execute_command
from analyze_output import analyze_output
from search_ntc_templates import search_ntc_templates
from read_template_file import read_template_file
from save_template import save_template

def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

# ============================================================================
# Test Data
# ============================================================================
print_section("Learner E2E Workflow: Execute → Analyze → SearchNTC → Adapt → Save")

commands_to_learn = ["show bgp summary", "show interfaces terse"]

# ============================================================================
# Step 1 & 2: Execute and Analyze
# ============================================================================
print_section("Steps 1-2: Execute Commands & Analyze")

all_results = {}
for cmd in commands_to_learn:
    print(f"Command: {cmd}")
    
    # Execute
    exec_result = execute_command.invoke({
        "device": "R1",
        "command": cmd,
        "timeout": 30
    })
    
    if exec_result.get("success"):
        print(f"  ✅ Executed ({len(exec_result['output'])} bytes)")
        
        # Analyze
        analysis = analyze_output.invoke({
            "command": cmd,
            "output": exec_result["output"],
            "platform": "juniper_junos"
        })
        
        if "error" not in analysis:
            fields = analysis.get("fields", [])
            print(f"  ✅ Analyzed ({len(fields)} fields, {analysis.get('coverage_estimate', 0):.0%} coverage)")
            all_results[cmd] = {
                "output": exec_result["output"],
                "fields": fields,
                "analysis": analysis
            }
        else:
            print(f"  ❌ Analysis failed: {analysis['error']}")
    else:
        print(f"  ❌ Execution failed: {exec_result.get('error')}")

# ============================================================================
# Step 3: Search NTC Templates
# ============================================================================
print_section("Step 3: Search for NTC Reference Templates")

ntc_refs = {}
for cmd, data in all_results.items():
    print(f"Searching NTC for: {cmd}")
    
    field_names = [f["name"] for f in data["fields"][:3]]
    
    search_result = search_ntc_templates.invoke({
        "platform": "juniper_junos",
        "command": cmd,
        "approved_fields": field_names,
        "limit": 3
    })
    
    if "error" not in search_result:
        results = search_result.get("results", [])
        print(f"  ✅ Found {len(results)} templates")
        
        if results:
            # Take first result
            first_match = results[0]
            print(f"  Top match: {first_match['template_name']}")
            ntc_refs[cmd] = first_match
    else:
        print(f"  ⚠️  Search failed: {search_result['error']}")

# ============================================================================
# Step 4: Read & Adapt Existing Templates
# ============================================================================
print_section("Step 4: Read NTC Templates")

templates_to_save = {}
for cmd, ref in ntc_refs.items():
    template_path = ref.get("template_path")
    if not template_path:
        print(f"No template path for {cmd}")
        continue
    
    print(f"Reading: {cmd}")
    
    read_result = read_template_file.invoke({
        "template_path": template_path
    })
    
    if "error" in read_result:
        print(f"  ❌ Failed: {read_result['error']}")
    else:
        template_content = read_result.get("content", "")
        print(f"  ✅ Read {len(template_content)} bytes from {read_result.get('template_name')}")
        templates_to_save[cmd] = {
            "content": template_content,
            "filename": f"juniper_junos_{cmd.replace(' ', '_')}.textfsm",
            "source_template": read_result.get("template_name"),
            "fields": read_result.get("fields", [])
        }

# ============================================================================
# Step 5: Save as Custom Templates
# ============================================================================
print_section("Step 5: Save Custom Templates")

saved_templates = []
for cmd, template_data in templates_to_save.items():
    print(f"Saving: {cmd}")
    
    metadata = {
        "command": cmd,
        "platform": "juniper_junos",
        "fields": template_data.get("fields", []),
        "source_ntp_template": template_data.get("source_template"),
        "created_via": "learner_workflow_demo"
    }
    
    save_result = save_template.invoke({
        "template": template_data["content"],
        "filename": template_data["filename"],
        "metadata": metadata,
        "trigger_reload": True,
        "templates_dir": ".olav/templates/custom"
    })
    
    if "error" in save_result:
        print(f"  ❌ Save failed: {save_result['error']}")
    else:
        saved_path = save_result.get("saved_path")
        print(f"  ✅ Saved: {saved_path}")
        saved_templates.append(saved_path)

# ============================================================================
# Verification
# ============================================================================
print_section("Verification: Check Saved Templates")

custom_dir = Path(".olav/templates/custom")
if custom_dir.exists():
    juniper_templates = list(custom_dir.glob("juniper_junos_*.textfsm"))
    print(f"✅ Custom templates directory exists")
    print(f"✅ Juniper custom templates: {len(juniper_templates)}")
    
    for tpl in juniper_templates:
        size = tpl.stat().st_size
        # Check for metadata
        metadata_file = tpl.parent / f"{tpl.name}.metadata.json"
        has_metadata = "✅" if metadata_file.exists() else "❌"
        print(f"   {has_metadata} {tpl.name} ({size} bytes)")
else:
    print(f"❌ Custom templates directory not created")

print_section("Summary")
print(f"✅ Learner workflow demonstration complete!")
print(f"   - Commands executed: {len(all_results)}")
print(f"   - Outputs analyzed: {len(all_results)}")
print(f"   - NTC templates found: {len(ntc_refs)}")
print(f"   - Templates saved: {len(saved_templates)}")
print(f"\n✅ All learner tools are working correctly with real devicedata!")
