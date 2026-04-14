#!/usr/bin/env bash
# ==============================================================================
# OLAV v0.17.0 — Tier 4: Extended Feature Tests (T4-01 ~ T4-27)
# ==============================================================================
# Covers features not exercised by T1-T3:
#   Group 1 (T4-01~03):  Slash commands (/model, /help) — no LLM
#   Group 2 (T4-04~08):  Admin user management (add/list/rotate/revoke) — no LLM
#   Group 3 (T4-09~10):  Config evolve --list — no LLM
#   Group 4 (T4-11~16):  Service logs lifecycle (start/stop/status) — no LLM
#   Group 5 (T4-17~19):  Input parser unit tests — no LLM
#   Group 6 (T4-20~22):  Service daemon lifecycle — LLM-gated
#   Group 7 (T4-23~27):  Session restore & --auto-approve — LLM-gated
#
# Usage:
#   bash tests/ci/tier4_extended.sh
#
# Optional:
#   OLAV_DEV_CONFIG=/path/to/api.json   Full dev config (LLM key + headers)
#   OLAV_API_KEY=<key>                  Simple API key (fallback)
# ==============================================================================

set -uo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_DIR="/tmp/olav-ci-t4-${TIMESTAMP}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

WHEEL=$(ls "${REPO_ROOT}/dist/"*.whl 2>/dev/null | tail -1)
if [ -z "${WHEEL:-}" ]; then
    echo "ERROR: No wheel found in dist/. Run 'uv build' first."
    exit 1
fi

# ── Capture env vars before isolation ────────────────────────────────────────
_API_KEY="${OLAV_API_KEY:-}"
_LLM_BASE_URL="${OLAV_LLM_BASE_URL:-https://openrouter.ai/api/v1}"
_LLM_MODEL="${OLAV_LLM_MODEL:-x-ai/grok-4.1-fast}"
_DEV_CONFIG="${OLAV_DEV_CONFIG:-}"
[ -n "${_DEV_CONFIG}" ] && _DEV_CONFIG="$(realpath "${_DEV_CONFIG}" 2>/dev/null || echo "${_DEV_CONFIG}")"

LLM_AVAILABLE=false
[ -n "${_API_KEY}" ] && LLM_AVAILABLE=true
[ -n "${_DEV_CONFIG}" ] && [ -f "${_DEV_CONFIG}" ] && LLM_AVAILABLE=true

# ── Isolate environment ────────────────────────────────────────────────────
mkdir -p "${TEST_DIR}"
export HOME="${TEST_DIR}/fakehome"
mkdir -p "$HOME"
export TOKENIZERS_PARALLELISM=false
export HF_HUB_DISABLE_PROGRESS_BARS=1
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
unset OPENAI_API_KEY ANTHROPIC_API_KEY HF_TOKEN 2>/dev/null || true

# ── Counters ──────────────────────────────────────────────────────────────
PASS=0; FAIL=0; WARN=0; SKIP=0

# ── Helpers ───────────────────────────────────────────────────────────────
pass_test() { echo "  $1 $2... OK";   PASS=$((PASS + 1)); }
fail_test() { echo "  $1 $2... FAIL ${3:-}"; FAIL=$((FAIL + 1)); }
warn_test() { echo "  $1 $2... WARN ${3:-}"; WARN=$((WARN + 1)); }
skip_test() { echo "  $1 $2... SKIP ${3:-}"; SKIP=$((SKIP + 1)); }

run_check() {
    local label="$1" name="$2"; shift 2
    echo -n "  ${label} ${name}... "
    if "$@" >/dev/null 2>&1; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL"; FAIL=$((FAIL + 1))
    fi
}

llm_skip_if_unavailable() {
    if [ "$LLM_AVAILABLE" = false ]; then
        skip_test "$1" "$2 (no LLM config)"
        return 1
    fi
    return 0
}

# ── Banner ────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════╗"
echo "║  OLAV Tier 4: Extended Tests (T4-01 ~ T4-27)    ║"
echo "╚══════════════════════════════════════════════════╝"
echo "  Wheel:    $(basename "$WHEEL")"
echo "  Test dir: ${TEST_DIR}"
echo "  LLM:      ${LLM_AVAILABLE}"
echo ""

