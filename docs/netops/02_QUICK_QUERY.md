# Quick Agent User Guide

**Quick Agent** is OLAV's default fast query entry point. It is optimized for everyday network operations queries, supporting SQL queries, CLI command execution, knowledge base searches, and data export functionalities, with a minimalist design to provide answers in 1 iteration.

### 🚀 Quick Agent is a Fast-Response Query Engine

Unlike deep analysis tools, Quick Agent operates in the **single-layer, rapid-feedback** dimensions:

| Dimension | Capability | Example |
|-----------|-----------|---------|
| **Real-time execution** | Connect directly to devices, execute show/config commands, get current state | "Show interface brief on R2" |
| **Historical queries** | Query historical state from snapshot database (no complex correlation needed) | "List all BGP neighbors and their state" |
| **Cache acceleration** | Frequent queries return in <1 second, eliminate redundant computation | Same query second time returns instantly |
| **Multi-source fusion** | Query database + real-time CLI + knowledge base simultaneously, one answer covers all dimensions | "R1 interfaces: current + history + incident cases" |
| **Single interaction** | Max 1 iteration to answer, no back-and-forth dialogue needed | Ask once, get complete answer |

These dimensions combine to make Quick Agent **the go-to tool for fast daily operational queries**.

---

## 📌 Quick Start

### Using the TUI (Text User Interface)

```bash
# Navigate to OLAV main directory
cd /home/yhvh/Olav

# Start Quick Agent (default)
olav "show all devices"

# Or explicitly specify Quick Agent
olav --agent quick "show ip ospf neighbor"
```

### Using Python API

```python
from olav.agents.quick import QuickAgent

agent = QuickAgent()
result = agent.run("What is the IP of device R1?")
print(result)
```

---

## 🎯 What Can Quick Agent Do?

Quick Agent supports the following four query modes:

### 1️⃣ **Database Queries (Query Mode)**
Query device data from historical snapshots.

**Examples:**
```
- "List all devices and their management IPs"
- "Show all core routers in the lab site"
- "What devices are inactive?"
- "Find all interfaces with error counts"
```

**Supported Tables:**
- `devices` — Device inventory (name, IP, platform, role, site)
- `interfaces` — Interface IPAM mapping
- `routes` — Routing table
- `bgp_neighbors` — BGP adjacency relationships
- `ospf_neighbors` — OSPF adjacency relationships
- `topology_links` — Resource topology (CDP/LLDP/BGP/OSPF)
- `v_routes_enriched` — Routing table (next-hop device names resolved)
- `v_bgp_neighbors_enriched` — BGP adjacency table (neighbor device names resolved)

**Performance:** ⚡ Cache hit < 1 second | First query < 5 seconds

---

### 2️⃣ **Real-time CLI Execution (CLI Mode)**
Connect to devices in real-time and execute show/config commands.

**Examples:**
```
- "Show interface brief on R2"
- "Display BGP summary on R1 and R4"
- "Check OSPF process status"
- "Get running-config | include router bgp"
```

**Workflow:**
1. System automatically selects appropriate commands based on device platform (Cisco, Juniper, etc.)
2. Verifies whether commands are blacklisted (not allowed to execute)
3. Connects to device and executes commands
4. Returns raw or parsed output

**Supported Platforms:** Cisco IOS(XE/XR), Juniper Junos, Arista EOS, etc. (defined by Nornir)

**Performance:** 🕐 Typically within 5 seconds (depends on device response time)

---

### 3️⃣ **Fault Analysis (Analysis Mode)**
Quickly diagnose network anomalies.

**Examples:**
```
- "Are all BGP peers up?"
- "Find interface down events in the last 7 days"
- "Which device has the most packet loss?"
- "Check if any routes are blackholed"
- "Find OSPF flap incidents"
```

**Analysis Workflow:**
1. **Define Scope** — Identify devices/protocols to analyze
2. **Baseline Query** — Get baseline metrics from historical snapshots
3. **Current State** — Compare with current real-time data
4. **Anomaly Detection** — Identify deviations from thresholds
5. **Verification** — Confirm findings with CLI commands
6. **Recommendations** — Suggest adjustments or improvements

---

### 4️⃣ **Knowledge Base Search + Web Search**
Query command usage and external information.

**Examples:**
```
- "How do I clear a BGP peer?"
- "What does OSPF cost mean?"
- "Show commands for BGP on Cisco"
- "Search external docs for MPLS configuration"
```

