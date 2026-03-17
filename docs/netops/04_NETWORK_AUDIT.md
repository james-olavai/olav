# Network Audit Agent

The Audit Agent runs **scheduled or on-demand health checks** across your entire network. You simply provide it with a **Profile** —— a declarative specification of what to check —— and it queries snapshot databases, detects anomalies, correlates events into incident clusters, and generates a structured report with directly executable **Ops Playbooks**.

Profiles are **always created and modified by the Designer sub-agent** —— never edit them manually. The Designer introspects the live database schema, test-runs each query against real data, and saves validated profiles to disk.

### 🔍 Audit Agent is a Multi-Dimensional Health Check System

Unlike point-in-time query tools, the Audit Agent operates across **multiple dimensions**:

| Dimension | Capability | Example |
|-----------|-----------|---------|
| **Current state snapshot** | Query any data in the latest snapshot (interfaces, adjacencies, routes, config) | "How many BGP neighbors are not in Established state?" |
| **Cross-snapshot drift detection** | Compare changes between snapshots, identify config/state drift | "Which interfaces have state changes in the last 3 days?" |
| **Anomaly detection (Z-score)** | Identify statistical outliers relative to each device's historical baseline | "Did R1's CPU surge relative to its own history?" |
| **Semantic log search** | Intelligently match failure keywords in Syslog via vector search | "What critical failure logs occurred in last 24 hours?" |
| **Event clustering** | Correlate scattered findings into topological incident clusters | "Which device failures actually share a root cause?" |
| **Configuration audit** | Track configuration changes, detect baseline drift | "Which devices deviate from our standard template?" |

These dimensions **work together** to enable **automated full-scope audits** and **root-cause-aware analysis** that simple query tools cannot achieve.

---

## Creating Profiles with the Designer

The **Designer** is the sub-agent responsible for crafting and validating audit profiles. It:

1. Introspects the live DuckDB/LanceDB schema —— never guesses column names.
2. Test-runs each query against real data before saving.
3. (Optionally) runs `analyze_thresholds` to compute P50/P90/P95 distributions for data-driven thresholds.
4. Writes validated profiles to `.olav/workspace/audit/profiles/<name>.md`.

### Invoking the Designer

**Two options: interactive dialogue or detailed instructions.**

**Option 1 — Interactive Dialogue** (Designer asks clarifying questions)

Use this when you have a rough idea but want the Designer to refine the details.

```bash
uv run python -m olav --agent audit
> Design a BGP health check profile for me
```

The Designer responds:
```
What should this profile focus on?
- Current BGP neighbor state?
- BGP session flaps over time?
- Anomalous prefix counts?
- All of the above?

Also, what severity levels would you like for each check?
```

Then you can refine your requirements interactively.

**Option 2 — Detailed Specification** (Designer executes immediately)

Use this when you have a clear spec and want fast, non-interactive execution.

```bash
uv run python -m olav --agent audit
> Design an audit profile named "bgp_health" that checks:
  1. BGP neighbors not in Established state (Critical)
  2. BGP session state changes detected via raw_diffs (Critical)
  3. Received prefix count drops >20% vs previous snapshot (Warning)
  Use data-driven thresholds where possible. Language: English.
```

The Designer immediately introspects the schema, test-runs queries, analyzes thresholds, and saves —— no back-and-forth needed.

### Example: health_full_drift (Built-in Profile)

The following specification generated the built-in `health_full_drift` profile. You can use it as a reference to understand Designer output, or run it verbatim to recreate the profile from scratch.

**Specification:**

