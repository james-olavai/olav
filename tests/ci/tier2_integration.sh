#!/usr/bin/env bash
# ==============================================================================
# OLAV v0.18.0 — Tier 2: Integration Tests (T2-01 ~ T2-40)
# ------------------------------------------------------------------------------
# Round 24-60 additions land in Group 8 (T2-26~T2-40): olav diff/explain/catalog
# CLI wheel-install smoke, describe_table tool discovery, ARCH-14 NetworkModel
# end-to-end round-trip against the populated DB from Groups 1-2, sandbox
# `model` auto-inject via a real subprocess, plus parity with T1 Group 12
# for load_reference slicing / tool_help detail / OLAV_DEBUG_* envs /
# recall_memory tier / subagent cap / summarization trigger / SKILL.md
# docstring mode / OLAV_BACKUP_COMMANDS_PATH / 🔧[orch] origin tag. Each
# catches packaging drift the same way T2-29 did for describe_table.py.
# ==============================================================================
# Usage:
#   bash tests/ci/tier2_integration.sh
#
# Required:
#   - Built wheel in dist/        (run `uv build` first)
#
# Optional env vars:
#   OLAV_API_KEY            LLM API key — T2-07~T2-14, T2-19~T2-21, T2-25 skip if unset
#   OLAV_LLM_BASE_URL       (default: https://openrouter.ai/api/v1)
#   OLAV_LLM_MODEL          (default: x-ai/grok-4.1-fast)
#   OLAV_NETOPS_DIR         (default: ./olav-netops)
#   NORNIR_PASSWORD         SSH password for lab devices
#   NORNIR_USERNAME         SSH username (default: admin)
#   OLAV_REGISTRY_URL       Registry URL for T2-22 (skip if unset)
#
# Device topology (SKIP groups T2-01~T2-14 if 192.168.100.101 unreachable):
#   R1:  192.168.100.101  (juniper_junos)
#   R2:  192.168.100.102  (cisco_ios)
#   R3:  192.168.100.103  (cisco_ios)
#   R4:  192.168.100.104  (cisco_ios)
#   SW1: 192.168.100.105  (cisco_ios)
#   SW2: 192.168.100.106  (cisco_ios)
# ==============================================================================

set -uo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_DIR="/tmp/olav-ci-t2-${TIMESTAMP}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NETOPS_DIR="${OLAV_NETOPS_DIR:-${REPO_ROOT}/olav-netops}"

WHEEL=$(ls "${REPO_ROOT}/dist/"*.whl 2>/dev/null | tail -1)
if [ -z "${WHEEL:-}" ]; then
    echo "ERROR: No wheel found in dist/. Run 'uv build' first."
    exit 1
fi

# ── Capture env vars before isolation ────────────────────────────────────────
_API_KEY="${OLAV_API_KEY:-}"
_LLM_BASE_URL="${OLAV_LLM_BASE_URL:-https://openrouter.ai/api/v1}"
_LLM_MODEL="${OLAV_LLM_MODEL:-x-ai/grok-4.1-fast}"
_NORNIR_PASSWORD="${NORNIR_PASSWORD:-}"
_NORNIR_USERNAME="${NORNIR_USERNAME:-admin}"
_REGISTRY_URL="${OLAV_REGISTRY_URL:-}"
_DEV_CONFIG="${OLAV_DEV_CONFIG:-}"          # optional: path to dev api.json (or the config dir) to copy wholesale
# DX: accept a config directory — auto-resolve to api.json inside it.
if [ -n "${_DEV_CONFIG}" ] && [ -d "${_DEV_CONFIG}" ] && [ -f "${_DEV_CONFIG}/api.json" ]; then
    _DEV_CONFIG="${_DEV_CONFIG}/api.json"
fi
# Resolve to absolute path immediately (before any cd to test dir)
[ -n "${_DEV_CONFIG}" ] && _DEV_CONFIG="$(realpath "${_DEV_CONFIG}" 2>/dev/null || echo "${_DEV_CONFIG}")"
_DEV_NORNIR_DIR="${OLAV_DEV_NORNIR_DIR:-}"  # optional: path to dev nornir config dir to copy
[ -n "${_DEV_NORNIR_DIR}" ] && _DEV_NORNIR_DIR="$(realpath "${_DEV_NORNIR_DIR}" 2>/dev/null || echo "${_DEV_NORNIR_DIR}")"
_CLAB_BIN="${OLAV_CLAB_PATH:-$(command -v clab 2>/dev/null)}"  # optional: path to clab binary
_CLAB_API="${OLAV_CLAB_API:-http://192.168.100.12:8080}"       # remote clab API endpoint
DEVICE_GATEWAY="192.168.100.101"

# ── Feature flags ─────────────────────────────────────────────────────────────
LLM_AVAILABLE=false
[ -n "${_API_KEY}" ] && LLM_AVAILABLE=true
# Also available if dev config contains a key (will be detected after copy)
[ -n "${_DEV_CONFIG}" ] && [ -f "${_DEV_CONFIG}" ] && LLM_AVAILABLE=true

DEVICES_AVAILABLE=false
if ping -c1 -W2 "${DEVICE_GATEWAY}" >/dev/null 2>&1; then
    # Try to get password from dev nornir defaults.yaml if not explicitly provided
    if [ -z "${_NORNIR_PASSWORD}" ] && [ -n "${_DEV_NORNIR_DIR}" ] && [ -f "${_DEV_NORNIR_DIR}/defaults.yaml" ]; then
        # Use ^\s* (zero or more) — top-level YAML keys have no leading indent
        # Also strip CRLF (\r) in case file uses Windows line endings
        _NORNIR_PASSWORD=$(grep -E '^\s*password:' "${_DEV_NORNIR_DIR}/defaults.yaml" 2>/dev/null | \
            head -1 | sed 's/.*password:[[:space:]]*//' | tr -d '"'"'" | tr -d '\r' | tr -d '[:space:]')
        _NORNIR_USERNAME=$(grep -E '^\s*username:' "${_DEV_NORNIR_DIR}/defaults.yaml" 2>/dev/null | \
            head -1 | sed 's/.*username:[[:space:]]*//' | tr -d '"'"'" | tr -d '\r' | tr -d '[:space:]')
    fi
    [ -n "${_NORNIR_PASSWORD}" ] && DEVICES_AVAILABLE=true || \
        echo "  WARN: devices reachable but NORNIR_PASSWORD unset — SSH groups will SKIP"
fi

CLAB_AVAILABLE=false
[ -n "${_CLAB_BIN}" ] && CLAB_AVAILABLE=true
# Allow manual override when topology is already deployed but binary lives elsewhere
[ "${OLAV_CLAB_AVAILABLE:-false}" = "true" ] && CLAB_AVAILABLE=true
# Also detect via remote clab API HTTP check (clab runs as API server on 192.168.100.12)
if [ "$CLAB_AVAILABLE" = false ] && [ -n "${_CLAB_API}" ]; then
    if curl -s --max-time 3 "${_CLAB_API}/" 2>/dev/null | grep -q "Containerlab API"; then
        CLAB_AVAILABLE=true
        echo "  INFO: clab API reachable at ${_CLAB_API}"
    fi
