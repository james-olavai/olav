# Admin Agent Specification

**Date**: 2026-02-15  
**Status**: 🟡 Design Phase  
**Version**: v2.1.0  
**Purpose**: Minimalist system administrator with full OLAV documentation as reference

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
    execute_olav,       # Run OLAV commands
    search_code,        # Search codebase
    git_operations,     # Git commit/push
]

system_prompt = f"""
Developer Reference (Single Document, ~1,200 lines):
{load_developer_reference()}

You have full OLAV Developer Reference. Learn how to:
- Create skills (§ Skill Development)
- Develop tools (§ Tool Development)
- Fix bugs (§ Debugging Guide)
- Test changes (§ Testing)
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

6. Commits: git_operations("add device-health skill")
```

---

## 🛠️ Tools Design

### Minimalist Tool Set (8 tools)

```python
# Generic, powerful tools (not admin-specific)
tools = [
    read_file,           # Read any file
    write_file,          # Write any file (HITL for .py)
    list_files,          # List directory contents
    search_code,         # Grep-like search
    execute_olav,        # Run OLAV commands (subprocess)
    execute_python,      # Run Python scripts (for testing)
    git_operations,      # Git commit, push, pull (HITL)
    backup_restore,      # Backup .olav/ directory
]

# All tools location: .olav/skills/olav-admin/tools/
# ✅ Portable: Can copy .olav/skills/olav-admin/ to other projects
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

### Tool 3: Execute OLAV

```python
@tool
def execute_olav(command: str, timeout: int = 60) -> dict:
    """Execute OLAV CLI command.
    
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
    
    Examples:
        execute_olav("ask 'how many devices?'")
        execute_olav("devices")
        execute_olav("admin status")
        execute_olav("/learn_cmd show version --device R1")    
    Location: .olav/skills/olav-admin/tools/olav_executor.py    """
    result = subprocess.run(
        ["uv", "run", "olav"] + command.split(),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=Path.cwd()  # Run in project directory
    )
    
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "success": result.returncode == 0
    }
```

### Tool 4: Search Code

```python
@tool
def search_code(
    pattern: str,
    directory: str = ".olav",
    file_pattern: str = "*.py",
    context_lines: int = 2
) -> list[dict]:
    """Search code by pattern (grep-like).
    
    Args:
        pattern: Search pattern (regex supported)
        directory: Directory to search (default: .olav)
        file_pattern: File glob pattern (default: *.py)
        context_lines: Lines of context (default: 2)
    
    Returns:
        [
            {
                "file": ".olav/tools/database.py",
                "line": 42,
                "content": "def execute_sql(query: str):",
                "context": ["# Previous line", "def execute_sql...", "# Next line"]
            }
        ]
    
    Security:
        ✅ Green: Read-only operation
    
    Example:
        search_code("execute_sql", directory=".olav", file_pattern="*.py")
    
    Location: .olav/skills/olav-admin/tools/code_searcher.py
    """
    import re
    
    results = []
    search_path = Path(directory)
    
    for file_path in search_path.rglob(file_pattern):
        with open(file_path) as f:
            lines = f.readlines()
        
        for i, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                results.append({
                    "file": str(file_path),
                    "line": i + 1,
                    "content": line.strip(),
                    "context": [
                        lines[max(0, i-context_lines):i],
                        lines[i+1:min(len(lines), i+context_lines+1)]
                    ]
                })
    
    return results
```

### Tool 5: Git Operations

```python
@tool
def git_operations(action: str, message: str = "", files: list[str] = None) -> dict:
    """Git operations (commit, push, pull).
    
    Args:
        action: "commit", "push", "pull", "status"
        message: Commit message (required for commit)
        files: Files to add (default: all .olav/ files)
    
    Returns:
        {
            "action": "commit",
            "success": true,
            "output": "git command output"
        }
    
    Security:
        🟡 Yellow: HITL approval required for commit/push
        ✅ Green: Auto-approved for status/pull
    
    Example:
        git_operations("commit", message="Add monitoring skill", files=[".olav/skills/monitoring"])
        git_operations("push")
    
    Location: .olav/skills/olav-admin/tools/git_handler.py
    """
    if action == "status":
        result = subprocess.run(["git", "status"], capture_output=True, text=True)
        return {"action": "status", "output": result.stdout}
    
    elif action == "commit":
        # Add files
        if files is None:
            files = [".olav/"]
        
        for file in files:
            subprocess.run(["git", "add", file])
        
        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True
        )
        
        return {
            "action": "commit",
            "success": result.returncode == 0,
            "output": result.stdout
        }
    
    elif action == "push":
        result = subprocess.run(["git", "push"], capture_output=True, text=True)
        return {
            "action": "push",
            "success": result.returncode == 0,
            "output": result.stdout
        }
```

### Tool 6: Execute Python

```python
@tool
def execute_python(script_path: str, args: list[str] = None) -> dict:
    """Execute Python script.
    
    Args:
        script_path: Path to Python script
        args: Command-line arguments
    
    Returns:
        {
            "stdout": "...",
            "stderr": "...",
            "returncode": 0,
            "success": true
        }
    
    Security:
        🟡 Yellow: HITL approval for scripts outside .olav/
        ✅ Green: Auto-approved for .olav/ scripts
    
    Example:
        execute_python(".olav/tools/database.py", args=["--query", "SELECT * FROM devices"])
    
    Location: .olav/skills/olav-admin/tools/python_executor.py
    """
    cmd = ["python3", script_path]
    if args:
        cmd.extend(args)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "success": result.returncode == 0
    }
```

### Tool 7: Backup/Restore

```python
@tool
def backup_restore(action: str, backup_path: str = None) -> dict:
    """Backup or restore .olav/ directory.
    
    Args:
        action: "backup" or "restore"
        backup_path: Path to backup file (auto-generated if not provided)
    
    Returns:
        {
            "action": "backup",
            "backup_file": ".olav/backups/backup_20260215_123456.tar.gz",
            "size_bytes": 1048576
        }
    
    Security:
        ✅ Green: Safe operation (no destructive changes without restore confirmation)
    
    Example:
        backup_restore("backup")
        backup_restore("restore", backup_path=".olav/backups/backup_20260215_123456.tar.gz")
    
    Location: .olav/skills/olav-admin/tools/backup_handler.py
    """
    # Use existing admin.py implementation
    from olav.cli.admin import AdminCommand
    admin = AdminCommand()
    
    if action == "backup":
        result = await admin.backup(backup_path)
        return result
    
    elif action == "restore":
        result = await admin.restore(backup_path)
        return result
```

### Tool 8: List Files

```python
@tool
def list_files(directory: str, pattern: str = "*", recursive: bool = False) -> list[str]:
    """List files in directory.
    
    Args:
        directory: Directory path
        pattern: File glob pattern (default: *)
        recursive: Recursive listing (default: False)
    
    Returns:
        List of file paths
    
    Security:
        ✅ Green: Read-only operation
    
    Example:
        list_files(".olav/skills", pattern="SKILL.md", recursive=True)
    
    Location: .olav/skills/olav-admin/tools/file_lister.py
    """
    path = Path(directory)
    
    if recursive:
        files = path.rglob(pattern)
    else:
        files = path.glob(pattern)
    
    return [str(f) for f in files if f.is_file()]
```

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

[Agent calls git_operations with HITL approval]

✅ Committed to Git
```

### Command Aliases

```bash
/admin           # Full command
/a               # Alias
```

---

## 🔐 Security & HITL

### Permission Model

| Operation | Risk Level | HITL Required | Reason |
|-----------|-----------|---------------|--------|
| Read files | 🟢 Green | No | Read-only, safe |
| Search code | 🟢 Green | No | Read-only, safe |
| Execute OLAV | 🟢 Green | No | Sandboxed subprocess |
| List files | 🟢 Green | No | Read-only, safe |
| Backup | 🟢 Green | No | No destructive changes |
| Write .md files | 🟢 Green | No | Documentation changes |
| Write .json files | 🟢 Green | No | Configuration changes |
| Write .py files | 🟡 Yellow | **Yes** | Code changes require review |
| Write to src/ | 🟡 Yellow | **Yes** | Framework changes require review |
| Git commit | 🟡 Yellow | **Yes** | Permanent changes |
| Git push | 🟡 Yellow | **Yes** | Remote changes |
| Execute Python | 🟡 Yellow | **Conditional** | If script outside .olav/ |
| Restore backup | 🟡 Yellow | **Yes** | Destructive operation |

### HITL Middleware Configuration

```python
from deepagents.middleware import HumanInTheLoopMiddleware

admin_agent = create_deep_agent(
    name="OLAVAdmin",
    tools=[...],
    middleware=[
        HumanInTheLoopMiddleware(
            dangerous_tools=[
                "write_file",        # If .py or src/
                "git_operations",    # If commit/push
                "execute_python",    # If outside .olav/
                "backup_restore"     # If restore action
            ],
            approval_callback=ask_user_approval
        )
    ]
)

def ask_user_approval(tool_name: str, tool_args: dict) -> bool:
    """Custom approval logic."""
    
    # write_file: Check if .py or src/
    if tool_name == "write_file":
        path = tool_args.get("path", "")
        if path.endswith(".py") or "src/" in path:
            print(f"\n⚠️  Admin wants to modify code: {path}")
            print(f"Content preview:\n{tool_args['content'][:500]}")
            response = input("Approve? (y/n): ")
            return response.lower() == "y"
        return True  # Auto-approve .md/.json
    
    # git_operations: Always require approval
    if tool_name == "git_operations":
        action = tool_args.get("action")
        if action in ["commit", "push"]:
            print(f"\n⚠️  Admin wants to {action}")
            print(f"Message: {tool_args.get('message', 'N/A')}")
            response = input("Approve? (y/n): ")
            return response.lower() == "y"
        return True  # Auto-approve status/pull
    
    # Default: require approval
    return False
```

### Safety Example

```
User: "Fix the bug in network-query skill"

Agent:
1. Reads network-query/SKILL.md
2. Searches for bug patterns
3. Proposes fix

⚠️  Admin wants to modify code: .olav/skills/network-query/tools/query.py

Change:
- if devices is None:
+ if devices is None or len(devices) == 0:

Approve? (y/n): y

✅ Applied fix
```

---

## 🔧 Implementation Details

### Agent Definition

```python
# src/olav/agents/admin_agent.py

from deepagents import create_deep_agent
from pathlib import Path

def load_developer_reference() -> str:
    """Load OLAV Developer Reference."""
    ref_path = Path("dev_docs/DEVELOPER_REFERENCE.md")
    return ref_path.read_text()

def create_admin_agent():
    """Create independent Admin agent."""
    
    # Load Developer Reference (~50 KB)
    dev_reference = load_developer_reference()
    
    return create_deep_agent(
        name="OLAVAdmin",
        tools=[
            read_file,
            write_file,
            list_files,
            search_code,
            execute_olav,
            execute_python,
            git_operations,
            backup_restore,
        ],
        skills_path=".olav/skills/olav-admin",  # Optional admin-specific skills
        system_prompt=f"""
        You are the OLAV System Administrator.
        
        # Your Mission
        Maintain and extend the OLAV network automation system.
        
        # Developer Reference (~1,200 lines, 50 KB)
        {dev_reference}
        
        # Your Capabilities
        - Read/write any file in the project
        - Execute OLAV commands (subprocess)
        - Search codebase
        - Git operations (with user approval)
        - Backup/restore system state
        
        # How to Learn
        - Need to create a skill? See § Skill Development
        - Need to create a tool? See § Tool Development
        - Need to understand architecture? See § Architecture
        - Need examples? Use read_file to check existing skills
        - Need to test? Use execute_olav() command
        
        # Safety Rules
        - ALL .py file changes require user approval
        - ALL git commits/pushes require user approval
        - Create backups before major changes
        - Test changes before committing
        
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
                dangerous_tools=["write_file", "git_operations", "execute_python"],
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

1. **Phase 2.1**: Implement 8 tools (read/write/execute/search/git/backup/list/python)
2. **Phase 2.2**: Load documentation as context (176 KB)
3. **Phase 2.3**: Create admin_agent.py
4. **Phase 2.4**: Implement HITL middleware
5. **Phase 2.5**: E2E testing (10 test cases)
6. **Phase 2.6**: Documentation and user guide

---

**Version**: v2.1.0-design  
**Author**: OLAV Architecture Team  
**Last Updated**: 2026-02-15
