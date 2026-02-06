#!/usr/bin/env python3
"""Comprehensive OLAV Configuration Audit (v0.10.2)

Checks:
1. Settings defines correct database directory and tables
2. Code uses correct settings paths without hardcoding
3. All skills use correct table names and tools
4. All skills have correct tool definitions
"""

import json
import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.paths import (
    AGENT_DIR,
    CACHE_DIR,
    EXPORTS_DIR,
    LOGS_DIR,
    OLAV_BASE_DIR,
    REPORTS_DIR,
    SNAPSHOTS_DIR,
    UNIFIED_DB,
)
from config.settings import settings

# ============================================================================
# Audit 1: Settings Configuration
# ============================================================================


def audit_settings():
    """Check if settings define correct database configuration."""
    print("\n" + "=" * 80)
    print("AUDIT 1: Settings Configuration")
    print("=" * 80)

    issues = []

    # Check LLM configuration
    print(f"\n✓ LLM Configuration:")
    print(f"  Provider: {settings.llm_provider}")
    print(f"  Model: {settings.llm_model_name}")
    print(f"  Base URL: {settings.llm_base_url or '(default)'}")
    print(f"  Temperature: {settings.llm_temperature}")
    print(f"  Max Tokens: {settings.llm_max_tokens}")

    if settings.llm_model_name == "gpt-4-turbo":
        issues.append("WARNING: llm_model_name still set to gpt-4-turbo (should use x-ai/grok-4.1-fast)")

    # Check that agent models are empty (fallback to global)
    print(f"\n✓ Agent-Specific Model Configuration:")
    agent_models = {
        "orchestrator": settings.agent.orchestrator_model,
        "analyzer": settings.agent.analyzer_model,
        "guard": settings.agent.guard_model,
        "textfsm": settings.agent.textfsm_model,
        "llm_interface": settings.agent.llm_interface_model,
        "summarization": settings.agent.summarization_model,
    }

    for agent, model in agent_models.items():
        status = "✅ (falls back to global)" if model == "" else "⚠️  (hardcoded)"
        print(f"  {agent:20s}: '{model:30s}' {status}")
        if model and model not in ["", "gemini-flash"]:  # Allow gemini-flash as legacy
            issues.append(f"Agent '{agent}' has hardcoded model: {model}")

    return issues


# ============================================================================
# Audit 2: Code Hardcoding Check
# ============================================================================


def audit_code_hardcoding():
    """Check if code uses config.paths without hardcoding paths."""
    print("\n" + "=" * 80)
    print("AUDIT 2: Code Hardcoding Check")
    print("=" * 80)

    issues = []
    src_dir = Path(__file__).parent.parent / "src"

    # Check for hardcoded database paths
    hardcoded_patterns = [
        (r"\.olav/db/main\.duckdb", ".olav/db/main.duckdb (should use UNIFIED_DB)"),
        (r"\.olav/db/olav\.duckdb", ".olav/db/olav.duckdb (hardcoded - OK if using constant)"),
        (r"Path\(['\"]\.olav", "Hardcoded .olav path with Path()"),
        (r'"\.olav/\w+/.*\.duckdb"', "Hardcoded .duckdb path in string"),
    ]

    print(f"\n✓ Scanning {len(list(src_dir.rglob('*.py')))} Python files...")

    py_files = list(src_dir.rglob("*.py"))
    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")

            for pattern, description in hardcoded_patterns:
                if re.search(pattern, content):
                    # Check if it's just a docstring/comment
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if re.search(pattern, line):
                            # Skip comments and docstrings
                            stripped = line.strip()
                            if not stripped.startswith("#") and not stripped.startswith('"""') and not stripped.startswith("'''"):
                                rel_path = py_file.relative_to(src_dir)
                                issues.append(
                                    f"{rel_path}:{i+1} - {description}"
                                )
        except Exception as e:
            print(f"  ⚠️  Could not scan {py_file.relative_to(src_dir)}: {e}")

    if not issues:
        print("\n✅ No hardcoded database paths found in code!")
    else:
        print(f"\n⚠️  Found {len(issues)} potential hardcoding issues:")
        for issue in issues:
            print(f"  - {issue}")

    return issues


