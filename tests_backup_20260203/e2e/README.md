# OLAV E2E Tests

This directory contains End-to-End tests for OLAV v0.9.3.

## Test Categories

### 1. Integration Tests (Fast, Free)
**Classes**: `TestConfiguration*`, `TestData*`, `TestDatabase*`, `TestTopology*`, `TestReport*`, `TestDataFlow*`, `TestAgentIntegration`

- **Runtime**: 2-5 seconds
- **Cost**: Free (no API calls)
- **Purpose**: Validate configuration, directory structure, database schema, and object creation
- **Dependencies**: None (uses mocks and in-memory databases)

**Run with**:
```bash
# Run all integration tests (default)
uv run pytest tests/e2e/test_complete_e2e_validation.py -v -m "not e2e"

# Or use --no-cov to skip coverage requirement
uv run pytest tests/e2e/test_complete_e2e_validation.py -v --no-cov -m "not e2e"
```

### 2. Real E2E Tests (Slow, Expensive)
**Class**: `TestRealE2EWorkflow`

- **Runtime**: 30 seconds - 5 minutes
- **Cost**: $0.10-$1.00 per run (LLM API tokens + device connection time)
- **Purpose**: Full workflow validation with real devices and LLM
- **Dependencies**: 
  - `.env` with `OPENAI_API_KEY` or `DEEPSEEK_API_KEY`
  - `.olav/inventory.yaml` with real device credentials

**Tests**:
- `test_21_real_device_sync`: Sync real devices with nornir (requires inventory.yaml)
- `test_22_real_llm_analysis`: Run LLM analysis on synced data (requires .env + data)
- `test_23_full_e2e_workflow`: Complete workflow (sync → parse → analyze → report)

**Run with**:
```bash
# Run all E2E tests
uv run pytest tests/e2e/test_complete_e2e_validation.py -v -m e2e --no-cov

# Run specific test
uv run pytest tests/e2e/test_complete_e2e_validation.py::TestRealE2EWorkflow::test_21_real_device_sync -v --no-cov

# Run only network tests (device sync)
uv run pytest tests/e2e/ -v -m network --no-cov

# Run only LLM tests
uv run pytest tests/e2e/ -v -m llm --no-cov
```

## Prerequisites

### For Integration Tests
No special setup required. Tests use:
- In-memory DuckDB (`:memory:`)
- Temporary directories
- No external API calls

### For Real E2E Tests

1. **Environment File** (`.env`):
   ```bash
   OPENAI_API_KEY=sk-...
   # OR
   DEEPSEEK_API_KEY=sk-...
   DEEPSEEK_API_BASE=https://api.deepseek.com
   ```

2. **Inventory File** (`.olav/inventory.yaml`):
   ```yaml
   devices:
     - hostname: R1
       ip: 192.168.1.1
       username: admin
       password: cisco
       platform: cisco_ios
     
     - hostname: SW1
       ip: 192.168.1.2
       username: admin
       password: cisco
       platform: cisco_ios
   ```

3. **Network Access**:
   - Devices must be reachable from test environment
   - SSH access enabled on devices

## Test Markers

All markers are defined in `pyproject.toml`:

- `e2e`: End-to-end tests (slow, expensive)
- `network`: Tests requiring real device access
- `llm`: Tests requiring real LLM API calls
- `integration`: Integration tests (fast, free)
- `unit`: Unit tests (fastest)

## Cost Estimation

### Integration Tests
- **Cost**: $0.00
- **Runtime**: ~2-5 seconds
- **API Calls**: 0

### Real E2E Tests
- **test_21_real_device_sync**:
  - Cost: $0.00 (no LLM calls)
  - Runtime: 10-60 seconds (depends on device count)
  - API Calls: 0

- **test_22_real_llm_analysis**:
  - Cost: $0.05-$0.20 (depends on data volume)
  - Runtime: 5-30 seconds
  - API Calls: 1-3 (depends on skill routing)

- **test_23_full_e2e_workflow**:
  - Cost: $0.10-$1.00 (sync + analysis + report generation)
  - Runtime: 30-300 seconds
  - API Calls: 2-5 (routing + analysis + formatting)

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run integration tests
        run: |
          uv run pytest tests/e2e/ -v -m "not e2e" --no-cov
  
  e2e:
    runs-on: ubuntu-latest
    # Only run on main branch or manual trigger
    if: github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
      - name: Run E2E tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          uv run pytest tests/e2e/ -v -m e2e --no-cov
```

## Troubleshooting

### "No .env file found"
- Create `.env` file with API keys (see Prerequisites)
- Or skip E2E tests: `pytest -m "not e2e"`

### "inventory.yaml not found"
- Create `.olav/inventory.yaml` with device credentials
- Or skip network tests: `pytest -m "not network"`

### "Coverage failure"
- E2E tests should skip coverage: use `--no-cov` flag
- Or adjust threshold in `pyproject.toml`

### "Connection timeout"
- Check device connectivity: `ping <device_ip>`
- Verify SSH access: `ssh admin@<device_ip>`
- Increase timeout in `pyproject.toml`: `timeout = 120`

## Output Inspection

After running real E2E tests, inspect generated files:

```bash
# Check synced data
ls -R exports/snapshots/$(date +%Y-%m-%d)/

# Check reports
ls -lh exports/reports/

# Check topology visualizations
ls -lh exports/topology/

# View latest report
cat exports/reports/$(ls -t exports/reports/*.md | head -1)
```

## Development Workflow

1. **During Development**: Run integration tests frequently
   ```bash
   uv run pytest tests/e2e/ -v -m "not e2e" --no-cov
   ```

2. **Before Commit**: Run all integration tests
   ```bash
   uv run pytest tests/e2e/ -v -m "not e2e"
   ```

3. **Before Release**: Run full E2E tests
   ```bash
   uv run pytest tests/e2e/ -v -m e2e --no-cov
   ```

4. **Manual Verification**: Inspect generated reports and topology files
   ```bash
   # Run full workflow
   uv run pytest tests/e2e/test_complete_e2e_validation.py::TestRealE2EWorkflow::test_23_full_e2e_workflow -v -s --no-cov
   
   # Check outputs
   ls -R exports/
   ```
