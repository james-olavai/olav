# LLM Experiment Sandbox - Quick Start Guide

## Overview

The LLM Experiment Sandbox enables large language models to autonomously design and execute complex network experiments in a completely isolated, secure environment.

**Key Capability**: LLMs can freely write Python code without templates, query production databases, perform complex analysis, and generate experiment designs—all while maintaining security through subprocess isolation.

---

## Basic Usage

### 1. Initialize Sandbox

```python
from olav.core.simulation.llm_sandbox import LLMExperimentSandbox
from olav.core.config import MAIN_DB_PATH

# Create sandbox instance
sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
```

### 2. Execute LLM-Designed Code

```python
import asyncio

async def run_experiment():
    # LLM can write ANY Python code here
    llm_code = """
# Example: Analyze network topology
topology = db.query('''
    SELECT source_device, destination_device, source_interface
    FROM topology_links
    LIMIT 20
''')

# Process results
graph = {}
for link in topology:
    src = link['source_device']
    if src not in graph:
        graph[src] = []
    graph[src].append(link['destination_device'])

# Generate report
_result = {
    "devices_analyzed": len(graph),
    "max_connections": max(len(v) for v in graph.values()) if graph else 0,
    "network_connectivity": graph
}
"""
    
    # Execute with 10-minute timeout
    result = await sandbox.execute_experiment(
        experiment_code=llm_code,
        experiment_name="topology_analysis",
        timeout=600
    )
    
    print(f"Status: {result.status}")
    print(f"Result: {result.result}")
    print(f"Execution Time: {result.execution_time:.2f}s")

asyncio.run(run_experiment())
```

---

## What LLMs Can Do

### ✅ Supported Python Features

1. **Database Queries** (Read-Only)
   ```python
   devices = db.query("SELECT * FROM devices WHERE is_active = TRUE")
   for device in devices:
       print(f"{device['device_id']}: {device['name']}")
   ```

2. **Standard Libraries**
   - `collections` - defaultdict, Counter, etc.
   - `itertools` - combinations, groupby, etc.
   - `datetime` - timestamp handling
   - `math` - calculations
   - Full `json` support

3. **Complex Logic**
   ```python
   from collections import defaultdict
   
   graph = defaultdict(list)
   for link in topology:
       graph[link['src']].append(link['dst'])
   
   # Find critical nodes
   critical = max(graph.items(), key=lambda x: len(x[1]))
   _result = {"critical_node": critical}
   ```

4. **File Operations** (in work directory)
   ```python
   # Read files
   content = file_system.read_file("config.txt")
   
   # Write results
   file_system.write_file("analysis_report.txt", "Results...", overwrite=True)
   ```

5. **Advanced Analysis**
   ```python
   # Statistical analysis
   import math
   avg = sum(degrees) / len(degrees)
   stdev = math.sqrt(sum((d - avg)**2 for d in degrees) / len(degrees))
   
   # Graph algorithms
   # (implement custom using Python standard library)
   ```

### ❌ Blocked Operations

For security, the following are prevented:

- ❌ `exec()`, `eval()` - Dynamic code execution
- ❌ `__import__()` - Dynamic imports
- ❌ `subprocess.run()` - OS commands
- ❌ `os.system()` - Shell execution
- ❌ `open()` with write outside sandbox
- ❌ Custom module imports (except stdlib + pre-installed)

---

## Common Experiment Patterns

### Pattern 1: Network Analysis

```python
llm_code = """
# Query and analyze network topology
topology = db.query('''SELECT * FROM topology_links''')
devices = db.query('''SELECT device_id FROM devices WHERE is_active = TRUE''')

# Build device connection count
connections = {}
for link in topology:
    src = link['source_device']
    connections[src] = connections.get(src, 0) + 1

# Identify critical infrastructure
critical_threshold = 5
critical_devices = [d for d, c in connections.items() if c >= critical_threshold]

_result = {
    "total_devices": len(devices),
    "critical_devices": critical_devices,
    "avg_connections": sum(connections.values()) / len(connections) if connections else 0
}
"""
```

