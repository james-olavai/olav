#!/usr/bin/env python3
"""
End-to-End Learner Workflow Demo

Demonstrates the complete learner workflow:
1. Execute commands on R1
2. Analyze output
3. Generate templates
4. Save templates

This script shows learner tools work correctly when called directly.
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
from generate_template import generate_template
from save_template import save_template
from search_ntc_templates import search_ntc_templates
from read_template_file import read_template_file

def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

# ============================================================================
# Step 1: Execute Commands
# ============================================================================
print_section("Step 1: Execute Commands on R1")

commands = [
    "show bgp summary",
    "show interfaces terse",
]

outputs = {}
for cmd in commands:
    print(f"Executing: {cmd}")
    result = execute_command.invoke({
        "device": "R1",
        "command": cmd,
        "timeout": 30
    })
    
    if result["success"]:
        outputs[cmd] = result["output"]
        print(f"  ✅ Success ({len(result['output'])} bytes)")
        if result.get("warning"):
            print(f"  ⚠️  {result['warning']}")
    else:
        print(f"  ❌ Failed: {result['error']}")

# ============================================================================
#Step 2: Analyze Output
# ============================================================================
print_section("Step 2: Analyze Outputs")

analyses = {}
for cmd, output in outputs.items():
    print(f"Analyzing: {cmd}")
    
    analysis = analyze_output.invoke({
        "command": cmd,
        "output": output,
        "platform": "juniper_junos"
    })
    
    if "error" in analysis:
        print(f"  ❌ Analysis failed: {analysis['error']}")
    else:
        analyses[cmd] = analysis
        fields = analysis.get("fields", [])
        coverage = analysis.get("coverage_estimate", 0)
        structure = analysis.get("structure", "unknown")
        print(f"  ✅ Found {len(fields)} fields, coverage: {coverage:.1%}, structure: {structure}")
        print(f"  Fields: {[f['name'] for f in fields[:5]]}...")

# ============================================================================
# Step 3: Search for NTC References
# ============================================================================
print_section("Step 3: Search NTC Templates")

for cmd, analysis in analyses.items():
    print(f"Searching for: {cmd}")
    
    fields = [f["name"] for f in analysis.get("fields", [])]
    
    results = search_ntc_templates.invoke({
        "platform": "juniper_junos",
        "command": cmd,
        "approved_fields": fields[:3],  # Use first 3 fields
        "limit": 3
    })
    
    if "error" in results:
        print(f"  ⚠️  Search failed: {results['error']}")
    else:
        num_results = len(results.get("results", []))
        print(f"  ✅ Found {num_results} templates")
        for i, ref in enumerate(results.get("results", [])[:2], 1):
            print(f"    {i}. {ref['template_name']} (score: {ref.get('match_score', 0):.2f})")

# ============================================================================
# Step 4: Generate Templates
# ============================================================================
print_section("Step 4: Generate Templates")

for cmd, output in outputs.items():
    analysis = analyses.get(cmd, {})
    fields = analysis.get("fields", [])
    
    if not fields:
        print(f"⚠️  Skipping {cmd} - no fields detected")
        continue
    
    print(f"Generating template for: {cmd}")
    
    result = generate_template.invoke({
        "command": cmd,
        "platform": "juniper_junos",
        "approved_fields": fields,
        "output_sample": output,
        "ntc_references": [],  # Could add NTC template content here
        "max_iterations": 3
    })
    
    if result.get("template"):
        test_result = result.get("test_result", {})
        print(f"  ✅ Template generated (iteration {result.get('iteration', '?')})")
        print(f"  Test result: {test_result}")
        print(f"  Filename: {result.get('filename')}")
        
        # ====================================================================
        # Step 5: Save Template
        # ====================================================================
        print(f"  Saving template...")
        
        save_result = save_template.invoke({
            "template": result["template"],
            "filename": result["filename"],
            "metadata": {
                "command": cmd,
                "platform": "juniper_junos",
                "fields": [f["name"] for f in fields],
                "coverage": test_result.get("coverage", 0),
                "created_via": "e2e_learner_demo"
            },
            "trigger_reload": True,
            "templates_dir": ".olav/templates/custom"
        })
        
        if "error" in save_result:
            print(f"    ❌ Save failed: {save_result['error']}")
        else:
            print(f"    ✅ Saved to: {save_result.get('saved_path')}")
            print(f"    ✅ Metadata saved to: {save_result.get('metadata_path')}")
    else:
        error = result.get("test_result", {}).get("error", "Unknown error")
        print(f"  ❌ Generation failed: {error}")

# ============================================================================
# Summary
# ============================================================================
print_section("Summary")

print("✅ Learner workflow demonstration complete!")
print(f"   - Commands executed: {len(outputs)}")
print(f"   - Outputs analyzed: {len(analyses)}")
print("   - Templates should be saved in .olav/templates/custom/")

# Verify templates exist
custom_dir = Path(".olav/templates/custom")
if custom_dir.exists():
    templates = list(custom_dir.glob("juniper_junos_*.textfsm"))
    print(f"   - Templates in custom dir: {len(templates)}")
    for tpl in templates:
        print(f"     • {tpl.name}")