**Features:**
- Local knowledge base semantic search (LanceDB)
- Web search (DuckDuckGo)
- Command lookup (search all known commands)

---

## 🚀 Use Cases and Examples

### Scenario 1: Query Device Inventory
```bash
$ olav "List all devices in the lab"

# Quick Agent's response:
| Name  | Hostname | Platform     | Role           | Site |
|-------|----------|--------------|----------------|------|
| R1    | router1  | cisco_ios    | core           | lab  |
| R2    | router2  | cisco_ios    | edge           | lab  |
| SW1   | switch1  | juniper_evo  | aggregation    | lab  |
```

### Scenario 2: Check BGP Adjacency Status
```bash
$ olav "Are all BGP peers up?"

# Response includes:
- Count and list of UP adjacencies
- Count of DOWN adjacencies (if any)
- Last snapshot timestamp
- Suggested next steps (if real-time confirmation needed, use `--agent ops`)
```

### Scenario 3: Real-time Command Execution
```bash
$ olav "Show interface brief on R1"

# Quick Agent executes CLI command via Nornir:
- Cisco: "show interface brief"
- Juniper: "show interfaces brief"

# Returns actual device output
```

### Scenario 4: Compare Configuration Changes
```bash
$ olav "Find config changes between 2026-03-01 and 2026-03-05 on R1"

# Response:
- Number of deleted lines
- Number of added lines
- Specific differences (e.g., routing policy changes)
```

---

## ⚙️ Configuration and Customization

### Command Blacklist
Dangerous commands are not allowed to execute (write, delete, etc.). View the blacklist:

```bash
cat .olav/config/blacklisted_commands.yaml
```

### Modify Timeout
Edit `api.json`:

```json
{
  "agents": {
    "quick": {
      "cli_timeout_seconds": 30,
      "max_iterations": 1
    }
  }
}
```

### Logging and Debugging
Enable detailed logging:

```bash
# View Quick Agent execution logs
tail -f .olav/logs/users/$(whoami).log
```

---

## 📊 Data Sources and Freshness

Quick Agent queries data from two sources:

| Data Source | Update Frequency | Applicable Queries |
|-------------|-----------------|------------------|
| **DuckDB Snapshot** | Regular collection (default every 8 hours) | Historical data, inventory, topology |
| **Real-time CLI (Nornir)** | On-demand execution | Current device state, real-time metrics |

**Check Snapshot Freshness:**
```bash
$ olav "When was the last snapshot?"

# Response will tell you the last collection time
# If older than 24 hours, Quick Agent will alert you
```

---

## 🛑 Capabilities and Limitations

### ✅ What Quick Agent Can Do

| Capability | Description |
|------------|-------------|
| **SQL Queries** | ✅ Simple SELECT, JOIN, aggregations |
| **Single-Device CLI** | ✅ Single show command |
| **Command Search** | ✅ Search by platform and keyword |
| **Data Export** | ✅ CSV/JSON/Markdown |
| **Knowledge Search** | ✅ Command usage, configuration examples |
| **Quick Diagnosis** | ✅ Simple fault localization (1-2 steps) |

### ❌ What Quick Agent Cannot Do

| Capability | Limitation | Solution |
|------------|-----------|----------|
| **Deep Root Cause Analysis** | Requires multi-step hypothesis testing | Use `--agent ops` |
| **Time-Series Analysis** | Requires complex historical comparison | Use `--agent ops` |
| **Network Simulation & Change Planning** | Requires configuration validation and impact analysis | Use `--agent ops` |
| **Large-Scale Config Push** | Does not support batch configuration delivery | Use Nornir scripts or `--agent sync` |
| **Multi-Step Auto-Remediation** | Requires manual approval | Use `--agent ops` for recommendations |
| **Complex Traffic Analysis** | Requires NetFlow data or SNMP | Integrate external tools |

### ⏱️ Performance Metrics

| Query Type | Typical Time | Max Recommended Scale |
|------------|------------|---------------------|
| SQL Query (cache hit) | < 1 second | 100K+ rows |
| SQL Query (first run) | < 5 seconds | 100K+ rows |
| Single-device CLI | < 5 seconds | 1 device |
| Multi-device parallel CLI | < 5 seconds | 10 devices |
| Knowledge base search | < 1 second | Unlimited |
| Data export | < 1 second | 1M+ rows |

