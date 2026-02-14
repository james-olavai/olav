# Command Learner Agent Specification

**Date**: 2026-02-15  
**Status**: 🟡 Design Phase  
**Version**: v2.1.0  
**Purpose**: Autonomous TextFSM template learning and generation

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Core Workflow](#core-workflow)
3. [Tools Design](#tools-design)
4. [NTC-Templates Integration](#ntc-templates-integration)
5. [Template Priority System](#template-priority-system)
6. [CLI Interface](#cli-interface)
7. [Reload Mechanism](#reload-mechanism)
8. [Implementation Details](#implementation-details)
9. [Testing Strategy](#testing-strategy)

---

## 🎯 Overview

### Purpose

The Command Learner Agent autonomously learns new network commands and generates accurate TextFSM templates. It's designed to be **portable** and **reusable** across projects.

### Key Features

✅ **Autonomous 6-step workflow** (LLM-guided)  
✅ **NTC-templates directory search** for high-quality references  
✅ **HITL approval** for field validation  
✅ **Custom + NTC template priority** (custom overrides NTC)  
✅ **Reload commands** to hot-reload new templates  
✅ **Portable design** - can be used in other projects

### Architecture

```
Command Learner Agent (Independent)
├── agent.py (DeepAgents core)
├── tools/
│   ├── execute_command.py      (Run command on device)
│   ├── analyze_output.py       (LLM field analysis)
│   ├── ntc_search.py           (Search NTC templates)
│   ├── template_viewer.py      (Browse NTC templates) ⭐ NEW
│   ├── generate_template.py    (LLM template generation)
│   └── save_template.py        (Save & register template)
├── state/
│   └── learner.duckdb          (Learning sessions)
└── reference/
    └── ntc_templates/          (NTC installation path)
```

---

## 🔄 Core Workflow

### 6-Step Autonomous Process

```
User: /learn_cmd show ip bgp summary --device R1

┌─────────────────────────────────────────────────────────────┐
│ Step 1: Execute Command                                     │
│ - Connect to device R1                                      │
│ - Execute "show ip bgp summary"                             │
│ - Capture raw output (with error handling)                  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Analyze Output (LLM)                                │
│ - Parse output structure                                    │
│ - Identify fields (router_id, neighbor, state, prefixes)    │
│ - Detect data types (string, int, IP address)               │
│ - Calculate coverage (% of output parsed)                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: User Approval (HITL) ⚠️                             │
│ Detected fields:                                            │
│   - router_id (string): 10.0.0.1                            │
│   - neighbor (IP): 10.0.1.1                                 │
│   - state (string): Established                             │
│   - prefixes (int): 1250                                    │
│ Approve? (y/n/modify):                                      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 4: Search NTC Templates ⭐ ENHANCED                    │
│ - Search ntc-templates installation                         │
│ - Score by: command match (30%), field coverage (50%),     │
│             platform match (20%)                            │
│ - Return top 3 matches with full template content           │
│ - Example: cisco_ios_show_ip_bgp_summary.textfsm (score: 0.85) │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 5: Generate Template (LLM)                             │
│ - Use approved fields + NTC references                      │
│ - Generate TextFSM template                                 │
│ - Test template against actual output                       │
│ - Iterate if parse fails (max 3 attempts)                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 6: Save & Register Template                            │
│ - Save to .olav/templates/custom/                           │
│ - Update index file                                         │
│ - Create metadata.json                                      │
│ - Trigger reload (hot-reload templates) ⭐ NEW              │
└─────────────────────────────────────────────────────────────┘
                          ↓
✅ Template ready: cisco_ios_show_ip_bgp_summary.textfsm
```

---

## 🛠️ Tools Design

### Tools Summary

```python
# 7 Tools for autonomous TextFSM template learning
tools = [
    execute_command,           # Tool 1: Execute command on device
    analyze_output,            # Tool 2: LLM-powered field detection
    search_ntc_templates,      # Tool 3: Enhanced NTC search (metadata only) ⭐
    read_template_file,        # Tool 4: Read specific template content (NEW) ⭐
    browse_ntc_directory,      # Tool 5: Browse NTC templates
    generate_template,         # Tool 6: LLM-powered template generation
    save_template,             # Tool 7: Save + auto-reload
]

# All tools location: .olav/skills/command_learner/tools/
# ✅ Portable: Can copy entire .olav/skills/command_learner/ to other projects
# ⚠️ Token optimization: search returns metadata, read loads full content only when needed
```

### Tool 1: Execute Command

```python
@tool
def execute_command(device: str, command: str, timeout: int = 60) -> dict:
    """Execute command on network device.
    
    Args:
        device: Device name or IP (from inventory)
        command: Command to execute (e.g., "show ip bgp summary")
        timeout: Command timeout in seconds (default: 60)
    
    Returns:
        {
            "device": "R1",
            "command": "show ip bgp summary",
            "output": "BGP router identifier...",
            "success": true,
            "error": null,
            "platform": "cisco_ios",
            "execution_time": 1.24
        }
    
    Example:
        execute_command("R1", "show ip bgp summary")
    """
    # Implementation uses existing nornir_execute from .olav/tools/network.py
```

### Tool 2: Analyze Output

```python
@tool
def analyze_output(command: str, output: str, platform: str) -> dict:
    """Analyze command output and identify fields (LLM-powered).
    
    Args:
        command: Original command executed
        output: Raw command output
        platform: Device platform (e.g., cisco_ios)
    
    Returns:
        {
            "fields": [
                {
                    "name": "router_id",
                    "type": "string",
                    "example": "10.0.0.1",
                    "description": "BGP router identifier"
                },
                {
                    "name": "neighbor",
                    "type": "ipv4",
                    "example": "10.0.1.1",
                    "description": "BGP neighbor IP"
                }
            ],
            "coverage_estimate": 0.85,
            "structure": "tabular"
        }
    
    LLM Prompt:
        Analyze this network command output and identify all fields...
    """
```

### Tool 3: NTC Search (Enhanced) ⭐

```python
@tool
def search_ntc_templates(
    platform: str,
    command: str,
    approved_fields: list[str],
    limit: int = 5
) -> dict:
    """Search NTC-templates for similar commands.
    
    Args:
        platform: Device platform (e.g., cisco_ios)
        command: Command to search for
        approved_fields: Fields user wants to extract
        limit: Maximum number of results (default: 5)
    
    Returns:
        {
            "ntc_path": "/path/to/venv/site-packages/ntc_templates/templates",
            "results": [
                {
                    "template_name": "cisco_ios_show_ip_bgp_summary.textfsm",
                    "template_path": "/path/to/ntc_templates/templates/cisco_ios_show_ip_bgp_summary.textfsm",  ⭐
                    "score": 0.85,
                    "command_match": ["bgp", "summary"],
                    "field_coverage": 0.75,  # 3 of 4 fields found
                    "fields_found": ["router_id", "neighbor", "state"],  # Matched fields
                    "fields_missing": ["uptime"],  # User wanted but not in template
                    "platform_match": true,
                    "file_size": 2048  # bytes
                },
                ...
            ],
            "total_found": 15,
            "search_time": 0.12
        }
    
    Enhancement: Returns metadata only (NO full content) to save tokens.
    Use read_template_file() to get full content of selected templates.
    
    Location: .olav/skills/command_learner/tools/ntc_search.py
    """
    # Implementation in .olav/skills/command_learner/tools/ntc_search.py
```

### Tool 4: Read Template File (NEW) ⭐

```python
@tool
def read_template_file(template_path: str) -> dict:
    """Read full TextFSM template content.
    
    Args:
        template_path: Full path to template file (from search_ntc_templates)
    
    Returns:
        {
            "template_name": "cisco_ios_show_ip_bgp_summary.textfsm",
            "content": """Value ROUTER_ID (\\S+)
            Value LOCAL_AS (\\d+)
            Value NEIGHBOR (\\S+)
            ...""",
            "size_bytes": 2048,
            "line_count": 45,
            "fields": ["ROUTER_ID", "LOCAL_AS", "NEIGHBOR", "STATE"],
            "header": "Value Filldown ROUTER_ID..."  # First 3 lines preview
        }
    
    Purpose: Get full template content ONLY for selected templates.
    Avoids loading all templates in search results.
    
    Workflow:
    1. search_ntc_templates() returns 5 results with paths
    2. LLM/User selects top 1-2 most relevant
    3. read_template_file() loads only selected ones
    → Saves tokens (5 templates metadata vs 1-2 full templates)
    
    Location: .olav/skills/command_learner/tools/template_reader.py
    """
    path = Path(template_path)
    if not path.exists():
        return {"error": f"Template not found: {template_path}"}
    
    content = path.read_text()
    fields = extract_textfsm_fields(content)  # Parse Value lines
    
    return {
        "template_name": path.name,
        "content": content,
        "size_bytes": path.stat().st_size,
        "line_count": len(content.splitlines()),
        "fields": fields,
        "header": "\n".join(content.splitlines()[:3])
    }
```

### Tool 5: Browse NTC Directory (NEW) ⭐

```python
@tool
def browse_ntc_directory(platform: str = None, limit: int = 10) -> dict:
    """Browse NTC-templates directory structure.
    
    Args:
        platform: Filter by platform (optional)
        limit: Maximum entries to return
    
    Returns:
        {
            "ntc_path": "/path/to/ntc_templates/templates",
            "total_templates": 856,
            "platforms": ["cisco_ios", "cisco_nxos", "arista_eos", ...],
            "templates": [
                {
                    "name": "cisco_ios_show_version.textfsm",
                    "size_bytes": 2048,
                    "commands": ["show version"],
                    "last_modified": "2024-01-15"
                },
                ...
            ]
        }
    
    Purpose: Let agent explore NTC templates before searching
    
    Location: .olav/skills/command_learner/tools/ntc_browser.py
    """
```

### Tool 6: Generate Template

```python
@tool
def generate_template(
    command: str,
    platform: str,
    approved_fields: list[dict],
    output_sample: str,
    ntc_references: list[dict]
) -> dict:
    """Generate TextFSM template (LLM-powered).
    
    Args:
        command: Command to create template for
        platform: Device platform
        approved_fields: Fields from Step 3 (user-approved)
        output_sample: Actual command output for testing
        ntc_references: Top NTC templates from Step 4
    
    Returns:
        {
            "template": "Value ROUTER_ID (\\S+)\\n...",
            "filename": "cisco_ios_show_ip_bgp_summary.textfsm",
            "test_result": {
                "success": true,
                "parsed_records": 5,
                "coverage": 0.92
            },
            "iteration": 1  # 1-3 attempts
        }
    
    LLM Prompt includes:
    - Approved fields
    - NTC reference templates (full content)
    - Output sample for testing
    - TextFSM best practices
    
    Location: .olav/skills/command_learner/tools/template_generator.py
    """
```

### Tool 7: Save Template

```python
@tool
def save_template(
    template: str,
    filename: str,
    metadata: dict,
    trigger_reload: bool = True
) -> dict:
    """Save template and trigger reload.
    
    Args:
        template: TextFSM template content
        filename: Template filename (e.g., cisco_ios_show_ip_bgp_summary.textfsm)
        metadata: Metadata dict (command, platform, fields, etc.)
        trigger_reload: Trigger hot-reload (default: True) ⭐
    
    Returns:
        {
            "saved_path": ".olav/templates/custom/cisco_ios_show_ip_bgp_summary.textfsm",
            "metadata_path": ".olav/templates/custom/cisco_ios_show_ip_bgp_summary.metadata.json",
            "index_updated": true,
            "reload_triggered": true ⭐
        }
    
    Side effects:
    1. Save template to .olav/templates/custom/
    2. Save metadata.json
    3. Update index file
    4. Trigger reload_commands() ⭐
    
    Location: .olav/skills/command_learner/tools/template_saver.py
    """
```

---

## 📚 NTC-Templates Integration

### Finding NTC Installation

```python
def find_ntc_templates_path() -> Path:
    """Locate ntc-templates installation."""
    try:
        import ntc_templates
        return Path(ntc_templates.__file__).parent / "templates"
    except ImportError:
        raise RuntimeError("ntc-templates not installed. Run: pip install ntc-templates")

# Example path:
# /home/yhvh/Olav/.venv/lib/python3.12/site-packages/ntc_templates/templates/
```

### NTC Directory Structure

```
ntc_templates/templates/
├── index                              (Template index for fast lookup)
├── cisco_ios_show_version.textfsm
├── cisco_ios_show_ip_bgp.textfsm
├── cisco_ios_show_ip_bgp_summary.textfsm
├── cisco_nxos_show_version.textfsm
└── ... (856 templates total)
```

### Enhanced Search Algorithm

```python
def score_template_match(
    template_name: str,
    template_content: str,
    platform: str,
    command: str,
    approved_fields: list[str]
) -> float:
    """
    Scoring factors:
    - Command keyword match (30%): "show ip bgp summary" → ["show", "ip", "bgp", "summary"]
    - Field coverage (50%): If template defines 3 of 4 user fields → 0.75 * 0.5
    - Platform match (20%): cisco_ios in filename → +0.2
    
    Example:
        - Template: cisco_ios_show_ip_bgp_summary.textfsm
        - Command: "show ip bgp summary"
        - Fields: ["router_id", "neighbor", "state", "prefixes"]
        
        Keyword match: 4/4 = 1.0 → 0.3
        Field coverage: 3/4 = 0.75 → 0.375
        Platform match: yes → 0.2
        Total: 0.875 (87.5%)
    """
```

### Example NTC Reference Output

```json
{
  "results": [
    {
      "template_name": "cisco_ios_show_ip_bgp_summary.textfsm",
      "score": 0.875,
      "content": "Value ROUTER_ID (\\S+)\nValue BGP_NEIGH (\\S+)\nValue STATE_PFXRCD (\\S+)\n\nStart\n  ^BGP router identifier ${ROUTER_ID}\n  ^${BGP_NEIGH}\\s+\\d+\\s+\\d+\\s+\\d+\\s+\\d+\\s+\\d+\\s+${STATE_PFXRCD} -> Record\n"
    }
  ]
}
```

---

## 🎨 Template Priority System

### Current Implementation (Verified ✅)

```python
# File: .olav/skills/shared/tools/network_parser.py (lines 115-135)

# Priority 1: Custom config directory (highest priority)
custom_textfsm_dir = Path(".olav/config/textfsm")
if custom_textfsm_dir.exists():
    os.environ["NET_TEXTFSM"] = str(custom_textfsm_dir)

# Priority 2: Default .olav/templates directory
elif Path(".olav/templates").exists():
    os.environ["NET_TEXTFSM"] = str(Path(".olav/templates"))

# Priority 3: NTC-templates (pip installed, fallback)
# Netmiko automatically searches ntc-templates if NET_TEXTFSM not set
```

### Priority Table

| Priority | Directory | Purpose | Source |
|----------|-----------|---------|--------|
| 1 | `.olav/config/textfsm/` | User overrides | Manual edits |
| 2 | `.olav/templates/custom/` | **Command Learner output** ⭐ | Generated by this agent |
| 3 | `.olav/templates/` | Legacy/mixed | Existing templates |
| 4 | `ntc_templates/templates/` | Fallback | pip package |

### Template Lookup Order (Example)

```
User executes: "show ip bgp summary" on cisco_ios

Lookup sequence:
1. .olav/config/textfsm/cisco_ios_show_ip_bgp_summary.textfsm     (custom override)
2. .olav/templates/custom/cisco_ios_show_ip_bgp_summary.textfsm   (learner generated) ⭐
3. .olav/templates/cisco_ios_show_ip_bgp_summary.textfsm          (legacy)
4. ntc_templates/templates/cisco_ios_show_ip_bgp_summary.textfsm  (NTC official)

✅ First match wins (custom overrides NTC)
```

### Verification in DB Import & Snapshot

**Check 1: DB Import Process**
```python
# File: .olav/tools/database.py or import logic
# Verify: Custom templates used before NTC templates

# Expected behavior:
execute_sql_with_parse(command="show ip bgp summary", device="R1")
→ Uses .olav/templates/custom/cisco_ios_show_ip_bgp_summary.textfsm (if exists)
→ Falls back to NTC (if custom doesn't exist)
```

**Check 2: Snapshot Process**
```python
# File: .olav/skills/network-snapshot/tools/nornir_execute.py
# Verify: Snapshots use same priority system

# Expected behavior:
create_snapshot(commands=["show version", "show ip bgp"])
→ Custom templates for both commands (if exist)
→ Mixed: custom for one, NTC for another (if partial)
→ All NTC (if no custom templates)
```

**Status**: ✅ Priority system already implemented correctly in `network_parser.py`

---

## 💻 CLI Interface

### Command Format

```bash
# Basic usage
$ olav /learn_cmd "show ip bgp summary" --device R1

# With platform override
$ olav /learn_cmd "show ip route" --device R1 --platform cisco_ios

# Interactive mode
$ olav
> /learn_cmd show version --device R1
[6-step workflow begins]

> Detected fields:
  - version (string): "15.2(4)M"
  - uptime (string): "2 days, 4 hours"
  Approve? (y/n/modify):
> y
[continues...]
```

### Command Aliases

```bash
/learn_cmd    # Full command
/learn        # Alias
/lc           # Short alias
```

### Options

```bash
--device, -d    # Target device (required)
--platform, -p  # Override platform (optional, auto-detected)
--timeout, -t   # Command timeout (default: 60s)
--no-interact   # Skip HITL approval (use all detected fields)
--dry-run       # Generate template but don't save
```

---

## 🔄 Reload Mechanism

### Problem Statement

**Current**: After generating a new template, must restart OLAV for it to be recognized.  
**Solution**: Hot-reload templates without restarting the process.

### Design: `reload_commands()` Function

```python
@tool
def reload_commands() -> dict:
    """Hot-reload TextFSM templates and command definitions.
    
    Reloads:
    1. TextFSM index file (.olav/templates/index)
    2. Command whitelist (.olav/config/allowed_commands.json)
    3. Command blacklist (.olav/config/blacklisted_commands.json)
    4. Template metadata (.olav/templates/custom/*.metadata.json)
    
    Returns:
        {
            "reloaded": {
                "templates": 23,
                "whitelisted_commands": 150,
                "blacklisted_patterns": 8
            },
            "new_templates": [
                "cisco_ios_show_ip_bgp_summary.textfsm"
            ],
            "errors": []
        }
    
    Usage:
        $ olav /admin reload-commands
        ✅ Reloaded 23 templates, 150 whitelisted commands
    """
    # Implementation:
    # 1. Re-read index file
    # 2. Refresh in-memory command registry
    # 3. Update Netmiko template cache
```

### Implementation Location

```
File: src/olav/core/command_registry.py (new file)

class CommandRegistry:
    """Global registry for commands and templates."""
    
    _instance = None
    _templates: dict[str, Path] = {}
    _whitelist: set[str] = set()
    _blacklist: list[str] = []
    
    @classmethod
    def reload(cls):
        """Hot-reload all command definitions."""
        cls._load_templates()
        cls._load_whitelist()
        cls._load_blacklist()
```

### Auto-reload on Template Save

```python
# In save_template() tool:
def save_template(..., trigger_reload=True):
    # Save template file
    template_path.write_text(template_content)
    
    # Update index
    update_index_file(template_path)
    
    # Auto-reload (if enabled)
    if trigger_reload:
        from olav.core.command_registry import CommandRegistry
        CommandRegistry.reload()
        logger.info(f"Auto-reloaded templates (new: {template_path.name})")
```

### CLI Commands for Reload

```bash
# Admin command
$ olav /admin reload-commands
✅ Reloaded 23 templates, 150 commands

# Alias
$ olav /admin reload
```

---

## 🔧 Implementation Details

### File Locations

```
src/olav/agents/
└── command_learner_agent.py          (Main agent definition)

.olav/skills/command_learner/
├── tools/
│   ├── execute_command.py
│   ├── analyze_output.py
│   ├── ntc_search.py                 (Enhanced with full content)
│   ├── template_viewer.py            (NEW)
│   ├── generate_template.py
│   └── save_template.py
├── prompts/
│   ├── analyze_output.md             (LLM prompt for Step 2)
│   └── generate_template.md          (LLM prompt for Step 5)
└── SKILL.md                           (Skill configuration)

src/olav/core/
└── command_registry.py                (NEW - reload mechanism)

.olav/databases/
└── command_learner.duckdb             (Agent state)

.olav/templates/custom/
├── index                              (Template index)
└── (generated templates)
```

### Agent Definition

```python
# src/olav/agents/command_learner_agent.py

from deepagents import create_deep_agent
from langchain.tools import tool

# Import tools
from .tools.execute_command import execute_command
from .tools.analyze_output import analyze_output
from .tools.ntc_search import search_ntc_templates
from .tools.template_viewer import browse_ntc_directory
from .tools.generate_template import generate_template
from .tools.save_template import save_template

def create_command_learner_agent():
    """Create independent Command Learner agent."""
    
    # Load NTC-templates path as reference
    ntc_path = find_ntc_templates_path()
    
    return create_deep_agent(
        name="CommandLearner",
        tools=[
            execute_command,
            analyze_output,
            search_ntc_templates,
            browse_ntc_directory,
            generate_template,
            save_template,
        ],
        skills_path=".olav/skills/command_learner",
        system_prompt=f"""
        You are a TextFSM template learning assistant.
        
        Your task: Learn new network commands and generate accurate TextFSM templates.
        
        NTC-Templates Reference: {ntc_path}
        (856 high-quality templates available for reference)
        
        Workflow:
        1. Execute command on device
        2. Analyze output and identify fields (use LLM)
        3. Get user approval for fields (HITL)
        4. Search NTC templates for similar commands
        5. Generate TextFSM template (use NTC as reference)
        6. Save template and trigger reload
        
        Quality standards:
        - Parse coverage > 80%
        - All approved fields must be extracted
        - Template must be testable against actual output
        - Follow TextFSM best practices
        """,
        checkpointer=DuckDBSaver(".olav/databases/command_learner.duckdb"),
        middleware=[
            TodoListMiddleware(),  # 6-step planning
            HumanInTheLoopMiddleware(
                approval_tools=["generate_template"]  # Step 3 needs user input
            )
        ]
    )

# Create singleton instance
command_learner_agent = create_command_learner_agent()
```

---

## 🧪 Testing Strategy

### E2E Test Cases

```python
# tests/e2e/test_command_learner_agent.py

@pytest.mark.e2e
async def test_learn_simple_command():
    """Test learning a simple command with clear output structure."""
    result = await command_learner_agent.ainvoke(
        "/learn_cmd show version --device R1"
    )
    
    assert result.success
    assert Path(".olav/templates/custom/cisco_ios_show_version.textfsm").exists()

@pytest.mark.e2e
async def test_ntc_reference_used():
    """Verify NTC templates are used as reference."""
    # Mock to capture LLM prompt
    with capture_llm_prompts() as prompts:
        await command_learner_agent.ainvoke(
            "/learn_cmd show ip bgp summary --device R1"
        )
    
    # Verify NTC template content in prompt
    assert "cisco_ios_show_ip_bgp_summary.textfsm" in prompts[0]
    assert "Value ROUTER_ID" in prompts[0]

@pytest.mark.e2e
async def test_custom_template_priority():
    """Verify custom templates override NTC."""
    # Generate custom template
    await command_learner_agent.ainvoke("/learn_cmd show version --device R1")
    
    # Execute command - should use custom template
    result = execute_with_textfsm(nr, "R1", "show version")
    
    # Verify custom template was used (check logs or template path)
    assert ".olav/templates/custom/cisco_ios_show_version.textfsm" in result.log

@pytest.mark.e2e
async def test_reload_commands():
    """Test hot-reload after template generation."""
    # Generate template
    await command_learner_agent.ainvoke("/learn_cmd show ip route --device R1")
    
    # Reload should be automatic
    # Verify new template is immediately usable
    result = execute_with_textfsm(nr, "R1", "show ip route")
    assert result.success
```

---

## 📋 Acceptance Criteria

### Functional
- ✅ Can learn new commands and generate templates
- ✅ NTC templates used as high-quality reference
- ✅ HITL approval works correctly
- ✅ Custom templates override NTC (priority system)
- ✅ Templates are immediately usable after generation (reload)

### Quality
- ✅ Template parse coverage > 80%
- ✅ All approved fields extracted correctly
- ✅ TextFSM syntax valid
- ✅ Testable against actual output

### Performance
- ✅ 6-step workflow < 2 minutes end-to-end
- ✅ NTC search < 1 second
- ✅ Reload < 100ms

### Portability
- ✅ Can be extracted as standalone package
- ✅ Zero dependency on main OLAV agent
- ✅ Independent state (learner.duckdb)

---

## 🚀 Next Steps

1. **Phase 1.1**: Enhance ntc_search.py to return full template content
2. **Phase 1.2**: Create template_viewer.py tool
3. **Phase 1.3**: Implement reload mechanism (command_registry.py)
4. **Phase 1.4**: Create command_learner_agent.py
5. **Phase 1.5**: E2E testing (8 test cases)
6. **Phase 1.6**: Documentation and user guide

---

**Version**: v2.1.0-design  
**Author**: OLAV Architecture Team  
**Last Updated**: 2026-02-15