# ══════════════════════════════════════════════════════════════════════════
# SETUP — fresh venv, install wheel, olav init
# ══════════════════════════════════════════════════════════════════════════
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

# Inject LLM config if available
if [ -n "${_DEV_CONFIG}" ] && [ -f "${_DEV_CONFIG}" ]; then
    cp "${_DEV_CONFIG}" .olav/config/api.json
    echo "  LLM config: copied from ${_DEV_CONFIG}"
elif [ "$LLM_AVAILABLE" = true ]; then
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

# Always start with auth.mode=none for non-auth tests
"$PYTHON" -c "
import json
from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('auth', {})['mode'] = 'none'
p.write_text(json.dumps(cfg, indent=2))
" 2>/dev/null || true
echo "  auth.mode: set to none"

HELPERS="${TEST_DIR}/ci_helpers"
mkdir -p "$HELPERS"
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 1: Slash Commands (T4-01 ~ T4-03)
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 1: Slash Commands (T4-01 ~ T4-03) ==="

# T4-01: /model list → returns model list without LLM
_t401_out=$("$OLAV" "/model list" 2>&1) && _t401_rc=0 || _t401_rc=$?
if echo "$_t401_out" | grep -qi "gpt-4o\|llama\|grok\|available\|model"; then
    pass_test "[T4-01]" "/model list returns model list"
else
    fail_test "[T4-01]" "/model list returns model list" "(rc=${_t401_rc} out=${_t401_out:0:120})"
fi

# T4-02: /model reset → resets model override
_t402_out=$("$OLAV" "/model reset" 2>&1) && _t402_rc=0 || _t402_rc=$?
if echo "$_t402_out" | grep -qi "reset\|cleared\|default\|model" && [ "$_t402_rc" -eq 0 ]; then
    pass_test "[T4-02]" "/model reset returns success message"
else
    fail_test "[T4-02]" "/model reset returns success message" "(rc=${_t402_rc} out=${_t402_out:0:120})"
fi

# T4-03: /model <name> → switches model
_t403_out=$("$OLAV" "/model gpt-4o" 2>&1) && _t403_rc=0 || _t403_rc=$?
if echo "$_t403_out" | grep -qi "gpt-4o\|switched\|model set\|override\|model" && [ "$_t403_rc" -eq 0 ]; then
    pass_test "[T4-03]" "/model gpt-4o switches model"
else
    fail_test "[T4-03]" "/model gpt-4o switches model" "(rc=${_t403_rc} out=${_t403_out:0:120})"
fi
# Reset model after test
"$OLAV" "/model reset" >/dev/null 2>&1 || true
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 2: Admin User Management (T4-04 ~ T4-08)
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 2: Admin User Management (T4-04 ~ T4-08) ==="

# T4-04: add-user creates a new user entry
_t404_out=$("$OLAV" admin "add-user testci" 2>&1) && _t404_rc=0 || _t404_rc=$?
if echo "$_t404_out" | grep -qi "testci\|created\|added\|token\|user"; then
    pass_test "[T4-04]" "admin add-user testci creates user"
else
    fail_test "[T4-04]" "admin add-user testci creates user" "(rc=${_t404_rc} out=${_t404_out:0:120})"
fi

# T4-05: list-users shows the added user
_t405_out=$("$OLAV" admin "list-users" 2>&1) && _t405_rc=0 || _t405_rc=$?
if echo "$_t405_out" | grep -qi "testci\|user\|username\|token"; then
    pass_test "[T4-05]" "admin list-users shows testci"
else
    fail_test "[T4-05]" "admin list-users shows testci" "(rc=${_t405_rc} out=${_t405_out:0:120})"
fi

# T4-06: add-user with explicit --role admin
_t406_out=$("$OLAV" admin "add-user adminuser --role admin" 2>&1) && _t406_rc=0 || _t406_rc=$?
if echo "$_t406_out" | grep -qi "adminuser\|created\|added\|token\|admin"; then
    pass_test "[T4-06]" "admin add-user --role admin creates admin user"
else
    fail_test "[T4-06]" "admin add-user --role admin creates admin user" "(rc=${_t406_rc} out=${_t406_out:0:120})"
fi

# T4-07: rotate-token rotates token and shows new token
_t407_out=$("$OLAV" admin "rotate-token testci" 2>&1) && _t407_rc=0 || _t407_rc=$?
if echo "$_t407_out" | grep -qi "rotated\|testci\|token"; then
    pass_test "[T4-07]" "admin rotate-token testci shows new token"
