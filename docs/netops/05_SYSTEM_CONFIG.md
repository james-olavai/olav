# Config Agent

Config Agent is OLAV's **system management and automation scheduling hub**. It manages LLM API credentials, device inventory, data collection scheduling, snapshot lifecycle, LLM cost budgets, and all runtime parameters, while supporting natural-language scheduling of complex network tasks (audits, syncs, simulations).

### 🎛️ Config Agent is a Multi-Dimensional System Management Engine

Config Agent is not just a simple config read/write tool—it operates across **multiple management dimensions**:

| Dimension | Capability | Example |
|-----------|-----------|---------|
| **Credential management** | Centralized management of LLM APIs, device SSH creds, third-party API keys | "Update GPT-4 API key" |
| **Inventory sync** | Auto-discover/import devices, maintain single source of truth | "Sync Cisco devices from CMDB" |
| **Scheduling automation** | Describe complex cron tasks in natural language, auto-deploy | "Run health audit every day at 06:00" |
| **Parameter tuning** | Dynamically adjust LLM model, request parameters, cost budgets | "Switch to Claude 3, set $100/month budget" |
| **Status monitoring** | Track execution status of all background tasks, failure alerts | "Why did last night's audit fail?" |
| **Lifecycle management** | Manage snapshot retention, data archival, cleanup old data | "Keep only last 30 days of snapshots" |

Combined, these dimensions make Config Agent **the control hub for automating the entire system**.

---

## Quick Start

### Using CLI

```bash
# Navigate to OLAV main directory
cd /home/yhvh/Olav

# Display current configuration
olav config

# Modify configuration via natural language
olav --agent config "Update LLM model to GPT-4"

# Schedule a recurring task
olav --agent config "Run health audit every day at 06:00"
```

### Using Python API

```python
from olav.agents.config import ConfigAgent

agent = ConfigAgent()

# Query configuration
result = agent.run("What is the current LLM model?")
print(result)

# Schedule task
agent.run("Schedule daily health audit at 06:00 using health_full_drift profile")
```

---

## What Can Config Agent Do?

### 1️⃣ **Credential and API Management**

Config Agent manages centralized storage of all sensitive information.

**Command examples:**
```bash
# LLM API credentials
olav --agent config "Set OpenAI API key to sk-xxxxx"
olav --agent config "Switch to Claude 3 with Anthropic API"

# Device access credentials
olav --agent config "Add SSH credentials for lab_site routers"
olav --agent config "Rotate device passwords"

# Cost management
olav --agent config "Set monthly LLM budget to $500"
olav --agent config "Alert me when LLM costs exceed $400"
```

**Supported integrations:**
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3)
- Local Ollama
- SSH key and password storage
- Alert Webhooks (Slack, Email)

**Performance:** ⚡ Credential updates take effect immediately | No restart required

---

### 2️⃣ **Device Inventory Management**

Auto-import and sync devices from external systems (CMDB, Ansible inventory, NetBox).

**Command examples:**
```bash
# Auto-discover and import
olav --agent config "Import devices from NetBox, sync every 24 hours"
olav --agent config "Sync Cisco devices from Ansible inventory"

# Manual management
olav --agent config "Add device R1 (10.0.1.1) with platform junos"
olav --agent config "Mark device SW1 as decommissioned"
olav --agent config "Update R1 management IP to 10.0.1.5"

# Verify
olav --agent config "List all devices by site and platform"
olav --agent config "Show devices with connectivity issues"
```

**Inventory sources:**
- YAML/CSV direct import
- NetBox API sync
- Ansible inventory integration
- Nornir auto-discovery

**Validation mechanism:** Auto Ping to check management IP reachability | Failure alerts

---

### 3️⃣ **Snapshot Collection Scheduling**

Automate network data collection with support for incremental and full collection.