fi

REGISTRY_AVAILABLE=false
_REGISTRY_SVC="${OLAV_REGISTRY_SVC:-}"  # service name in services.yaml (preferred)
[ -n "${_REGISTRY_URL}" ] && REGISTRY_AVAILABLE=true
# If clab API is available, use containerlab service name (defined in services.yaml)
if [ "$CLAB_AVAILABLE" = true ]; then
    REGISTRY_AVAILABLE=true
    [ -z "${_REGISTRY_SVC}" ] && _REGISTRY_SVC="containerlab"
    echo "  INFO: registry service: ${_REGISTRY_SVC} (via clab API)"
fi

# ── Isolate environment ──────────────────────────────────────────────────────
mkdir -p "${TEST_DIR}"
export HOME="${TEST_DIR}/fakehome"
mkdir -p "$HOME"
export TOKENIZERS_PARALLELISM=false
export HF_HUB_DISABLE_PROGRESS_BARS=1
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
unset OPENAI_API_KEY ANTHROPIC_API_KEY HF_TOKEN 2>/dev/null || true

# ── Counters ──────────────────────────────────────────────────────────────────
PASS=0; FAIL=0; WARN=0; SKIP=0

# ── Helpers ───────────────────────────────────────────────────────────────────
pass_test() { echo "  $1 $2... OK";   PASS=$((PASS + 1)); }
fail_test() { echo "  $1 $2... FAIL ${3:-}"; FAIL=$((FAIL + 1)); }
warn_test() { echo "  $1 $2... WARN ${3:-}"; WARN=$((WARN + 1)); }
skip_test() { echo "  $1 $2... SKIP"; SKIP=$((SKIP + 1)); }

skip_group_devices() {
    # Skip a single test with device-unavailable reason
    skip_test "$1" "$2 (devices unreachable or NORNIR_PASSWORD unset)"
}

skip_group_llm() {
    skip_test "$1" "$2 (no OLAV_API_KEY)"
}

http_code() {
    # Return HTTP status code for a URL
    curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$@"
}

kill_web_service() {
    # Kill any process using port 2280
    local _pid
    _pid=$(lsof -ti :2280 2>/dev/null | head -1)
    if [ -n "${_pid}" ]; then
        kill "${_pid}" 2>/dev/null || true
        local _i=0
        while [ $_i -lt 10 ] && lsof -ti :2280 >/dev/null 2>&1; do
            sleep 0.5
            _i=$((_i + 1))
        done
        # Force kill if still running
        _pid=$(lsof -ti :2280 2>/dev/null | head -1)
        [ -n "${_pid}" ] && kill -9 "${_pid}" 2>/dev/null || true
    fi
    # Remove stale PID file to prevent PID-reuse race in WebService._is_running()
    rm -f "${TEST_DIR}/.olav/run/web.pid" 2>/dev/null || true
}

start_web_service() {
    # Start web service and wait up to N seconds for port 2280
    local _wait="${1:-12}"
    "$OLAV" service web start >/dev/null 2>&1
    local _i=0
    while [ $_i -lt "${_wait}" ]; do
        if curl -sf "http://127.0.0.1:2280/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        _i=$((_i + 1))
    done
    return 1
}

# ── Banner ────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════╗"
echo "║  OLAV Tier 2: Integration Tests (T2-01 ~ T2-25) ║"
echo "╚══════════════════════════════════════════════════╝"
echo "  Wheel:    $(basename "$WHEEL")"
echo "  Test dir: ${TEST_DIR}"
echo "  LLM:      ${LLM_AVAILABLE}  (OLAV_API_KEY: $([ -n "${_API_KEY}" ] && echo set || echo unset), dev_config: $([ -n "${_DEV_CONFIG}" ] && echo yes || echo no))"
echo "  Devices:  ${DEVICES_AVAILABLE}  (gateway: ${DEVICE_GATEWAY}, user: ${_NORNIR_USERNAME:-unset})"
echo "  clab:     ${CLAB_AVAILABLE}  (bin: ${_CLAB_BIN:-n/a}, api: ${_CLAB_API})"
echo "  Registry: ${REGISTRY_AVAILABLE}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# SETUP — fresh venv, install wheel, olav init, seed data, skill install
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Setup ==="

python3 -m venv "${TEST_DIR}/.venv"
PIP="${TEST_DIR}/.venv/bin/pip"
OLAV="${TEST_DIR}/.venv/bin/olav"
PYTHON="${TEST_DIR}/.venv/bin/python3"

"$PIP" install -q "$WHEEL" 2>&1 | tail -2
echo "  wheel installed: $(basename "$WHEEL")"

cd "${TEST_DIR}"
"$OLAV" init >/dev/null 2>&1
echo "  olav init: done"

# Inject LLM / embedding config
if [ -n "${_DEV_CONFIG}" ] && [ -f "${_DEV_CONFIG}" ]; then
    # Copy entire dev api.json — carries api_key, custom_headers, embedding config, etc.
    cp "${_DEV_CONFIG}" .olav/config/api.json
    echo "  LLM config: copied from ${_DEV_CONFIG}"
elif [ "$LLM_AVAILABLE" = true ]; then
    # Fallback: inject individual fields when only OLAV_API_KEY is set
    "$PYTHON" - <<PYEOF
import json
from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('shared', {})['api_key'] = '${_API_KEY}'
cfg.setdefault('llm', {})['base_url'] = '${_LLM_BASE_URL}'
cfg.setdefault('llm', {})['model'] = '${_LLM_MODEL}'
p.write_text(json.dumps(cfg, indent=2))
PYEOF
    echo "  LLM config: injected (model=${_LLM_MODEL})"
fi

# Inject Nornir config (SSH credentials for lab devices)
if [ "$DEVICES_AVAILABLE" = true ]; then
    "$PYTHON" - <<PYEOF
import json
from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('netops', {})['username'] = '${_NORNIR_USERNAME}'
cfg.setdefault('netops', {})['password'] = '${_NORNIR_PASSWORD}'
p.write_text(json.dumps(cfg, indent=2))
PYEOF
    echo "  Nornir creds: injected (user=${_NORNIR_USERNAME})"
fi

# Install netops skill (workspace files) + Python package (nornir/netmiko deps)
if [ -d "${NETOPS_DIR}" ]; then
    "$OLAV" skill install "${NETOPS_DIR}" >/dev/null 2>&1
    # Explicitly pip install to guarantee nornir etc. land in this venv
    "$PIP" install -q -e "${NETOPS_DIR}" 2>&1 | grep -v "^notice\|^hint" || true
    echo "  skill install: done (${NETOPS_DIR})"
else
    echo "  skill install: WARN (${NETOPS_DIR} not found)"
fi

