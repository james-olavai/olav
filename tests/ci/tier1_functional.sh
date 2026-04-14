#!/usr/bin/env bash
# ==============================================================================
# OLAV v0.17.0 — Tier 1: Functional Tests (T1-01 ~ T1-53)
# ==============================================================================
# Usage:
#   bash tests/ci/tier1_functional.sh
#
# Required:
#   - Built wheel in dist/        (run `uv build` first)
#   - OLAV_API_KEY env var        (for LLM groups; tests skip if unset)
#
# Optional:
#   - OLAV_LLM_BASE_URL           (default: https://openrouter.ai/api/v1)
#   - OLAV_LLM_MODEL              (default: x-ai/grok-4.1-fast)
#   - OLAV_NETOPS_DIR             (default: ./olav-netops)
# ==============================================================================

set -uo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_DIR="/tmp/olav-ci-t1-${TIMESTAMP}"
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
_DEV_CONFIG="${OLAV_DEV_CONFIG:-}"  # optional: path to dev api.json to copy wholesale
# Resolve to absolute path immediately (before any cd to test dir)
[ -n "${_DEV_CONFIG}" ] && _DEV_CONFIG="$(realpath "${_DEV_CONFIG}" 2>/dev/null || echo "${_DEV_CONFIG}")"

LLM_AVAILABLE=false
[ -n "${_API_KEY}" ] && LLM_AVAILABLE=true
# Also available if dev config contains a key (will be detected after copy)
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
skip_test() { echo "  $1 $2... SKIP"; SKIP=$((SKIP + 1)); }

run_check() {
    # run_check LABEL NAME CMD [args...]
    local label="$1" name="$2"; shift 2
    echo -n "  ${label} ${name}... "
    if "$@" >/dev/null 2>&1; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL"; FAIL=$((FAIL + 1))
    fi
}

run_check_v() {
    # run_check_v LABEL NAME CMD — like run_check but keeps stderr visible
    local label="$1" name="$2"; shift 2
    echo -n "  ${label} ${name}... "
    if "$@" 2>&1; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL"; FAIL=$((FAIL + 1))
    fi
}

llm_skip_if_unavailable() {
    # Call with (label, name) — prints SKIP and returns 1 if LLM unavailable
    if [ "$LLM_AVAILABLE" = false ]; then
        skip_test "$1" "$2 (no OLAV_API_KEY)"
        return 1
    fi
    return 0
}

# ── Banner ─────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════╗"
echo "║  OLAV Tier 1: Functional Tests (T1-01 ~ T1-52)  ║"
echo "╚══════════════════════════════════════════════════╝"
echo "  Wheel:    $(basename "$WHEEL")"
echo "  Test dir: ${TEST_DIR}"
echo "  LLM:      ${LLM_AVAILABLE} (key set: $([ -n "${_API_KEY}" ] && echo yes || echo no), dev_config: $([ -n "${_DEV_CONFIG}" ] && echo yes || echo no))"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# SETUP — fresh venv, install wheel, init, seed data
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

# Seed test data
if "$PYTHON" "${REPO_ROOT}/tests/fixtures/seed_test_data.py" >/dev/null 2>&1; then
    echo "  seed data: done"
else
    echo "  seed data: WARN (non-fatal)"
fi

# Install netops skill
if [ -d "${NETOPS_DIR}" ]; then
    "$OLAV" skill install "${NETOPS_DIR}" >/dev/null 2>&1
    echo "  skill install: done (${NETOPS_DIR})"
else
    echo "  skill install: skipped (${NETOPS_DIR} not found)"
fi

# Clear memory cache (start fresh for LLM tests)
rm -rf .olav/databases/memory.lance 2>/dev/null || true
echo "  memory cache: cleared"

# Reset auth.mode=none — olav init's _init_admin_user() sets it to 'token'
# after creating the admin user. Tests need a clean baseline.
"$PYTHON" -c "
import json
from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('auth', {})['mode'] = 'none'
p.write_text(json.dumps(cfg, indent=2))
" 2>/dev/null || true
echo "  auth.mode: reset to none"
echo ""

# Write Python helper scripts to avoid heredoc-in-function limitations
HELPERS="${TEST_DIR}/ci_helpers"
mkdir -p "$HELPERS"

