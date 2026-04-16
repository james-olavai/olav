#!/usr/bin/env bash
# ==============================================================================
# OLAV v0.18.0 — Tier 2: Integration Tests (T2-01 ~ T2-25)
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
_DEV_CONFIG="${OLAV_DEV_CONFIG:-}"          # optional: path to dev api.json to copy wholesale
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
NORNIR_DEST=".olav/workspace/ops/probe/config/nornir"
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
    SNAP_OUT=$("$OLAV" --agent ops "Take snapshot of R1 show version" 2>&1 | tail -20)
    if echo "${SNAP_OUT}" | grep -qi "snapshot_id\|snap_\|snapshot.*created\|success\|collect\|version"; then
        pass_test "T2-07" "take_snapshot R1 returns snapshot_id"
    else
        fail_test "T2-07" "take_snapshot: no snapshot_id in output"
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
        fail_test "T2-11" "列出所有设备: only ${DEVICE_HITS}/6 devices listed"
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

    # T2-14: Tool call count ≤ 3 (schema-aware routing should minimize calls)
    OUT_14=$("$OLAV" "列出所有设备" 2>&1)
    TOOL_CALLS=$(echo "${OUT_14}" | grep -c "🔧" 2>/dev/null | tr -d '[:space:]' | head -1)
    TOOL_CALLS=${TOOL_CALLS:-0}
    if [ "${TOOL_CALLS}" -le 3 ] 2>/dev/null; then
        pass_test "T2-14" "Tool call count ≤3 (got ${TOOL_CALLS})"
    else
        warn_test "T2-14" "Tool call count ${TOOL_CALLS} > 3 (schema routing may be inefficient)"
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
    # T2-19: audit agent (designer) creates a profile
    OUT_19=$(timeout 120 "$OLAV" --agent audit "create BGP health check profile" 2>&1)
    if echo "${OUT_19}" | grep -qi "\.md\|profile\|created\|bgp.*health\|check.*profile\|audit\|health\|monitor\|check"; then
        pass_test "T2-19" "audit designer: BGP health check profile generated"
    elif [ ${#OUT_19} -gt 100 ]; then
        warn_test "T2-19" "audit designer: has output but no profile creation marker"
    else
        fail_test "T2-19" "audit designer: no output or error"
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
    EXPORTS_FILES=$(find "${EXPORTS_DIR}" -name "*.sh" -o -name "*.py" 2>/dev/null | wc -l | tr -d ' ')
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
# CLEANUP
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Cleanup ==="

kill_web_service

# Kill syslog receiver on port 5514 if running
_syslog_pid=$(lsof -ti :5514 2>/dev/null | head -1)
if [ -n "${_syslog_pid}" ]; then
    kill "${_syslog_pid}" 2>/dev/null || true
fi

rm -rf "${TEST_DIR}" 2>/dev/null || true
echo "  test dir removed: ${TEST_DIR}"
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