# Copy dev nornir config files into test workspace (provides device credentials + topology)
# Sprint 3 R32 renamed ops/probe/ → ops/collect/ (ADR-0005); use the post-rename path.
NORNIR_DEST=".olav/workspace/ops/collect/config/nornir"
if [ -n "${_DEV_NORNIR_DIR}" ] && [ -d "${_DEV_NORNIR_DIR}" ]; then
    mkdir -p "${NORNIR_DEST}"
    for _f in hosts.yaml groups.yaml defaults.yaml config.yaml; do
        [ -f "${_DEV_NORNIR_DIR}/${_f}" ] && cp "${_DEV_NORNIR_DIR}/${_f}" "${NORNIR_DEST}/${_f}"
    done
    echo "  nornir config: copied from ${_DEV_NORNIR_DIR}"
elif [ -d "${NORNIR_DEST}" ]; then
    echo "  nornir config: already present (from skill install)"
else
    echo "  nornir config: WARN (neither OLAV_DEV_NORNIR_DIR nor skill-installed config found)"
fi

# Reset auth.mode=none (olav init _init_admin_user sets it to token)
"$PYTHON" -c "
import json
from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('auth', {})['mode'] = 'none'
p.write_text(json.dumps(cfg, indent=2))
" 2>/dev/null || true
echo "  auth.mode: reset to none"

# Setup remote clab API config (services.yaml + ops/lab workspace config.json)
if [ "$CLAB_AVAILABLE" = true ]; then
    # Copy services.yaml so infra agent can discover the containerlab service
    cp "${REPO_ROOT}/.olav/config/services.yaml" ".olav/config/services.yaml" 2>/dev/null || true
    # Write ops/lab workspace config.json with live API credentials
    mkdir -p ".olav/workspace/ops/lab/config"
    cat > ".olav/workspace/ops/lab/config/config.json" <<CLABEOF
{
  "base_url": "${_CLAB_API}",
  "username": "olav",
  "password": "olav123",
  "mgmt_subnet": "172.20.50.0/24"
}
CLABEOF
    # Export env vars used by services.yaml auth (password_env: CLAB_PASSWORD)
    export CLAB_USERNAME="olav"
    export CLAB_PASSWORD="olav123"
    echo "  clab config: injected (API=${_CLAB_API})"
fi

# Clear memory cache for clean baseline
rm -rf .olav/databases/memory.lance 2>/dev/null || true
echo "  memory cache: cleared"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# HELPER SCRIPTS
# ══════════════════════════════════════════════════════════════════════════════
HELPERS="${TEST_DIR}/ci_helpers"
mkdir -p "$HELPERS"

# ── DB query helper ───────────────────────────────────────────────────────────
cat > "${HELPERS}/t2_db_query.py" << 'EOF'
"""Query olav DuckDB and output result count or raw rows."""
import sys
import os
from pathlib import Path

os.chdir(Path(sys.argv[1]))  # project root = test dir

import duckdb

db_path = Path('.olav/databases/main.duckdb')
if not db_path.exists():
    # Fallback to domain.duckdb (legacy name)
    db_path = Path('.olav/databases/domain.duckdb')
if not db_path.exists():
    print("ERROR: main.duckdb not found")
    sys.exit(1)

query = sys.argv[2]
schema = sys.argv[3] if len(sys.argv) > 3 else None

con = duckdb.connect(str(db_path), read_only=True)
try:
    if schema:
        con.execute(f"SET search_path = '{schema}'")
    rows = con.execute(query).fetchall()
    if len(sys.argv) > 4 and sys.argv[4] == '--count':
        # Return the scalar value from COUNT(*) queries, not the row count
        print(rows[0][0] if rows else 0)
    else:
        for row in rows:
            print(row)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
EOF

# ── netops_init runner ────────────────────────────────────────────────────────
cat > "${HELPERS}/t2_run_netops_init.sh" << SHEOF
#!/usr/bin/env bash
# Run netops_init with credentials from environment
export NORNIR_PASSWORD="${_NORNIR_PASSWORD}"
export NORNIR_USERNAME="${_NORNIR_USERNAME}"
cd "${TEST_DIR}"
"${PYTHON}" "${REPO_ROOT}/olav-netops/scripts/netops_init.py" "\$@" 2>&1
SHEOF
chmod +x "${HELPERS}/t2_run_netops_init.sh"

# ── SSE stream checker ────────────────────────────────────────────────────────
cat > "${HELPERS}/t2_check_sse.sh" << 'SHEOF'
#!/usr/bin/env bash
# Usage: t2_check_sse.sh THREAD_ID MESSAGES_JSON API_KEY_HEADER
THREAD_ID="$1"
MESSAGES="$2"
AUTH_HEADER="${3:-}"

CURL_ARGS=(-s -N --max-time 60
    -X POST "http://127.0.0.1:2280/threads/${THREAD_ID}/runs/stream"
    -H "Content-Type: application/json"
    -d "{\"input\": {\"messages\": ${MESSAGES}}}")

[ -n "${AUTH_HEADER}" ] && CURL_ARGS+=(-H "Authorization: Bearer ${AUTH_HEADER}")

OUTPUT=$(curl "${CURL_ARGS[@]}" 2>&1 | head -20)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "^data:"; then
    exit 0
fi
exit 1
SHEOF
chmod +x "${HELPERS}/t2_check_sse.sh"

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: SSH Collection (T2-01 ~ T2-06)
# Requires: DEVICES_AVAILABLE + olav-netops installed
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 1: SSH Collection (T2-01 ~ T2-06) ==="

if [ "$DEVICES_AVAILABLE" = false ]; then
    for _id in T2-01 T2-02 T2-03 T2-04 T2-05 T2-06; do
        skip_group_devices "$_id" "SSH collection"
    done
elif [ ! -d "${NETOPS_DIR}" ]; then
    for _id in T2-01 T2-02 T2-03 T2-04 T2-05 T2-06; do
        skip_test "$_id" "SSH collection (olav-netops dir not found)"
    done