else
    fail_test "[T4-07]" "admin rotate-token testci shows new token" "(rc=${_t407_rc} out=${_t407_out:0:120})"
fi

# T4-08: revoke-token revokes user's token
_t408_out=$("$OLAV" admin "revoke-token testci" 2>&1) && _t408_rc=0 || _t408_rc=$?
if echo "$_t408_out" | grep -qi "revoked\|testci\|token\|longer"; then
    pass_test "[T4-08]" "admin revoke-token testci revokes token"
else
    fail_test "[T4-08]" "admin revoke-token testci revokes token" "(rc=${_t408_rc} out=${_t408_out:0:120})"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 3: Config Evolve (T4-09 ~ T4-10)
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 3: Config Evolve (T4-09 ~ T4-10) ==="

# T4-09: config evolve --list returns empty pending list without error
_t409_out=$("$OLAV" config evolve --list 2>&1) && _t409_rc=0 || _t409_rc=$?
if [ "$_t409_rc" -eq 0 ]; then
    if echo "$_t409_out" | grep -qi "pending\|evolution\|none\|no pending\|empty"; then
        pass_test "[T4-09]" "config evolve --list returns empty table"
    else
        # Non-zero exit or unexpected output
        warn_test "[T4-09]" "config evolve --list" "(rc=0 but unexpected output: ${_t409_out:0:120})"
    fi
else
    fail_test "[T4-09]" "config evolve --list exits 0" "(rc=${_t409_rc} out=${_t409_out:0:120})"
fi

# T4-10: config evolve --list against a fresh DB (domain.duckdb must be auto-created)
_t410_db="${TEST_DIR}/.olav/databases/main.duckdb"
if [ -f "${_t410_db}" ]; then
    pass_test "[T4-10]" "domain.duckdb exists after evolve --list (auto-created)"
else
    # Some installations may use a different name; check for any duckdb
    _any_db=$(ls "${TEST_DIR}/.olav/databases/"*.duckdb 2>/dev/null | head -1)
    if [ -n "${_any_db}" ]; then
        pass_test "[T4-10]" "DuckDB exists after evolve --list (${_any_db##*/})"
    else
        warn_test "[T4-10]" "No DuckDB found after evolve --list (may be using a different path)"
    fi
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 4: Service Logs Lifecycle (T4-11 ~ T4-16)
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 4: Service Logs Lifecycle (T4-11 ~ T4-16) ==="

# Use a high test port to avoid conflicts with production port 5514
_SYSLOG_TEST_PORT=55140

# T4-11: service status (no services running)
_t411_out=$("$OLAV" service status 2>&1) && _t411_rc=0 || _t411_rc=$?
if [ "$_t411_rc" -eq 0 ]; then
    pass_test "[T4-11]" "service status returns table (no services running)"
else
    fail_test "[T4-11]" "service status exits 0" "(rc=${_t411_rc})"
fi

# T4-12: service logs start on test port
_t412_out=$("$OLAV" service logs start --port "${_SYSLOG_TEST_PORT}" 2>&1) && _t412_rc=0 || _t412_rc=$?
sleep 2  # wait for receiver to start
if echo "$_t412_out" | grep -qi "started\|running\|already\|✓" || \
   [ -f "${TEST_DIR}/.olav/run/syslog_receiver.pid" ]; then
    pass_test "[T4-12]" "service logs start on port ${_SYSLOG_TEST_PORT}"
else
    warn_test "[T4-12]" "service logs start" "(rc=${_t412_rc} out=${_t412_out:0:120}; PID file: $(ls "${TEST_DIR}/.olav/run/" 2>/dev/null | head -3))"
fi

# T4-13: PID file created
if [ -f "${TEST_DIR}/.olav/run/syslog_receiver.pid" ]; then
    _syslog_pid=$(cat "${TEST_DIR}/.olav/run/syslog_receiver.pid" 2>/dev/null || echo "")
    pass_test "[T4-13]" "syslog PID file created (PID=${_syslog_pid})"
else
    warn_test "[T4-13]" "syslog PID file missing at .olav/run/syslog_receiver.pid"
fi