**Command examples:**
```bash
# Basic scheduling
olav --agent config "Schedule daily snapshots at 06:00"
olav --agent config "Run hourly incremental snapshots for core routers only"

# Flexible scheduling
olav --agent config "Every Monday 22:00 run full snapshot, label 'weekly-baseline'"
olav --agent config "On the 1st of month, retain only that snapshot for 90 days"

# Event-triggered collection
olav --agent config "When CPU exceeds 80% on any device, trigger immediate snapshot"
olav --agent config "On BGP flap events, capture logs and snapshot"

# Verify
olav --agent config "Show snapshot schedule and last execution status"
olav --agent config "What snapshots are stored, how much disk used?"
```

**Collection modes:**
- **Full collection** - All devices, all command templates
- **Incremental collection** - Only changed configs and failure-related devices
- **On-demand collection** - Immediate trigger for troubleshooting

**Storage policies:**
- Date-categorized storage
- Auto compression and archival
- Lifecycle management (delete old data)
- Incremental backup support

---

### 4️⃣ **Background Task Scheduling**

Describe complex tasks in natural language; auto-generate cron entries and execution flows.

**Command examples:**
```bash
# Audit tasks
olav --agent config "Every day 06:00 run comprehensive health audit with health_full_drift"
olav --agent config "Every Friday 20:00 run resilience assessment and email report to ops@company.com"

# Sync tasks
olav --agent config "Sync device inventory from NetBox every 12 hours"
olav --agent config "Check configuration drift every 4 hours, alert on changes"

# Data processing
olav --agent config "Archive snapshots older than 90 days, compress to gz format"
olav --agent config "Generate weekly network topology report, save to exports/"

# Combined tasks
olav --agent config "Every Sunday 23:59: run full health audit, archive old snapshots, send summary email"
```

**Task execution:**
- Background execution (cron)
- Logging to `.olav/logs/cron_*.log`
- Auto-retry on failure
- Parallel execution (max 5 concurrent tasks)

**Monitoring and alerts:**
```bash
olav --agent config "Show all scheduled tasks and their execution history"
olav --agent config "Why did yesterday's audit task fail?"
olav --agent config "Alert me if any cron task fails"
```

---

### 5️⃣ **Parameter Tuning and Optimization**

Dynamically adjust system parameters, LLM behavior, database settings.

**Command examples:**
```bash
# LLM configuration
olav --agent config "Set LLM temperature to 0.3 for more deterministic responses"
olav --agent config "Increase max_tokens to 4000 for detailed analysis"
olav --agent config "Use GPT-4 Turbo for Ops Agent, keep GPT-3.5 for Quick Agent"

# Performance parameters
olav --agent config "Disable caching for real-time queries"
olav --agent config "Set snapshot cache size to 10 GB"
olav --agent config "Increase database query timeout to 30 seconds"

# Audit parameters
olav --agent config "Set anomaly detection Z-score threshold to 2.0 (more sensitive)"
olav --agent config "Enable incident clustering in all audit profiles"
olav --agent config "Max 50 findings per audit report"
```

**Show current parameters:**
```bash
olav config
# Displays all current settings
```

---

### 6️⃣ **System Health Checks & Diagnostics**

Proactively monitor and diagnose system health across all layers: infrastructure, databases, network, LLM services, automation tasks, and APIs.

#### Check Scope

**🖥️ System Resources:**
```bash
# CPU, memory, disk
olav --agent config "Full system health report"
olav --agent config "Check disk usage, alert if >80%"
olav --agent config "Show memory usage by agent"
olav --agent config "CPU load trends over last 7 days"
```

**🗄️ Database Health:**
```bash
# DuckDB / LanceDB integrity
olav --agent config "Database integrity check"
olav --agent config "Show database size and growth rate"
olav --agent config "Check slow queries and indexes"
olav --agent config "Snapshot table statistics"
olav --agent config "Verify data consistency across tables"
```