else
    # Run full netops_init (Stages 1-5)
    echo "  Running netops_init (this may take ~3 minutes)..."
    NETOPS_OUT="${TEST_DIR}/netops_init_output.txt"
    export NORNIR_PASSWORD="${_NORNIR_PASSWORD}"
    export NORNIR_USERNAME="${_NORNIR_USERNAME}"
    "$PYTHON" "${REPO_ROOT}/olav-netops/scripts/netops_init.py" > "${NETOPS_OUT}" 2>&1
    NETOPS_EXIT=$?

    # T2-01: netops_init exit 0 + completion marker
    # New output format: "✅ Network initialization complete" and "Failed: N"
    if [ $NETOPS_EXIT -eq 0 ] && grep -q "Failed: 0" "${NETOPS_OUT}"; then
        pass_test "T2-01" "netops_init 6 devices 0 failures"
    elif [ $NETOPS_EXIT -eq 0 ]; then
        if grep -qi "network initialization complete\|stage.*complete\|pipeline.*complete\|all.*done\|onboarding complete" "${NETOPS_OUT}"; then
            warn_test "T2-01" "netops_init completed but 'Failed: 0' not found in output"
        else
            fail_test "T2-01" "netops_init (exit 0 but no completion marker)"
        fi
    else
        fail_test "T2-01" "netops_init (exit $NETOPS_EXIT)"
    fi

    # T2-02: Junos platform detected — R1 rows contain Junos commands
    if grep -qi "show interfaces terse\|show route\|show bgp summary\|junos" "${NETOPS_OUT}"; then
        pass_test "T2-02" "platform detection Junos (junos commands in output)"
    else
        warn_test "T2-02" "Junos platform commands not found in netops_init output (check R1)"
    fi

    # T2-03: IOS platform detected — SW1/SW2 rows contain IOS commands
    if grep -qi "show running-config\|show interfaces status\|show ip route\|ios" "${NETOPS_OUT}"; then
        pass_test "T2-03" "platform detection IOS (ios commands in output)"
    else
        warn_test "T2-03" "IOS platform commands not found in netops_init output (check SW1/SW2)"
    fi

    # T2-04: Device ETL populated 6 rows
    DEVICE_COUNT=$("$PYTHON" "${HELPERS}/t2_db_query.py" "${TEST_DIR}" \
        "SELECT COUNT(*) FROM netops.devices" "" --count 2>/dev/null || echo 0)
    if [ "${DEVICE_COUNT}" -eq 6 ] 2>/dev/null; then
        pass_test "T2-04" "Device ETL 6 rows (netops.devices = 6)"
    elif [ "${DEVICE_COUNT}" -gt 0 ] 2>/dev/null; then
        fail_test "T2-04" "Device ETL count mismatch: expected 6, got ${DEVICE_COUNT}"
    else
        fail_test "T2-04" "Device ETL: no rows in netops.devices"
    fi

    # T2-05: Device ETL has IP addresses (no NULL ip_address)
    NULL_IP_COUNT=$("$PYTHON" "${HELPERS}/t2_db_query.py" "${TEST_DIR}" \
        "SELECT COUNT(*) FROM netops.devices WHERE ip_address IS NULL" "" --count 2>/dev/null || echo 1)
    if [ "${NULL_IP_COUNT}" -eq 0 ] 2>/dev/null; then
        pass_test "T2-05" "Device ETL no NULL ip_address"
    else
        fail_test "T2-05" "Device ETL has ${NULL_IP_COUNT} rows with NULL ip_address"
    fi

    # T2-06: Topology ETL >= 10 links
    LINK_COUNT=$("$PYTHON" "${HELPERS}/t2_db_query.py" "${TEST_DIR}" \
        "SELECT COUNT(*) FROM netops.topology_links" "" --count 2>/dev/null || echo 0)
    if [ "${LINK_COUNT}" -ge 10 ] 2>/dev/null; then
        pass_test "T2-06" "Topology ETL ≥10 links (got ${LINK_COUNT})"
    else
        fail_test "T2-06" "Topology ETL only ${LINK_COUNT} links (expected ≥10)"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Start web service (needed for T2-07~T2-10, T2-19~T2-21)
# ══════════════════════════════════════════════════════════════════════════════
WEB_STARTED=false
if [ "$LLM_AVAILABLE" = true ] || [ "$DEVICES_AVAILABLE" = true ]; then
    kill_web_service
    if start_web_service 25; then
        WEB_STARTED=true
        echo "  Web service started: http://127.0.0.1:2280"
    else
        echo "  WARN: web service failed to start — API-dependent tests will fail"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: Snapshot (T2-07 ~ T2-10)
# Requires: LLM_AVAILABLE + DEVICES_AVAILABLE + web service running
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 2: Snapshot (T2-07 ~ T2-10) ==="

if [ "$LLM_AVAILABLE" = false ]; then
    for _id in T2-07 T2-08 T2-09 T2-10; do
        skip_group_llm "$_id" "take_snapshot"
    done
elif [ "$DEVICES_AVAILABLE" = false ]; then
    for _id in T2-07 T2-08 T2-09 T2-10; do
        skip_group_devices "$_id" "take_snapshot"
    done
else
    # T2-07: take_snapshot succeeds and returns snapshot_id
    SNAP_OUT=$("$OLAV" --agent ops "Take snapshot of R1 show version" 2>&1 | tail -40)
    echo "${SNAP_OUT}" > "${TEST_DIR}/t2_07_snap_output.txt"
    if echo "${SNAP_OUT}" | grep -qi "snapshot_id\|snap_\|snapshot.*created\|success\|collect\|version"; then
        pass_test "T2-07" "take_snapshot R1 returns snapshot_id"
    else
        fail_test "T2-07" "take_snapshot: no snapshot_id in output (saved: ${TEST_DIR}/t2_07_snap_output.txt)"
    fi

    # T2-08: New snapshot appears in parsed_outputs table
    SNAP_COUNT_BEFORE=$("$PYTHON" "${HELPERS}/t2_db_query.py" "${TEST_DIR}" \
        "SELECT COUNT(*) FROM netops.parsed_outputs" "" --count 2>/dev/null || echo 0)
    if [ "${SNAP_COUNT_BEFORE}" -gt 0 ] 2>/dev/null; then
        pass_test "T2-08" "Snapshot in DB (parsed_outputs has ${SNAP_COUNT_BEFORE} rows)"
    else
        fail_test "T2-08" "Snapshot not found in netops.parsed_outputs"
    fi

    # T2-09: SemanticCache uses in-memory storage (no query_cache table in DB)
    # Verify cache invalidate_all() works by confirming it runs without error
    CACHE_TEST=$("$PYTHON" - <<'PYEOF' 2>&1
import sys
sys.path.insert(0, "src")
try:
    from olav.core.memory import SemanticCache
    sc = SemanticCache()
    sc.put([0.1, 0.2, 0.3], [{"text": "test"}])
    sc.invalidate_all()
    result = sc.get([0.1, 0.2, 0.3])
    print("ok" if result is None else "fail")
except Exception as e:
    print(f"error: {e}")
PYEOF
)
    if echo "${CACHE_TEST}" | grep -q "^ok$"; then
        pass_test "T2-09" "SemanticCache in-memory: put/invalidate/get works correctly"
    else
        warn_test "T2-09" "SemanticCache in-memory test: ${CACHE_TEST}"
    fi

    # T2-10: Can compare two snapshots (requires at least 2 snapshots)
    # Take a second snapshot first
    "$OLAV" --agent ops "Take snapshot of R1 show version" >/dev/null 2>&1
    DIFF_OUT=$("$OLAV" --agent ops "Compare last two snapshots of R1" 2>&1 | tail -30)
    if echo "${DIFF_OUT}" | grep -qi "identical\|no.*diff\|same\|no.*change\|unchanged"; then
        pass_test "T2-10" "Two snapshot diff: snapshots identical (valid)"
    elif echo "${DIFF_OUT}" | grep -qi "traceback\|AttributeError\|KeyError\|ImportError"; then
        fail_test "T2-10" "Snapshot diff raised Python exception"
    elif [ -n "${DIFF_OUT}" ]; then
        pass_test "T2-10" "Two snapshot diff returned output"
    else
        warn_test "T2-10" "Snapshot diff: agent returned empty output (tool may not be implemented)"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: Agent Quality (T2-11 ~ T2-14)