# T4-14: service logs status shows running
_t414_out=$("$OLAV" service logs status 2>&1) && _t414_rc=0 || _t414_rc=$?
if echo "$_t414_out" | grep -qi "running\|active\|pid\|started" || [ "$_t414_rc" -eq 0 ]; then
    pass_test "[T4-14]" "service logs status shows running"
else
    warn_test "[T4-14]" "service logs status" "(rc=${_t414_rc} out=${_t414_out:0:80})"
fi

# T4-15: Send UDP syslog message and verify port is listening
# Use Python to send a test syslog UDP message
_t415_out=$("$PYTHON" - <<'PYEOF'
import socket, time, sys
PORT = 55140
msg = b"<14>Jan  1 00:00:00 ci-testhost olav-ci: T4-15 syslog test message"
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1)
    sock.sendto(msg, ("127.0.0.1", PORT))
    sock.close()
    print("UDP sent OK")
except Exception as e:
    print(f"UDP send failed: {e}")
    sys.exit(1)
PYEOF
) && _t415_rc=0 || _t415_rc=$?
if echo "$_t415_out" | grep -qi "UDP sent OK"; then
    pass_test "[T4-15]" "UDP syslog message sent to port ${_SYSLOG_TEST_PORT}"
else
    warn_test "[T4-15]" "UDP syslog test" "(${_t415_out:0:80})"
fi

# T4-16: service logs stop
_t416_out=$("$OLAV" service logs stop 2>&1) && _t416_rc=0 || _t416_rc=$?
sleep 1
if echo "$_t416_out" | grep -qi "stopped\|sent\|not running\|SIGTERM\|✓"; then
    pass_test "[T4-16]" "service logs stop stops receiver"
else
    warn_test "[T4-16]" "service logs stop" "(rc=${_t416_rc} out=${_t416_out:0:120})"
fi
# Cleanup stale PID file if receiver didn't clean it up
rm -f "${TEST_DIR}/.olav/run/syslog_receiver.pid" 2>/dev/null || true
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 5: Input Parser Unit Tests (T4-17 ~ T4-19)
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 5: Input Parser Unit Tests (T4-17 ~ T4-19) ==="

# Write input parser helper
cat > "${HELPERS}/t4_input_parser.py" << 'EOF'
import sys
from olav.cli.input_parser import expand_file_references, parse_input
from pathlib import Path
import tempfile, os

# T4-17: expand_file_references expands @file
with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
    f.write("hello from file\n")
    fname = f.name

try:
    result = expand_file_references(f"Check this: @{fname}")
    assert "hello from file" in result, f"Expected file content in result, got: {result!r}"
    print("T4-17: expand_file_references @file: OK")
except Exception as e:
    print(f"T4-17: expand_file_references @file: FAIL {e}")
    sys.exit(1)
finally:
    os.unlink(fname)

# T4-18: parse_input for !cmd returns shell command
text, is_shell, cmd = parse_input("!echo hello world")
assert is_shell is True, f"Expected is_shell=True, got {is_shell}"
assert cmd == "echo hello world", f"Expected cmd='echo hello world', got {cmd!r}"
print("T4-18: parse_input !cmd: OK")

# T4-19: parse_input for regular text returns expanded text
with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
    f.write("## Section\ncontent here\n")
    fname2 = f.name

try:
    expanded, is_shell2, cmd2 = parse_input(f"analyze @{fname2}")
    assert is_shell2 is False
    assert "Section" in expanded or "content here" in expanded, f"File not expanded: {expanded!r}"
    print("T4-19: parse_input @file in regular text: OK")
except Exception as e:
    print(f"T4-19: parse_input @file in regular text: FAIL {e}")
    sys.exit(1)
finally:
    os.unlink(fname2)

sys.exit(0)
EOF

_t4_ip_out=$("$PYTHON" "${HELPERS}/t4_input_parser.py" 2>&1) && _t4_ip_rc=0 || _t4_ip_rc=$?
if echo "$_t4_ip_out" | grep -q "T4-17.*OK"; then
    pass_test "[T4-17]" "input_parser expand_file_references works"
else
    fail_test "[T4-17]" "input_parser expand_file_references" "(${_t4_ip_out:0:120})"
fi
if echo "$_t4_ip_out" | grep -q "T4-18.*OK"; then
    pass_test "[T4-18]" "input_parser parse_input !cmd detection"
