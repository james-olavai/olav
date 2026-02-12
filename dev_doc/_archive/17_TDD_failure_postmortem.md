# TDD Failure Postmortem - Why Tests Passed but Production Failed

**Date**: 2026-02-05  
**Context**: v0.10.0 query routing failure  
**Impact**: 17/17 tests passing, manual test completely failed

---

## 🔥 The Incident

**Test Status**: ✅ 17/17 passing (100%)  
**Production Status**: ❌ Complete failure

```bash
# Tests say everything is fine
$ uv run pytest tests/e2e/test_units.py -v
======================== 17 passed in 15.2s ========================

# Production says everything is broken
$ uv run olav query "save all devices' version info to csv"
⚡ Fast-Path: query_database → MISS
🔍 Agent analysis...
❌ Executing: show ospf neighbor (WRONG!)
❌ Executing: show bgp summary (WRONG!)
❌ Executing: show cdp neighbors (WRONG!)
⚠️ R2 failed repeatedly
📁 Created poor-quality CSV with R2 unavailable
```

**User reaction**: "为什么测试总是无法发现问题？"

**Critical insight**: Our tests validated **implementation details**, not **user outcomes**.

---

## 🔍 Root Cause Analysis: Why TDD Failed

### **1. Test Coverage Illusion** 🎭

**What we tested**:
```python
class TestCliQueries:
    def test_simple_show_devices_query(self):
        """Test: 'show devices' returns device list"""
        result = cli_query("show devices")
        assert "R1" in result.stdout  # ✅ Pass
        
    def test_device_count_query(self):
        """Test: 'how many devices' returns count"""
        result = cli_query("how many devices")
        assert "6" in result.stdout  # ✅ Pass
```

**What we DIDN'T test**:
- ❌ Multi-step workflows (query → process → export)
- ❌ LLM routing decisions (which SubAgent gets called)
- ❌ Tool chain integrity (promised tools actually exist)
- ❌ Error recovery paths (Fast-Path → Agent fallback)
- ❌ Complex queries requiring multiple operations

**Analogy**: Testing a car by checking "engine starts" and "wheels turn", but never actually **driving** it.

---

### **2. Mocking vs Reality Gap** 🪞

**The test path** (fast, isolated):
```
User query → Direct SQL → Return data ✅
(Fast-Path hit, 0.2s response)
```

**The production path** (slow, integrated):
```
User query → Cache miss → Fast-Path miss → Agent fallback
→ SubAgent routing → Tool selection → query_network
→ NEW QueryAgent() → Wrong understanding → Wrong commands ❌
```

**Problem**: Tests hit **happy path** (Fast-Path), production hit **fallback path** (Agent).

**Key insight**: Tests validated Fast-Path works, but didn't validate **what happens when Fast-Path fails**.

---

### **3. Test the What, Not the How** 🎯

**Current tests** (implementation-focused):
```python
# ❌ BAD: Tests implementation detail
def test_query_database_works():
    result = query_database("SELECT * FROM devices")
    assert len(result) > 0
    assert result[0]['hostname'] == 'R1'
    # ✅ Pass - DB query works
    # ❌ Doesn't test if USER can export to CSV
```

**Better tests** (outcome-focused):
```python
# ✅ GOOD: Tests user outcome
def test_user_can_export_device_versions_to_csv():
    cli_query("save all devices' version info to csv")
    
    # Verify outcome: CSV file exists with correct data
    csv_path = Path("exports").glob("*version*.csv")
    assert csv_path.exists()
    
    # Verify data quality
    df = pd.read_csv(csv_path)
    assert len(df) == 6  # All devices
    assert 'hostname' in df.columns
    assert 'version' in df.columns
    assert df['hostname'].tolist() == ['R1', 'R2', 'R3', 'R4', 'SW1', 'SW2']
```

**Difference**:
- Implementation test: "Does query_database() return data?"
- Outcome test: "Can user accomplish their goal?"

---

### **4. Tool Promise vs Reality** 🤥

**The lie in system prompt**:
```python
SubAgent(
    name="query",
    system_prompt=(
        "You have access to:\n"
        "4. Database query tools: query_database, inspect_schema, smart_query\n\n"
        # ⬆️ PROMISE: 3 tools available
    ),
    tools=query_tools,  # ❌ REALITY: Only [query_network]
)
```

**Why tests didn't catch this**:
- Tests called CLI directly (no SubAgent routing)
- Tests didn't validate **tool availability**
- Tests didn't check if **system prompt matches tools list**

**Proposed test**:
```python
def test_subagent_tools_match_promises():
    """Verify SubAgent tools match system prompt declarations."""
    subagents = _create_subagents()
    
    for subagent in subagents:
        # Extract tool names from prompt
        promised_tools = extract_tool_names(subagent.system_prompt)
        actual_tools = [t.name for t in subagent.tools]
        
        # Verify promises match reality
        for tool in promised_tools:
            assert tool in actual_tools, (
                f"{subagent.name} SubAgent promises '{tool}' but doesn't provide it"
            )
```