```
Design a comprehensive network health audit profile named "health_full_drift".

It should cover:

1. Anomaly Detection (Z-score, per-device baseline, threshold 2.5):
   - CPU utilization (5-second avg from parsed_outputs)
   - Memory utilization percentage

2. Current State Checks (SQL, Critical):
   - Physical interfaces not in 'up' state (exclude Loopback, Management, Vlan, Tunnel)
   - BGP neighbors not in Established state
   - OSPF neighbors not in FULL or 2WAY state
   - Switch ports in err-disable state

3. Semantic Syslog Search (LanceDB, Critical):
   - Critical failure keywords: critical error alert failure interface down BGP reset flap
     memory OOM spanning-tree BPDU err-disable chassis hardware fault

4. Cross-Snapshot Drift Checks (SQL, Warning), using raw_diffs:
   - CPU changes between consecutive snapshots (flag delta ≥5%)
   - Memory utilization changes (flag delta ≥3%)
   - Interface link-protocol state flips
   - BGP session state changes (Established added/removed)
   - OSPF neighbor state changes (FULL removed, LOADING/DOWN added)
   - Spanning-tree port role or root bridge changes
   - Syslog line count spikes (>10 new lines)

5. Configuration Change Detection (SQL, Warning):
   - Running-config diffs, added+deleted > 0 (total >50 flagged as high-risk)

Enable incident clustering (run_incident_clustering: true), snapshot resolution: 1d,
max findings per job: 100. Language: English.
```

**Generated Profile —— 15 checks:**

| Check | Severity | Detects |
|---|---|---|
| **CPU_Anomaly** | Critical | CPU statistical surge/drop relative to device's own history (Z-score) |
| **Memory_Anomaly** | Critical | Memory statistical deviation; sustained growth = memory leak signal |
| **Interface_Down** | Critical | Physical interfaces currently in down state (excluding mgmt/loopback) |
| **BGP_Not_Established** | Critical | BGP neighbors not in Established state |
| **OSPF_Not_Full** | Critical | OSPF neighbors not in FULL or 2WAY state |
| **STP_Error_Disable** | Critical | Switch ports in err-disable state |
| **Critical_Syslog** | Critical | Semantic-matched failure log entries (vector search via Syslog) |
| **CPU_Drift** | Warning | CPU change ≥5% between consecutive snapshots |
| **Memory_Drift** | Warning | Memory utilization change ≥3% between consecutive snapshots |
| **Interface_State_Drift** | Warning | Interface link-protocol state flips across snapshots |
| **BGP_Drift** | Warning | BGP session state changes across snapshots |
| **OSPF_Drift** | Warning | OSPF neighbor state changes (directional: FULL → LOADING/DOWN) |
| **STP_Drift** | Warning | Spanning-tree topology changes (port role/state transitions) |
| **Log_Spike** | Warning | Syslog line count increase >10 new lines |
| **Config_Drift** | Warning | Running-config changes; >50 lines flagged as high-risk |

### Example: Create a BGP-Focused Profile

```
Design an audit profile named "bgp_health" focusing only on BGP.
Checks to include:
1. BGP neighbors not in Established state (Critical)
2. BGP session state changes detected via raw_diffs in time window (Critical)
3. BGP prefix count change —— flag if received prefix count drops >20% vs previous snapshot (Warning)
Use data-driven thresholds where possible.
Language: English.
```

The Designer will introspect the schema, compute actual P90/P95 prefix distributions from the database, propose thresholds, and wait for your confirmation before saving.

---

## What the Audit Agent Can Monitor

The Audit Agent can check **any data stored in the snapshot database**. Custom profiles can target any table, column, or combination thereof.

### Coverage Categories

| Category | Examples |
|---|---|
| **Per-Device Anomaly Detection** | Any numeric metric in `parsed_outputs` —— latency, queue depth, error counters, BGP prefix count |
| **Cross-Snapshot Drift** | Any table with `created_at` column and state fields in `raw_diffs` |
| **Device Configuration Drift** | Differences in any `show running-config` / `show configuration` section |
| **Syslog / Semantic Log Search** | Vector search via LanceDB matching any failure keyword pattern |
| **Third-party API Data** | Any table populated by `api_anomaly` tasks —— Prometheus metrics, SNMP trap aggregation, NMS feeds |
| **Topology Checks** | Queries against `topology_links`, checking expected link count, missing neighbors, asymmetric paths |