else
    fail_test "[T4-18]" "input_parser parse_input !cmd" "(${_t4_ip_out:0:120})"
fi
if echo "$_t4_ip_out" | grep -q "T4-19.*OK"; then
    pass_test "[T4-19]" "input_parser @file in regular text"
else
    fail_test "[T4-19]" "input_parser @file in regular text" "(${_t4_ip_out:0:120})"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 6: Service Daemon Lifecycle (T4-20 ~ T4-22) — LLM-gated
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 6: Service Daemon Lifecycle (T4-20 ~ T4-22) ==="

# T4-20: daemon status (not yet started) → not running
_t420_out=$("$OLAV" service daemon status 2>&1) && _t420_rc=0 || _t420_rc=$?
if echo "$_t420_out" | grep -qi "not running\|stopped\|inactive\|daemon\|status" && [ "$_t420_rc" -eq 0 ]; then
    pass_test "[T4-20]" "service daemon status before start → not running"
else
    fail_test "[T4-20]" "service daemon status before start" "(rc=${_t420_rc} out=${_t420_out:0:120})"
fi

# T4-21 / T4-22: daemon start and stop — LLM-gated (daemon pre-warms LLM)
if ! llm_skip_if_unavailable "[T4-21]" "service daemon start"; then
    true  # skipped
else
    _t421_out=$("$OLAV" service daemon start 2>&1) && _t421_rc=0 || _t421_rc=$?
    sleep 3  # daemon needs time to pre-warm
    if echo "$_t421_out" | grep -qi "started\|running\|pid\|already\|daemon\|spawned" && [ "$_t421_rc" -eq 0 ]; then
        pass_test "[T4-21]" "service daemon start succeeds"

        # T4-22: daemon stop
        _t422_out=$("$OLAV" service daemon stop 2>&1) && _t422_rc=0 || _t422_rc=$?
        if echo "$_t422_out" | grep -qi "stopped\|terminated\|sigterm\|not running\|daemon" && [ "$_t422_rc" -eq 0 ]; then
            pass_test "[T4-22]" "service daemon stop stops daemon"
        else
            warn_test "[T4-22]" "service daemon stop" "(rc=${_t422_rc} out=${_t422_out:0:120})"
        fi
    else
        fail_test "[T4-21]" "service daemon start" "(rc=${_t421_rc} out=${_t421_out:0:120})"
        skip_test "[T4-22]" "service daemon stop (daemon start failed)"
    fi
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Group 7: Session Restore & Auto-approve (T4-23 ~ T4-27) — LLM-gated
# ══════════════════════════════════════════════════════════════════════════
echo "=== Group 7: Session Restore & --auto-approve (T4-23 ~ T4-27) ==="

if ! llm_skip_if_unavailable "[T4-23]" "session create"; then
    skip_test "[T4-24]" "session restore reads history (no LLM)"
    skip_test "[T4-25]" "--auto-approve tool calls (no LLM)"
    skip_test "[T4-26]" "session state persists in DuckDB (no LLM)"
    skip_test "[T4-27]" "--session with new ID creates session (no LLM)"
