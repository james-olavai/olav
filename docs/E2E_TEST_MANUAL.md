# OLAV Agent Capabilities E2E Test Manual

## Overview

This manual defines end-to-end tests for validating OLAV agent capabilities. Unlike unit tests that verify code execution, these tests focus on **result quality and correctness** - ensuring the AI agent returns accurate, actionable network operations intelligence.

**Test Approach**: Each test uses the real CLI with YOLO mode (auto-approve HITL) to execute queries against live infrastructure, then validates not just success, but the **semantic correctness** of responses.

## Test Files

| File | Purpose | Server Required |
|------|---------|-----------------|
| `test_agent_capabilities.py` | Full E2E via streaming API | Yes |
| `test_cli_capabilities.py` | CLI-based tests (simpler) | No |
| `fixtures/__init__.py` | Shared fixtures and validators | - |

## Running Tests

```bash
# Run CLI tests (no server needed)
uv run pytest tests/e2e/test_cli_capabilities.py -v

# Run without slow tests
uv run pytest tests/e2e/test_cli_capabilities.py -m "not slow" -v

# Run full API tests (requires server)
docker-compose up -d  # Start server first
uv run pytest tests/e2e/test_agent_capabilities.py -v

# Generate HTML report
uv run pytest tests/e2e/ --html=reports/e2e.html
```

## Test Environment Requirements

### Infrastructure (Docker Compose)
```bash
docker-compose up -d  # Start all services
```

Required services:
- PostgreSQL (Checkpointer)
- OpenSearch (Schema/Memory indexes)
- Redis (Cache)
- SuzieQ (Network telemetry - with test Parquet data)
- NetBox (SSOT - with test devices)

### Test Data Setup
```bash
# 1. Initialize indexes
uv run olav --init

# 2. Full init with NetBox devices
uv run olav --init --full

# 3. Verify test devices exist
uv run python scripts/check_netbox_devices.py
```

### Environment Variables
```bash
# .env.test
OLAV_SERVER_URL=http://localhost:8000
OLAV_YOLO_MODE=true  # Auto-approve all HITL requests
OLAV_TEST_MODE=true  # Enable test fixtures
```

---

## Test Categories

### Category 1: Query & Diagnostic (SuzieQ Workflow)

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| Q01 | BGP Status Query | `check R1 BGP status` | ✅ Returns BGP peer list with state (Established/Idle) |
| Q02 | Interface Status | `show all interfaces on R1` | ✅ Returns interface list with admin/oper status |
| Q03 | Route Table | `display routing table of R1` | ✅ Returns routes with prefix, nexthop, protocol |
| Q04 | OSPF Neighbors | `check OSPF neighbors` | ✅ Returns OSPF adjacency list with state |
| Q05 | Device Summary | `summarize all devices` | ✅ Returns device count, types, OS versions |
| Q06 | Cross-Table Query | `find interfaces with BGP peers` | ✅ Correlates interface + BGP data correctly |
| Q07 | Time-Range Query | `show BGP changes in last 24h` | ✅ Filters by timestamp correctly |
| Q08 | Error Detection | `check for interface errors` | ✅ Identifies CRC/FCS/input errors |
| Q09 | Multi-Device Query | `compare BGP status across all routers` | ✅ Returns consolidated multi-device data |
| Q10 | Schema Discovery | `what tables are available?` | ✅ Lists SuzieQ tables with descriptions |

### Category 2: Batch Inspection (Inspection Mode)

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| I01 | BGP Audit | `audit BGP on all routers` | ✅ Returns multi-device summary |
| I02 | Interface Audit | `check interface status on all devices` | ✅ Returns interface states |
| I03 | OSPF Neighbor Audit | `audit OSPF neighbors on all devices` | ✅ Returns OSPF states |

### Category 3: NetBox Management (SSOT Workflow)

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| N01 | Device Lookup | `find device R1 in NetBox` | ✅ Returns device details (IP, role, site) |
| N02 | IP Search | `what device has IP 10.1.1.1?` | ✅ Returns correct device match |
| N03 | Site Query | `list all devices in datacenter-1` | ✅ Returns site-filtered list |
| N04 | Device Role Filter | `show all spine switches` | ✅ Returns role-filtered list |

