# OLAV Platform Health Reference

Use this reference when generating scripts that check or automate OLAV platform
health — database integrity, workspace registration, cron schedules, logs.

---

## 1. Health Check — What to Validate

When writing a platform health script, check these categories in order:

### 1.1 Workspace Registration

| Check | Path | Expected |
|-------|------|---------|
| AGENT.md exists | `.olav/workspace/<agent>/AGENT.md` | present |
| SKILL.md frontmatter valid | `.olav/workspace/<agent>/SKILL.md` | `name`, `tools` fields |
| system.md prompt exists | `.olav/workspace/<agent>/prompts/system.md` | present |
| Tool files on disk | `.olav/workspace/<agent>/tools/<name>.py` | all declared tools |

Agents in `.olav/workspace/`: `config`, `infra`, `devops`, `audit`, `quick`, `ops` (netops)

### 1.2 Database Health

| Check | Command | Healthy |
|-------|---------|---------|
| Main DB accessible | `duckdb .olav/databases/main.duckdb "SELECT 1"` | exit 0 |
| Domain DB accessible | `duckdb .olav/databases/domain.duckdb "SELECT 1"` | exit 0 |
| netops.devices populated | `duckdb ... "SELECT COUNT(*) FROM netops.devices"` | > 0 |
| api_registry tables | `duckdb ... "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='api_registry'"` | ≥ 0 |

### 1.3 Config Files

| File | Purpose | Valid when |
|------|---------|-----------|
| `.olav/config/api.json` | Active workspace config | JSON parseable, `active_workspace` key present |
| `.olav/config/settings.yaml` | Global settings | YAML parseable |
| `.olav/config/cron_schedules.yaml` | Cron job definitions | YAML parseable |

### 1.4 Cron Jobs

```bash
# List all olav-managed cron jobs
crontab -l | grep "olav --agent"

# Check for common required schedules
crontab -l | grep "olav --agent config"    # snapshot schedule
crontab -l | grep "olav --agent audit"     # audit schedule
```

### 1.5 Log / Execution History

OLAV logs are in `.olav/logs/`. Query execution history via DuckDB:

```sql
-- Recent agent invocations
SELECT created_at, agent, query, status
FROM execution_log
ORDER BY created_at DESC
LIMIT 20
```

---

## 2. Standard Health Script Template

```bash
#!/bin/bash
set -euo pipefail

OLAV_DIR="${OLAV_DIR:-.olav}"
PASS=0; WARN=0; FAIL=0

check() {
  local name="$1" cmd="$2"
  if eval "$cmd" &>/dev/null; then
    echo "✅ $name"; ((PASS++))
  else
    echo "❌ $name"; ((FAIL++))
  fi
}

warn_check() {
  local name="$1" cmd="$2"
  if eval "$cmd" &>/dev/null; then
    echo "✅ $name"; ((PASS++))
  else
    echo "⚠️  $name (non-critical)"; ((WARN++))
  fi
}

echo "=== OLAV Platform Health Check ==="

# Database
check "main.duckdb accessible"   "duckdb $OLAV_DIR/databases/main.duckdb 'SELECT 1'"
check "domain.duckdb accessible" "duckdb $OLAV_DIR/databases/domain.duckdb 'SELECT 1'"

# Config
check "api.json valid JSON"  "python3 -c \"import json; json.load(open('$OLAV_DIR/config/api.json'))\""
warn_check "cron schedules present"  "crontab -l 2>/dev/null | grep -q 'olav --agent'"

# Workspaces
for agent in config infra devops audit quick; do
  check "$agent workspace AGENT.md" "test -f $OLAV_DIR/workspace/$agent/AGENT.md"
done

echo ""
echo "Summary: ✅ $PASS passed  ⚠️ $WARN warnings  ❌ $FAIL failed"
[[ $FAIL -eq 0 ]]
```

---

## 3. Automated Health via olav CLI

```bash
# Full health check via config-system agent
olav --agent config "run health check and show all issues"

# Target specific check
olav --agent config "check database health and list any DuckDB lock errors"
olav --agent config "audit workspace for missing tools or broken SKILL.md"
olav --agent config "list all cron jobs and flag any that haven't run in 24h"
```

---

## 4. Common Issues & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `database is locked` | DuckDB write conflict | Kill stale process: `pkill -f duckdb` |
| Tool file missing | SKILL.md references non-existent `.py` | Add tool file or remove from SKILL.md |
| `api.json` missing `active_workspace` | Fresh install | `olav workspace activate <name>` |
| No cron jobs running | crontab empty | `olav --agent config "apply default cron schedules"` |