### Anomaly Detection: Adaptive Per-Device Z-score

For numeric metrics, the Audit Agent uses **per-device Z-score anomaly detection**, not global thresholds. Each device's own historical baseline within the time window determines what is "normal":

- A core router permanently at 80% CPU is healthy —— it will never be flagged.
- An access switch jumping from 20% to 65% will be immediately flagged.
- Sustained upward drift across consecutive snapshots produces steadily rising `z_score` —— a strong memory leak signal.

---

## Running Audits

### Command Line (CLI)

```bash
# Recommended shorthand
uv run python -m olav --agent audit --profile health_full_drift

# Non-interactive mode (for CI / cron)
uv run python -m olav --agent audit --profile health_full_drift --auto-approve

# Natural language query
echo "Run full health audit using health_full_drift profile with 3-day time window" \
  | uv run python -m olav --agent audit --auto-approve
```

Reports are written as `.md` (human-readable) and `.json` (raw findings) to `exports/audit_reports/`.

The `--profile` flag accepts shorthand names: `--profile health_full_drift` resolves to `.olav/workspace/audit/profiles/health_full_drift.md`.

### Via Config Agent (Scheduling)

```bash
# Run once immediately
echo "Run a full health audit now using profile health_full_drift" \
  | uv run python -m olav --agent config --auto-approve

# Schedule daily at 06:00
echo "Schedule a network health audit every day at 06:00 using profile health_full_drift, \
log to .olav/logs/cron_audit.log" \
  | uv run python -m olav --agent config --auto-approve
```

The Config Agent writes a cron entry like:
```cron
0 6 * * * cd /home/yhvh/Olav && uv run python -m olav --agent audit --profile health_full_drift --auto-approve >> .olav/logs/cron_audit.log 2>&1
```

---

## Using Ops Playbooks

Each report ends with a **Post-Check Playbook** —— auto-generated `olav -a ops` commands you can copy-paste directly into your terminal.

**Priority 1** —— Incident clusters (confirmed topological root causes):
```bash
olav -a ops "Incident Cluster #INC-001 (2026-03-03 17:48, 4min): Root link SW1, SW2 → R1, R2, R3, R4.
Use networkx to simulate removing root nodes [SW1, SW2]: identify all downstream affected devices and links,
verify if redundant paths exist, output recovery sequence.
Event types: ospf_not_full×6, config_change×2"
```

**Priority 2** —— Per-device verification:
```bash
olav -a ops "R3 OSPF neighbor 1.1.1.1 not in FULL state: SSH run 
'show ip ospf neighbor detail 1.1.1.1' to check MTU/Hello/Dead intervals"
```

Each command is self-contained. Can be run in any order.

---

## Updating or Appending Profiles with the Designer

The Designer supports two workflows for modifying existing profiles via natural language —— without manual YAML editing.

### Pattern 2: Recalibrate Thresholds Based on Current Data

Use this when alert sensitivity needs adjustment or when new data has arrived.

```bash
uv run python -m olav --agent audit
> Based on actual CPU and memory data from the last 30 days, recalibrate the anomaly thresholds 
  in health_full_drift. Show me P90/P95 distributions before making any changes.
```

The Designer will:
1. Read the existing profile to get current task definitions and thresholds.
2. Run `analyze_thresholds` for each numeric metric, compute P50/P90/P95/P99 distributions.
3. Show a diff table: current threshold vs recommended threshold for each metric.
4. **Wait for your explicit confirmation** (human-in-the-loop), then execute the override.
5. Save the updated profile with new thresholds.

Use cases:
- Existing thresholds too noisy (triggering too many false positives).
- Network conditions changed; baseline needs recalibration.
- You want data-driven thresholds instead of manual guesses.