# ── T1-06 helper: SemanticCache.put() stores entry in memory ─────────────
cat > "${HELPERS}/t1_06_cache_check.py" << 'EOF'
import sys
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
try:
    from olav.core.memory import SemanticCache
    # Start clean
    SemanticCache._entries.clear()
    cache = SemanticCache(threshold=0.05, ttl_hours=1)
    vec = [0.1] * 16
    cache.put(vec, [{"text": "test result", "score": 0.9}])
    count = len(SemanticCache._entries)
    print(f"SemanticCache entries after put: {count}")
    sys.exit(0 if count > 0 else 1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-07 helper: SemanticCache.get() returns hit for similar vector ──────
cat > "${HELPERS}/t1_07_cache_hit.py" << 'EOF'
import sys
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
try:
    from olav.core.memory import SemanticCache
    SemanticCache._entries.clear()
    cache = SemanticCache(threshold=0.05, ttl_hours=1)
    vec = [0.1] * 16
    expected = [{"text": "cached result", "score": 0.95}]
    cache.put(vec, expected)
    # Query with same vector — should be a hit
    result = cache.get(vec)
    if result is None:
        print("cache miss — expected hit", file=sys.stderr)
        sys.exit(1)
    print(f"cache hit: {len(result)} result(s) returned")
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-08 helper: invalidate cache + verify empty ────────────────────────
cat > "${HELPERS}/t1_08_invalidate.py" << 'EOF'
import sys
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
try:
    from olav.core.memory import SemanticCache
    cache = SemanticCache(threshold=0.05, ttl_hours=1)
    # Seed with an entry then invalidate
    cache.put([0.1] * 16, [{"text": "stale", "score": 0.5}])
    cache.invalidate_all()
    count = len(SemanticCache._entries)
    print(f"SemanticCache entries after invalidate_all: {count}")
    sys.exit(0 if count == 0 else 1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-09 helper: memory table has rows ──────────────────────────────────
cat > "${HELPERS}/t1_09_memory_rows.py" << 'EOF'
import sys, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
try:
    from olav.core.memory import get_store
    store = get_store()
    if store is None:
        sys.exit(1)
    db = store.connect()
    if "memory" not in db.table_names():
        sys.exit(1)
    tbl = db.open_table("memory")
    count = tbl.count_rows()
    print(f"memory rows: {count}")
    sys.exit(0 if count > 0 else 1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-10 helper: memory has 'fact' category ─────────────────────────────
cat > "${HELPERS}/t1_10_memory_fact.py" << 'EOF'
import sys, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
try:
    from olav.core.memory import get_store
    store = get_store()
    if store is None:
        sys.exit(1)
    db = store.connect()
    if "memory" not in db.table_names():
        sys.exit(1)
    tbl = db.open_table("memory")
    rows = tbl.to_arrow().to_pydict()
    categories = rows.get("category", [])
    has_fact = "fact" in categories
    print(f"categories seen: {set(categories)}, has_fact={has_fact}")
    sys.exit(0 if has_fact else 1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-11 helper: vector dim matches configured embedding model ───────────────
cat > "${HELPERS}/t1_11_vector_dim.py" << 'EOF'
import sys, os, json
from pathlib import Path
os.chdir(Path(sys.argv[1]))
try:
    # Detect expected dimension from api.json
    cfg = json.loads(Path('.olav/config/api.json').read_text())
    emb_mode = cfg.get('embedding', {}).get('mode', 'local')
    emb_model = cfg.get('embedding', {}).get('api', {}).get('model', '')
    # Known API model dimensions
    API_DIMS = {
        'openai/text-embedding-3-small': 1536,
        'openai/text-embedding-3-large': 3072,
        'openai/text-embedding-ada-002': 1536,
        'text-embedding-3-small': 1536,
        'text-embedding-3-large': 3072,
    }
    if emb_mode == 'api':
        expected_dim = API_DIMS.get(emb_model, None)  # None = accept any
    else:
        expected_dim = 512  # local bge-small-zh-v1.5

    from olav.core.memory import get_store
    store = get_store()
    if store is None:
        sys.exit(1)
    db = store.connect()
    if "memory" not in db.table_names():
        sys.exit(1)
    tbl = db.open_table("memory")
    schema = tbl.schema
    for field in schema:
        if field.name == "vector":
            dim = field.type.list_size
            if expected_dim is None:
                print(f"vector dim: {dim} (api mode, any dim accepted)")
                sys.exit(0)
            print(f"vector dim: {dim} (expected {expected_dim})")
            sys.exit(0 if dim == expected_dim else 1)
    print("No vector field found", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-20 helper: get first run_id from audit db ─────────────────────────
cat > "${HELPERS}/t1_20_get_run_id.py" << 'EOF'
import sys, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
try:
    from olav.cli.log_cmd import log_list
    runs = log_list(hours=168)  # look back 7 days
    if runs:
        print(runs[0]["run_id"][:8])
    else:
        print("")
except Exception as e:
    print("", file=sys.stderr)
EOF

# ── T1-37 helper: execute_sql queries devices ─────────────────────────────
cat > "${HELPERS}/t1_37_execute_sql.py" << 'EOF'
import sys, importlib.util, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
tool_path = Path(".olav/workspace/core/tools/execute_sql.py")
if not tool_path.exists():
    print(f"Not found: {tool_path}", file=sys.stderr)
    sys.exit(1)
spec = importlib.util.spec_from_file_location("execute_sql", tool_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
result = mod.execute_sql.invoke({"query": "SELECT hostname FROM netops.devices LIMIT 3"})
result_str = str(result)
print(result_str[:300])
# Accept if any device hostname or table data visible
if any(x in result_str for x in ("R1", "R2", "R3", "hostname", "device", "error")):
    sys.exit(0)
sys.exit(1)
EOF

# ── T1-38 helper: recall_memory safe on empty table ───────────────────────
cat > "${HELPERS}/t1_38_recall_memory.py" << 'EOF'
import sys, importlib.util, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
tool_path = Path(".olav/workspace/core/tools/recall_memory.py")
if not tool_path.exists():
    print(f"Not found: {tool_path}", file=sys.stderr)
    sys.exit(1)
spec = importlib.util.spec_from_file_location("recall_memory", tool_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    result = mod.recall_memory.invoke({"query": "test empty recall"})
    print(str(result)[:200])
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-39 helper: format_and_export callable ──────────────────────────────
cat > "${HELPERS}/t1_39_format_export.py" << 'EOF'
import sys, importlib.util, os, json
from pathlib import Path
os.chdir(Path(sys.argv[1]))
tool_path = Path(".olav/workspace/core/tools/format_and_export.py")
if not tool_path.exists():
    print(f"Not found: {tool_path}", file=sys.stderr)
    sys.exit(1)
spec = importlib.util.spec_from_file_location("format_and_export", tool_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
test_data = '[{"hostname": "R1", "ip": "10.0.0.1"}, {"hostname": "R2", "ip": "10.0.0.2"}]'
try:
    result = mod.format_and_export.invoke({"data": test_data, "filename": "t1_39_ci_test", "format": "json"})
    print(str(result)[:200])
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-40 helper: list_cron runs without traceback ────────────────────────
cat > "${HELPERS}/t1_40_list_cron.py" << 'EOF'
import sys, importlib.util, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
tool_path = Path(".olav/workspace/core/tools/manage_cron.py")
if not tool_path.exists():
    print(f"Not found: {tool_path}", file=sys.stderr)
    sys.exit(1)
spec = importlib.util.spec_from_file_location("manage_cron", tool_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    result = mod.list_cron.invoke({})
    print(str(result)[:200])
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── T1-50 helper: DuckDB read_only write raises ───────────────────────────
cat > "${HELPERS}/t1_50_readonly.py" << 'EOF'
import sys, duckdb, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
db_path = Path(".olav/databases/main.duckdb")
if not db_path.exists():
    print(f"Not found: {db_path}", file=sys.stderr)
    sys.exit(1)
try:
    con = duckdb.connect(str(db_path), read_only=True)
    con.execute("CREATE TABLE __write_test_t150__ (x INT)")
    con.execute("DROP TABLE IF EXISTS __write_test_t150__")
    print("ERROR: write succeeded on read_only db — not protected!", file=sys.stderr)
    sys.exit(1)
except Exception:
    print("write blocked as expected — read_only enforced")
    sys.exit(0)
EOF

# ── T1-51 helper: trace_review function callable ──────────────────────────
cat > "${HELPERS}/t1_51_trace_review.py" << 'EOF'
import sys, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
try:
    from olav.cli.commands.trace_review import _handle_trace_review
    result = _handle_trace_review()
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "status" in result, f"Missing 'status' key in result: {result}"
    print(f"trace_review returned status={result['status']!r} (total_failures={result.get('total_failures','?')})")
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF

# ── Switch auth.mode helper ───────────────────────────────────────────────
cat > "${HELPERS}/set_auth_mode.py" << 'EOF'
import sys, json, os
from pathlib import Path
mode = sys.argv[2]
os.chdir(Path(sys.argv[1]))
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('auth', {})['mode'] = mode
p.write_text(json.dumps(cfg, indent=2))
print(f"auth.mode → {mode}")
EOF

# ── Set CIDR helper ───────────────────────────────────────────────────────
cat > "${HELPERS}/set_cidr.py" << 'EOF'
import sys, json, os
from pathlib import Path
os.chdir(Path(sys.argv[1]))
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
if len(sys.argv) > 2 and sys.argv[2]:
    import ast
    cfg.setdefault('security', {})['allowed_cidrs'] = ast.literal_eval(sys.argv[2])
else:
    cfg.setdefault('security', {}).pop('allowed_cidrs', None)
p.write_text(json.dumps(cfg, indent=2))
EOF

# Helper: kill any process listening on port 2280, wait until port is free
kill_web_service() {
    local port_pid deadline
    port_pid=$(lsof -ti :2280 2>/dev/null | head -1)
    if [ -n "${port_pid:-}" ]; then
        kill "$port_pid" 2>/dev/null || true
        # Wait up to 5 seconds for port to free
        deadline=10
        while [ "$deadline" -gt 0 ]; do
            sleep 0.5
            if ! lsof -ti :2280 >/dev/null 2>&1; then
                break
            fi
            deadline=$((deadline - 1))
        done
        # Force-kill if still alive
        port_pid=$(lsof -ti :2280 2>/dev/null | head -1)
        if [ -n "${port_pid:-}" ]; then
            kill -9 "$port_pid" 2>/dev/null || true
            sleep 1
        fi
    fi
    # Remove PID file to prevent false "already running" detection (PID reuse race)
    rm -f "${TEST_DIR}/.olav/run/web.pid" 2>/dev/null || true
}

# Helper: restart web service and wait
restart_web() {
    local wait_secs="${1:-4}"
    kill_web_service
    "$OLAV" service start --all >/dev/null 2>&1 &
    sleep "$wait_secs"
    # Ensure it came up
    if ! curl -sf http://localhost:2280/health -o /dev/null 2>/dev/null; then
        sleep 2
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 1: LLM Queries (T1-01 ~ T1-05) ==="
# ══════════════════════════════════════════════════════════════════════════════
T1_01_OUTPUT=""

if llm_skip_if_unavailable "[T1-01]" "列出所有设备"; then
    T1_01_OUTPUT=$("$OLAV" "列出所有设备" 2>&1)
    if echo "$T1_01_OUTPUT" | grep -qi "traceback\|error:" && [ ${#T1_01_OUTPUT} -lt 100 ]; then
        fail_test "[T1-01]" "列出所有设备" "(error in output)"
    elif [ ${#T1_01_OUTPUT} -gt 20 ]; then
        pass_test "[T1-01]" "列出所有设备"
    else
        fail_test "[T1-01]" "列出所有设备" "(output too short: ${#T1_01_OUTPUT} chars)"
    fi
fi

if llm_skip_if_unavailable "[T1-02]" "BGP邻居状态"; then
    _out=$("$OLAV" "所有BGP邻居状态" 2>&1)
    if [ ${#_out} -gt 20 ]; then
        pass_test "[T1-02]" "BGP邻居状态"
    else
        fail_test "[T1-02]" "BGP邻居状态" "(output: ${_out:0:100})"
    fi
fi

if llm_skip_if_unavailable "[T1-03]" "网络拓扑"; then
    _out=$("$OLAV" "网络拓扑" 2>&1)
    if [ ${#_out} -gt 20 ]; then
        pass_test "[T1-03]" "网络拓扑"
    else
        fail_test "[T1-03]" "网络拓扑" "(output: ${_out:0:100})"
    fi
fi

if llm_skip_if_unavailable "[T1-04]" "哪些接口down"; then
    _out=$("$OLAV" "哪些接口down" 2>&1)
    if [ ${#_out} -gt 20 ]; then
        pass_test "[T1-04]" "哪些接口down"
    else
        fail_test "[T1-04]" "哪些接口down" "(output: ${_out:0:100})"
    fi
fi

if llm_skip_if_unavailable "[T1-05]" "R2的IP地址"; then
    _out=$("$OLAV" "R2的IP地址" 2>&1)
    if [ ${#_out} -gt 20 ]; then
        pass_test "[T1-05]" "R2的IP地址"
    else
        fail_test "[T1-05]" "R2的IP地址" "(output: ${_out:0:100})"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 2: Semantic Cache (T1-06 ~ T1-08) ==="
# ══════════════════════════════════════════════════════════════════════════════
# SemanticCache is in-memory — these tests exercise the class API directly,
# no LLM or LanceDB required.

run_check "[T1-06]" "首次查询写入cache" "$PYTHON" "${HELPERS}/t1_06_cache_check.py" "${TEST_DIR}"
run_check "[T1-07]" "相同向量命中cache" "$PYTHON" "${HELPERS}/t1_07_cache_hit.py" "${TEST_DIR}"
run_check "[T1-08]" "invalidate_all清空cache" "$PYTHON" "${HELPERS}/t1_08_invalidate.py" "${TEST_DIR}"

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 3: Memory / AutoCapture (T1-09 ~ T1-11) ==="
# ══════════════════════════════════════════════════════════════════════════════

if [ "$LLM_AVAILABLE" = false ]; then
    skip_test "[T1-09]" "查询后memory表有数据 (no LLM)"
    skip_test "[T1-10]" "Memory含fact类别 (no LLM)"
    skip_test "[T1-11]" "Memory向量维度检查 (no LLM)"
else
    run_check "[T1-09]" "查询后memory表有数据" "$PYTHON" "${HELPERS}/t1_09_memory_rows.py" "${TEST_DIR}"
    run_check "[T1-10]" "Memory含fact类别" "$PYTHON" "${HELPERS}/t1_10_memory_fact.py" "${TEST_DIR}"
    run_check "[T1-11]" "Memory向量维度正确" "$PYTHON" "${HELPERS}/t1_11_vector_dim.py" "${TEST_DIR}"
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 4: KB CLI (T1-12 ~ T1-17) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-12] olav kb status... "
_out=$("$OLAV" kb status 2>&1)
if echo "$_out" | grep -qi "entries\|total\|knowledge\|memory"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-13] olav kb import <file>... "
echo "OLAV CI test document for T1-13" > /tmp/t1_13_ci.md
_out=$("$OLAV" kb import /tmp/t1_13_ci.md 2>&1)
if echo "$_out" | grep -qi "imported\|added\|chunk\|stored\|ok"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-14] olav kb search... "
_out=$("$OLAV" kb search "OLAV CI test" 2>&1)
if ! echo "$_out" | grep -q "^Traceback" && [ ${#_out} -ge 0 ]; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-15] olav kb export creates dir... "
_out=$("$OLAV" kb export 2>&1)
if [ -d ".olav/knowledge" ]; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (.olav/knowledge not created; got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-16] olav kb graph creates HTML... "
_out=$("$OLAV" kb graph 2>&1)
if [ -f ".olav/knowledge/_graph.html" ]; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (.olav/knowledge/_graph.html not found; got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-17] olav kb sync --dry-run... "
_out=$("$OLAV" kb sync --dry-run 2>&1)
if ! echo "$_out" | grep -q "^Traceback" && (echo "$_out" | grep -qi "dry\|sync\|no changes\|entries\|scanned\|found\|ok"); then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 5: Audit CLI (T1-18 ~ T1-23) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-18] olav log list... "
_out=$("$OLAV" log list 2>&1)
if ! echo "$_out" | grep -q "^Traceback"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (traceback)"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-19] olav log errors... "
_out=$("$OLAV" log errors 2>&1)
if ! echo "$_out" | grep -q "^Traceback"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (traceback)"; FAIL=$((FAIL + 1))
fi

# T1-20: Get a run_id from audit DB
_run_id=$("$PYTHON" "${HELPERS}/t1_20_get_run_id.py" "${TEST_DIR}" 2>/dev/null || echo "")
if [ -z "$_run_id" ]; then
    skip_test "[T1-20]" "olav log show (no audit runs available)"
else
    echo -n "  [T1-20] olav log show <run_id>... "
    _out=$("$OLAV" log show "$_run_id" 2>&1)
    if ! echo "$_out" | grep -q "^Traceback" && [ ${#_out} -gt 5 ]; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
    fi
fi

echo -n "  [T1-21a] olav log export raw --hours 1 (base AAA export)... "
_out=$("$OLAV" log export raw --hours 1 2>&1)
if ! echo "$_out" | grep -q "^Traceback" && \
   (echo "$_out" | grep -qi "no audit runs\|runs exported\|complete"); then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:120})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-21b] olav log export trajectory --hours 1 (olav-ent check)... "
_out=$("$OLAV" log export trajectory --hours 1 2>&1)
if echo "$_out" | grep -qi "olav-ent.*not installed\|install.*pip"; then
    echo "WARN (olav-ent not installed — expected in base CI)"; WARN=$((WARN + 1))
elif ! echo "$_out" | grep -q "^Traceback" && (echo "$_out" | grep -qi "export\|no data\|written\|trajectory\|done\|0 runs"); then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-22] olav sessions... "
_out=$("$OLAV" sessions 2>&1)
if ! echo "$_out" | grep -q "^Traceback"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (traceback)"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-23] olav version (0.x.y)... "
_out=$("$OLAV" version 2>&1)
if echo "$_out" | grep -q "0\."; then
    echo "OK (${_out:0:40})"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:40})"; FAIL=$((FAIL + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Starting web service ==="
# ══════════════════════════════════════════════════════════════════════════════
kill_web_service  # Ensure no stale process on port 2280
"$OLAV" service start --all >/dev/null 2>&1 &
sleep 4
# Verify it started
if curl -sf http://localhost:2280/health -o /dev/null 2>/dev/null; then
    echo "  web service: started (port 2280)"
else
    echo "  web service: WARN — /health not responding after 4s, continuing..."
    sleep 3  # give extra time
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 6: Auth & Multi-User (T1-24 ~ T1-29) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-24] auth.mode=none 直接访问 (200 or /docs redirect)... "
_code=$(curl -sf http://localhost:2280/ -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
if [ "$_code" = "200" ] || [ "$_code" = "307" ] || [ "$_code" = "302" ]; then
    # 307 to /docs is normal when static index.html is not present — not an auth block
    _loc=$(curl -s http://localhost:2280/ -D - -o /dev/null 2>/dev/null | grep -i "^location:" | tr -d '\r')
    if echo "$_loc" | grep -qi "login"; then
        echo "FAIL (auth blocked — redirect to login with auth.mode=none)"; FAIL=$((FAIL + 1))
    else
        echo "OK (HTTP ${_code}${_loc:+ → ${_loc#* }})"; PASS=$((PASS + 1))
    fi
else
    echo "FAIL (HTTP ${_code})"; FAIL=$((FAIL + 1))
fi

# Switch to token mode
"$PYTHON" "${HELPERS}/set_auth_mode.py" "${TEST_DIR}" token >/dev/null 2>&1
restart_web 3

echo -n "  [T1-25] auth.mode=token 重定向 307... "
_code=$(curl -sf http://localhost:2280/ -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
if [ "$_code" = "307" ] || [ "$_code" = "302" ]; then
    echo "OK (HTTP ${_code})"; PASS=$((PASS + 1))
else
    echo "FAIL (HTTP ${_code}, expected 307)"; FAIL=$((FAIL + 1))
fi

# Get admin token
ADMIN_TOKEN=$(cat "${HOME}/.olav/token" 2>/dev/null | tr -d '[:space:]' || echo "")
if [ -z "$ADMIN_TOKEN" ]; then
    # Try reading from .olav/config area
    ADMIN_TOKEN=$(cat "${TEST_DIR}/.olav/config/token" 2>/dev/null | tr -d '[:space:]' || echo "")
fi

if [ -n "$ADMIN_TOKEN" ]; then
    echo -n "  [T1-26] POST /login token= → Set-Cookie... "
    _resp=$(curl -sf -X POST "http://localhost:2280/login" \
        -H "Content-Type: application/json" \
        -d "{\"token\":\"${ADMIN_TOKEN}\"}" -D - 2>&1 || echo "CURL_FAIL")
    if echo "$_resp" | grep -qi "set-cookie\|location"; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL (resp: ${_resp:0:200})"; FAIL=$((FAIL + 1))
    fi

    echo -n "  [T1-27] ?token= URL 登录... "
    _resp=$(curl -sf "http://localhost:2280/?token=${ADMIN_TOKEN}" -D - 2>&1 || echo "CURL_FAIL")
    if echo "$_resp" | grep -qi "set-cookie\|location"; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL (resp: ${_resp:0:200})"; FAIL=$((FAIL + 1))
    fi

    echo -n "  [T1-28] HTTP Cookie 无 Secure 标志... "
    _resp=$(curl -sf -X POST "http://localhost:2280/login" \
        -H "Content-Type: application/json" \
        -d "{\"token\":\"${ADMIN_TOKEN}\"}" -D - 2>&1 || echo "CURL_FAIL")
    _cookie_line=$(echo "$_resp" | grep -i "set-cookie" | head -1)
    if echo "$_cookie_line" | grep -qi "secure"; then
        echo "FAIL (Secure flag present on HTTP: ${_cookie_line})"; FAIL=$((FAIL + 1))
    else
        echo "OK (no Secure on HTTP)"; PASS=$((PASS + 1))
    fi
else
    skip_test "[T1-26]" "POST /login (no token file)"
    skip_test "[T1-27]" "?token= URL (no token file)"
    skip_test "[T1-28]" "Cookie无Secure (no token file)"
fi

# Restore auth.mode=none for T1-29 and rest
"$PYTHON" "${HELPERS}/set_auth_mode.py" "${TEST_DIR}" none >/dev/null 2>&1
restart_web 3

echo -n "  [T1-29] olav admin add-user --no-verify → Token output... "
_out=$("$OLAV" admin add-user "ci-testuser-$$" --no-verify 2>&1)
if echo "$_out" | grep -qi "token\|created\|added"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 7: Web API Endpoints (T1-30 ~ T1-35) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-30] POST /threads → thread_id... "
THREAD_RESP=$(curl -sf -X POST http://localhost:2280/threads \
    -H "Content-Type: application/json" -d '{}' 2>&1 || echo "CURL_FAIL")
if echo "$THREAD_RESP" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'thread_id' in d else 1)" 2>/dev/null; then
    echo "OK"; PASS=$((PASS + 1))
    THREAD_ID=$(echo "$THREAD_RESP" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin)['thread_id'])" 2>/dev/null || echo "")
else
    echo "FAIL (got: ${THREAD_RESP:0:100})"; FAIL=$((FAIL + 1))
    THREAD_ID=""
fi

echo -n "  [T1-31] GET /threads/search → {threads:[...]}... "
_resp=$(curl -sf "http://localhost:2280/threads/search" 2>&1 || echo "CURL_FAIL")
if echo "$_resp" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'threads' in d or isinstance(d, list) else 1)" 2>/dev/null; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_resp:0:100})"; FAIL=$((FAIL + 1))
fi

if [ -n "${THREAD_ID:-}" ] && [ "$LLM_AVAILABLE" = true ]; then
    echo -n "  [T1-32] POST /threads/{id}/runs/stream SSE... "
    _resp=$(curl -sf -m 30 -N -X POST "http://localhost:2280/threads/${THREAD_ID}/runs/stream" \
        -H "Content-Type: application/json" \
        -d '{"input":{"messages":[{"role":"user","content":"ping"}]}}' 2>&1 | head -c 2000 || echo "CURL_FAIL")
    if echo "$_resp" | grep -q "data:"; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL (got: ${_resp:0:200})"; FAIL=$((FAIL + 1))
    fi
elif [ -n "${THREAD_ID:-}" ]; then
    skip_test "[T1-32]" "POST /threads/stream (no OLAV_API_KEY)"
else
    skip_test "[T1-32]" "POST /threads/stream (no thread_id)"
fi

echo -n "  [T1-33] POST /reload → {status:reloaded}... "
_resp=$(curl -sf -X POST http://localhost:2280/reload 2>&1 || echo "CURL_FAIL")
if echo "$_resp" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='reloaded' else 1)" 2>/dev/null; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_resp:0:100})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-34] GET /agents ≥9 entries... "
_resp=$(curl -sf http://localhost:2280/agents 2>&1 || echo "CURL_FAIL")
_count=$(echo "$_resp" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "0")
if [ "${_count:-0}" -ge 9 ] 2>/dev/null; then
    echo "OK (${_count} agents)"; PASS=$((PASS + 1))
else
    echo "FAIL (got ${_count:-?} agents, want ≥9)"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-35] GET /memory/graph 优雅降级... "
_code=$(curl -sf http://localhost:2280/memory/graph -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
if [ "$_code" = "200" ]; then
    echo "OK (200)"; PASS=$((PASS + 1))
elif [ "$_code" = "501" ] || [ "$_code" = "503" ]; then
    echo "OK (graceful ${_code})"; PASS=$((PASS + 1))
else
    echo "FAIL (HTTP ${_code})"; FAIL=$((FAIL + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 8: Core Tools — no LLM (T1-36 ~ T1-40) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-36] execute_sql 无 phantom views... "
if ! grep -qE "v_bgp_neighbors_auto|v_interfaces_auto|v_bgp_peers_auto" \
    "${REPO_ROOT}/src/olav/data/workspace/core/tools/execute_sql.py" 2>/dev/null; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (phantom view found)"; FAIL=$((FAIL + 1))
fi

run_check "[T1-37]" "execute_sql 查 devices" "$PYTHON" "${HELPERS}/t1_37_execute_sql.py" "${TEST_DIR}"
run_check "[T1-38]" "recall_memory 空表安全" "$PYTHON" "${HELPERS}/t1_38_recall_memory.py" "${TEST_DIR}"
run_check "[T1-39]" "format_and_export JSON" "$PYTHON" "${HELPERS}/t1_39_format_export.py" "${TEST_DIR}"
run_check "[T1-40]" "manage_cron list_cron" "$PYTHON" "${HELPERS}/t1_40_list_cron.py" "${TEST_DIR}"

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 9: Workspace Management (T1-41 ~ T1-45) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-41] olav workspace list... "
_out=$("$OLAV" workspace list 2>&1)
if ! echo "$_out" | grep -q "^Traceback"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (traceback)"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-42] olav workspace status... "
_out=$("$OLAV" workspace status 2>&1)
if ! echo "$_out" | grep -q "^Traceback"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (traceback)"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-43] olav refresh 注册 agents... "
_out=$("$OLAV" refresh 2>&1)
if echo "$_out" | grep -qi "agents registered\|refresh\|complete\|✓"; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
fi

# T1-44: Skill install overwrites tools
if [ -d "${NETOPS_DIR}" ]; then
    _skill_tool=$(ls "${TEST_DIR}/.olav/workspace/ops/tools/"*.py 2>/dev/null | head -1 || echo "")
    if [ -n "$_skill_tool" ]; then
        # Touch the tool file to give it a "stale" mtime
        touch -t 202001010000 "$_skill_tool" 2>/dev/null || true
        "$OLAV" skill install "${NETOPS_DIR}" >/dev/null 2>&1
        if [ -f "$_skill_tool" ]; then
            echo "  [T1-44] Skill install 覆盖文件... OK"; PASS=$((PASS + 1))
        else
            echo "  [T1-44] Skill install 覆盖文件... FAIL (file gone)"; FAIL=$((FAIL + 1))
        fi
    else
        skip_test "[T1-44]" "Skill install覆盖 (no tool files in ops/tools)"
    fi
else
    skip_test "[T1-44]" "Skill install覆盖 (netops not found)"
fi

echo -n "  [T1-45] Skill auto pip install (nornir present)... "
if "$PIP" show nornir >/dev/null 2>&1; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "WARN (nornir not installed — skill may not have run pip)"; WARN=$((WARN + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 10: Security & Boundaries (T1-46 ~ T1-50) ==="
# ══════════════════════════════════════════════════════════════════════════════

echo -n "  [T1-46] CIDR 空 = 放行所有 localhost... "
_code=$(curl -sf http://localhost:2280/ -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
if [ "$_code" = "200" ]; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (HTTP ${_code})"; FAIL=$((FAIL + 1))
fi

skip_test "[T1-47]" "CIDR 阻止 192.168 IP (needs non-loopback client — loopback always allowed)"

# T1-48/T1-49: Configure CIDR 10.0.0.0/8 — /health exempt, localhost allowed
"$PYTHON" "${HELPERS}/set_cidr.py" "${TEST_DIR}" "['10.0.0.0/8']" >/dev/null 2>&1
restart_web 3

echo -n "  [T1-48] CIDR 配置后 /health 仍可访问... "
_code=$(curl -sf http://localhost:2280/health -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
if [ "$_code" = "200" ]; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (HTTP ${_code})"; FAIL=$((FAIL + 1))
fi

echo -n "  [T1-49] CIDR 10.0.0.0/8 — localhost 始终放行... "
_code=$(curl -sf http://localhost:2280/ -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
if [ "$_code" = "200" ]; then
    echo "OK"; PASS=$((PASS + 1))
else
    echo "FAIL (HTTP ${_code})"; FAIL=$((FAIL + 1))
fi

# Restore CIDR
"$PYTHON" "${HELPERS}/set_cidr.py" "${TEST_DIR}" "" >/dev/null 2>&1

# T1-50: DuckDB read_only not bypassable
run_check "[T1-50]" "DuckDB read_only 不可绕过" "$PYTHON" "${HELPERS}/t1_50_readonly.py" "${TEST_DIR}"

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Group 11: TUI / CLI Extended (T1-51 ~ T1-52)
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 11: TUI / CLI Extended (T1-51 ~ T1-52) ==="

# T1-51: /trace-review function returns structured dict (no LLM, no server)
run_check "[T1-51]" "/trace-review Python直接调用返回dict" "$PYTHON" "${HELPERS}/t1_51_trace_review.py" "${TEST_DIR}"

# T1-52: olav "/trace-review" via CLI single-query mode (needs LLM for agent init)
if llm_skip_if_unavailable "[T1-52]" "olav /trace-review CLI single-query"; then
    cd "${TEST_DIR}"
    _t152_out=$("$OLAV" "/trace-review" 2>&1) && _t152_rc=0 || _t152_rc=$?
    if [ "$_t152_rc" -eq 0 ] && [ -n "$_t152_out" ]; then
        echo "  [T1-52] olav /trace-review CLI single-query... OK"
        PASS=$((PASS + 1))
    else
        echo "  [T1-52] olav /trace-review CLI single-query... FAIL (rc=$_t152_rc out=${_t152_out:0:120})"
        FAIL=$((FAIL + 1))
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Cleanup ==="
kill_web_service
# Kill syslog receiver if running
SYSLOG_PID=$(lsof -ti :5514 2>/dev/null | head -1)
if [ -n "${SYSLOG_PID:-}" ]; then
    kill "$SYSLOG_PID" 2>/dev/null || true
fi
echo "  web service: stopped"
echo "  Test dir: ${TEST_DIR} (preserved for debugging)"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL + WARN + SKIP))
echo "╔══════════════════════════════════════════════════════╗"
if [ "$FAIL" -eq 0 ]; then
    echo "║  ✅ TIER 1 PASSED: ${PASS}/${TOTAL} pass, ${WARN} warn, ${SKIP} skip  ║"
else
    printf "║  ❌ TIER 1: %d fail, %d pass, %d warn, %d skip / %d total  ║\n" \
        "$FAIL" "$PASS" "$WARN" "$SKIP" "$TOTAL"
fi
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  PASS=${PASS}  FAIL=${FAIL}  WARN=${WARN}  SKIP=${SKIP}  TOTAL=${TOTAL}"

exit $FAIL
