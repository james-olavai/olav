# Quick Test Commands Reference
**Updated**: 2026-02-09  
**Status**: Level 1 & 2 ✅ Complete

---

## 🚀 Run All Tests

```bash
# Full test suite (all levels)
uv run pytest tests/e2e/test_real_scenarios.py -v

# Only Level 1-2 (what passed)
uv run pytest tests/e2e/test_real_scenarios.py -v -k "real_llm"

# Fast mode (short output)
uv run pytest tests/e2e/test_real_scenarios.py -v --tb=short

# With detailed output
uv run pytest tests/e2e/test_real_scenarios.py -vv --tb=long
```

---

## 🎯 Run Specific Tests

```bash
# List all tests
uv run pytest tests/e2e/test_real_scenarios.py --collect-only

# Run one test
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_list_devices_real_llm -v

# Run test category
uv run pytest tests/e2e/test_real_scenarios.py -k "export" -v

# Run excluding failures
uv run pytest tests/e2e/test_real_scenarios.py -k "not csv" -v
```

---

## 🧪 Test Single Query (Interactive)

```bash
# List capabilities
uv run olav ask "help"

# Simple query (English)
uv run olav ask "How many devices are there?"

# Chinese query
uv run olav ask "有多少个设备?"

# Complex query
uv run olav ask "List all devices with their interface count"

# Debug mode
OLAV_LOG_LEVEL=DEBUG uv run olav ask "有多少个设备?"
```

---

## 📊 View Test Results

```bash
# HTML coverage report
open htmlcov/index.html

# Last 20 lines of output
uv run pytest tests/e2e/test_real_scenarios.py -v | tail -20

# Save to file
uv run pytest tests/e2e/test_real_scenarios.py -v > test_output.log
```

---

## 🔧 Configuration Checks

```bash
# Verify .env is setup
cat .env | grep LLM_

# Check database connection
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
print('Devices:', conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0])
print('Interfaces:', conn.execute('SELECT COUNT(*) FROM interfaces').fetchone()[0])
"

# Verify LLM API works
uv run python -c "
from src.olav.core.llm_factory import LLMFactory
model = LLMFactory.get_chat_model()
response = model.invoke('Hello, say hi back')
print('LLM Response:', response.content)
"
```

---

## 📈 Performance Check

```bash
# Run with timing
time uv run olav ask "Sum all interface IDs"

# Run 5 queries to check consistency
for i in {1..5}; do
  echo "Query $i:"
  time uv run olav ask "How many devices?" 2>&1 | grep real
done
```

---

## 🐛 Debugging

```bash
# Full debug logging
OLAV_LOG_LEVEL=DEBUG uv run olav ask "有多少个设备?"

# With Python traceback
PYTHONTRACEBACKLIMIT=20 uv run pytest tests/e2e/test_real_scenarios.py -v --tb=long

# Check orchestrator directly
uv run python -c "
import asyncio
from src.olav.agents.orchestrator import orchestrate_query_sync

result = orchestrate_query_sync('有多少个设备?')
print('Result:', result)
"
```

---

## ✅ Pre-commit Verification

```bash
# Before pushing code:
# 1. Run Level 1-2 tests
uv run pytest tests/e2e/test_real_scenarios.py -k "real_llm" -q

# 2. Format code
uv run ruff format src/

# 3. Check imports
uv run ruff check src/ --fix

# 4. Type check
uv run pyright src/ --pythonversion 3.11

# 5. Summary
echo "✅ Ready to commit"
```

---

## 🎯 Level 3 Test Commands (Future)

```bash
# When Level 3 tests are created:
# uv run pytest tests/e2e/test_level3_advanced.py -v

# Run complex filtering tests only
# uv run pytest tests/e2e/test_level3_advanced.py -k "filtering" -v

# Run aggregation tests
# uv run pytest tests/e2e/test_level3_advanced.py -k "aggregate" -v
```

---

## 📋 Test Status Summary

```bash
# One-liner test summary
uv run pytest tests/e2e/test_real_scenarios.py -v --tb=no -q | tail -5
```

---

## 🔄 Common Workflows

### Workflow 1: Fix Failing Test
```bash
# 1. Find problem
uv run pytest tests/e2e/test_real_scenarios.py::test_name -vv

# 2. Fix code
# ... edit file ...

# 3. Verify fix
uv run pytest tests/e2e/test_real_scenarios.py::test_name -v

# 4. Run full suite
uv run pytest tests/e2e/test_real_scenarios.py -v
```

### Workflow 2: Add New Test
```bash
# 1. Create test function in test_real_scenarios.py
# 2. Run to verify it fails
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_new -vv

# 3. Implement feature
# ... edit orchestrator ...

# 4. Verify test passes
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_new -v

# 5. Check full suite
uv run pytest tests/e2e/test_real_scenarios.py -v
```

### Workflow 3: Performance Check
```bash
# Run each test, record time
uv run pytest tests/e2e/test_real_scenarios.py -v | grep PASSED | awk '{print $NF}'

# Average should be <10s, check for outliers
uv run pytest tests/e2e/test_real_scenarios.py -v 2>&1 | grep -E "PASSED|FAILED"
```

---

## 💾 Useful Bash Aliases

Add to `.bashrc` or `.zshrc`:

```bash
# Fast test run
alias test='uv run pytest tests/e2e/test_real_scenarios.py -v -k "real_llm" --tb=short'

# Quick query
alias olavask='uv run olav ask'

# Debug mode
alias olavdebug='OLAV_LOG_LEVEL=DEBUG uv run olav ask'

# Check database
alias olavdb='uv run python -c "
import duckdb
conn = duckdb.connect(\".olav/db/main.duckdb\")  
print(\"Devices:\", conn.execute(\"SELECT COUNT(*) FROM devices\").fetchone()[0])
print(\"Interfaces:\", conn.execute(\"SELECT COUNT(*) FROM interfaces\").fetchone()[0])
"'
```

---

## 📞 Quick Help

```bash
# List available commands
uv run olav --help

# Show version
uv run olav --version

# Test help system
uv run olav ask "what can you do?"
```

---

**Last Updated**: 2026-02-09  
**Test Status**: Level 1-2 ✅ Complete (13/14 PASS)  
**Next**: Level 3 Advanced Testing