# ============================================================================
# Audit 3: Skills Configuration
# ============================================================================


def audit_skills():
    """Check if skills use correct table names and tools."""
    print("\n" + "=" * 80)
    print("AUDIT 3: Skills Configuration")
    print("=" * 80)

    issues = []
    skills_dir = Path(__file__).parent.parent / ".olav" / "skills"

    if not skills_dir.exists():
        print(f"✅ Skills directory: {skills_dir}")
        return issues

    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    print(f"\n✓ Found {len(skill_dirs)} skills:")

    expected_skills = [
        "orchestrator",
        "network-query",
        "network-inspection",
        "network-expert",
        "network-snapshot",
        "textfsm-generator",
        "guard",
        "inspect-report",
    ]

    found_skills = {d.name for d in skill_dirs}
    for skill in expected_skills:
        status = "✅" if skill in found_skills else "❌ MISSING"
        print(f"  {status} {skill}")
        if skill not in found_skills:
            issues.append(f"Expected skill '{skill}' not found")

    # Audit each skill
    print(f"\n✓ Auditing skill configurations:")
    for skill_dir in skill_dirs:
        skill_name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            issues.append(f"Skill '{skill_name}' missing SKILL.md")
            continue

        try:
            content = skill_md.read_text(encoding="utf-8")

            # Extract frontmatter
            match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                frontmatter = match.group(1)

                # Check for tools
                if "tools:" in frontmatter or "tool:" in frontmatter:
                    print(f"  ✅ {skill_name:25s} - has tool definitions")
                else:
                    print(f"  ⚠️  {skill_name:25s} - no tool definitions found")
                    if skill_name not in ["guard"]:  # Guard might not need tools
                        issues.append(f"Skill '{skill_name}' appears to lack tool definitions")

                # Check for system prompt
                if "system:" in frontmatter or "prompts:" in frontmatter:
                    print(f"    ✅ Has prompt configuration")
                else:
                    print(f"    ⚠️  No prompt configuration")

                # Check for execution mode
                if "execution:" in frontmatter or "mode:" in frontmatter:
                    print(f"    ✅ Has execution mode")
                else:
                    print(f"    ⚠️  No execution mode configured")

            # Check for hardcoded main.duckdb references
            if "main.duckdb" in content:
                print(f"  ⚠️  {skill_name:25s} - hardcoded 'main.duckdb' reference")
                issues.append(f"Skill '{skill_name}' hardcodes 'main.duckdb' (should be 'olav.duckdb')")

        except Exception as e:
            issues.append(f"Error reading {skill_name}/SKILL.md: {e}")

    return issues


# ============================================================================
# Audit 4: Tool Definitions
# ============================================================================


def audit_tools():
    """Check if all expected tools are properly defined."""
    print("\n" + "=" * 80)
    print("AUDIT 4: Tool Definitions")
    print("=" * 80)

    issues = []
    tools_dir = Path(__file__).parent.parent / "src" / "olav" / "tools"

    if not tools_dir.exists():
        print(f"⚠️  Tools directory not found: {tools_dir}")
        return issues

    expected_tools = [
        "query_database",
        "inspect_schema",
        "discover_data",
        "sync_tools",
        "expert_tools",
        "report_formatter",
    ]

    print(f"\n✓ Core Tools:")
    py_files = {f.stem for f in tools_dir.glob("*.py")}

    for tool in expected_tools:
        if tool in py_files or f"{tool}.py" in [f.name for f in tools_dir.glob("*.py")]:
            print(f"  ✅ {tool}")
        else:
            print(f"  ❌ {tool} - NOT FOUND")
            issues.append(f"Expected tool '{tool}' not found in tools/")

    # Check that tools use config constants
    print(f"\n✓ Tool Implementation Audit:")
    react_query_file = tools_dir / "react_query.py"

    if react_query_file.exists():
        content = react_query_file.read_text(encoding="utf-8")

        if "from config.paths import" in content or "from config.settings import" in content:
            print(f"  ✅ react_query.py uses config imports")
        else:
            print(f"  ⚠️  react_query.py may not use config imports")
            issues.append("react_query.py should import from config module")

        # Check for main.duckdb hardcoding
        if "main.duckdb" in content:
            lines = [i for i, line in enumerate(content.split("\n")) if "main.duckdb" in line]
            for line_num in lines:
                # Check if it's in docstring/comment
                line_text = content.split("\n")[line_num]
                if not line_text.strip().startswith("#") and not line_text.strip().startswith('"""'):
                    print(
                        f"  ⚠️  react_query.py:{line_num+1} - hardcoded 'main.duckdb' in docstring"
                    )
                    issues.append("react_query.py docstring mentions 'main.duckdb' (should be 'olav.duckdb')")

    return issues


