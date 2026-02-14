# Query Routing Failure Analysis - v0.10.0

**Date**: 2026-02-05  
**Issue**: "Save all devices' version info to CSV" executed wrong commands  
**Status**: Root cause identified, pending fix

---

## 🔍 Problem Summary

User query: `"save all devices' version info to a csv table"`

**Expected behavior**:
1. Query devices table → get all device names
2. Execute `show version` on each device (or query existing data)
3. Parse version info
4. Export to CSV file

**Actual behavior**:
1. ⚡ Fast-Path query_database → MISS (no version table)
2. 🔍 Fell back to Agent analysis
3. ❌ Executed WRONG commands: `show ospf neighbor`, `show bgp summary`, `show cdp neighbors`
4. ⚠️ R2 failed repeatedly with "Command execution failed" (TextFSM parsing errors)
5. ✓ Eventually created `/devices_version.csv` but R2 marked unavailable

---

## 🐛 Root Cause Analysis

### **Issue 1: query_network Tool Recursive Agent Creation** ❌

**Location**: [src/olav/tools/react_query.py](../src/olav/tools/react_query.py#L57-L87)

**Problem**:
```python
@tool
async def query_network(question: str | None = None, sql: str | None = None) -> str:
    """执行网络数据查询。

    支持直接的 SQL 语句或自然语言问题。
    使用专门的 SQL Assistant Agent，具备跨表关联、自省 Schema 和错误自愈能力。
    """
    query_text = question or sql
    if not query_text:
        return "Error: No question or SQL query provided."

    try:
        from olav.agents.query_agent import QueryAgent  # ❌ WRONG!

        agent = QueryAgent()  # ❌ Creates new agent instance
        result = await agent.query(query_text)
        ...
```

**Why this is wrong**:
1. query SubAgent calls query_network tool
2. query_network creates NEW QueryAgent instance (different from orchestrator)
3. New agent has NO CONTEXT about "save to CSV" request
4. New agent starts its OWN ReAct loop with different understanding
5. Executes unrelated commands (OSPF, BGP, CDP)

**Flow diagram**:
```
User: "save devices version to CSV"
  ↓
Orchestrator → query SubAgent
  ↓
query SubAgent: "Let me use query_network tool"
  ↓
query_network: Creates NEW QueryAgent() ❌
  ↓
NEW QueryAgent: "I see 'network' keyword, let me query network protocols"
  ↓
Executes: show ospf neighbor, show bgp summary, show cdp neighbors ❌
```

---

### **Issue 2: Missing Direct Database Query Tool** ❌

**Location**: [src/olav/agents/orchestrator.py](../src/olav/agents/orchestrator.py#L64-L108)

**Problem**:
```python
SubAgent(
    name="query",
    description="Enhanced network query specialist with Fast Path and caching (from QueryAgent)",
    system_prompt=(
        "You are an enhanced network query specialist powered by QueryAgent capabilities. "
        "You have access to:\n"
        "1. Fast Path intent detection for simple queries\n"
        "2. Query caching for repeated requests\n"
        "3. Skill-based tool loading (network-query skill)\n"
        "4. Database query tools: query_database, inspect_schema, smart_query\n\n"  # ⚠️ LIES!
        ...
    ),
    tools=query_tools,  # ❌ Actually only contains [query_network]
),
```

**Why this is wrong**:
- System prompt **promises** `query_database`, `inspect_schema`, `smart_query` tools
- **Actually** only provides `query_network` (which recursively creates agents)
- Agent cannot execute simple SQL: `SELECT hostname, ios_version FROM devices`
- Forced to use query_network → triggers Issue 1

---

### **Issue 3: Missing Export Tool in Orchestrator** ❌

**Location**: [src/olav/agents/orchestrator.py](../src/olav/agents/orchestrator.py#L336-L345)

**Problem**:
```python
# Orchestrator system prompt mentions export tool
system_prompt = """...
File Export Tool:
- format_and_export(data, filename, format) - Save results to exports/

**Export Examples:**
User: "查询所有VLAN信息，导出CSV"
→ 1. Call query SubAgent → get VLAN data
→ 2. Call format_and_export(data, format="csv", filename="vlans")
→ Output: "✅ 已导出到 exports/vlans.csv"
...
"""

# But create_deep_agent doesn't include the tool!
agent = create_deep_agent(
    model="gpt-4o",
    system_prompt=system_prompt,
    subagents=tuple(subagents) if subagents else None,
    middleware=tuple(middleware) if middleware else (),
    checkpointer=checkpointer,
    store=store,
    name="orchestrator",
    # ❌ Missing: tools=[format_and_export]
)
```

**Why this is wrong**:
- User asks "save to CSV"
- Orchestrator sees instruction in its prompt to call format_and_export
- **But the tool is not in its tool list!**
- Cannot execute the export
- Delegates to SubAgent (which also doesn't have the tool)

---

## ✅ Solution Design

### **Fix 1: Replace query_network with Direct Database Tools**

**Goal**: Remove recursive agent creation, provide direct SQL access

**New implementation**:
```python
# src/olav/tools/react_query.py

@tool
async def query_database(sql: str, params: list | None = None) -> str:
    """Execute SQL query on network database (.olav/db/main.duckdb).
    
    Args:
        sql: SQL SELECT statement (e.g., "SELECT * FROM devices")
        params: Optional parameters for parameterized query
        
    Returns:
        Query results as JSON string
        
    Examples:
        >>> query_database("SELECT hostname, ios_version FROM devices")
        [{"hostname": "R1", "ios_version": "16.12.5"}, ...]
        
        >>> query_database("SELECT * FROM devices WHERE hostname = ?", ["R1"])
        [{"hostname": "R1", "ip_address": "10.0.0.1", ...}]
    """
    from olav.lib.data_gateway import get_gateway
    import json
    
    try:
        gateway = get_gateway()
        results = gateway.query_database(sql, params)
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Database Error: {e}\n\nTip: Use inspect_schema() to check available tables"


@tool
def inspect_schema(table_name: str | None = None) -> str:
    """Inspect database schema to see available tables and columns.
    
    Args:
        table_name: Optional table name to inspect specific table
        
    Returns:
        Schema information as text
        
    Examples:
        >>> inspect_schema()  # List all tables
        Available tables: devices, raw_outputs, v_lldp, v_bgp_neighbors
        
        >>> inspect_schema("devices")  # Show columns for devices table
        Table: devices
        Columns:
        - hostname (VARCHAR)
        - ip_address (VARCHAR)
        - vendor (VARCHAR)
        - model (VARCHAR)
        - ios_version (VARCHAR)
        - device_role (VARCHAR)
        - site (VARCHAR)
    """
    from olav.lib.data_gateway import get_gateway
    
    try:
        gateway = get_gateway()
        if table_name:
            # Get columns for specific table
            result = gateway.query_database(
                f"PRAGMA table_info('{table_name}')"
            )
            return f"Table: {table_name}\nColumns:\n" + "\n".join(
                f"- {row['name']} ({row['type']})" for row in result
            )
        else:
            # List all tables
            result = gateway.query_database(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row['name'] for row in result]
            return f"Available tables: {', '.join(tables)}"
    except Exception as e:
        return f"Schema Error: {e}"
```

**Key changes**:
- ✅ No agent creation - direct gateway access
- ✅ Simple, predictable behavior
- ✅ Proper error messages with hints
- ✅ Examples in docstring for LLM

---

### **Fix 2: Update query SubAgent Tools**

**Goal**: Provide promised tools in system prompt

**Implementation**:
```python
# src/olav/agents/orchestrator.py

def _create_subagents() -> list[SubAgent]:
    """Create declarative SubAgent specialist configurations."""
    
    # Import direct database tools (NO agent creation)
    from olav.tools.react_query import (
        query_database,    # Direct SQL access
        inspect_schema,    # Schema inspection
        discover_data,     # File discovery
    )
    
    database_tools = [
        query_database,
        inspect_schema,
        discover_data,
    ]
    
    return [
        SubAgent(
            name="query",
            description="Database query specialist with direct SQL access",
            system_prompt=(
                "You are a database query specialist with direct SQL access.\n\n"
                "**Available Tools:**\n"
                "1. query_database(sql, params) - Execute SQL on .olav/db/main.duckdb\n"
                "2. inspect_schema(table_name) - Check available tables and columns\n"
                "3. discover_data(pattern) - Find parsed data files\n\n"
                "**Available Database Tables:**\n"
                "- **devices** - Device inventory (hostname, ip_address, vendor, model, ios_version, device_role, site)\n"
                "- **raw_outputs** - CLI command outputs (device, command, output, timestamp)\n"
                "- Check for views: v_lldp, v_bgp_neighbors, v_ospf_neighbors (may not exist)\n\n"
                "**Workflow:**\n"
                "1. If unsure about schema, call inspect_schema() first\n"
                "2. Execute SQL query with query_database()\n"
                "3. If table doesn't exist, inform orchestrator to use CLI SubAgent\n"
                "4. Return results to orchestrator for export/formatting\n\n"
                "⚠️ YOU are responsible for data retrieval only. "
                "DO NOT attempt to save files - orchestrator handles that."
            ),
            tools=database_tools,  # ✅ Direct tools, NO agent recursion
        ),
        # ... other subagents
    ]
```

**Key changes**:
- ✅ Clear separation: query SubAgent = data retrieval only
- ✅ Promises match reality (no fake tools in prompt)
- ✅ Explicit workflow guidance
- ✅ No file export responsibility (that's orchestrator's job)

---

### **Fix 3: Add Export Tool to Orchestrator**

**Goal**: Enable orchestrator to save SubAgent results

**Implementation**:
```python
# src/olav/agents/orchestrator.py

def create_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool = False,
) -> Any:
    """Create SubAgent-based orchestrator."""
    
    # Import export tool
    from olav.tools.data_export import format_and_export
    
    # Orchestrator's own tools (separate from SubAgent tools)
    orchestrator_tools = [
        format_and_export,  # File export capability
    ]
    
    # SubAgent configuration
    subagents = _create_subagents()
    
    # System prompt (unchanged)
    system_prompt = """..."""
    
    # Middleware stack
    middleware = []
    if enable_summarization:
        ...
    
    # Create orchestrator with both tools AND subagents
    agent = create_deep_agent(
        model="gpt-4o",
        system_prompt=system_prompt,
        tools=orchestrator_tools,  # ✅ Orchestrator's own tools
        subagents=tuple(subagents) if subagents else None,
        middleware=tuple(middleware) if middleware else (),
        checkpointer=checkpointer,
        store=store,
        name="orchestrator",
    )
    
    return CachedOrchestrator(agent)
```

**Key changes**:
- ✅ Orchestrator has format_and_export tool
- ✅ Can save SubAgent results to files
- ✅ Clear separation: SubAgents retrieve data, Orchestrator exports

---

## 📋 Expected Flow After Fix

```
User: "save all devices' version info to csv"
  ↓
Orchestrator: "I need device data + export to CSV"
  ↓ (Step 1: Get data)
Delegate to query SubAgent
  ↓
query SubAgent: inspect_schema("devices") → see columns
  ↓
query SubAgent: query_database("SELECT hostname, ios_version FROM devices")
  ↓
Returns: [{"hostname": "R1", "ios_version": "16.12.5"}, ...]
  ↓ (Step 2: Export)
Orchestrator: format_and_export(data, filename="devices_version", format="csv")
  ↓
Output: "✅ 已导出到 exports/devices_version.csv (6 devices)"
```

**No more**:
- ❌ Recursive agent creation
- ❌ Wrong command execution (OSPF, BGP, CDP)
- ❌ R2 repeated failures
- ❌ Poor data quality

---

## 🧪 Test Coverage Gap Analysis

### **Why Tests Passed but Manual Test Failed?**

**Current test suite** (tests/e2e/test_units.py):
```python
class TestCliQueries:
    def test_simple_show_devices_query(self):
        """Test: olav query 'show devices'"""
        # ✅ Passes because queries devices table directly via Fast-Path
        
    def test_device_count_query(self):
        """Test: olav query 'how many devices'"""
        # ✅ Passes because simple count query hits Fast-Path
        
    def test_query_interfaces(self):
        """Test: olav query 'show interfaces on R1'"""
        # ✅ Passes because uses nornir_execute (CLI path)
```

**What tests DON'T cover**:
1. ❌ **Multi-step workflows** (data retrieval + export)
2. ❌ **SubAgent routing decisions** (which specialist to use)
3. ❌ **Tool availability validation** (promised tools actually exist)
4. ❌ **Export operations** (save to CSV/JSON/MD)
5. ❌ **Error recovery paths** (Fast-Path miss → Agent fallback)

**Why TDD failed**:
- Tests focused on **single-operation success** (DB query works, CLI works)
- Didn't test **integration** (query → process → export)
- Didn't validate **tool chain consistency** (SubAgent tools match prompts)
- Didn't test **LLM routing logic** (which SubAgent gets called)

---

## 📊 Proposed Test Improvements

### **1. Integration Test: Data Export Workflows**

```python
# tests/e2e/test_export_workflows.py

class TestExportWorkflows:
    """Test multi-step data export operations."""
    
    def test_export_device_versions_to_csv(self):
        """Test: Save device versions to CSV file."""
        result = subprocess.run(
            ["uv", "run", "olav", "query", 
             "save all devices' version info to a csv table"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        # Verify success message
        assert "已导出" in result.stdout or "exported" in result.stdout.lower()
        
        # Verify CSV file created
        csv_files = list(Path("exports").glob("*version*.csv"))
        assert len(csv_files) > 0, "No CSV file created"
        
        # Verify CSV content
        import csv
        with open(csv_files[0]) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) >= 6, f"Expected 6 devices, got {len(rows)}"
            assert all('hostname' in row for row in rows)
            assert all('version' in row or 'ios_version' in row for row in rows)
    
    def test_export_topology_to_json(self):
        """Test: Export topology data to JSON."""
        # Similar pattern for JSON export
        ...
    
    def test_export_analysis_to_markdown(self):
        """Test: Save analysis report to Markdown."""
        # Test analysis + export workflow
        ...
```

---

### **2. Unit Test: SubAgent Tool Validation**

```python
# tests/unit/test_subagent_tools.py

class TestSubAgentTools:
    """Validate SubAgent tool consistency."""
    
    def test_query_subagent_has_promised_tools(self):
        """Verify query SubAgent tools match system prompt promises."""
        from olav.agents.orchestrator import _create_subagents
        
        subagents = _create_subagents()
        query_subagent = next(s for s in subagents if s.name == "query")
        
        # Extract tool names from system prompt
        prompt_tools = extract_tool_names(query_subagent.system_prompt)
        actual_tools = [t.name for t in query_subagent.tools]
        
        # Verify all promised tools exist
        for tool in prompt_tools:
            assert tool in actual_tools, (
                f"Tool '{tool}' promised in prompt but not in tools list"
            )
    
    def test_orchestrator_has_export_tool(self):
        """Verify orchestrator has format_and_export tool."""
        from olav.agents.orchestrator import create_orchestrator
        
        orchestrator = create_orchestrator()
        # Check if format_and_export is available
        # (DeepAgents API to inspect tools - TBD)
        ...
```

---

### **3. Behavior Test: Tool Execution Paths**

```python
# tests/integration/test_tool_execution.py

class TestToolExecution:
    """Test tool execution paths (no agent recursion)."""
    
    def test_query_database_no_agent_creation(self):
        """Verify query_database doesn't create new agents."""
        from olav.tools.react_query import query_database
        
        # Mock QueryAgent to detect if it's instantiated
        with patch('olav.agents.query_agent.QueryAgent') as mock_agent:
            result = await query_database("SELECT * FROM devices")
            
            # Should NOT create agent
            mock_agent.assert_not_called()
            
            # Should return data
            assert "hostname" in result.lower()
    
    def test_query_network_deprecated(self):
        """Verify query_network is deprecated or removed."""
        # After fix, query_network should be removed
        from olav.tools import react_query
        
        # Should not have query_network anymore
        assert not hasattr(react_query, 'query_network')
```

---

## 🎯 Recommended TDD Process Improvements

### **Current TDD Gap: Test What, Not How**

**Problem**: Tests validated **implementation details** instead of **user outcomes**

**Example**:
```python
# ❌ BAD: Tests implementation
def test_database_query_works():
    result = query("SELECT * FROM devices")
    assert len(result) > 0  # Just checks DB works

# ✅ GOOD: Tests user outcome
def test_user_can_export_device_list_to_csv():
    run_cli("save device list to CSV")
    assert Path("exports/devices.csv").exists()
    assert csv_has_valid_data("exports/devices.csv")
```

---

### **New TDD Strategy: Outside-In Testing**

**Pyramid Structure**:
```
      /\        E2E Tests (5-10 tests)
     /  \       - User workflows
    /____\      - Multi-step operations
   /      \     Integration Tests (20-30 tests)
  /        \    - SubAgent routing
 /__________\   - Tool chain execution
/            \  Unit Tests (50+ tests)
/______________\- Individual functions
                - Tool validation
```

**Checklist for new features**:
1. ✅ Write E2E test for user workflow FIRST
2. ✅ Watch it fail (red)
3. ✅ Implement feature + integration tests
4. ✅ Add unit tests for edge cases
5. ✅ Validate tool promises match reality
6. ✅ Test error recovery paths

---

## 📝 Action Items

### **Immediate (This PR)**:
- [ ] Fix 1: Replace query_network with query_database + inspect_schema
- [ ] Fix 2: Update query SubAgent tools list
- [ ] Fix 3: Add format_and_export to orchestrator tools
- [ ] Test: Verify "save devices to CSV" works end-to-end

### **Short-term (Next Sprint)**:
- [ ] Add tests/e2e/test_export_workflows.py (3 export tests)
- [ ] Add tests/unit/test_subagent_tools.py (tool validation)
- [ ] Add tests/integration/test_tool_execution.py (no recursion)
- [ ] Document TDD checklist in docs/08_TESTING_GIT_CICD_GUIDE.md

### **Long-term (v0.10.1)**:
- [ ] Audit all SubAgent system prompts for tool promise accuracy
- [ ] Create test coverage matrix (workflows × tools × outcomes)
- [ ] Add pre-commit hook: Validate SubAgent tools match prompts
- [ ] Migrate all "implementation tests" to "outcome tests"

---

## 📚 References

- **Issue report**: User query "检查为什么失败，而且使用了大量错误的查询？"
- **Affected files**:
  - [src/olav/tools/react_query.py](../src/olav/tools/react_query.py) - Tool implementation
  - [src/olav/agents/orchestrator.py](../src/olav/agents/orchestrator.py) - SubAgent config
  - [tests/e2e/test_units.py](../tests/e2e/test_units.py) - Current test suite
- **Related docs**:
  - [14_data_export_design.md](14_data_export_design.md) - Export tool design
  - [08_TESTING_GIT_CICD_GUIDE.md](08_TESTING_GIT_CICD_GUIDE.md) - Testing strategy

---

**Version**: v0.10.0  
**Status**: Analysis complete, implementation pending