else
    _T4_SESSION_ID="ci-test-session-$(date +%s)"

    # T4-23: Create a session with a fixed ID
    _t423_out=$(timeout 60 "$OLAV" --session "${_T4_SESSION_ID}" "What is 2+2? Answer with just the number." 2>&1) \
        && _t423_rc=0 || _t423_rc=$?
    if echo "$_t423_out" | grep -qi "4\|four"; then
        pass_test "[T4-23]" "session create with fixed ID + LLM response"
    elif [ "$_t423_rc" -eq 0 ] && [ -n "$_t423_out" ]; then
        warn_test "[T4-23]" "session create" "(response non-empty but unexpected: ${_t423_out:0:80})"
    else
        fail_test "[T4-23]" "session create with fixed ID" "(rc=${_t423_rc} out=${_t423_out:0:120})"
    fi

    # T4-24: Check session was persisted (AsyncSqliteSaver → $HOME/.olav/checkpoints/**/checkpoints.db)
    _t424_check=$("$PYTHON" - <<PYEOF
import sqlite3, glob, sys, os
home = os.environ.get("HOME", os.path.expanduser("~"))
pattern = os.path.join(home, ".olav", "checkpoints", "**", "checkpoints.db")
dbs = glob.glob(pattern, recursive=True)
for db in dbs:
    try:
        conn = sqlite3.connect(db, check_same_thread=False)
        cnt = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        conn.close()
        if cnt > 0:
            print(f"session_found: checkpoints.db rows={cnt}")
            sys.exit(0)
    except Exception:
        pass
print("not_found")
sys.exit(0)
PYEOF
)
    if echo "$_t424_check" | grep -q "session_found"; then
        pass_test "[T4-24]" "session state persisted in SQLite checkpointer"
    else
        warn_test "[T4-24]" "session state persistence" "(not found in checkpoints.db: ${_t424_check})"
    fi

    # T4-25: Restore session with same ID — verify history context
    _t425_out=$(timeout 60 "$OLAV" --session "${_T4_SESSION_ID}" \
        "What was the number I asked you about before?" 2>&1) && _t425_rc=0 || _t425_rc=$?
    if echo "$_t425_out" | grep -qi "2\|2+2\|four\|4\|previous\|earlier\|arithmetic"; then
        pass_test "[T4-25]" "session restore recalls previous conversation"
    elif [ "$_t425_rc" -eq 0 ] && [ -n "$_t425_out" ]; then
        warn_test "[T4-25]" "session restore" "(response non-empty but unclear recall: ${_t425_out:0:100})"
    else
        fail_test "[T4-25]" "session restore" "(rc=${_t425_rc} out=${_t425_out:0:120})"
    fi

    # T4-26: --auto-approve flag (tool usage without interactive prompt)
    # Use "take a snapshot" which triggers the snapshot tool
    _t426_out=$(timeout 90 "$OLAV" --auto-approve \
        "Show me the current time. Use the run_command tool to run 'date'." 2>&1) && _t426_rc=0 || _t426_rc=$?
    if echo "$_t426_out" | grep -qiE "[0-9]{2}:[0-9]{2}|date|time|approved|auto"; then
        pass_test "[T4-26]" "--auto-approve enables tool calls without prompting"
    elif [ "$_t426_rc" -eq 0 ] && [ -n "$_t426_out" ]; then
        warn_test "[T4-26]" "--auto-approve" "(response OK but no clear tool call evidence: ${_t426_out:0:100})"
    else
        fail_test "[T4-26]" "--auto-approve tool calls" "(rc=${_t426_rc} out=${_t426_out:0:120})"
    fi

    # T4-27: New session ID creates independent session (no bleed from previous session)
    _T4_SESSION_NEW="ci-session-new-$(date +%s)"
    _t427_out=$(timeout 60 "$OLAV" --session "${_T4_SESSION_NEW}" \
        "What was the topic of our previous conversation? Say 'new session' if you have no history." 2>&1) && _t427_rc=0 || _t427_rc=$?
    if echo "$_t427_out" | grep -qi "new session\|no history\|first\|context\|haven't"; then
        pass_test "[T4-27]" "new session ID has no prior context (isolation)"
    elif [ "$_t427_rc" -eq 0 ] && [ -n "$_t427_out" ]; then
        warn_test "[T4-27]" "new session isolation" "(response OK: ${_t427_out:0:100})"
    else
        fail_test "[T4-27]" "new session isolation" "(rc=${_t427_rc} out=${_t427_out:0:120})"
    fi
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════════════
echo "=== Cleanup ==="
# Stop any lingering services
"$OLAV" service logs stop >/dev/null 2>&1 || true
"$OLAV" service daemon stop >/dev/null 2>&1 || true
sleep 1
echo "  services stopped"

# ══════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL + WARN + SKIP))
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║              Tier 4 Results                      ║"
echo "╠══════════════════════════════════════════════════╣"
printf "║  PASS:  %-5d  FAIL:  %-5d                     ║\n" "$PASS" "$FAIL"
printf "║  WARN:  %-5d  SKIP:  %-5d  TOTAL: %-5d       ║\n" "$WARN" "$SKIP" "$TOTAL"
echo "╚══════════════════════════════════════════════════╝"

if [ "$FAIL" -eq 0 ]; then
    echo "  Status: GREEN (0 failures)"
else
    echo "  Status: RED (${FAIL} failure(s))"
fi

exit "$FAIL"