**🌐 Network Connectivity:**
```bash
# Device reachability, API connectivity
olav --agent config "Network connectivity report"
olav --agent config "Which devices are unreachable (not reached in 7 days)"
olav --agent config "Verify LLM API endpoints are reachable"
olav --agent config "Check database host connectivity"
olav --agent config "DNS resolution vs actual device IPs"
```

**🔑 API & Credential Health:**
```bash
# LLM API, SSH credentials, third-party APIs
olav --agent config "Verify all API credentials are valid"
olav --agent config "Test OpenAI API key, check rate limits"
olav --agent config "Validate SSH credentials for all devices"
olav --agent config "Test NetBox API connectivity"
olav --agent config "Show API key expiration dates"
```

**⚙️ Background Task Health:**
```bash
# Cron jobs, snapshot collection, sync task status
olav --agent config "Show all scheduled tasks and their status"
olav --agent config "List failed tasks in the last 24 hours"
olav --agent config "Any tasks stuck or not responding?"
olav --agent config "Snapshot collection success rate"
olav --agent config "Show tasks that take longest to complete"
```

**💰 Cost & Quota Tracking:**
```bash
# LLM costs, API quotas, storage limits
olav --agent config "LLM API costs and spending trends"
olav --agent config "Which agent consumes most LLM tokens?"
olav --agent config "API rate limit status and usage"
olav --agent config "Storage usage vs available quota"
olav --agent config "Cost projection for this month"
```

**📊 Logs & Alerts:**
```bash
# Errors, warnings, anomalies
olav --agent config "Show recent errors and warnings"
olav --agent config "Critical alerts in the last 24 hours"
olav --agent config "Any permission or authentication errors?"
olav --agent config "Syslog analysis - common error patterns"
olav --agent config "Trends: are errors increasing?"
```

#### Generated Health Reports

When executing system health checks, Config Agent generates a comprehensive report with these sections:

| Report Section | Content | Alert Conditions |
|---|---|---|
| **Resource Summary** | CPU, memory, disk usage percentages | Disk>85% / Memory sustained>80% |
| **Database Health** | Table sizes, growth rates, slow queries | Corrupted tables / Query timeouts |
| **Device Reachability** | Unreachable device count, last contact time | Core devices unreachable |
| **API Availability** | LLM, NetBox, SNMP, other API status | Timeouts / Auth failures |
| **Task Execution** | Success rate (last 24h), failure breakdown | Success rate <95% / Critical task failures |
| **Cost Trends** | Monthly spend, MoM comparison, projection | Spending exceeds budget |
| **Alert Summary** | Error frequency, severity distribution | Critical alerts >5 |
| **Optimization Tips** | Improvement suggestions from historical data | Top 5 recommendations |

#### Automated Health Check Alerts

Config Agent supports automated health checking with alert rules:

```bash
# Run lightweight check every hour
olav --agent config "Schedule hourly system health check (light mode)"

# Detailed check daily with email report
olav --agent config "Every day 07:00 run full health check, email report to ops@company.com"

# Immediate alerts on critical metric changes
olav --agent config "Alert immediately if:
  - Disk usage >90%
  - Database query latency >5 seconds
  - Any core device unreachable
  - LLM API rate limited"

# View active alert rules
olav --agent config "Show all active health check alerts"
```

#### Deep Diagnostic Commands

For troubleshooting and root cause analysis:

```bash
# Trace a specific device issue
olav --agent config "Diagnostic: Device R1 unreachable - trace connectivity, check logs, device status"

# Analyze performance issues
olav --agent config "Performance diagnosis: Database queries slow - show slow query log, index stats, table size"

# Trace task failure
olav --agent config "Task diagnostic: Why did 2026-03-06 audit fail? Show logs, resource usage, error details"

# API troubleshooting
olav --agent config "API diagnostic: OpenAI rate limited - show request history, quota, reset time"

# Storage troubleshooting
olav --agent config "Storage diagnostic: Disk almost full - show snapshot sizes, find largest tables, recommend cleanup"
```