### Category 4: Deep Dive (Expert Mode)

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| D01 | Multi-Step Diagnosis | `why can't R1 reach R2?` | ✅ Follows hypothesis loop, finds root cause |
| D02 | Root Cause Analysis | `analyze why BGP is flapping on R1` | ✅ Multi-step analysis |
| D03 | Topology Analysis | `what is the path from R1 to R3?` | ✅ Returns hop-by-hop path |

### Category 5: Device Execution (HITL Workflow)

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| E01 | Show Command | `run 'show version' on R1` | ✅ Returns parsed show output |
| E02 | Config Preview | `preview adding a new loopback interface` | ✅ Shows proposed config |
| E03 | Backup Config | `backup R1 configuration` | ✅ Retrieves running config |

### Category 6: RAG & Schema Search

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| R01 | Schema Search | `what fields does BGP table have?` | ✅ Returns schema fields |
| R02 | Table Discovery | `what tables can I query?` | ✅ Lists available tables |
| R03 | Method Help | `what methods are available for BGP?` | ✅ Explains get/summarize/etc |
| R04 | Filter Syntax | `how do I filter BGP by ASN?` | ✅ Explains filter usage |

### Category 7: Error Handling & Edge Cases

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| X01 | Unknown Device | `check BGP on UNKNOWN_DEVICE_XYZ123` | ✅ Returns "not found" gracefully |
| X02 | Invalid Table | `query table NONEXISTENT_TABLE_ABC` | ✅ Handles gracefully |
| X03 | Empty Result | `check BGP peers with ASN 99999` | ✅ Returns "no data" message |
| X04 | Ambiguous Query | `check status` | ✅ Asks for clarification or provides summary |
| X05 | Malformed Filter | `get BGP where something=???` | ✅ Handles gracefully |
| X06 | Chinese Query | `查询 R1 的 BGP 状态` | ✅ Works same as English |
| X07 | Mixed Language | `check R1 的接口状态` | ✅ Works with mixed language |

### Category 8: Multi-turn Conversation

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| M01 | Context Retention | Turn 1: `check R1 BGP`, Turn 2: `what about interfaces?` | ✅ Understands "R1" from context |
| M02 | Follow-up Filter | Turn 1: `show all BGP peers`, Turn 2: `filter by Established` | ✅ Applies filter to previous query |
| M03 | Clarification | Turn 1: `check the router`, Turn 2: `R1` | ✅ Uses clarification correctly |
| I04 | Compliance Check | `verify all devices have NTP configured` | ✅ Returns compliant/non-compliant list |
| I05 | Report Generation | `generate inspection report for core-routers` | ✅ Creates structured report |

### Category 6: RAG & Schema Search

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| R01 | Schema Search | `what fields does BGP table have?` | ✅ Returns schema fields from index |
| R02 | OpenConfig XPath | `find XPath for interface counters` | ✅ Returns correct YANG path |
| R03 | Document Search | `how to configure BGP on Cisco IOS-XE?` | ✅ Returns relevant doc chunks |
| R04 | Memory Recall | `what did I query last time about R1?` | ✅ Returns episodic memory |
| R05 | Intent → Schema | `query packet drops` | ✅ Maps intent to correct table/field |

### Category 7: Error Handling & Edge Cases

| ID | Capability | Test Query | Expected Result Validation |
|----|------------|------------|---------------------------|
| X01 | Unknown Device | `check BGP on UNKNOWN_DEVICE` | ✅ Returns clear "device not found" error |
| X02 | Invalid Table | `query nonexistent_table` | ✅ Returns "table not found" with suggestions |
| X03 | Empty Result | `check BGP on device with no BGP` | ✅ Returns "no data" message, not error |
| X04 | Timeout | `run slow_command on all 100 devices` | ✅ Handles timeout gracefully |
| X05 | Ambiguous Query | `check R1` | ✅ Asks for clarification or shows options |
| X06 | Chinese Query | `查询 R1 的 BGP 状态` | ✅ Works same as English query |

---

## Quality Validation Criteria

