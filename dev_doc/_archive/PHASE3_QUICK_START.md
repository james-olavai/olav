# Phase 3 Quick Start Guide

## 🚀 What to Do Next

### Current Status
✅ **135 tests passing** (100% pass rate)  
✅ **Test framework complete** (11 files, 14 fixtures)  
✅ **Async/sync normalized** (all clean)  
⏸️ **Phase 2 complete** - Ready for Phase 3

---

## 📋 Phase 3 Roadmap

### Priority 1: query_agent.py (MOST CRITICAL)
**Current**: 10% coverage (27/274 stmts)  
**Target**: 80% coverage  
**Work**: Implement 30 real tests

**What to do**:
1. Open: `tests/unit/agents/test_query_agent.py`
2. Find skeleton tests (marked with `pass`)
3. Replace with real implementation:
   ```python
   def test_query_database_with_valid_sql(self, mock_db):
       # Arrange
       sql = "SELECT * FROM devices WHERE id = ?"
       params = [1]
       mock_db.query.return_value = [{"id": 1, "name": "router1"}]
       
       # Act
       result = mock_db.query(sql, params)
       
       # Assert
       assert len(result) == 1
       assert result[0]["name"] == "router1"
   ```

**Test Classes to Complete**:
- TestQueryAgentContextPreparation (3 tests)
- TestQueryAgentRouting (3 tests)
- TestQueryAgentExecution (3 tests)
- TestQueryAgentFormatting (3 tests)
- TestQueryAgentCaching (3 tests)
- TestQueryAgentEdgeCases (6 tests)
- TestQueryAgentIntegration (2 tests)

### Priority 2: agent_enhancements.py
**Current**: 0% coverage (0/254 stmts)  
**Target**: 75% coverage  
**Work**: Implement 21 real tests

**Test Classes**:
- TestAgentEnhancementsEmbeddings
- TestAgentEnhancementsCaching
- TestAgentEnhancementsFormatting
- TestAgentEnhancementsContextBuilding
- TestAgentEnhancementsValidation
- TestAgentEnhancementsErrorHandling
- TestAgentEnhancementsPerformance
- TestAgentEnhancementsIntegration

---

## 💻 How to Continue

### Step 1: Setup
```bash
cd /home/yhvh/Olav
uv run pytest tests/unit/agents/ -q  # Verify 114 tests pass
```

### Step 2: Start with query_agent.py
```bash
# Find skeleton tests
grep -n "pass$" tests/unit/agents/test_query_agent.py

# Run tests to see what fails
uv run pytest tests/unit/agents/test_query_agent.py -v

# Pick one test to implement
uv run pytest tests/unit/agents/test_query_agent.py::TestQueryAgentContextPreparation::test_prepare_context_with_schema -v
```

### Step 3: Implement Real Test Logic
1. Remove the `pass` statement
2. Add real implementation using fixtures
3. Run test to verify it passes
4. Move to next test

### Step 4: Check Coverage
```bash
uv run pytest tests/unit/agents/ --cov=src/olav/agents/query_agent --cov-report=term-missing
```

### Step 5: Commit Progress
```bash
git add tests/unit/agents/test_query_agent.py
git commit -m "feat(tests): implement query_agent real tests - coverage 10% → 45%"
```

---

## 🔧 Useful Commands

### Quick Test Run
```bash
# Run query_agent tests only
uv run pytest tests/unit/agents/test_query_agent.py -v

# Run specific test class
uv run pytest tests/unit/agents/test_query_agent.py::TestQueryAgentContextPreparation -v

# Run one test with output
uv run pytest tests/unit/agents/test_query_agent.py::TestQueryAgentContextPreparation::test_prepare_context_with_schema -vv -s
```

### Coverage Analysis
```bash
# Check current coverage
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=term-missing | grep query_agent

# Generate HTML coverage for detail
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=html
# Open: htmlcov/index.html
```