---

## 🔄 When to Upgrade to Ops Agent?

Quick Agent will auto-suggest upgrading in these cases:

```
⚠️ Quick analysis failed or is too complex. For deep troubleshooting and 
automated expert analysis, please try again with: olav --agent ops
```

Or, if your query falls into these categories, **use Ops Agent directly**:

```bash
# Deep troubleshooting
olav --agent ops "Why is BGP down on R1? Check historical logs and suggest fix"

# Change planning and verification
olav --agent ops "Plan a core switch upgrade from SW1 to SW2"

# Performance analysis
olav --agent ops "Analyze BGP convergence time over the last week"
```

---

## 💡 Usage Tips

### 1. Use Explicit Column Labels
**Good:**
```
"Show device name, IP address, and platform for all devices"
```

**Poor:**
```
"Show me the devices"  # System doesn't know which fields you want
```

### 2. Specify Time Range (for historical queries)
**Good:**
```
"Show interface errors in the last 7 days"
```

**Poor:**
```
"Show interface errors"  # Uses latest snapshot, may be outdated
```

### 3. Use Device Role or Site Filtering
```
"Show all core routers in site 'lab'"
# Faster than querying R1, R2, R3... individually
```

### 4. Export Results for Local Analysis
```bash
$ olav "Show BGP routes with low local-pref" > bgp_routes.csv

# Then analyze in Excel or other tools
```

### 5. Combine Queries
```bash
# Step 1: Query the fault point
olav "Which interfaces have packet loss?"

# Step 2: Check topology of that interface
olav "Show topology links connected to interface Ge-0/0/0 on SW1"

# Step 3: Review peer device logs (if needed)
olav "Show last error on R1 interface Ge-0/0/1"
```

---

## 🆘 Frequently Asked Questions (FAQ)

### Q: What if my query returns "No data"?

**A:** Possible causes:
1. Device/interface has no data in snapshot → verify with `show devices`
2. Snapshot is too old → check `When was the last snapshot?`
3. SQL syntax error → check logs or rephrase

```bash
# View available tables and columns
olav "Show schema of devices table"

# Re-collect snapshot
olav --agent sync "collect_snapshot"
```

### Q: CLI command execution timeout?

**A:** 
1. Check if device is online: `olav "Show device R1 status"`
2. Increase timeout (edit `api.json`)
3. Retry with simplified command (avoid large config dumps)

### Q: How to check which commands are blacklisted?

**A:**
```bash
# View blacklist
cat .olav/config/blacklisted_commands.yaml

# Query allowed commands for a device
olav "Show all commands allowed on Cisco devices"
```

### Q: How often are snapshots collected? Can I trigger manually?

**A:**
```bash
# View current collection schedule
olav "Show snapshot schedule"

# Manually collect once
olav --agent sync "collect_snapshot --force"

# View collection history
.olav/logs/snapshot_*.log
```

### Q: Do you support admin accounts?

**A:**
Quick Agent only reads snapshots and executes show commands. Configuration changes are not supported. For changes, use:
```bash
# Plan the change (analyze impact)
olav --agent ops "Plan config change: ..."

# Execute the change (manually or via Nornir)
cd /path/to/nornir/tasks && nornir_cli ...
```

---

## 📞 Getting Help

### Online Resources
- 📖 Complete Documentation: `README.md`
- 🔧 Configuration Reference: `01_CONFIGURATION.md`
- 📊 Database Schema: `.olav/workspace/quick/references/SCHEMA_REFERENCE.md`

### Troubleshooting
1. View logs: `.olav/logs/users/<username>.log`
2. Test SQL: `.olav/sql_debug.md`
3. Upgrade to Ops Agent: `olav --agent ops "<complex_query>"`

### Feedback and Suggestions
```bash
# Report an issue
echo "Problem: ..." > .olav/feedback.txt

# Check version and system info
olav --version
olav --system-info
```

---

## 📝 Changelog

**v1.1.0** (Current)
- ✅ Added 4 major query modes (Query/CLI/Analysis/Search)
- ✅ Support for topology-aware fault diagnosis
- ✅ Added log query capability (Parquet support)
- ✅ Data export to CSV/JSON/Markdown

**v1.0.0**
- ✅ Basic SQL queries
- ✅ CLI command execution
- ✅ Knowledge base search

---

**Last Updated: March 6, 2026**