**Sample output:**
```
Threshold recommendations for health_full_drift:

| Metric | Current Warning | Recommended Warning | Current Critical | Recommended Critical |
|---|---|---|---|---|
| CPU_Anomaly | 2.5 | 2.1 | 3.5 | 3.2 |
| Memory_Anomaly | 2.5 | 2.8 | 3.5 | 3.7 |

Proceed with update? (yes/no)
```

### Pattern 3: Append New Checks to Existing Profile

Use this to extend your profile without modifying existing checks.

```bash
uv run python -m olav --agent audit
> Add a new check to health_full_drift to monitor OSPF external LSA count ——
  flag if any device's external LSA count increases by 500+ between snapshots.
  Use data-driven thresholds where possible.
```

The Designer will:
1. Read the existing profile to get current task names (prevent duplicates).
2. Introspect the database schema to confirm table and column availability.
3. Test-run the new query against real data.
4. (Optionally) invoke `analyze_thresholds` to compute recommended alert thresholds.
5. Append the validated task block to the profile —— existing tasks unchanged.

Use cases:
- Add specific device metrics you discovered during troubleshooting.
- Expand coverage to new tables (e.g., newly integrated NMS feeds).
- Create specialized checks for specific device roles or sites.

**Another example:**
```bash
python -m olav --agent audit
> Add a Syslog check to health_full_drift based on keywords, flagging any lines containing 
  "packet drop" or "discard". Name the task PACKET_DROP_SPIKE.
  Use lancedb semantic search. Set severity to Warning.
```

### Pattern 1 (Reuse): Change Prompt to Improve Report Quality

If you want to improve LLM analysis of existing checks (not add new tasks, not recalibrate thresholds), ask the Designer to refine the prompt:

```bash
uv run python -m olav --agent audit
> In the health_full_drift profile, update the prompt in the OSPF_Not_Full section to add:
  LOADING state stuck for >60 seconds usually means MTU mismatch.
  When both occur, ask LLM to correlate findings with Interface_State_Drift.
```

The Designer will:
1. Read the profile.
2. Find the specified section.
3. Update only the `section_prompt` field (natural language guidance to the LLM).
4. Resave the profile.

Use cases:
- Reduce noise by teaching the LLM context about your environment.
- Correlate related checks (e.g., "If OSPF is down AND interface is down, someone unplugged the cable").
- Clarify what is a real issue vs expected behavior.

---

## Interpreting Reports

```
exports/audit_reports/health_full_drift_2026-03-04_20260304T060427Z.md
```

**Executive Summary** (top) —— Cross-section correlation analysis, incident cluster summary, top 3 action items, health assessment (✅ Healthy / ⚠️ At Risk / 🔴 Degraded).

**Per-Check Sections** —— Each task occupies one section. Checks with no anomalies print `✅ No anomalies detected` without consuming LLM credits. Tasks with findings include a findings table and LLM analysis.

**Post-Check Playbook** (bottom) —— Priority 1 = incident cluster commands. Priority 2 = per-device findings. All commands are self-contained `olav -a ops` strings.

---

## Tips

- **Start with `health_full_drift`** —— It covers all major failure modes. Run it a few times, see what triggers, then ask the Designer to adjust thresholds.
- **Shrink time window for faster runs** —— `3d` is enough for most operational checks; `7d` works better for trends and leak detection.
- **Enable `run_incident_clustering: true` in production** —— It converts scattered findings into actionable incident narratives and identifies topological root causes.
- **Drift tasks require at least 2 snapshots** —— `BGP_Drift`, `OSPF_Drift`, `Config_Drift`, and `STP_Drift` query `raw_diffs`, which only has data after the second snapshot run.
- **`section_prompt` is the biggest lever for improving report quality** —— When you ask the Designer to update prompts, describe which correlations matter in your environment and how to distinguish noise from real issues.