---

### **5. Integration Blind Spots** 🕶️

**What we tested** (isolated components):
```
✅ query_database() works
✅ format_and_export() works
✅ SubAgent routing config valid
✅ CLI query command works
```

**What we MISSED** (component interactions):
```
❌ query SubAgent → query_network → NEW QueryAgent (recursion!)
❌ Orchestrator can't call format_and_export (not in tools)
❌ query_network doesn't preserve context from parent agent
❌ Fast-Path miss → Agent fallback → wrong tool selection
```

**Lesson**: **Isolated tests ≠ Integrated system**

**Analogy**: Testing keyboard, mouse, monitor separately, but never plugging them together to test if computer works.

---

## 📊 Coverage Analysis

### **Current Test Distribution**

```
Test Type          | Count | % Coverage
-------------------|-------|------------
CLI Startup        |   4   |   23%     (version, help, startup, interactive)
Database Queries   |   3   |   18%     (table, fields, devices)
Performance        |   2   |   12%     (speed, multiple queries)
Error Handling     |   1   |    6%     (invalid query)
Cache Behavior     |   2   |   12%     (directory, readability)
CLI Integration    |   5   |   29%     (show, list, count, name, interfaces)
-------------------|-------|------------
TOTAL              |  17   |  100%
```

### **Missing Test Categories**

```
Test Category              | Priority | Estimated Tests
---------------------------|----------|----------------
Multi-step Workflows       | 🔴 HIGH  |      5-8
SubAgent Routing Logic     | 🔴 HIGH  |      8-12
Export Operations          | 🔴 HIGH  |      3-5
Tool Chain Validation      | 🟡 MED   |      4-6
Error Recovery Paths       | 🟡 MED   |      6-10
Context Preservation       | 🟡 MED   |      3-5
LLM Decision Validation    | 🟢 LOW   |      5-8
---------------------------|----------|----------------
TOTAL MISSING              |          |    34-54 tests
```

**Insight**: We have **17 tests for 6 categories**, missing **7 critical categories** (~40 tests).

**Real coverage**: ~30% (17 out of ~60 needed tests)

---

## 🎓 Lessons Learned

### **Lesson 1: Test User Journeys, Not Code Paths** 🚶

**DON'T**:
```python
# ❌ Testing internal implementation
def test_query_agent_has_tools():
    agent = QueryAgent()
    assert hasattr(agent, 'tools')
    assert len(agent.tools) > 0
```

**DO**:
```python
# ✅ Testing user outcome
def test_user_can_find_device_by_ip():
    cli_query("which device has IP 10.0.0.1")
    # Verify answer is correct and helpful
    assert "R1" in result.stdout
```

---

### **Lesson 2: Test Failure Modes, Not Just Success** 🚫

**DON'T**:
```python
# ❌ Only testing happy path
def test_query_database():
    result = query_database("SELECT * FROM devices")
    assert len(result) > 0  # ✅ Works when DB has data
```

**DO**:
```python
# ✅ Testing failure modes
def test_query_database_failure_recovery():
    # What happens when query fails?
    result = query_database("SELECT * FROM nonexistent_table")
    assert "Error" in result
    assert "Use inspect_schema()" in result  # Helpful hint
    
    # What happens when Fast-Path misses?
    result = cli_query("complex multi-step query")
    assert "Fell back to Agent" not in result  # Should not expose internals
    assert result.exit_code == 0  # Should still succeed
```

---

### **Lesson 3: Validate Promises Match Reality** 🤝

**DON'T**:
```python
# ❌ Trust system prompts
def test_query_subagent_exists():
    subagents = _create_subagents()
    assert any(s.name == "query" for s in subagents)
```

**DO**:
```python
# ✅ Verify promises are kept
def test_query_subagent_provides_promised_tools():
    subagents = _create_subagents()
    query_agent = next(s for s in subagents if s.name == "query")
    
    # Extract from prompt: "Database query tools: query_database, inspect_schema"
    promised = ["query_database", "inspect_schema"]
    actual = [t.name for t in query_agent.tools]
    
    for tool in promised:
        assert tool in actual, f"Promised tool '{tool}' not provided"
```

---

### **Lesson 4: Test Integration, Not Isolation** 🔗

**DON'T**:
```python
# ❌ Test components separately
def test_database_works():
    assert query_database("SELECT 1") == [{"1": 1}]
    
def test_export_works():
    assert format_and_export({"test": 1}, "test") == "exported"
```