---

## Config Agent Workflow

### Process Flow

1. **Parse request** → Understand user's natural language intent
2. **Check permissions** → Verify user can modify that config
3. **Validate change** → Test new config validity (e.g., verify API key)
4. **Human confirmation** (HITL) → Require confirmation for sensitive operations (e.g., deleting data)
5. **Execute update** → Write to disk and memory config
6. **Apply changes** → Reload affected services (if no restart needed)

### Human-in-the-Loop (HITL) Scenarios

Some operations require explicit confirmation:
```bash
olav --agent config "Delete all snapshots older than 90 days"
# Output: confirmation prompt, requires 'yes' input
# Verifies again before executing delete
```

---

## Configuration File Locations

| File | Purpose | Permission |
|------|---------|-----------|
| `.olav/config/api.json` | LLM API config, cost budget | Admin |
| `.olav/config/paths.json` | Data path configuration | Read-only |
| `.olav/config/logging.yaml` | Logging level and output | Admin |
| `~/.olav/personal_config.json` | User personal config (local override) | User |

### Configuration Priority

1. **User local** `~/.olav/personal_config.json` (highest priority)
2. **Project config** `.olav/config/api.json`
3. **Defaults** `src/olav/core/defaults.py`

---

## Common Command Reference

```bash
# Display configuration
olav config
olav --agent config "Show current LLM model and API provider"

# LLM and API
olav --agent config "Set LLM model to gpt-4-turbo"
olav --agent config "Add new Anthropic API key"

# Device management
olav --agent config "Sync devices from NetBox"
olav --agent config "Add device R1 (10.0.1.1)"
olav --agent config "List all devices by site"

# Scheduling
olav --agent config "Every day 06:00 run health audit"
olav --agent config "Show all scheduled tasks"

# Snapshot management
olav --agent config "Schedule daily snapshots at 06:00"
olav --agent config "Archive snapshots older than 60 days"

# Monitoring
olav --agent config "System health status"
olav --agent config "LLM costs this month"
olav --agent config "Show failed tasks"
```

---

## Permissions and Security

### User Roles

| Role | Permissions | Examples |
|------|-----------|----------|
| **Viewer** | Read-only config | `olav config` |
| **Operator** | Can schedule tasks, view logs | Schedule audits, view snapshots |
| **Admin** | Can modify sensitive config | Change API keys, update inventory |

### Sensitive Operation Audit Log

All configuration changes are logged to `.olav/logs/config_audit.log`:
```
2026-03-06 12:34:56 | user: alice | action: update_api_key | target: openai | status: success
2026-03-06 12:35:10 | user: bob | action: delete_snapshots | count: 100 | status: confirmed
```

---

## Troubleshooting

### Issue: Scheduled task didn't execute

**Diagnosis:**
```bash
# Check task status
olav --agent config "Show scheduled tasks and execution history"

# Check logs
tail -f .olav/logs/cron_*.log
```

**Common causes:**
- Cron daemon not running → `ps aux | grep cron`
- Disk space full → `df -h`
- Permission issue → Check `.olav/` directory permissions

### Issue: Configuration change didn't take effect

**Diagnosis:**
```bash
# Force reload configuration
olav --agent config "Reload all configurations"

# Verify new settings
olav config
```

### Issue: Device inventory import failed

**Diagnosis:**
```bash
# Check inventory file format
olav --agent config "Validate inventory file"

# Test connectivity
olav --agent config "Test connectivity to all devices"
```

---

## Tips

- **Test before applying** — For sensitive configs, always test in test environment first
- **Backup regularly** — Regularly backup `.olav/config/` directory
- **Use personal config** — Different users use `~/.olav/personal_config.json` to override global settings
- **Monitor costs** — Regularly check LLM costs, adjust budget or model selection in time
- **Auto alerts** — Set task failure alerts to catch issues early

---

**Last Updated: March 6, 2026**
