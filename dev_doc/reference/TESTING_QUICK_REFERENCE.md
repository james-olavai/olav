# Quick Reference - Test Suite Commands

## 📋 Essential Commands

### Run All Agent Tests (with coverage)
```bash
uv run pytest tests/unit/agents/ tests/e2e/test_real_scenarios.py --cov=src/olav/agents --cov-report=term-missing
```

### Run Specific Test File
```bash
uv run pytest tests/unit/agents/test_analyzer.py -v
```

### Run Specific Test Class
```bash
uv run pytest tests/unit/agents/test_analyzer.py::TestAnalyzerDiagnosis -v
```

### Run Specific Test Method
```bash
uv run pytest tests/unit/agents/test_analyzer.py::TestAnalyzerDiagnosis::test_diagnose_issue_state_initialization -v
```

### Generate HTML Coverage Report
```bash
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=html
# Then open: htmlcov/index.html
```

### Run Tests with Verbose Output
```bash
uv run pytest tests/unit/agents/ -vv --tb=short
```

### Run Only Unit Tests (exclude E2E)
```bash
uv run pytest tests/unit/agents/ -v
```

### Run Only E2E Tests
```bash
uv run pytest tests/e2e/test_real_scenarios.py -v
```

### Run CLI E2E Tests (subprocess-based)
```bash
# All CLI tests (tests actual CLI via subprocess)
uv run pytest tests/e2e/test_cli_scenarios.py -v

# Fast tests only (no LLM calls)
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIBasicCommands -v

# Specific CLI test
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIQueryCommand::test_query_list_devices -v
```

### Check for Slow Tests
```bash
uv run pytest tests/unit/agents/ --durations=10
```

---

## 🔍 Code Quality Commands

### Check Ruff Violations
```bash
uv run ruff check src/olav/agents/
```

### Auto-Fix Ruff Issues
```bash
uv run ruff check src/olav/agents/ --fix
```

### Show Proposed Fixes
```bash
uv run ruff check src/olav/agents/ --show-fixes
```

### Format Code (Ruff)
```bash
uv run ruff format src/olav/agents/
```

---

## 📊 Test Status at a Glance

```
✅ Total Tests:        135
✅ Unit Tests:         114
✅ E2E Tests:          21
✅ Pass Rate:          100%
⏱️ Execution Time:     ~92 seconds

Coverage (Agents):
  - orchestrator.py:          67%
  - analyzer.py:              18% 
  - query_agent.py:           10%
  - agent_enhancements.py:     0%
  - Others:                    0-20%
  
  Target: 50%+ overall agents
```

---

## 🧪 Test Files Reference

| File | Tests | Status |
|------|-------|--------|
| test_analyzer.py | 28 | ✅ Real |
| test_query_agent.py | 30 | ✅ Real |
| test_orchestrator.py | 16 | ✅ Real |
| test_agent_enhancements.py | 21 | ✅ Structured |
| test_intent_agent.py | 2 | ✅ Working |
| test_diagnosis_cache.py | 3 | ✅ Working |
| test_inspector.py | 2 | ✅ Working |
| test_textfsm_agent.py | 5 | ✅ Working |
| test_relevance_checker.py | 3 | ✅ Working |
| test_subagent_pool.py | 3 | ✅ Working |
| conftest.py | 14 fixtures | ✅ Ready |

---

## 🛠️ Common Tasks

### Add a New Test
1. Add to appropriate test file (e.g., `test_analyzer.py`)
2. Use fixtures from `conftest.py`
3. Follow pattern: Arrange → Act → Assert
4. Run: `uv run pytest <file>::<class>::<method> -v`

### Fix a Test
1. Run test with verbose output: `uv run pytest -vv`
2. Check error message and stack trace
3. Update test logic or fixture
4. Re-run to verify

### Check Test Dependency
```bash
uv run pytest tests/unit/agents/conftest.py -v --collect-only
```

### Run Tests in Parallel
```bash
uv run pytest tests/unit/agents/ -n auto
```

---

## 📈 Performance Tips

- **Fastest**: Single test method (~0.1s)
- **Fast**: Single test class (~0.5s)
- **Medium**: Single test file (~3-5s)
- **Full suite**: All agent tests (~13s), with E2E (~92s)

To speed up:
```bash
# Use pytest-xdist for parallel execution
uv run pytest tests/unit/agents/ -n auto --dist loadscope
```

---

## 🔧 Debugging

### See Full Traceback
```bash
uv run pytest tests/unit/agents/test_analyzer.py::TestAnalyzerDiagnosis::test_diagnose_issue_state_initialization -vv --tb=long
```

### Stop on First Failure
```bash
uv run pytest tests/unit/agents/ -x
```

### Show Print Statements
```bash
uv run pytest tests/unit/agents/ -s
```

### Drop into Debugger on Failure
```bash
uv run pytest tests/unit/agents/ --pdb
```

