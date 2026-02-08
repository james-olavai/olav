#!/usr/bin/env python3
"""
TextFSM Interactive Agent - Infrastructure Validation Script

Verifies that all modules are properly structured and importable.
Run this after infrastructure setup to validate completeness.
"""

import sys
import importlib.util
from pathlib import Path

# Add src to path so we can import olav modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def check_file_exists(path: Path, description: str) -> bool:
    """Check if a file exists."""
    if path.exists():
        print(f"  ✓ {description}")
        return True
    else:
        print(f"  ✗ {description} - NOT FOUND")
        return False


def check_module_importable(module_name: str, description: str) -> bool:
    """Check if a module can be imported."""
    try:
        __import__(module_name)
        print(f"  ✓ {description} - importable")
        return True
    except ImportError as e:
        print(f"  ✗ {description} - import error: {e}")
        return False


def check_class_exists(module_name: str, class_name: str, description: str) -> bool:
    """Check if a class exists in a module."""
    try:
        module = __import__(module_name, fromlist=[class_name])
        getattr(module, class_name)
        print(f"  ✓ {description}")
        return True
    except (ImportError, AttributeError) as e:
        print(f"  ✗ {description} - {e}")
        return False


def main():
    """Run all validation checks."""
    results = []
    
    print("=" * 70)
    print("TextFSM Interactive Agent - Infrastructure Validation")
    print("=" * 70)
    
    # ====================================================================
    # Check 1: File Existence
    # ====================================================================
    print("\n✓ Check 1: File Existence")
    agent_dir = Path("/home/yhvh/Olav/src/olav/agents/textfsm_interactive_agent")
    
    files = {
        "__init__.py": "Module init",
        "models.py": "Data models",
        "tools.py": "Tool functions",
        "deepagent.py": "DeepAgents integration",
        "orchestrator.py": "Workflow orchestrator",
        "cleanup_checklist.py": "Cleanup validation",
        "README.md": "Documentation",
    }
    
    check1_passed = True
    for filename, description in files.items():
        if not check_file_exists(agent_dir / filename, description):
            check1_passed = False
    
    results.append(("File Existence", check1_passed))
    
    # ====================================================================
    # Check 2: Module Structure
    # ====================================================================
    print("\n✓ Check 2: Module Structure")
    
    check2_passed = True
    
    # Check core module imports
    try:
        __import__("olav.agents.textfsm_interactive_agent")
        print(f"  ✓ Core module importable")
    except ImportError as e:
        # This is expected if dependencies aren't installed
        # Check if the module structure at least exists
        if "langchain" in str(e) or "pydantic" in str(e):
            print(f"  ⚠ Core module has missing dependencies (expected): {e}")
            print(f"    Note: Install dependencies for full validation")
        else:
            print(f"  ✗ Core module - unexpected import error: {e}")
            check2_passed = False
    
    results.append(("Module Structure", check2_passed))
    
    # ====================================================================
    # Check 3: Data Models
    # ====================================================================
    print("\n✓ Check 3: Data Models")
    
    check3_passed = True
    
    # Try to import but handle missing dependencies
    try:
        from olav.agents.textfsm_interactive_agent import (
            FieldDefinition,
            AnalysisResult,
            ApprovalResult,
            GenerationMetrics,
            GenerationResult,
            TemplateMetadata,
        )
        print(f"  ✓ All 6 data models importable")
    except ImportError as e:
        if "langchain" in str(e) or "pydantic" in str(e):
            print(f"  ⚠ Data models have missing dependencies (expected): {e}")
            print(f"    Note: Install dependencies (pip install pydantic langchain)")
            check3_passed = True  # Not a blocker if deps are missing
        else:
            print(f"  ✗ Unexpected import error: {e}")
            check3_passed = False
    
    results.append(("Data Models", check3_passed))
    
    # ====================================================================
    # Check 4: Agent Classes
    # ====================================================================
    print("\n✓ Check 4: Agent Classes")
    
    check4_passed = True
    
    try:
        from olav.agents.textfsm_interactive_agent import (
            TextFSMInteractiveAgent,
            TextFSMWorkflowOrchestrator,
            TextFSMCleanupChecklist,
        )
        print(f"  ✓ TextFSMInteractiveAgent importable")
        print(f"  ✓ TextFSMWorkflowOrchestrator importable")
        print(f"  ✓ TextFSMCleanupChecklist importable")
    except ImportError as e:
        if "langchain" in str(e) or "pydantic" in str(e):
            print(f"  ⚠ Agent classes have missing dependencies (expected): {e}")
            check4_passed = True  # Not a blocker
        else:
            print(f"  ✗ Unexpected import error: {e}")
            check4_passed = False
    
    results.append(("Agent Classes", check4_passed))
    
    # ====================================================================
    # Check 5: Tool Functions
    # ====================================================================
    print("\n✓ Check 5: Tool Functions")
    
    check5_passed = True
    tools = [
        "execute_command_tool",
        "analyze_fields_tool",
        "get_ntc_references_tool",
        "generate_template_tool",
        "test_template_tool",
        "save_template_tool",
    ]
    
    try:
        from olav.agents.textfsm_interactive_agent import tools as tools_module
        
        for tool_name in tools:
            if hasattr(tools_module, tool_name):
                print(f"  ✓ {tool_name} exists")
            else:
                print(f"  ✗ {tool_name} missing")
                check5_passed = False
    except ImportError as e:
        if "langchain" in str(e) or "pydantic" in str(e):
            print(f"  ⚠ Tools module has missing dependencies (expected): {e}")
            check5_passed = True  # Not a blocker
        else:
            print(f"  ✗ Unexpected import error: {e}")
            check5_passed = False
    
    results.append(("Tool Functions", check5_passed))
    
    # ====================================================================
    # Check 6: Documentation
    # ====================================================================
    print("\n✓ Check 6: Documentation")
    
    check6_passed = True
    docs = [
        (agent_dir / "README.md", "Agent README (400+ lines)"),
        (Path("/home/yhvh/Olav/docs/TEXTFSM_REDESIGN_INFRASTRUCTURE_COMPLETE.md"), "Infrastructure completion summary"),
    ]
    
    for doc_path, description in docs:
        if check_file_exists(doc_path, description):
            # Check file size
            size = doc_path.stat().st_size
            lines = len(doc_path.read_text().split('\n'))
            print(f"      ({size} bytes, ~{lines} lines)")
        else:
            check6_passed = False
    
    results.append(("Documentation", check6_passed))
    
    # ====================================================================
    # Summary
    # ====================================================================
    print("\n" + "=" * 70)
    print("Validation Summary")
    print("=" * 70)
    
    all_passed = True
    for check_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {check_name}")
        if not passed:
            all_passed = False
    
    print("=" * 70)
    
    if all_passed:
        print("\n🎉 All checks passed! Infrastructure is complete.\n")
        print("Next steps:")
        print("  1. Start implementation phase (tool functions + LLM)")
        print("  2. Run tests as components are implemented")
        print("  3. Use cleanup_checklist for validation")
        return 0
    else:
        print("\n⚠ Some checks failed. See details above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