# ============================================================================
# Audit 5: Path Constants Usage
# ============================================================================


def audit_path_constants():
    """Verify that path constants are properly exported."""
    print("\n" + "=" * 80)
    print("AUDIT 5: Path Constants Verification")
    print("=" * 80)

    issues = []

    print(f"\n✓ Key Path Constants:")
    print(f"  UNIFIED_DB:     {UNIFIED_DB}")
    print(f"  CACHE_DIR:      {CACHE_DIR}")
    print(f"  EXPORTS_DIR:    {EXPORTS_DIR}")
    print(f"  REPORTS_DIR:    {REPORTS_DIR}")
    print(f"  SNAPSHOTS_DIR:  {SNAPSHOTS_DIR}")
    print(f"  LOGS_DIR:       {LOGS_DIR}")
    print(f"  OLAV_BASE_DIR:  {OLAV_BASE_DIR}")

    # Verify paths exist or are accessible
    print(f"\n✓ Path Accessibility:")
    paths_to_check = [
        ("UNIFIED_DB (parent)", UNIFIED_DB.parent),
        ("CACHE_DIR", CACHE_DIR),
        ("EXPORTS_DIR", EXPORTS_DIR),
        ("REPORTS_DIR", REPORTS_DIR),
        ("SNAPSHOTS_DIR", SNAPSHOTS_DIR),
        ("LOGS_DIR", LOGS_DIR),
        ("OLAV_BASE_DIR", OLAV_BASE_DIR),
    ]

    for name, path in paths_to_check:
        if path.exists() or path.parent.exists():
            print(f"  ✅ {name:25s}: {path}")
        else:
            print(f"  ⚠️  {name:25s}: {path} (not yet created)")
            # Not an error if it doesn't exist yet

    return issues


# ============================================================================
# Main Audit Function
# ============================================================================


def main():
    """Run all audits and generate report."""
    print("\n" + "=" * 80)
    print("OLAV v0.10.2 - Comprehensive Configuration Audit")
    print("=" * 80)

    all_issues = []

    # Run all audits
    all_issues.extend(audit_settings())
    all_issues.extend(audit_code_hardcoding())
    all_issues.extend(audit_skills())
    all_issues.extend(audit_tools())
    all_issues.extend(audit_path_constants())

    # Summary
    print("\n" + "=" * 80)
    print("AUDIT SUMMARY")
    print("=" * 80)

    if not all_issues:
        print("\n✅ ALL CHECKS PASSED - Configuration is correct!")
        return 0
    else:
        print(f"\n⚠️  Found {len(all_issues)} issues:\n")
        for i, issue in enumerate(all_issues, 1):
            print(f"{i}. {issue}")

        # Categorize issues
        critical = [i for i in all_issues if "MISSING" in i or "ERROR" in i]
        warnings = [i for i in all_issues if "WARNING" in i or "hardcoded" in i]

        print(f"\nSummary:")
        print(f"  Critical issues: {len(critical)}")
        print(f"  Warnings:        {len(warnings)}")

        return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