### Pattern 2: Change Impact Simulation

```python
llm_code = """
# Analyze impact of disabling BGP on primary gateway
devices = db.query('''
    SELECT device_id, name
    FROM devices
    WHERE device_role = 'Primary_Gateway'
    LIMIT 5
''')

# Find dependent devices
impacted = []
for device in devices:
    # Query devices that depend on this gateway
    downstream = db.query(f'''
        SELECT source_device FROM topology_links
        WHERE destination_device = '{device['device_id']}'
    ''')
    impacted.extend([d['source_device'] for d in downstream])

_result = {
    "primary_gateways": len(devices),
    "potentially_impacted_devices": list(set(impacted)),
    "impact_severity": "high" if len(set(impacted)) > 10 else "medium"
}
"""
```

### Pattern 3: Compliance Verification

```python
llm_code = """
# Check compliance with configuration standards
devices = db.query('''SELECT device_id, config_hash FROM devices''')

# Compliance rules (simple hashing)
import hashlib
expected_hashes = {
    'R1': 'config_v1_hash',
    'R2': 'config_v1_hash'
}

non_compliant = []
for device in devices:
    device_id = device['device_id']
    if device_id in expected_hashes:
        if device['config_hash'] != expected_hashes[device_id]:
            non_compliant.append({
                'device': device_id,
                'status': 'out_of_compliance'
            })

_result = {
    "total_devices_checked": len(devices),
    "compliant_count": len(devices) - len(non_compliant),
    "non_compliant_devices": non_compliant,
    "compliance_percentage": ((len(devices) - len(non_compliant)) / len(devices) * 100) if devices else 0
}
"""
```

### Pattern 4: Anomaly Detection

```python
llm_code = """
# Detect anomalies in interface metrics
interfaces = db.query('''
    SELECT interface_name, error_count, input_drop_count
    FROM interface_metrics
    ORDER BY error_count DESC
    LIMIT 50
''')

# Calculate anomaly threshold (simple method: 2 std dev)
import math

if interfaces:
    error_counts = [i['error_count'] for i in interfaces]
    mean = sum(error_counts) / len(error_counts)
    variance = sum((x - mean)**2 for x in error_counts) / len(error_counts)
    stdev = math.sqrt(variance)
    threshold = mean + (2 * stdev)
    
    anomalies = [i for i in interfaces if i['error_count'] > threshold]
else:
    anomalies = []

_result = {
    "anomaly_threshold": threshold if interfaces else 0,
    "anomalous_interfaces": len(anomalies),
    "top_anomaly": anomalies[0] if anomalies else None,
    "recommendation": "investigate_immediately" if len(anomalies) > 5 else "monitor"
}
"""
```

---

## Error Handling

### Pattern: Graceful Error Handling

```python
llm_code = """
try:
    # Attempt complex analysis
    data = db.query('''SELECT * FROM topology_links''')
    
    # Process data
    if not data:
        _result = {"error": "No topology data found", "status": "warning"}
    else:
        # Continue processing
        _result = {"status": "success", "records_processed": len(data)}

except Exception as e:
    # Capture error details for debugging
    import traceback
    _result = {
        "error": str(e),
        "error_type": type(e).__name__,
        "traceback": traceback.format_exc()
    }
"""
```

---

## Authentication & Permissions

### Database Access
- **Mode**: Read-only (SELECT queries only)
- **Scope**: All data accessible
- **Transactions**: Auto-committed
- **Locks**: Automatically handled with retry logic

### File System
- **Working Directory**: `/tmp/llm_sandbox_<sandbox_id>/<experiment_name>/`
- **Allowed Operations**: Read, write, append
- **Restrictions**: Cannot access parent directories (path traversal blocked)

---

## Performance Considerations

### Timeout Management

