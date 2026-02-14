# Admin Agent Specification

**Date**: 2026-02-15  
**Status**: 🟡 Design Phase  
**Version**: v2.1.0 (Ultra-Minimalist)  
**Purpose**: Minimalist system administrator with full OLAV documentation as reference

**🎯 Key Optimization (2026-02-15 PM)**:
- Reduced from 8 tools → 4 tools (50% reduction)
- Philosophy: "代码即工具" - Use shell commands directly, don't create abstractions
- execute_command replaces: list_files, search_code, git_operations, execute_python, backup_restore
- Result: 95% less code (1,200 → 200 lines), more flexible, transferable knowledge

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Design Philosophy](#design-philosophy)
3. [Documentation as Reference](#documentation-as-reference)
4. [Tools Design](#tools-design)
5. [CLI Interface](#cli-interface)
6. [Security & HITL](#security--hitl)
7. [Implementation Details](#implementation-details)
8. [Testing Strategy](#testing-strategy)

---

## 🎯 Overview

### Purpose

The Admin Agent is a **minimalist system administrator** that maintains and extends OLAV. Instead of complex abstractions, it's given **full OLAV documentation as reference** and uses simple, powerful tools.

### Key Principles

✅ **Minimalist Design** - No complex abstractions, direct tools  
✅ **Documentation as Knowledge** - All dev_docs/ as LLM context  
✅ **Self-Service** - Can modify skills, create tools, fix bugs  
✅ **Safe by Default** - HITL approval for dangerous operations  
✅ **Portable** - Can manage other Python projects (not just OLAV)

### What Makes It Different

| Traditional Admin Agent | OLAV Admin Agent |
|------------------------|------------------|
| Pre-defined admin tools | Generic filesystem/subprocess tools |
| Hard-coded workflows | LLM decides workflow based on docs |
| Limited to admin tasks | Can modify code, create features |
| Project-specific | Portable to any Python project |

---

## 🧠 Design Philosophy

### "给它说明书，让它自己学"

Instead of teaching the agent how to do every task:
```python
# ❌ Traditional: Pre-define every admin operation
tools = [
    create_skill_tool,         # 100 lines
    modify_skill_tool,         # 150 lines
    backup_database_tool,      # 80 lines
    # ... 20 more specialized tools
]

# ✅ Minimalist: Give it generic tools + documentation
tools = [
    read_file,          # Read any file
    write_file,         # Write any file
    execute_command,    # Run ANY shell command (replaces 5 tools)
    execute_olav,       # Run OLAV commands (convenience wrapper)
]

system_prompt = f"""
Developer Reference (Single Document, ~1,200 lines):
{load_developer_reference()}

You have full OLAV Developer Reference. Learn how to:
- Create skills (§ Skill Development)
- Develop tools (§ Tool Development)
- Fix bugs (§ Debugging Guide)
- Test changes (§ Testing)

Use execute_command for everything:
- List files: execute_command("find dir -name '*.py'")
- Search: execute_command("grep -r 'pattern' dir")
- Git: execute_command("git commit -m 'msg'")
"""
```

### Example: Creating a New Skill

```
User: "Create a monitoring skill that checks device health"

Traditional Agent:
→ Calls pre-defined create_skill_tool()
→ Limited to template-based skill creation
→ Can't handle custom requirements

Admin Agent:
→ Reads Developer Reference § Skill Development
→ Uses read_file to check existing skills for examples  
→ Creates SKILL.md with proper structure
→ Creates tools directory
→ Tests with execute_olav("ask 'test query'")
```

---

## 📚 Developer Reference as Knowledge Base

### Single Reference Document

```python
def load_developer_reference() -> str:
    """Load OLAV Developer Reference as LLM context.
    
    Returns:
        DEVELOPER_REFERENCE.md content (~1,200 lines, 50 KB)
    """
    ref_path = Path("dev_docs/DEVELOPER_REFERENCE.md")
    return ref_path.read_text()
```

### Developer Reference Structure

```
DEVELOPER_REFERENCE.md (~1,200 lines):

1. 🏗️ Architecture
   - Project structure
   - Core concepts (Skills, Tools, Agents)
   - Design patterns

2. 📝 Skill Development  
   - Creating skills
   - SKILL.md format
   - Skill examples

3. 🔧 Tool Development
   - Tool template
   - Common patterns (DB, network, file)
   - Best practices

4. ⚙️ Configuration
   - Settings location
   - config/settings.py
   - config/paths.py

5. 🐛 Debugging Guide
   - Common issues
   - Debug tools
   - Troubleshooting

6. 📊 Database Schema
   - Schema definitions
   - Query examples

7. 🧪 Testing
   - Running tests
   - Writing tests

8. 📋 Common Tasks Reference
   - Create monitoring skill
   - Fix bugs
   - Backup/restore

9. 🚀 Advanced Topics
   - Creating agents
   - Hot-reloading

10. 📖 API Reference
    - Key modules
```

### Why Single Reference Document?

**Problem with loading all docs**:
- 176 KB, 6,509 lines across multiple files
- Mix of user docs + dev docs + specs
- Too much irrelevant information
- LLM context pollution

**Solution: Curated Developer Reference**:
- Single 50 KB document
- Only developer-relevant information
- Well-structured with clear sections
- Easy to navigate with § references
- Fits well in LLM context window

### How Agent Uses Reference

```
User: "Add a health monitoring skill"

Agent:
1. References: Developer Reference § Skill Development
   → Learns SKILL.md structure
   
2. Uses read_file to check existing skills
   → read_file(".olav/skills/network-query/SKILL.md")
   
3. References: Developer Reference § Tool Development
   → Learns tool template
   
4. Creates files with write_file:
   .olav/skills/device-health/
   ├── SKILL.md
   └── tools/check_health.py

5. Tests: execute_olav("ask 'check device R1 health'")

6. Commits: execute_command("git add .olav/skills/device-health && git commit -m 'feat: add device-health skill'")
```

---

## 🛠️ Tools Design

### Evolution: 8 Tools → 4 Tools (50% Reduction)

| Version | Tools | Lines of Code | Philosophy |
|---------|-------|---------------|------------|
| **v1** (Initial) | 8 tools: read_file, write_file, list_files, search_code, execute_olav, execute_python, git_operations, backup_restore | ~1,200 lines | Specialized wrappers for every operation |
| **v2** (Current) | 4 tools: read_file, write_file, execute_command, execute_olav | ~200 lines | 🎯 "代码即工具" - Use shell commands directly |

**Key Insight**: Admin Agent has `execute_command` that can run **ANY** shell command. Why wrap `grep`, `git`, `find` in Python? Just use them directly!

**Benefits**:
- 🔻 95% less code to maintain (1,200 → 200 lines)
- 🚀 More flexible (not limited to pre-defined operations)
- 🧠 LLM learns transferable knowledge (Unix commands work everywhere)
- 📦 Portable to any project (not OLAV-specific)

---

### Ultra-Minimalist Tool Set (4 tools) ⭐

```python
# "代码即工具" - Code as tool, minimal abstraction
tools = [
    read_file,           # Read any file
    write_file,          # Write any file (HITL for .py)
    execute_command,     # Execute ANY shell command (git, grep, ls, tar, python, etc.) ⭐
    execute_olav,        # Test OLAV commands (subprocess)
]

# Why only 4 tools?
# ✅ execute_command replaces:
#    - list_files → execute_command("find .olav/skills -name '*.py'")
#    - search_code → execute_command("grep -r 'pattern' .olav/")
#    - git_operations → execute_command("git commit -m 'msg'")
#    - backup_restore → execute_command("tar -czf backup.tar.gz .olav/")
#    - execute_python → execute_command("python3 script.py")

# All tools location: .olav/skills/olav-admin/tools/
# ✅ Portable: Can copy .olav/skills/olav-admin/ to other projects
# ✅ True minimalism: Don't create abstractions, use shell commands
```

### Tool 1: Read File

```python
@tool
def read_file(path: str) -> str:
    """Read file content.
    
    Args:
        path: File path (relative to project root or absolute)
    
    Returns:
        File content as string
    
    Security:
        ✅ Green: No restrictions (read-only operation)
    
    Example:
        read_file(".olav/skills/network-query/SKILL.md")
        read_file("dev_docs/DEVELOPER_REFERENCE.md")
    
    Location: .olav/skills/olav-admin/tools/file_reader.py
    """
    full_path = Path(path)
    if not full_path.is_absolute():
        full_path = Path.cwd() / path
    
    if not full_path.exists():
        return f"Error: File not found: {path}"
    
    return full_path.read_text()
```

### Tool 2: Write File

```python
@tool
def write_file(path: str, content: str, backup: bool = True) -> str:
    """Write content to file.
    
    Args:
        path: File path (relative to .olav/ or config/)
        content: Content to write
        backup: Create backup before overwriting (default: True)
    
    Returns:
        Success message or error
    
    Security:
        🟡 Yellow: HITL approval required for:
            - .py files (code changes)
            - src/ directory (framework code)
        ✅ Green: Auto-approved for:
            - .md files (documentation)
            - .json files (configuration)
            - .olav/skills/ (skill definitions)
    
    Example:
        write_file(".olav/skills/monitoring/SKILL.md", content)
    
    Location: .olav/skills/olav-admin/tools/file_writer.py
    """
    full_path = Path(path)
    if not full_path.is_absolute():
        full_path = Path.cwd() / path
    
    # Security check
    if path.endswith(".py") or "src/" in path:
        # HITL approval required (handled by middleware)
        pass
    
    # Backup existing file
    if backup and full_path.exists():
        backup_path = full_path.with_suffix(full_path.suffix + ".backup")
        shutil.copy(full_path, backup_path)
    
    # Write file
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    
    return f"✅ Written to {path}"
```

### Tool 3: Execute Command ⭐ (Replaces 5 Tools)

```python
@tool
def execute_command(command: str, timeout: int = 60, cwd: str = None) -> dict:
    """Execute ANY shell command.
    
    This is the power tool that replaces 5 specialized tools:
    - list_files → "find dir -name '*.py'"
    - search_code → "grep -r 'pattern' dir"
    - git_operations → "git commit -m 'msg'"
    - backup_restore → "tar -czf backup.tar.gz dir"
    - execute_python → "python3 script.py"
    
    Args:
        command: Shell command to execute (full command line)
        timeout: Command timeout in seconds
        cwd: Working directory (default: project root)
    
    Returns:
        {
            "stdout": "command output",
            "stderr": "error output",
            "returncode": 0,
            "success": true,
            "command": "original command"
        }
    
    Security:
        🟡 Yellow: HITL approval required for:
            - git commit, git push (permanent changes)
            - rm, mv (destructive operations)
            - Commands modifying src/ directory
        ✅ Green: Auto-approved for:
            - Read-only: ls, find, grep, cat
            - Safe operations: mkdir, cp (to .olav/)
    
    Examples:
        # List Python files
        execute_command("find .olav/skills -name '*.py' -type f")
        
        # Search code
        execute_command("grep -r 'execute_sql' .olav/skills/")
        
        # Git operations
        execute_command("git add .olav/skills/monitoring/")
        execute_command("git commit -m 'Add monitoring skill'")
        execute_command("git push")
        
        # Backup
        execute_command("tar -czf backup_$(date +%Y%m%d).tar.gz .olav/")
        
        # Execute Python script
        execute_command("python3 .olav/tools/database.py --query 'SELECT * FROM devices'")
        
        # Call existing admin commands
        execute_command("python3 -m olav.cli.admin backup")
        execute_command("python3 -m olav.cli.admin status")
    
    Location: .olav/skills/olav-admin/tools/command_executor.py
    """
    import subprocess
    import shlex
    
    # Parse command
    cmd_parts = shlex.split(command)
    
    # Execute
    result = subprocess.run(
        cmd_parts,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or Path.cwd(),
        shell=False  # Security: No shell injection
    )
    
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "success": result.returncode == 0,
        "command": command
    }
```

### Tool 4: Execute OLAV

```python
@tool
def execute_olav(command: str, timeout: int = 60) -> dict:
    """Execute OLAV CLI command (specialized wrapper for testing).
    
    Args:
        command: OLAV command (without "olav" prefix)
        timeout: Command timeout in seconds
    
    Returns:
        {
            "stdout": "command output",
            "stderr": "error output",
            "returncode": 0,
            "success": true
        }
    
    Security:
        ✅ Green: Safe (OLAV runs in subprocess sandbox)
    
    Note: This is a convenience wrapper. Could also use:
        execute_command("uv run olav ask 'query'")
    
    Examples:
        execute_olav("ask 'how many devices?'")
        execute_olav("devices")
        execute_olav("admin status")
        execute_olav("/learn_cmd show version --device R1")
    
    Location: .olav/skills/olav-admin/tools/olav_executor.py
    """
    result = subprocess.run(
        ["uv", "run", "olav"] + command.split(),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=Path.cwd()
    )
    
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "success": result.returncode == 0
    }
```

---

## 🗑️ Removed Tools (Replaced by execute_command)

The following tools are **no longer needed** because `execute_command` is more flexible:

#### ❌ list_files (removed)
```python
# Before: Dedicated tool
list_files(".olav/skills", pattern="*.py", recursive=True)

# After: Shell command
execute_command("find .olav/skills -name '*.py' -type f")
execute_command("ls -la .olav/skills/*/SKILL.md")
```

#### ❌ search_code (removed)
```python
# Before: Python wrapper
search_code("execute_sql", directory=".olav", file_pattern="*.py")

# After: grep command
execute_command("grep -r 'execute_sql' .olav/ --include='*.py'")
execute_command("grep -n -C 3 'class Agent' src/olav/agents/")
```

#### ❌ git_operations (removed)
```python
# Before: Specialized wrapper
git_operations("commit", message="Add skill", files=[".olav/skills/"])

# After: Direct git commands
execute_command("git add .olav/skills/monitoring/")
execute_command("git commit -m 'Add monitoring skill'")
execute_command("git push origin refactor/v2.0-deepagents")
```

#### ❌ execute_python (removed)
```python
# Before: Python wrapper
execute_python(".olav/tools/database.py", args=["--query", "SELECT * FROM devices"])

# After: Direct python command
execute_command("python3 .olav/tools/database.py --query 'SELECT * FROM devices'")
execute_command("python3 -m pytest tests/e2e/test_admin.py -v")
```

#### ❌ backup_restore (removed)
```python
# Before: Custom backup tool
backup_restore("backup")

# After: Standard Unix tools or existing code
execute_command("tar -czf backup_$(date +%Y%m%d_%H%M%S).tar.gz .olav/")
execute_command("python3 -m olav.cli.admin backup")
```

---

### Why This Is Better

**Code Maintenance**:
- ❌ Before: Maintain 5 Python wrapper tools (200-300 lines each)
- ✅ After: 1 generic execute_command tool (50 lines)

**Flexibility**:
- ❌ Before: Limited to pre-defined operations
- ✅ After: Any shell command, unlimited combinations

**LLM Learning**:
- ❌ Before: Agent must learn 8 tool APIs
- ✅ After: Agent learns standard Unix commands (transferable knowledge)

**Portability**:
- ❌ Before: Tools depend on OLAV-specific logic
- ✅ After: Works with any project (just shell commands)

---

## 📚 Developer Reference Integration

Admin Agent learns shell commands from Developer Reference:

```markdown
# Developer Reference § Common Tasks

## List Files
execute_command("find .olav/skills -name 'SKILL.md'")
execute_command("ls -la .olav/skills/*/tools/*.py")

## Search Code  
execute_command("grep -r 'execute_sql' .olav/")
execute_command("grep -n 'class.*Agent' src/olav/agents/*.py")

## Git Operations
execute_command("git add .olav/")
execute_command("git commit -m 'Update skills'")
execute_command("git push")

## Backup
execute_command("tar -czf backup.tar.gz .olav/")

## Testing
execute_command("python3 -m pytest tests/e2e/ -v")
```

Agent references this when user asks: "Search for execute_sql usage"

---

## 💻 CLI Interface

### Command Format

```bash
# Admin commands
$ olav /admin <task>

# Examples:
$ olav /admin create-skill monitoring
$ olav /admin reload-commands
$ olav /admin backup
$ olav /admin show documentation about skills
$ olav /admin fix bug in network-query skill
$ olav /admin search for "execute_sql"
```

### Interactive Mode

```bash
$ olav
> /admin

Admin Agent activated. I have full access to OLAV documentation.

What would you like me to do?

> Create a new skill called "device-health" that checks CPU and memory

[Agent reads SKILL_AUTHORING_GUIDE.md]
[Agent reads existing skills for examples]
[Agent creates .olav/skills/device-health/SKILL.md]
[Agent creates .olav/skills/device-health/tools/check_health.py]
[Agent tests with execute_olav]

✅ Created device-health skill
   Files:
   - .olav/skills/device-health/SKILL.md
   - .olav/skills/device-health/tools/check_health.py
   
   Test: olav ask "check device R1 health"

Would you like me to commit these changes?

> Yes

[Agent calls execute_command("git add .olav/skills/device-health") with HITL approval]
[Agent calls execute_command("git commit -m 'feat: add device-health skill'") with HITL approval]

✅ Committed to Git
```

### Command Aliases

```bash
/admin           # Full command
/a               # Alias
```

---

## 🔐 Security & HITL

### Permission Model (Ultra-Minimalist: 4 Tools)

| Operation | Tool | Risk Level | HITL Required | Reason |
|-----------|------|-----------|---------------|--------|
| Read files | `read_file` | 🟢 Green | No | Read-only, safe |
| Write .md/.json files | `write_file` | 🟢 Green | No | Doc/config changes |
| Write .py files | `write_file` | 🟡 Yellow | **Yes** | Code changes require review |
| Write to src/ | `write_file` | 🟡 Yellow | **Yes** | Framework changes require review |
| Execute OLAV commands | `execute_olav` | 🟢 Green | No | Sandboxed subprocess |
| List files (find/ls) | `execute_command` | 🟢 Green | No | Read-only |
| Search code (grep) | `execute_command` | 🟢 Green | No | Read-only |
| Git status/log | `execute_command` | 🟢 Green | No | Read-only |
| Git commit/push | `execute_command` | 🟡 Yellow | **Yes** | Permanent changes |
| Python scripts (.olav/) | `execute_command` | 🟢 Green | No | Safe directory |
| Python scripts (src/) | `execute_command` | 🟡 Yellow | **Yes** | Framework code |
| rm/mv commands | `execute_command` | 🟡 Yellow | **Yes** | Destructive operations |
| Backup (tar) | `execute_command` | 🟢 Green | No | No destructive changes |

### execute_command Security Logic

```python
def is_dangerous_command(command: str) -> bool:
    """Check if command requires HITL approval."""
    
    # Parse command
    parts = shlex.split(command)
    cmd = parts[0] if parts else ""
    
    # Destructive commands
    if cmd in ["rm", "mv", "dd", "mkfs"]:
        return True  # Always dangerous
    
    # Git write operations
    if cmd == "git" and len(parts) > 1:
        if parts[1] in ["commit", "push", "merge", "rebase"]:
            return True
    
    # Python in src/ directory
    if cmd == "python3" and len(parts) > 1:
        if "src/" in parts[1]:
            return True
    
    # Commands with src/ in path
    if "src/" in command:
        return True
    
    return False  # Safe by default
```

### HITL Middleware Configuration (Ultra-Minimalist: 4 Tools)

```python
from deepagents.middleware import HumanInTheLoopMiddleware
import shlex

admin_agent = create_deep_agent(
    name="OLAVAdmin",
    tools=[
        read_file,           # Safe: read-only
        write_file,          # Conditional: check extension and path
        execute_command,     # Conditional: check command danger level
        execute_olav,        # Safe: sandboxed subprocess
    ],
    middleware=[
        HumanInTheLoopMiddleware(
            dangerous_tools=["write_file", "execute_command"],
            approval_callback=ask_user_approval
        )
    ]
)

def ask_user_approval(tool_name: str, tool_args: dict) -> bool:
    """Custom approval logic for ultra-minimalist tools."""
    
    # write_file: Check if .py or src/
    if tool_name == "write_file":
        path = tool_args.get("path", "")
        if path.endswith(".py") or "src/" in path:
            print(f"\n⚠️  Admin wants to modify code: {path}")
            print(f"Content preview:\n{tool_args['content'][:500]}")
            response = input("Approve? (y/n): ")
            return response.lower() == "y"
        return True  # Auto-approve .md/.json
    
    # execute_command: Parse command and check danger level
    if tool_name == "execute_command":
        command = tool_args.get("command", "")
        
        # Parse command safely
        try:
            parts = shlex.split(command)
            cmd = parts[0] if parts else ""
        except:
            return False  # Invalid command syntax
        
        # Destructive commands
        if cmd in ["rm", "mv", "dd", "mkfs"]:
            print(f"\n⚠️  Admin wants to run destructive command: {command}")
            response = input("Approve? (y/n): ")
            return response.lower() == "y"
        
        # Git write operations
        if cmd == "git" and len(parts) > 1:
            if parts[1] in ["commit", "push", "merge", "rebase"]:
                print(f"\n⚠️  Admin wants to run: {command}")
                response = input("Approve? (y/n): ")
                return response.lower() == "y"
        
        # Python scripts in src/
        if "src/" in command and cmd in ["python3", "python"]:
            print(f"\n⚠️  Admin wants to run Python in src/: {command}")
            response = input("Approve? (y/n): ")
            return response.lower() == "y"
        
        return True  # Auto-approve safe commands (find, grep, ls, etc.)
    
    # Default: require approval for unknown tools
    return False
```

### Safety Example

```
User: "Fix the bug in network-query skill"

Agent:
1. execute_command("grep -r 'def query' .olav/skills/network-query")  # ✅ Auto-approved
2. read_file(".olav/skills/network-query/tools/query.py")              # ✅ Auto-approved
3. Analyzes bug

⚠️  Admin wants to modify code: .olav/skills/network-query/tools/query.py

Change:
- if devices is None:
+ if devices is None or len(devices) == 0:

Approve? (y/n): y

4. write_file(path, new_content)                                        # ✅ User approved
5. execute_command("git add .olav/skills/network-query")                # ✅ Auto-approved

⚠️  Admin wants to run: git commit -m 'fix: handle empty devices list'

Approve? (y/n): y

6. execute_command("git commit -m 'fix: ...'")                          # ✅ User approved

✅ Bug fixed and committed
```

---

## 🔧 Implementation Details

### Agent Definition (Ultra-Minimalist: 4 Tools)

```python
# src/olav/agents/admin_agent.py

from deepagents import create_deep_agent
from pathlib import Path

def load_developer_reference() -> str:
    """Load OLAV Developer Reference."""
    ref_path = Path("dev_docs/DEVELOPER_REFERENCE.md")
    return ref_path.read_text()

def create_admin_agent():
    """Create independent Admin agent with ultra-minimalist tool set."""
    
    # Load Developer Reference (~50 KB)
    dev_reference = load_developer_reference()
    
    return create_deep_agent(
        name="OLAVAdmin",
        tools=[
            read_file,         # Essential: read any file
            write_file,        # Essential: write any file (with HITL for .py)
            execute_command,   # Universal: any shell command (replaces 5 tools)
            execute_olav,      # Convenience: domain-specific wrapper
        ],
        skills_path=".olav/skills/olav-admin",  # Optional admin-specific skills
        system_prompt=f"""
        You are the OLAV System Administrator.
        
        # Your Mission
        Maintain and extend the OLAV network automation system.
        
        # Developer Reference (~1,200 lines, 50 KB)
        {dev_reference}
        
        # Your Capabilities (4 Tools Only)
        1. read_file - Read any file in the project
        2. write_file - Write any file (HITL for .py files)
        3. execute_command - Run ANY shell command:
           - List files: find, ls
           - Search code: grep, ag, rg
           - Git: commit, push, status, log
           - Python: python3 script.py
           - Backup: tar, zip
           - Admin: uv, pytest
        4. execute_olav - Shortcut for "uv run olav ask ..."
        
        # How to Learn
        - Need examples? execute_command("find .olav/skills -name '*.py'")
        - Need to search? execute_command("grep -r 'pattern' .olav/")
        - Need git status? execute_command("git status")
        - See Developer Reference for development patterns
        
        # Safety Rules
        - ALL .py file changes require user approval
        - ALL git commits/pushes require user approval
        - Destructive commands (rm, mv) require user approval
        - Test changes: execute_olav("ask 'test query'")
        
        # Quality Standards
        - Follow existing code patterns
        - Add documentation for new features
        - Write tests for new tools
        - Keep changes minimal and focused
        """,
        checkpointer=DuckDBSaver(".olav/databases/admin.duckdb"),
        middleware=[
            TodoListMiddleware(),  # Multi-step task planning
            HumanInTheLoopMiddleware(
                dangerous_tools=["write_file", "execute_command"],
                approval_callback=ask_user_approval
            )
        ]
    )

# Create singleton instance
admin_agent = create_admin_agent()
```

---

## 🧪 Testing Strategy

### E2E Test Cases

```python
# tests/e2e/test_admin_agent.py

@pytest.mark.e2e
async def test_admin_read_docs():
    """Test admin can read and understand documentation."""
    result = await admin_agent.ainvoke(
        "What is the structure of a SKILL.md file?"
    )
    
    assert "frontmatter" in result.lower()
    assert "name:" in result.lower()

@pytest.mark.e2e
async def test_admin_create_skill():
    """Test admin can create a new skill."""
    result = await admin_agent.ainvoke(
        "Create a monitoring skill that checks device CPU"
    )
    
    assert Path(".olav/skills/monitoring/SKILL.md").exists()
    assert Path(".olav/skills/monitoring/tools/check_cpu.py").exists()

@pytest.mark.e2e
async def test_admin_search_code():
    """Test admin can search codebase."""
    result = await admin_agent.ainvoke(
        "Where is execute_sql implemented?"
    )
    
    assert ".olav/tools/database.py" in result

@pytest.mark.e2e
async def test_admin_hitl_approval():
    """Test HITL approval for code changes."""
    with mock_user_input("n"):  # User denies
        result = await admin_agent.ainvoke(
            "Modify execute_sql to add caching"
        )
    
    # Should not modify file
    original = Path(".olav/tools/database.py").read_text()
    # ... verify no changes

@pytest.mark.e2e
async def test_admin_execute_olav():
    """Test admin can execute OLAV commands."""
    result = await admin_agent.ainvoke(
        "Test the monitoring skill by querying device R1"
    )
    
    # Verify execute_olav was called
    assert "execute_olav" in result.tool_calls
```

---

## 📋 Acceptance Criteria

### Functional
- ✅ Can read and understand OLAV documentation
- ✅ Can create new skills from scratch
- ✅ Can modify existing skills
- ✅ Can search and understand codebase
- ✅ Can execute OLAV commands for testing
- ✅ Can perform git operations (with approval)

### Security
- ✅ HITL approval works for .py files
- ✅ HITL approval works for git operations
- ✅ Cannot modify src/ without approval
- ✅ Cannot push to git without approval

### Quality
- ✅ Generated code follows existing patterns
- ✅ Changes are tested before committing
- ✅ Documentation is updated with changes

### Portability
- ✅ Can be used for other Python projects (not just OLAV)
- ✅ Independent state (admin.duckdb)
- ✅ Zero dependency on main_agent

---

## 🚀 Next Steps

1. **Phase 2.1**: Implement 4 ultra-minimalist tools (read/write/execute_command/execute_olav)
2. **Phase 2.2**: Load Developer Reference as context (~50 KB)
3. **Phase 2.3**: Create admin_agent.py
4. **Phase 2.4**: Implement HITL middleware with execute_command security logic
5. **Phase 2.5**: E2E testing (10 test cases)
6. **Phase 2.6**: Documentation and user guide

---

**Version**: v2.1.0-design  
**Author**: OLAV Architecture Team  
**Last Updated**: 2026-02-15