### Debugging
```bash
# Run with full traceback
uv run pytest tests/unit/agents/test_query_agent.py -vv --tb=long

# Stop on first failure
uv run pytest tests/unit/agents/test_query_agent.py -x

# Drop into debugger
uv run pytest tests/unit/agents/test_query_agent.py --pdb

# Show print statements
uv run pytest tests/unit/agents/test_query_agent.py -s
```

---

## 📚 Reference Files

### Available Fixtures (in conftest.py)
```python
mock_db              # Mock database with query(), execute(), get_schema()
mock_llm             # Mock LLM with predict(), invoke()
mock_cache           # Mock cache with get(), set(), exists()
mock_router          # Mock router with route(), get_agent_type()
sample_diagnostic_data   # Real diagnostic data dict
sample_query_data    # Real query results list
agent_dependencies   # All dependencies bundled
sample_orchestrator_state # Orchestrator state
mock_nornir          # Nornir mock with run_command()
sample_nornir_output # Real Nornir output examples
mock_langchain_tool  # LangChain tool mock
mock_embedding_model # Embedding model mock
```

### How to Use Fixtures
```python
def test_example(self, mock_db, sample_query_data):
    # Use mock_db
    mock_db.query.return_value = sample_query_data
    
    # Act
    result = mock_db.query("SELECT * FROM devices")
    
    # Assert
    assert len(result) == 2
```

---

## ⚡ Quick Test Template

```python
class TestYourAgent:
    """Your agent tests."""
    
    def test_your_feature(self, mock_db, sample_query_data):
        """Test description."""
        # Arrange
        expected_value = "something"
        mock_db.query.return_value = sample_query_data
        
        # Act
        result = mock_db.query("SELECT * FROM devices")
        
        # Assert
        assert result is not None
        assert len(result) == 2
```

---

## 📊 Progress Tracking

### Coverage Goals
```
Current:  8.61% (8462 stmts, 7733 missing)
Phase 3:  15-25% (improve 6-17%)
Phase 4:  50%+ (improve another 25-30%)
```

### Test Count Goals
```
Current:  135 tests
Phase 3:  160+ tests (add 25+)
Phase 4:  200+ tests (add 40+)
```

### Time Estimate
```
query_agent.py:      2-3 hours (30 tests × 4-6 min/test)
agent_enhancements:  2-3 hours (21 tests × 6-8 min/test)
Other modules:       2 hours
Testing/fixing:      1 hour
Total Phase 3:       7-9 hours
```

---

## ❓ Common Questions

### Q: Which test should I implement first?
**A**: Start with `test_prepare_context_with_schema` in TestQueryAgentContextPreparation. It's simple and foundational.

### Q: How do I know if my test is correct?
**A**: Run it:
```bash
uv run pytest tests/unit/agents/test_query_agent.py::TestQueryAgentContextPreparation::test_prepare_context_with_schema -v
```
If it passes (shows PASSED), you're good!

### Q: What if I break something?
**A**: All tests are independent. Just run all tests:
```bash
uv run pytest tests/unit/agents/ -q
```
Should still show 114 unit tests passing + your new ones.

### Q: How much coverage is enough?
**A**: For this phase, aim for 70%+ per module. The goal is comprehensive coverage of happy path + edge cases.

---

## 🎯 Success Checklist for Phase 3

- [ ] query_agent.py coverage: 10% → 80%
- [ ] agent_enhancements.py coverage: 0% → 75%
- [ ] Other modules: 0-20% → 70%
- [ ] All 160+ tests passing
- [ ] Overall coverage: 15-25%
- [ ] 18 ruff violations fixed
- [ ] Documentation updated

---

## 🚀 Ready to Go!

Everything is set up and ready. The framework is solid, fixtures are working, and all you need to do is implement real test logic in the skeleton tests.

**Good luck! You've got this! 💪**

---

**Last Updated**: February 6, 2026  
**Status**: Ready for Phase 3  
**Estimated Time**: 7-9 hours  
**Difficulty**: Medium (copy-paste + modify pattern)