```python
# Default timeout: 600 seconds (10 minutes)
result = await sandbox.execute_experiment(code, timeout=600)

# Shorter timeout for quick checks
result = await sandbox.execute_experiment(code, timeout=30)

# Longer timeout for complex analysis
result = await sandbox.execute_experiment(code, timeout=1800)
```

### Database Query Optimization

```python
# ❌ Inefficient: Load all data
all_devices = db.query("SELECT * FROM devices")
filtered = [d for d in all_devices if d['status'] == 'down']

# ✅ Efficient: Filter in database
downed_devices = db.query("SELECT * FROM devices WHERE status = 'down'")
```

### Result Serialization

The sandbox automatically converts Python objects to JSON:

```python
# ✅ Works (JSON-serializable)
_result = {
    "count": 42,
    "name": "test",
    "items": [1, 2, 3],
    "timestamp": "2026-02-28T12:34:56"
}

# ⚠️ Needs conversion (non-JSON types)
from datetime import datetime
_result = {
    "timestamp": datetime.now().isoformat()  # Convert to string
}
```

---

## Integration with Orchestrator

Use the sandbox in your orchestration workflow:

```python
from olav.core.simulation.llm_sandbox import LLMExperimentSandbox

async def orchestrate_network_analysis():
    sandbox = LLMExperimentSandbox(db_path=str(MAIN_DB_PATH))
    
    # Step 1: Get LLM design from your orchestrator
    design_code = llm_model.generate_experiment(
        prompt="Analyze BGP convergence impact"
    )
    
    # Step 2: Execute in sandbox
    result = await sandbox.execute_experiment(
        design_code,
        experiment_name="bgp_analysis"
    )
    
    # Step 3: Process results
    if result.status == "success":
        changes = result.result.get("proposed_changes", [])
        for change in changes:
            # Feed to Change Simulation for impact analysis
            impact = await simulator.simulate(change)
            store_impact_result(change, impact)
    else:
        log_error(f"Experiment failed: {result.error}")
```

---

## Best Practices

1. **Always Check Result Status**
   ```python
   if result.status == "success":
       # Process result.result
   else:
       # Handle error: result.error contains error message
   ```

2. **Assign Results to `_result`**
   ```python
   # This is how sandbox captures output
   _result = {"my_analysis": "result"}  # ✅ Correct
   
   # Not this:
   my_result = ...  # ❌ Won't be returned
   ```

3. **Use Timeout Appropriately**
   - 30-60s: Simple queries
   - 300-600s: Complex analysis
   - 1800s+: Large dataset processing

4. **Handle Empty Results**
   ```python
   data = db.query("SELECT ...")
   if not data:
       _result = {"status": "no_data", "count": 0}
   else:
       # Process
   ```

5. **Document Assumptions**
   ```python
   # In your LLM prompt:
   # "Assume devices have 'device_id' and 'status' columns"
   ```

---

## Troubleshooting

### Timeout Error
- **Cause**: Query or processing took too long
- **Solution**: Increase timeout, optimize database queries, or break into smaller experiments

### Database Lock Error (Rare)
- **Cause**: Subprocess couldn't acquire database lock
- **Solution**: Automatically retried (5 attempts), if persists check concurrent access

### File Not Found Error
- **Cause**: Attempted file write outside sandbox directory
- **Solution**: Use `file_system.write_file()` or verify target is in work directory

### JSON Serialization Error
- **Cause**: Result contains non-JSON-serializable object (datetime, custom class)
- **Solution**: Convert to JSON-compatible types (string, number, dict, list)

---

## Examples Repository

More complete examples available in:
- `tests/e2e/test_llm_sandbox.py` - 7 comprehensive test cases
- `dev_docs/LLM_SANDBOX_VERIFICATION.md` - Full verification report with evidence

---

## See Also

- [LLM Sandbox Architecture](../src/olav/core/simulation/llm_sandbox.py)
- [Verification Report](./LLM_SANDBOX_VERIFICATION.md)
- [Change Simulation](./CHANGE_SIMULATION_VERIFICATION.md)
