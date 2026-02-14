# Two-Stage Pipeline Architecture

## Overview

OLAV v0.8采用两阶段流程设计，将数据收集和分析分离，避免超时问题。

## Design Problem

之前的设计：`sync_all() → execute → parse → LLM → report`
- 所有步骤串行执行
- 命令执行×LLM分析 = 长时间阻塞
- 大量命令导致超时

## New Design: Two-Stage Pipeline

```
┌─────────────────────────────────────────┐
│ Stage 1: Fast Data Collection           │
│ (Parallel via Nornir)                   │
├─────────────────────────────────────────┤
│ 1. Initialize Nornir (parallel runner)  │
│ 2. Query capabilities database          │
│ 3. Execute commands (all devices)       │
│ 4. Save raw output to disk              │
│ 5. Return summary immediately           │
│ ⏱️ Typical: 5-15 seconds for 6 devices   │
└─────────────────────────────────────────┘
                    ↓
        ✅ Return to user immediately
        (Users see: "Sync completed: 6 devices, 24 commands, data/sync/2026-01-13/")
                    ↓
┌─────────────────────────────────────────┐
│ Stage 2: Async Post-Processing          │
│ (Background Thread - Non-Blocking)      │
├─────────────────────────────────────────┤
│ 1. Parse raw data (TextFSM, regex)      │
│ 2. Initialize sync database             │
│ 3. Generate reports                     │
│ 4. Topology visualization               │
│ 5. LLM analysis                         │
│ ⏱️ Runs in background (minutes)          │
└─────────────────────────────────────────┘
```

## Key Benefits

| Aspect | Before | After |
|--------|--------|-------|
| Response Time | 60-120s (timeout) | 7-15s ✅ |
| User Experience | Hanging/timeout | Immediate feedback |
| Scalability | Limited by command count | Can process 100+ commands |
| Resource Usage | All in one process | Distributed (bg thread) |

## Implementation

### sync_all() Function Signature

```python
@tool
def sync_all(
    devices: str = "all",
    group: str = "test",  # NEW: Group selection
    categories: str | None = None
) -> str:
```

### Stage 1: Data Collection

```python
# Execute commands on all devices (parallel)
for device_name in device_names:
    for cmd_info in all_commands:
        result = nr.filter(name=device_name).run(
            task=netmiko_send_command,
            command_string=command,
            read_timeout=10,  # Reduced from 30s
            on_failed=True,
        )
        # Save to disk immediately
        output_file.write_text(result[device_name].result)

# Return immediately
return "Sync STAGE 1 completed..."
```

### Stage 2: Async Post-Processing

```python
def _stage2_async_processing():
    """Non-blocking Stage 2: parse + LLM analysis."""
    try:
        _process_sync_stage2(sync_dir, device_names)
    except Exception as e:
        print(f"[WARN] Stage 2 failed: {e}")

# Start in background thread (non-blocking)
thread = threading.Thread(
    target=_stage2_async_processing,
    daemon=True  # Doesn't prevent process exit
)
thread.start()
```

## Device Group Selection

All devices in inventory have group tags:

```yaml
# .olav/config/nornir/hosts.yaml
R1:
  hostname: 192.168.100.101
  platform: cisco_ios
  groups:
    - test  # Group identifier
  data:
    role: border
    site: lab
```

### Usage Examples

```python
# Sync all test devices (default)
sync_all(devices="all", group="test")

# Sync specific test devices
sync_all(devices="R1,R2", group="test")

# Sync production devices
sync_all(devices="all", group="core")

# Sync with limited categories (faster)
sync_all(group="test", categories="system,interfaces")
```

## Execution Flow

1. **User triggers inspection**
   ```
   /inspect all devices
   ```

2. **Agent calls sync_all(group="test")**
   - Stage 1 starts (data collection)
   - Nornir executes commands in parallel
   - Raw data saved to `data/sync/YYYY-MM-DD/raw/`

3. **Stage 1 completes (7-15 seconds)**
   - Returns: "Sync completed: 6 devices, 24 commands"
   - User gets immediate feedback

4. **Stage 2 runs in background**
   - Parses data
   - Generates reports
   - Runs LLM analysis
   - Updates `data/sync/YYYY-MM-DD/parsed/` and `reports/`

## Performance Metrics

### Test Run Results
- **Devices**: 6 (R1-R4, SW1, SW2)
- **Commands**: 24 (4 per device)
- **Execution Time**: 7.0 seconds
- **Raw Files Generated**: 25
- **Parsed Files Generated**: 19

### Calculation
- Per-command execution: ~350ms average
- Parallel execution: 6 devices × 4 commands ÷ parallel factor ≈ 7s
- Nornir runner: ThreadPoolExecutor with 20 workers

## Database Optimization

**Command Limit**: 6 total (per invocation)
- Prevents excessive database queries
- Allows 6 devices × 6 commands = 36 operations
- Completes in <15 seconds

**Configuration**:
```python
# In sync_all()
max_commands = 6
for intent in unique_intents:
    if commands_found >= max_commands:
        break
```

## Future Improvements

1. **Configurable command limits**
   - `sync_all(..., max_commands=20)` for detailed inspection
   - `sync_all(..., max_commands=3)` for quick status

2. **Streaming output**
   - Stage 2 reports sent to user as they complete
   - Real-time progress updates

3. **Caching**
   - Cache parsed data across multiple requests
   - Avoid re-parsing same data

4. **Priority-based execution**
   - High-priority devices/commands first
   - Optional categories for flexible inspection

## Skills Updated

- ✅ `daily-sync/SKILL.md` - Added group selection documentation
- ✅ `device-inspection/SKILL.md` - Added two-stage pipeline explanation
- ✅ `health-check/SKILL.md` - (To be updated)

## References

- Design Document: [DESIGN_V0.8.md](DESIGN_V0.8.md)
- Execution Layer: [src/olav/tools/sync_tools.py](../src/olav/tools/sync_tools.py)
- Network Tools: [src/olav/tools/network_executor.py](../src/olav/tools/network_executor.py)