**DO**:
```python
# ✅ Test component interaction
def test_database_to_export_pipeline():
    # Full workflow: query → process → export
    data = query_database("SELECT * FROM devices")
    assert len(data) > 0
    
    export_path = format_and_export(data, filename="devices", format="csv")
    assert export_path.exists()
    
    # Verify exported data matches query result
    import csv
    with open(export_path) as f:
        reader = csv.DictReader(f)
        exported_data = list(reader)
    
    assert len(exported_data) == len(data)
    assert exported_data[0]['hostname'] == data[0]['hostname']
```

---

### **Lesson 5: Test the Orchestrator, Not Just Tools** 🎼

**DON'T**:
```python
# ❌ Test individual SubAgents
def test_query_subagent():
    # Test query SubAgent in isolation
    ...
    
def test_cli_subagent():
    # Test CLI SubAgent in isolation
    ...
```

**DO**:
```python
# ✅ Test orchestrator routing decisions
def test_orchestrator_routes_to_correct_subagent():
    # Simple query → should use query SubAgent
    with patch('query_subagent.invoke') as mock_query:
        cli_query("show devices")
        mock_query.assert_called_once()
    
    # Complex analysis → should use expert SubAgent
    with patch('expert_subagent.invoke') as mock_expert:
        cli_query("diagnose OSPF issues on R1")
        mock_expert.assert_called_once()
```

---

## 🛠️ Action Plan: Fix the TDD Process

### **Phase 1: Immediate Fixes** (This Week)

**Goal**: Catch the failure that just happened

```python
# tests/e2e/test_export_workflows.py

class TestExportWorkflows:
    """Test real user export workflows."""
    
    def test_export_device_versions_to_csv(self):
        """User: 'save all devices version info to csv'"""
        result = cli_query("save all devices' version info to csv")
        
        # Should succeed
        assert result.exit_code == 0
        
        # Should NOT execute wrong commands
        assert "ospf" not in result.stdout.lower()
        assert "bgp" not in result.stdout.lower()
        assert "cdp" not in result.stdout.lower()
        
        # Should create valid CSV
        csv_files = list(Path("exports").glob("*version*.csv"))
        assert len(csv_files) == 1
        
        # Should have data for ALL devices
        df = pd.read_csv(csv_files[0])
        assert len(df) == 6
        assert all(device in df['hostname'].values 
                  for device in ['R1', 'R2', 'R3', 'R4', 'SW1', 'SW2'])
```

**Acceptance**: If this test existed, it would have **failed** and caught the bug.

---

### **Phase 2: Tool Validation** (Next Week)

**Goal**: Prevent promise vs reality mismatches

```python
# tests/unit/test_subagent_tools.py

def test_all_subagents_tools_match_prompts():
    """Validate SubAgent tools match system prompt promises."""
    subagents = _create_subagents()
    
    for subagent in subagents:
        # Extract tool promises from prompt
        # Pattern: "tools: tool1, tool2, tool3"
        import re
        pattern = r"tools?:\s*([a-z_,\s]+)"
        matches = re.findall(pattern, subagent.system_prompt, re.IGNORECASE)
        
        if not matches:
            continue  # No tool promises in prompt
        
        promised = [t.strip() for match in matches 
                   for t in match.split(',')]
        actual = [t.name for t in subagent.tools]
        
        for tool in promised:
            assert tool in actual, (
                f"SubAgent '{subagent.name}' promises tool '{tool}' "
                f"but only provides {actual}"
            )
```

---

### **Phase 3: Integration Testing** (Sprint 2)

**Goal**: Test component interactions

```python
# tests/integration/test_subagent_interactions.py

class TestSubAgentInteractions:
    """Test SubAgent delegation and result handling."""
    
    def test_orchestrator_delegates_to_query_subagent(self):
        """Orchestrator should delegate DB queries to query SubAgent."""
        with patch('query_subagent') as mock_query:
            mock_query.return_value = [{"hostname": "R1"}]
            
            orchestrator = create_orchestrator()
            result = orchestrator.invoke("show devices")
            
            # Should call query SubAgent
            mock_query.assert_called_once()
            
            # Should NOT create new QueryAgent
            with patch('QueryAgent.__init__') as mock_init:
                mock_init.assert_not_called()
    
    def test_query_subagent_returns_data_not_exports(self):
        """query SubAgent should return data, not export files."""
        result = query_subagent_invoke("get device list")
        
        # Should return data structure
        assert isinstance(result, (list, dict))
        
        # Should NOT create files
        before = list(Path("exports").glob("*"))
        after = list(Path("exports").glob("*"))
        assert len(before) == len(after)
```

---

### **Phase 4: Outcome-Based Testing** (Sprint 3)

**Goal**: Rewrite all tests to focus on user outcomes