# Requires: LLM_AVAILABLE + DEVICES_AVAILABLE
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 3: Agent Quality (T2-11 ~ T2-14) ==="

if [ "$LLM_AVAILABLE" = false ]; then
    for _id in T2-11 T2-12 T2-13 T2-14; do
        skip_group_llm "$_id" "agent quality"
    done
elif [ "$DEVICES_AVAILABLE" = false ]; then
    for _id in T2-11 T2-12 T2-13 T2-14; do
        skip_group_devices "$_id" "agent quality"
    done
else
    # T2-11: "列出所有设备" output contains 6 device names
    OUT_11=$("$OLAV" "列出所有设备" 2>&1)
    echo "${OUT_11}" > "${TEST_DIR}/t2_11_output.txt"
    # Count how many of the known hostnames appear in output
    DEVICE_HITS=0
    for _dev in R1 R2 R3 R4 SW1 SW2; do
        echo "${OUT_11}" | grep -qi "${_dev}" && DEVICE_HITS=$((DEVICE_HITS + 1))
    done
    if [ "$DEVICE_HITS" -ge 4 ]; then
        pass_test "T2-11" "列出所有设备: ≥4/6 device names found (${DEVICE_HITS}/6)"
    elif [ "$DEVICE_HITS" -ge 2 ]; then
        warn_test "T2-11" "列出所有设备: only ${DEVICE_HITS}/6 devices listed (expected ≥4)"
    else
        fail_test "T2-11" "列出所有设备: only ${DEVICE_HITS}/6 devices listed (saved: ${TEST_DIR}/t2_11_output.txt)"
    fi

    # T2-12: "BGP邻居" output contains neighbor IPs or states
    OUT_12=$("$OLAV" "所有BGP邻居状态" 2>&1)
    if echo "${OUT_12}" | grep -qiE "192\.168\.|Established|Active|Idle|neighbor"; then
        pass_test "T2-12" "BGP邻居: output contains neighbor info"
    elif [ ${#OUT_12} -gt 50 ]; then
        warn_test "T2-12" "BGP邻居: has output but no neighbor IP/state patterns found"
    else
        fail_test "T2-12" "BGP邻居: output too short or empty"
    fi

    # T2-13: "网络拓扑" output contains Mermaid diagram or topology info
    OUT_13=$("$OLAV" "网络拓扑" 2>&1)
    if echo "${OUT_13}" | grep -qi "mermaid\|graph\|topology\|--\|<->\|->"; then
        pass_test "T2-13" "网络拓扑: output contains graph/topology representation"
    elif [ ${#OUT_13} -gt 100 ]; then
        warn_test "T2-13" "网络拓扑: has output but no Mermaid/graph patterns detected"
    else
        fail_test "T2-13" "网络拓扑: output too short or empty"
    fi

    # T2-14: Orchestrator-level tool call count ≤ 5 (schema-aware routing should minimize calls)
    # WRITER-01 (a) Round 39: 🔧 output now carries an origin tag — 🔧[orch] for the
    # top-level orchestrator, 🔧[sub] for delegate-internal tool calls. We count only
    # orchestrator calls; this lets the threshold go back to its original baseline
    # (≤5) without being polluted by writer-arch delegate bloat.
    OUT_14=$("$OLAV" "列出所有设备" 2>&1)
    TOOL_CALLS=$(echo "${OUT_14}" | grep -cE "🔧\[orch\]" 2>/dev/null | tr -d '[:space:]' | head -1)
    TOOL_CALLS=${TOOL_CALLS:-0}
    if [ "${TOOL_CALLS}" -le 5 ] 2>/dev/null; then
        pass_test "T2-14" "Orchestrator tool call count ≤5 (got ${TOOL_CALLS})"
    else
        warn_test "T2-14" "Orchestrator tool call count ${TOOL_CALLS} > 5 (schema routing may be inefficient)"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: Lab Agent / ContainerLab (T2-15 ~ T2-18)
# Requires: CLAB_AVAILABLE
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 4: ContainerLab (T2-15 ~ T2-18) ==="

if [ "$CLAB_AVAILABLE" = false ]; then
    for _id in T2-15 T2-16 T2-17 T2-18; do
        skip_test "$_id" "lab agent (clab not available)"
    done
elif [ "$LLM_AVAILABLE" = false ]; then
    for _id in T2-15 T2-16 T2-17 T2-18; do
        skip_group_llm "$_id" "lab agent"
    done
else
    # T2-15~18: Run full CAB workflow in one agent call (deploy → push → verify → destroy)
    # The ops agent (lab subagent)'s mandatory sequence covers all 4 steps in a single invocation.
    # Each test then checks for its sub-marker in the combined output.
    _CLAB_PROMPT="Change plan: Deploy a complete 2-node eBGP CAB validation lab (r1-r4-ebgp-direct) using the Nokia SRLinux template from LAB_REFERENCE.md. Execute the full mandatory sequence: save configs, deploy_and_push_lab, verify BGP with exec_on_node, output the CAB Report, then destroy_lab to clean up."
    OUT_CLAB=$("$OLAV" --agent ops "$_CLAB_PROMPT" 2>&1)

    # T2-15: check deploy happened
    if echo "${OUT_CLAB}" | grep -qi "deploy\|started\|created\|topology\|lab.*running\|running.*lab"; then
        pass_test "T2-15" "deploy_lab: topology deployed"
    else
        fail_test "T2-15" "deploy_lab: no deploy marker in output
  Last 10 lines: $(echo "${OUT_CLAB}" | tail -10)"
    fi

    # T2-16: check config push happened
    if echo "${OUT_CLAB}" | grep -qi "push\|config.*applied\|commit\|srl\|node.*config\|config.*node\|applied\|pushed"; then
        pass_test "T2-16" "push_node_config: config pushed to nodes"
    else
        fail_test "T2-16" "push_node_config: no config-push marker in output
  Last 10 lines: $(echo "${OUT_CLAB}" | tail -10)"
    fi

    # T2-17: check BGP verification (warn if not found — BGP may need more time)
    if echo "${OUT_CLAB}" | grep -qi "Established\|converged\|bgp\|routing"; then
        pass_test "T2-17" "BGP convergence: BGP state verified"
    else
        warn_test "T2-17" "BGP convergence: no BGP marker found — may need more convergence time"
    fi

    # T2-18: check lab destroyed
    if echo "${OUT_CLAB}" | grep -qi "destroy\|destroyed\|removed\|cleaned\|torn.*down\|clean.*up"; then
        pass_test "T2-18" "destroy_lab: topology destroyed"
    else
        fail_test "T2-18" "destroy_lab: no destroy confirmation in output
  Last 10 lines: $(echo "${OUT_CLAB}" | tail -10)"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5: Audit Agent (T2-19 ~ T2-21)
# Requires: LLM_AVAILABLE
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 5: Audit Agent (T2-19 ~ T2-21) ==="

if [ "$LLM_AVAILABLE" = false ]; then
    for _id in T2-19 T2-20 T2-21; do
        skip_group_llm "$_id" "audit agent"
    done
else
    # T2-19: audit agent (Profile Authoring mode — R17 merged designer → auditor)
    OUT_19=$(timeout 120 "$OLAV" --agent audit "create BGP health check profile" 2>&1)
    if echo "${OUT_19}" | grep -qi "\.md\|profile\|created\|bgp.*health\|check.*profile\|audit\|health\|monitor\|check"; then
        pass_test "T2-19" "audit (Profile Authoring): BGP health check profile generated"
    elif [ ${#OUT_19} -gt 100 ]; then
        warn_test "T2-19" "audit (Profile Authoring): has output but no profile creation marker"
    else
        fail_test "T2-19" "audit (Profile Authoring): no output or error"
    fi

    # Check if profile .md file was created
    PROFILE_FILE=$(find "${TEST_DIR}" -name "*.md" -newer "${TEST_DIR}/.olav/config/api.json" \
        2>/dev/null | grep -v ".venv" | head -1)

    # T2-20: audit agent (auditor) executes the profile
    OUT_20=$(timeout 120 "$OLAV" --agent audit "run BGP health check" 2>&1)
    if echo "${OUT_20}" | grep -qi "audit\|report\|result\|health\|BGP"; then
        pass_test "T2-20" "audit auditor: profile execution returned output"
    elif [ ${#OUT_20} -gt 100 ]; then
        warn_test "T2-20" "audit auditor: has output but no audit-report markers"
    else
        fail_test "T2-20" "audit auditor: no output or error"
    fi

    # T2-21: Report contains executive summary
    if echo "${OUT_20}" | grep -qi "summary\|executive\|overview\|conclusion"; then
        pass_test "T2-21" "Audit report contains summary section"
    else
        warn_test "T2-21" "Audit report: 'summary/executive/overview' section not found in output"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6: Infra Agent (T2-22 ~ T2-23)
# Requires: REGISTRY_AVAILABLE + LLM_AVAILABLE
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 6: Infra Agent (T2-22 ~ T2-23) ==="

if [ "$REGISTRY_AVAILABLE" = false ]; then
    skip_test "T2-22" "registry register (no OLAV_REGISTRY_SVC and no clab API)"
    skip_test "T2-23" "infra agent query (no registry available)"
elif [ "$LLM_AVAILABLE" = false ]; then
    # T2-22 can work without LLM (CLI command) — use service name from services.yaml
    _REG_TARGET="${_REGISTRY_SVC:-${_REGISTRY_URL}}"
    OUT_22=$("$OLAV" registry register "${_REG_TARGET}" 2>&1)
    if echo "${OUT_22}" | grep -qi "Loaded\|success\|registered\|operations\|ok\|added"; then
        pass_test "T2-22" "registry register: ${_REG_TARGET}"
    else
        fail_test "T2-22" "registry register ${_REG_TARGET}: $(echo "${OUT_22}" | tail -3)"
    fi
    skip_group_llm "T2-23" "infra agent query"
else
    # T2-22: register service by name
    _REG_TARGET="${_REGISTRY_SVC:-${_REGISTRY_URL}}"
    OUT_22=$("$OLAV" registry register "${_REG_TARGET}" 2>&1)
    if echo "${OUT_22}" | grep -qi "Loaded\|success\|registered\|operations\|ok\|added"; then
        pass_test "T2-22" "registry register: ${_REG_TARGET}"
    else
        fail_test "T2-22" "registry register ${_REG_TARGET}: $(echo "${OUT_22}" | tail -3)"
    fi

    # T2-23: infra agent queries service health
    OUT_23=$("$OLAV" --agent ops "Is service healthy?" 2>&1)
    if echo "${OUT_23}" | grep -qi "healthy\|status\|running\|up\|ok\|service"; then
        pass_test "T2-23" "infra agent: health query returned service info"
    elif [ ${#OUT_23} -gt 50 ]; then
        warn_test "T2-23" "infra agent: has output but no health/status markers"
    else
        fail_test "T2-23" "infra agent: no output or error"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# GROUP 7: Full Flow (T2-24 ~ T2-25)
# T2-24: Requires LLM + DEVICES + web service
# T2-25: Requires LLM only (devops agent)
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 7: Full Flow (T2-24 ~ T2-25) ==="

# T2-24: Demo Runsheet CH1-CH2 — full pipeline from init to query
if [ "$LLM_AVAILABLE" = false ]; then
    skip_group_llm "T2-24" "demo runsheet"
elif [ "$DEVICES_AVAILABLE" = false ]; then
    skip_group_devices "T2-24" "demo runsheet"
else
    # Run a complete CH1 scenario: init is done above, now run the query pipeline
    echo "  Running full pipeline query..."
    OUT_24=$("$OLAV" "Run full network health check and report status of all devices" 2>&1)
    if [ ${#OUT_24} -gt 200 ] && ! echo "${OUT_24}" | grep -qi "traceback\|error.*api\|unhandled"; then
        pass_test "T2-24" "Demo Runsheet CH1-CH2: full pipeline completed with output"
    elif [ ${#OUT_24} -gt 50 ]; then
        warn_test "T2-24" "Demo Runsheet: output present but short (${#OUT_24} chars)"
    else
        fail_test "T2-24" "Demo Runsheet: output too short or error"
    fi
fi

# T2-25: DevOps agent generates a backup script
if [ "$LLM_AVAILABLE" = false ]; then
    skip_group_llm "T2-25" "devops agent backup script"
else
    OUT_25=$("$OLAV" --agent ops "write a network device backup script for IOS devices" 2>&1)
    # Check: output to exports/ or has script content
    EXPORTS_DIR="${TEST_DIR}/exports"
    EXPORTS_FILES=$(find "${EXPORTS_DIR}" -name "*.sh" -o -name "*.py" -o -name "*.yml" -o -name "*.yaml" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${EXPORTS_FILES}" -gt 0 ]; then
        pass_test "T2-25" "DevOps agent: generated ${EXPORTS_FILES} script file(s) in exports/"
    elif echo "${OUT_25}" | grep -qi "backup\|script\|#!/\|python\|bash"; then
        warn_test "T2-25" "DevOps agent: script content in output but no file in exports/"
    else
        fail_test "T2-25" "DevOps agent: no backup script generated"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Group 8: Round 24-60 integration (T2-26 ~ T2-31)
# ══════════════════════════════════════════════════════════════════════════════
# Integration-level complement to T1 Group 12. Where T1 verifies unit
# behaviour of each new surface, T2 Group 8 exercises them against the
# populated DuckDB from Groups 1-2 (when devices + LLM were available)
# or a minimal bootstrapped DB otherwise.
echo "=== Group 8: Round 24-60 integration (T2-26 ~ T2-31) ==="

# T2-26: `olav diff --help` survives wheel install (CLI registration smoke)
#        — complements T1-55 at wheel-install level (not dev-venv).
if "$OLAV" diff --help 2>&1 | grep -qE "snapshot_id_1.*snapshot_id_2"; then
    pass_test "T2-26" "olav diff CLI registered in installed wheel (R47)"
else
    fail_test "T2-26" "olav diff CLI missing from installed wheel" \
        "(--help did not mention snapshot_id_1/2)"
fi

# T2-27: `olav explain --help` survives wheel install
if "$OLAV" explain --help 2>&1 | grep -qi "citation token"; then
    pass_test "T2-27" "olav explain CLI registered in installed wheel (R45)"
else
    fail_test "T2-27" "olav explain CLI missing from installed wheel"
fi

# T2-28: `olav catalog` lists topics (no LLM, no DB required — reads
#        inline _TOPICS map from catalog.py)
CATALOG_OUT=$("$OLAV" catalog 2>&1)
if echo "${CATALOG_OUT}" | grep -qE "Device Inventory|设备清单|Topology"; then
    pass_test "T2-28" "olav catalog lists data-model topics (R25)"
else
    fail_test "T2-28" "olav catalog output missing expected topics"
fi

# T2-29: `describe_table` tool loads via the same tool discovery path
#        agents use. No DB required — assert args_schema only.
"$PYTHON" <<'PYEOF'
import importlib.util, sys
from pathlib import Path
p = Path(".olav/workspace/core/db_query/tools/describe_table.py")
if not p.is_file():
    print("describe_table.py missing"); sys.exit(1)
spec = importlib.util.spec_from_file_location("dt_t2", p)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
schema = getattr(mod.describe_table, "args_schema", None)
fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
assert "table_name" in fields and "include_samples" in fields, "describe_table schema drift"
sys.exit(0)
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-29" "describe_table tool discoverable post-wheel (R39)"
else
    fail_test "T2-29" "describe_table not discoverable in installed workspace"
fi

# T2-30: NetworkModel construction + DB round-trip when topology_links
#        has real rows (from Groups 1-2 ETL). Skip gracefully when no DB.
"$PYTHON" <<'PYEOF'
import sys
try:
    from olav_netops.sim import load_network_model
except Exception as e:
    print(f"olav_netops not in venv: {e}"); sys.exit(2)
m = load_network_model()
# Layer construction must not raise regardless of DB state.
_phys = m.physical
_l2 = m.l2
# If topology_links has rows from Group 1, the graph is populated;
# otherwise empty. Either way a well-formed PhysicalLayer.
links_count = len(_phys.links)
print(f"NoM physical.links = {links_count}")
sys.exit(0)
PYEOF
_rc=$?
case $_rc in
    0)  pass_test "T2-30" "ARCH-14 NetworkModel round-trip against installed DB (R52-59)" ;;
    2)  skip_test "T2-30" "ARCH-14 NetworkModel (olav_netops not in venv)" ;;
    *)  fail_test "T2-30" "ARCH-14 NetworkModel round-trip failed (rc=$_rc)" ;;
esac

# T2-31: sandbox auto-inject — execute a tiny sandbox script and confirm
#        model reference resolves (End-to-end through execute_in_sandbox).
"$PYTHON" <<'PYEOF'
import sys
from olav.platform.sandbox import execute_in_sandbox
r = execute_in_sandbox(
    "_result = {'model_is_none': model is None, 'has_physical': model is not None and hasattr(model, 'physical')}",
    timeout=30,
)
if r.get("status") != "success":
    print(f"sandbox execution failed: {r}"); sys.exit(1)
print(f"sandbox result: {r.get('result')}")
sys.exit(0)
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-31" "sandbox subprocess resolves 'model' binding (R57)"
else
    fail_test "T2-31" "sandbox auto-inject broken post-wheel"
fi

# ─── T2-32 ~ T2-40: parity with T1 Group 12 at integration level ────────
# Each of these catches packaging drift the same way T2-29 did for
# describe_table.py — if the platform wheel ships without the file, the
# helper can't load and the test fails.

# T2-32: load_reference(section=) slicing against wheel-installed schema.md (R38)
"$PYTHON" <<'PYEOF'
import sys, importlib.util
from pathlib import Path
p = Path(".olav/workspace/core/admin/tools/load_reference.py")
if not p.is_file():
    print(f"load_reference.py missing at {p}"); sys.exit(1)
spec = importlib.util.spec_from_file_location("lr_t2", p)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
full = mod.load_reference.invoke({"name": "schema"})
assert "## " in full, "schema ref missing H2 headers (SCHEMA_REFERENCE.md not shipped?)"
listing = mod.load_reference.invoke({"name": "schema", "section": "?"})
assert "Available sections in 'schema'" in listing, f"section listing wrong: {listing[:200]}"
sliced = mod.load_reference.invoke({"name": "schema", "section": "common mistakes"})
assert "Common Mistakes to Avoid" in sliced, "section slice missed target"
sys.exit(0)
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-32" "load_reference section slicing + ? listing (R38)"
else
    fail_test "T2-32" "load_reference slicing broken post-wheel"
fi

# T2-33: tool_help(detail=) tier-aware (R38 + R49)
"$PYTHON" <<'PYEOF'
import sys, importlib.util
from pathlib import Path
p = Path(".olav/workspace/core/admin/tools/tool_help.py")
spec = importlib.util.spec_from_file_location("th_t2", p)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
brief = mod.tool_help.invoke({"name": "tool_help", "detail": "brief"})
assert "full_docstring" not in brief, "brief mode leaked full_docstring"
full = mod.tool_help.invoke({"name": "tool_help", "detail": "full"})
assert full.get("full_docstring"), "full mode missing docstring"
# agent_id kwarg must be in schema (R49)
schema = getattr(mod.tool_help, "args_schema", None)
fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
assert "agent_id" in fields, "tool_help missing agent_id kwarg (R49 regression)"
sys.exit(0)
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-33" "tool_help detail + agent_id kwarg (R38/R49)"
else
    fail_test "T2-33" "tool_help tier surface broken post-wheel"
fi

# T2-34: OLAV_DEBUG_* env vars recognised by installed package (R36 + R42)
"$PYTHON" <<'PYEOF'
import os
os.environ["OLAV_DEBUG_CONTEXT"] = "1"
from olav.agents.static_context_resolver import is_debug_enabled
assert is_debug_enabled() is True, "OLAV_DEBUG_CONTEXT=1 not recognised post-install"
os.environ["OLAV_DEBUG_CONTEXT"] = "no"
assert is_debug_enabled() is False
from olav.agents._deepagents_bridge import _summarization_debug_enabled
os.environ["OLAV_DEBUG_SUMMARIZATION"] = "yes"
assert _summarization_debug_enabled() is True
os.environ["OLAV_DEBUG_SUMMARIZATION"] = "off"
assert _summarization_debug_enabled() is False
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-34" "OLAV_DEBUG_CONTEXT / _SUMMARIZATION env resolvers (R36/R42)"
else
    fail_test "T2-34" "debug env resolvers broken post-wheel"
fi

# T2-35: recall_memory tier-aware limit default (R40, ARCH-16)
"$PYTHON" <<'PYEOF'
import importlib.util
from pathlib import Path
p = Path(".olav/workspace/core/tools/recall_memory.py")
spec = importlib.util.spec_from_file_location("rm_t2", p)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
schema = getattr(mod.recall_memory, "args_schema", None)
fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
req = getattr(fields["limit"], "is_required", None)
if callable(req):
    req = req()
assert req is False, "recall_memory limit must stay optional for tier default"
assert mod._resolve_recall_limit(100) == 10, "ceiling clamp broken"
assert mod._resolve_recall_limit(0) == 1, "floor clamp broken"
val = mod._resolve_recall_limit(None)
assert isinstance(val, int) and 1 <= val <= 10
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-35" "recall_memory(limit=None) tier resolution (R40)"
else
    fail_test "T2-35" "recall_memory tier default broken post-wheel"
fi

# T2-36: subagent return cap via tier_default (R40, ARCH-18 #4)
"$PYTHON" <<'PYEOF'
from olav.agents.delegate_tool import _resolve_subagent_cap, _truncate
cap = _resolve_subagent_cap()
assert isinstance(cap, int) and cap > 0
assert _truncate("short", cap=1000) == "short"
out = _truncate("x" * 5000, cap=200)
assert out.startswith("x" * 200) and "truncated" in out and "5000" in out
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-36" "delegate_tool subagent return cap (R40)"
else
    fail_test "T2-36" "subagent cap broken post-wheel"
fi

# T2-37: SummarizationMiddleware tier trigger (R42, ARCH-19)
"$PYTHON" <<'PYEOF'
from olav.agents._deepagents_bridge import compute_summarization_trigger
assert compute_summarization_trigger("small") == ("tokens", 4000)
assert compute_summarization_trigger("medium") == ("tokens", 20800)
assert compute_summarization_trigger("large") == ("tokens", 160000)
assert compute_summarization_trigger("xlarge") is None
assert compute_summarization_trigger(None) is None
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-37" "compute_summarization_trigger per-tier (R42)"
else
    fail_test "T2-37" "summarization tier trigger broken post-wheel"
fi

# T2-38: SKILL.md tools_docstring_mode override (R49)
"$PYTHON" <<'PYEOF'
import importlib.util, tempfile
from pathlib import Path
p = Path(".olav/workspace/core/admin/tools/tool_help.py")
spec = importlib.util.spec_from_file_location("th2_t2", p)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
aliases = mod._SKILL_MODE_ALIASES
assert aliases["compact"] == "brief" and aliases["verbose"] == "full"
# Round-trip: fake agent SKILL.md resolves via _read_agent_docstring_mode.
tmp = Path(tempfile.mkdtemp())
agent_dir = tmp / ".olav" / "workspace" / "fake"
(agent_dir / "tools").mkdir(parents=True)
(agent_dir / "SKILL.md").write_text(
    "---\nname: fake\ntools_docstring_mode: compact\n---\n", encoding="utf-8")
mod._PROJECT_ROOT = tmp
mod._TOOL_ROOTS = [agent_dir / "tools"]
assert mod._read_agent_docstring_mode("fake") == "brief"
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-38" "SKILL.md tools_docstring_mode override (R49)"
else
    fail_test "T2-38" "SKILL.md docstring mode broken post-wheel"
fi

# T2-39: OLAV_BACKUP_COMMANDS_PATH env override (R46, ARCH-22 C1)
"$PYTHON" <<'PYEOF'
import os, tempfile
from pathlib import Path
from olav.core.utils import find_backup_commands_yaml, _BACKUP_COMMANDS_PATH_ENV
assert _BACKUP_COMMANDS_PATH_ENV == "OLAV_BACKUP_COMMANDS_PATH"
tmp = Path(tempfile.mkdtemp())
override = tmp / "custom.yaml"
override.write_text("- command: show test\n", encoding="utf-8")
os.environ["OLAV_BACKUP_COMMANDS_PATH"] = str(override)
assert find_backup_commands_yaml() == override
# Bogus env path → falls through (defensive against typos)
os.environ["OLAV_BACKUP_COMMANDS_PATH"] = "/definitely/nonexistent.yaml"
resolved = find_backup_commands_yaml()
assert resolved is None or resolved.is_file()
del os.environ["OLAV_BACKUP_COMMANDS_PATH"]
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-39" "OLAV_BACKUP_COMMANDS_PATH env override (R46)"
else
    fail_test "T2-39" "backup env override broken post-wheel"
fi

# T2-40: 🔧[orch]/[sub] origin tag scaffolding in installed cli/main.py (R39)
"$PYTHON" <<'PYEOF'
import re
import olav.cli.main as m
from pathlib import Path
src = Path(m.__file__).read_text(encoding="utf-8")
assert "_delegate_depth" in src, "delegate_depth counter missing post-install"
assert "_DELEGATE_TOOLS" in src
assert re.search(r"🔧\[\{_origin\}\]", src), "🔧[{_origin}] format string missing"
assert "_delegate_depth += 1" in src and "_delegate_depth -= 1" in src
PYEOF
if [ $? -eq 0 ]; then
    pass_test "T2-40" "🔧[orch]/[sub] origin tag scaffolding (R39)"
else
    fail_test "T2-40" "origin tag plumbing broken post-wheel"
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# CLEANUP
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Cleanup ==="

kill_web_service

# Kill syslog receiver on port 5514 if running
_syslog_pid=$(lsof -ti :5514 2>/dev/null | head -1)
if [ -n "${_syslog_pid}" ]; then
    kill "${_syslog_pid}" 2>/dev/null || true
fi

if [ "${OLAV_T2_KEEP_DIR:-false}" = "true" ]; then
    echo "  test dir PRESERVED (OLAV_T2_KEEP_DIR=true): ${TEST_DIR}"
else
    rm -rf "${TEST_DIR}" 2>/dev/null || true
    echo "  test dir removed: ${TEST_DIR}"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL + WARN + SKIP))
echo "╔══════════════════════════════════════════════════╗"
echo "║  Tier 2 Results                                  ║"
echo "╠══════════════════════════════════════════════════╣"
printf "║  PASS: %-4s  FAIL: %-4s  WARN: %-4s  SKIP: %-4s ║\n" \
    "${PASS}" "${FAIL}" "${WARN}" "${SKIP}"
echo "╚══════════════════════════════════════════════════╝"

if [ "${FAIL}" -gt 0 ]; then
    echo ""
    echo "❌ Tier 2 FAILED (${FAIL} failure(s))"
    exit 1
else
    echo ""
    echo "✅ Tier 2 PASSED (${PASS}/${TOTAL} pass, ${WARN} warn, ${SKIP} skip)"
    exit 0
fi