### For Each Test, Validate:

1. **Completeness**: All requested data returned
2. **Accuracy**: Data matches source (SuzieQ/NetBox/Device)
3. **Relevance**: No extraneous information
4. **Format**: Structured, parseable output
5. **Latency**: Response within acceptable time (<30s for simple, <60s for complex)
6. **No Hallucination**: Claims only verifiable facts

### Scoring Rubric

| Score | Description |
|-------|-------------|
| ✅ Pass | Correct, complete, well-formatted response |
| ⚠️ Partial | Correct but incomplete or poor formatting |
| ❌ Fail | Incorrect, missing, or hallucinated content |
| 🔄 Retry | Flaky - passed on retry |

---

## Test Execution Commands

### Single Query Test
```bash
# Standard mode (single query)
uv run olav query "check R1 BGP status" --json

# Expert mode (enables Deep Dive)
uv run olav query "why can't R1 reach R2?" --mode expert --json
```

### Interactive Test (REPL)
```bash
uv run olav
# Then type queries interactively
# /s for standard mode
# /e for expert mode
# /i for inspection mode
```

### Batch Test with pytest
```bash
# Run all E2E agent tests
uv run pytest tests/e2e/test_agent_capabilities.py -v

# Run specific category
uv run pytest tests/e2e/test_agent_capabilities.py -k "query" -v

# Generate report
uv run pytest tests/e2e/test_agent_capabilities.py --html=reports/e2e_report.html
```

---

## Test Implementation Structure

```
tests/e2e/
├── test_agent_capabilities.py      # Main capability tests
├── fixtures/
│   ├── expected_responses/         # Ground truth for validation
│   │   ├── q01_bgp_status.json
│   │   ├── q02_interfaces.json
│   │   └── ...
│   ├── test_queries.yaml           # Test case definitions
│   └── validation_rules.py         # Custom validators
├── conftest.py                     # Shared fixtures
└── utils/
    ├── cli_runner.py               # CLI execution wrapper
    ├── response_validator.py       # Quality validation
    └── report_generator.py         # HTML report generation
```

---

## Test Data Requirements

### SuzieQ Parquet Data
Must include:
- BGP table with at least 2 peers
- Interface table with varied states
- Routes table with multiple protocols
- Device table with 3+ devices

### NetBox Data
Must include:
- 3+ devices (R1, R2, SW1)
- 2+ sites (datacenter-1, datacenter-2)
- IP addresses assigned to devices
- VLANs configured

### Expected Response Templates

```yaml
# tests/e2e/fixtures/expected_responses/q01_bgp_status.yaml
query: "check R1 BGP status"
expected:
  contains:
    - "R1"
    - "BGP"
    - "Established"  # Or "Idle" if down
  structure:
    type: table_or_list
    fields:
      - peer_ip
      - state
      - asn
  no_hallucination:
    - Must not mention devices not in query
    - Must not invent peer IPs
```

---

## Continuous Quality Monitoring

### Metrics to Track
1. **Pass Rate**: % of tests passing
2. **Hallucination Rate**: % with incorrect claims
3. **Latency P95**: 95th percentile response time
4. **Tool Call Efficiency**: Avg tool calls per query

### Quality Gates
- Pass Rate > 95% for merge to main
- Hallucination Rate < 1%
- P95 Latency < 30s for simple queries

---

## Appendix: YOLO Mode Configuration

YOLO mode auto-approves HITL requests for testing:

```python
# In test fixtures
@pytest.fixture
def yolo_mode():
    """Enable YOLO mode for E2E tests."""
    import os
    os.environ["OLAV_YOLO_MODE"] = "true"
    yield
    del os.environ["OLAV_YOLO_MODE"]
```

**Warning**: Never use YOLO mode in production!

---

## Next Steps

1. [ ] Create `test_agent_capabilities.py` with test implementations
2. [ ] Create `expected_responses/` fixtures with ground truth
3. [ ] Create `response_validator.py` with quality checks
4. [ ] Add GitHub Actions workflow for E2E tests
5. [ ] Create dashboard for quality metrics

---

*Last Updated: 2025-12-03*
*Version: 1.0*