**Before** (implementation-focused):
```python
class TestDatabaseOperations:
    def test_query_database_returns_list(self):
        result = query_database("SELECT * FROM devices")
        assert isinstance(result, list)
    
    def test_query_database_has_columns(self):
        result = query_database("SELECT * FROM devices")
        assert 'hostname' in result[0]
```

**After** (outcome-focused):
```python
class TestUserCanQueryNetworkData:
    def test_user_can_list_all_devices(self):
        """User: 'show me all devices'"""
        result = cli_query("show me all devices")
        assert all(device in result.stdout 
                  for device in ['R1', 'R2', 'R3', 'R4', 'SW1', 'SW2'])
    
    def test_user_can_export_device_list(self):
        """User: 'save device list to file'"""
        cli_query("save device list to file")
        exported_files = list(Path("exports").glob("device*"))
        assert len(exported_files) > 0
```

---

## 📋 New Testing Checklist

For every new feature, ensure:

### **1. User Journey Tests** ✅
- [ ] Test complete user workflow (A → Z)
- [ ] Test from CLI entry point, not internal functions
- [ ] Verify outcome, not implementation
- [ ] Include setup and teardown in test

### **2. Failure Mode Tests** ✅
- [ ] Test what happens when database is empty
- [ ] Test what happens when network is down
- [ ] Test what happens when file already exists
- [ ] Test what happens when LLM returns error

### **3. Tool Chain Validation** ✅
- [ ] Verify promised tools are provided
- [ ] Verify tools don't create infinite recursion
- [ ] Verify tools preserve context
- [ ] Verify error messages are helpful

### **4. Integration Tests** ✅
- [ ] Test component A → B interactions
- [ ] Test orchestrator routing decisions
- [ ] Test SubAgent result handling
- [ ] Test cache hit/miss scenarios

### **5. Performance Baselines** ✅
- [ ] Simple query < 1s (Fast-Path)
- [ ] Complex query < 10s (Agent)
- [ ] Export operation < 5s
- [ ] No infinite loops or hangs

---

## 🎯 Success Metrics

### **Before** (Current State)
- 17 tests, 100% passing ✅
- Manual test: Complete failure ❌
- User confidence: Low 📉
- Bug detection: 0% for this issue

### **After** (Target State)
- 50+ tests covering user journeys ✅
- Manual test: Same result as automated tests ✅
- User confidence: High 📈
- Bug detection: 90%+ for integration issues

---

## 🔮 Preventing Future Failures

### **1. Pre-Commit Hooks**

```bash
# .git/hooks/pre-commit
#!/bin/bash

# Run tool validation tests
uv run pytest tests/unit/test_subagent_tools.py -v

# Run user journey tests
uv run pytest tests/e2e/test_export_workflows.py -v

# Check for tool recursion
grep -r "QueryAgent()" src/olav/tools/ && {
    echo "❌ BLOCKED: Tools must not create agents"
    exit 1
}
```

---

### **2. CI/CD Stages**

```yaml
# .github/workflows/test.yml

jobs:
  unit-tests:
    - run: pytest tests/unit/ -v
    
  integration-tests:
    - run: pytest tests/integration/ -v
    
  e2e-user-journeys:  # NEW: Mandatory
    - run: pytest tests/e2e/test_export_workflows.py -v
    - run: pytest tests/e2e/test_analysis_workflows.py -v
    
  manual-smoke-test:  # NEW: Run actual CLI commands
    - run: uv run olav query "save device list to csv"
    - run: test -f exports/*.csv
```

---

### **3. Test Review Checklist**

Before merging any test PR, verify:

- [ ] Tests execute from CLI entry point (not internal functions)
- [ ] Tests verify user outcomes (not implementation details)
- [ ] Tests include failure scenarios (not just happy path)
- [ ] Tests validate tool promises match reality
- [ ] Tests check integration (not just isolated components)

---

## 📝 Summary

### **Why TDD Failed**

1. **Test Coverage Illusion**: 100% test pass rate, 0% real coverage
2. **Happy Path Bias**: Only tested Fast-Path, not Agent fallback
3. **Implementation Focus**: Tested code works, not user outcomes
4. **Missing Integration**: Tested components separately, not together
5. **No Tool Validation**: Didn't check if promised tools exist

### **How to Fix**

1. **Write User Journey Tests**: Test A→Z workflows
2. **Test Failure Modes**: What happens when things break
3. **Validate Tool Chains**: Promises must match reality
4. **Integration Over Isolation**: Test component interactions
5. **Outcome Over Implementation**: Test goals, not code paths

### **Key Principle**

> **"Tests should fail when users can't accomplish their goals,  
> not when implementation details change."**

If a test passes but the feature doesn't work for users, **the test is lying**.

---

**Version**: v0.10.0  
**Next Review**: After Phase 1 implementation  
**Success Criteria**: Manual test = Automated test result