### Run with Logging
```bash
uv run pytest tests/unit/agents/ --log-cli-level=DEBUG
```

---

## �️ CLI E2E Testing (True User Simulation)

### Why CLI E2E Tests?

**Problem**: Existing E2E tests (`test_real_scenarios.py`) import `orchestrate_query()` directly, bypassing the CLI layer:

```python
# ❌ Bypasses CLI layer
from olav.agents.orchestrator import orchestrate_query
result = await orchestrate_query("query text")
```

**Misses CLI-specific bugs**:
- ❌ Typer argument parsing errors
- ❌ Command routing issues
- ❌ Exit code handling bugs
- ❌ Console output formatting problems
- ❌ Environment variable loading failures
- ❌ Interactive mode issues

**Solution**: CLI E2E tests (`test_cli_scenarios.py`) execute real commands via subprocess:

```python
# ✅ Tests full CLI stack
tester = CLITester()
result = tester.run_command(["query", "list devices"])
assert result.exit_code == 0
assert "router" in result.stdout
```

### CLI Test Utilities

```python
from tests.utils.cli_tester import (
    CLITester,
    CLIAssertions,
    CLITestEnvironment,
)

def test_my_cli_command():
    """Test actual CLI command via subprocess."""
    tester = CLITester(timeout=30.0)
    
    # Execute: uv run olav query "list devices"
    result = tester.run_query("list devices")
    
    # Assertions
    CLIAssertions.assert_success(result)
    CLIAssertions.assert_contains(result, "router")
    CLIAssertions.assert_llm_execution(result, min_time=1.0)
    CLIAssertions.assert_no_errors(result)
```

### CLI Test Examples

**Basic Commands (No LLM)**:
```bash
# Fast tests - no API calls
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIBasicCommands -v

# Tests: version, devices, doctor commands
# Duration: ~5-10 seconds
```

**Query Commands (Real LLM)**:
```bash
# Tests real LLM API calls via CLI
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIQueryCommand -v

# Tests: Query with LLM, exports, debug flag
# Duration: ~30-60 seconds
```

**Error Handling**:
```bash
# Tests exit codes, invalid args, missing API keys
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIErrorHandling -v
```

**Output Formatting**:
```bash
# Tests Rich console, markdown, tables
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIOutputFormat -v
```

**Environment Variables**:
```bash
# Tests OLAV_EXPORTS_DIR, OLAV_LOG_LEVEL overrides
uv run pytest tests/e2e/test_cli_scenarios.py::TestCLIEnvironment -v
```

### Isolated Test Environment

```python
def test_with_isolated_env():
    """Test with temporary directories and clean environment."""
    with CLITestEnvironment() as env:
        # Execute command in isolated environment
        result = env.tester.run_query("export devices to csv")
        
        # Check files in isolated exports directory
        csv_files = list(env.exports_dir.glob("*.csv"))
        assert len(csv_files) == 1
        
        # Environment auto-cleaned up after test
```

### CLI Testing Best Practices

1. **Test Real Commands**: Use `CLITester.run_command()`, not direct Python imports
2. **Check Exit Codes**: Assert `result.exit_code == 0` for success
3. **Capture Output**: Use `result.stdout`, `result.stderr`
4. **Isolate Environment**: Use `CLITestEnvironment` for file/directory tests
5. **Fast vs Slow**: Separate tests by `requires_llm` marker
6. **Timeout Protection**: Set appropriate timeouts (10s basic, 60s LLM queries)

### Test Coverage

| Test Suite | What It Tests | What It Misses |
|------------|---------------|----------------|
| `test_real_scenarios.py` | Orchestrator, agents, tools logic | CLI layer, exit codes, output format |
| `test_cli_scenarios.py` | Full CLI stack via subprocess | N/A (tests everything) |

**Recommendation**: Run both test suites for comprehensive coverage.

---

## �📝 Documentation

- **Progress Report**: [docs/25_pytest_ruff_improvement_progress.md](docs/25_pytest_ruff_improvement_progress.md)
- **Improvement Plan**: [docs/24_pytest_ruff_improvement_plan.md](docs/24_pytest_ruff_improvement_plan.md)
- **OLAV Dev Guide**: [.github/copilot-instructions.md](.github/copilot-instructions.md)
- **Code Audit**: [docs/99_audit.md](docs/99_audit.md)

---

## ⚡ Next Steps

1. **Improve Coverage**: Focus on query_agent.py (10% → 80%)
2. **Implement Tests**: agent_enhancements.py (0% → 75%)
3. **Fix Ruff**: Resolve 18 remaining violations
4. **Target**: Reach 25-35% agent coverage in Phase 3

---

**Last Updated**: January 2025  
**For Questions**: Refer to [docs/25_pytest_ruff_improvement_progress.md](docs/25_pytest_ruff_improvement_progress.md)
