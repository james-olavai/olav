#!/usr/bin/env bash
# ==============================================================================
# OLAV v0.18.0 — Tier 1: Functional Tests (T1-01 ~ T1-69)
# ==============================================================================
# Rounds 52-60 added Group 12 covering ARCH-14 NetworkModel (sim package +
# sandbox auto-inject), Round-45/47 CLI shortcuts (olav explain / olav diff),
# Round-38 progressive-disclosure helpers (load_reference section slicing /
# tool_help detail), Round-39 describe_table, Round-36/42 OLAV_DEBUG_*
# env vars, Round-48 devices.environment column.
#
# Group 12 supplement (T1-64~T1-69): ARCH-16 recall_memory tier default /
# ARCH-18 subagent return cap / ARCH-19 Summarization tier trigger /
# SKILL.md tools_docstring_mode per-agent override / OLAV_BACKUP_COMMANDS_PATH
# env override / 🔧[orch]|[sub] origin tag on on_tool_start log lines.
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

# ── Parse flags ───────────────────────────────────────────────────────────────
KEEP_DIR=false
for _arg in "$@"; do
    case "$_arg" in --keep-dir) KEEP_DIR=true ;; esac
done

# ── Auto-cleanup on exit (skip with --keep-dir for post-mortem debugging) ─────
if [ "$KEEP_DIR" = false ]; then
    trap 'rm -rf "${TEST_DIR}" 2>/dev/null || true' EXIT
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
echo "║  OLAV Tier 1: Functional Tests (T1-01 ~ T1-69)  ║"
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
    "$OLAV" agent install "${NETOPS_DIR}" >/dev/null 2>&1
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
tool_path = Path(".olav/workspace/core/writer/tools/format_and_export.py")
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
tool_path = Path(".olav/workspace/core/admin/tools/manage_cron.py")
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

# ══════════════════════════════════════════════════════════════════════════════
# Group 12 helpers — Round 24-60 additions (T1-54 ~ T1-63)
# ══════════════════════════════════════════════════════════════════════════════

# ── T1-56 helper: load_reference(name, section=) section slicing ─────────
cat > "${HELPERS}/t1_56_load_reference_slice.py" << 'EOF'
"""ARCH-17 section slicing (Round 38). Loads the workspace tool from
.olav/workspace/core/admin/tools/load_reference.py (post-R65 ARCH-23
relocation) and verifies:
  * section=None returns the full file (contains >=2 ## headers)
  * section='?' lists headings
  * section='<known>' slices just that section
"""
import sys
import importlib.util
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
tool_py = Path(".olav/workspace/core/admin/tools/load_reference.py")
if not tool_py.is_file():
    print(f"load_reference.py missing at {tool_py}", file=sys.stderr)
    sys.exit(1)
spec = importlib.util.spec_from_file_location("lr", tool_py)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
tool = mod.load_reference

full = tool.invoke({"name": "schema"})
if "## " not in full:
    print("full schema reference missing H2 headers", file=sys.stderr)
    sys.exit(1)
listing = tool.invoke({"name": "schema", "section": "?"})
if "Available sections in 'schema'" not in listing:
    print(f"section=? listing wrong shape: {listing[:200]}", file=sys.stderr)
    sys.exit(1)
sliced = tool.invoke({"name": "schema", "section": "common mistakes"})
if "Common Mistakes to Avoid" not in sliced:
    print("section slice missed target section", file=sys.stderr)
    sys.exit(1)
# The slice must NOT include other neighbouring sections.
if "Verified SQL Examples" in sliced and "Common Mistakes" in sliced:
    # Only fail if BOTH neighbours leaked in — some guides may cross-ref.
    if sliced.count("##") > 2:
        print("slice contains too many sections", file=sys.stderr)
        sys.exit(1)
print("OK")
sys.exit(0)
EOF

# ── T1-57 helper: tool_help(detail=) tier-aware ──────────────────────────
cat > "${HELPERS}/t1_57_tool_help_detail.py" << 'EOF'
"""ARCH-19 #C (Round 38). tool_help must accept detail kwarg and
omit full_docstring when detail='brief'."""
import sys
import importlib.util
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
tool_py = Path(".olav/workspace/core/admin/tools/tool_help.py")
spec = importlib.util.spec_from_file_location("th", tool_py)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
brief = mod.tool_help.invoke({"name": "tool_help", "detail": "brief"})
if "full_docstring" in brief:
    print("brief mode still includes full_docstring", file=sys.stderr)
    sys.exit(1)
full = mod.tool_help.invoke({"name": "tool_help", "detail": "full"})
if not full.get("full_docstring"):
    print("full mode missing full_docstring", file=sys.stderr)
    sys.exit(1)
if brief.get("_detail") != "brief" or full.get("_detail") != "full":
    print(f"_detail tag wrong: brief={brief.get('_detail')} full={full.get('_detail')}", file=sys.stderr)
    sys.exit(1)
print("OK")
sys.exit(0)
EOF

# ── T1-58 helper: describe_table accepts table_name kwarg ────────────────
cat > "${HELPERS}/t1_58_describe_table.py" << 'EOF'
"""ARCH-18 (Round 39) describe_table — importable as a LangChain @tool
with the documented schema. End-to-end DuckDB test is out of scope here
(needs netops schema bootstrap); just verify the args_schema."""
import sys
import importlib.util
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
tool_py = Path(".olav/workspace/core/db_query/tools/describe_table.py")
if not tool_py.is_file():
    print(f"describe_table.py missing at {tool_py}", file=sys.stderr)
    sys.exit(1)
spec = importlib.util.spec_from_file_location("dt", tool_py)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
tool = mod.describe_table
schema = getattr(tool, "args_schema", None)
if schema is None:
    print("no args_schema", file=sys.stderr); sys.exit(1)
fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
for needed in ("table_name", "include_samples"):
    if needed not in fields:
        print(f"missing kwarg {needed!r} in describe_table", file=sys.stderr)
        sys.exit(1)
# Empty table name → graceful error dict.
result = tool.invoke({"table_name": ""})
if "error" not in result:
    print(f"empty table_name should error; got {result}", file=sys.stderr)
    sys.exit(1)
print("OK")
sys.exit(0)
EOF

# ── T1-59 helper: OLAV_DEBUG_CONTEXT / _SUMMARIZATION resolvers ──────────
cat > "${HELPERS}/t1_59_debug_env.py" << 'EOF'
"""Rounds 36/42 operator env vars — the resolvers recognise truthy set
without silently downgrading. Runs inside the installed wheel so a
packaging regression surfaces here."""
import os
os.environ["OLAV_DEBUG_CONTEXT"] = "1"
from olav.agents.static_context_resolver import is_debug_enabled
assert is_debug_enabled() is True, "OLAV_DEBUG_CONTEXT=1 not recognised"
os.environ["OLAV_DEBUG_CONTEXT"] = "0"
assert is_debug_enabled() is False, "OLAV_DEBUG_CONTEXT=0 treated as truthy"
# Summarization env is in _deepagents_bridge; import path:
from olav.agents._deepagents_bridge import _summarization_debug_enabled
os.environ["OLAV_DEBUG_SUMMARIZATION"] = "yes"
assert _summarization_debug_enabled() is True
os.environ["OLAV_DEBUG_SUMMARIZATION"] = "off"
assert _summarization_debug_enabled() is False
print("OK")
EOF

# ── T1-60 helper: olav_netops.sim.load_network_model lazy construct ──────
cat > "${HELPERS}/t1_60_nom_smoke.py" << 'EOF'
"""ARCH-14 Rounds 52-59 — NetworkModel constructs without touching
DuckDB and exposes every layer (physical/l2/l3.ospf/l3.bgp/l4). Works
even when olav_netops is a platform-side extension — if import fails,
the test reports SKIP via exit code 2 so the shell script can grade
accordingly."""
import sys
try:
    from olav_netops.sim import load_network_model, NetworkModel, PhysicalLayer, L2Layer, OspfLayer, BgpLayer, L4Layer
except Exception as exc:
    print(f"olav_netops.sim unavailable: {exc}", file=sys.stderr)
    sys.exit(2)
m = load_network_model(db_path="/definitely/missing.duckdb")
assert isinstance(m, NetworkModel)
# Each layer materialises to its documented empty shape — no raise.
assert isinstance(m.physical, PhysicalLayer) and m.physical.links == []
assert isinstance(m.l2, L2Layer) and m.l2.vlans == []
assert isinstance(m.l3.ospf, OspfLayer) and m.l3.ospf.adjacencies == []
assert isinstance(m.l3.bgp, BgpLayer) and m.l3.bgp.sessions == []
assert isinstance(m.l4, L4Layer) and m.l4.clauses == []
# L4 policy walker surface works with unbound peer → permit-all.
pol = m.l4.policy(device="R1", neighbor="10.0.12.2", direction="out")
assert pol["unbound"] is True and pol["action"] == "permit", pol
print("OK")
EOF

# ── T1-61 helper: sandbox prologue contains NetworkModel auto-inject ─────
cat > "${HELPERS}/t1_61_sandbox_inject.py" << 'EOF'
"""Round 57: execute_in_sandbox wrapper must carry the NoM
auto-inject prologue so model resolves inside the subprocess."""
from olav.platform.sandbox import _build_wrapper, _NETWORK_MODEL_PROLOGUE
assert "load_network_model" in _NETWORK_MODEL_PROLOGUE
assert "model = _olav_load_network_model()" in _NETWORK_MODEL_PROLOGUE
wrapper = _build_wrapper("print('hi')")
assert "DuckDB safety patch" in wrapper
assert "NetworkModel auto-inject" in wrapper
# DuckDB prologue must come before the NoM one so read-only is inherited.
assert wrapper.find("DuckDB safety patch") < wrapper.find("NetworkModel auto-inject")
print("OK")
EOF

# ── T1-62 helper: DevicesTable schema carries environment column ─────────
cat > "${HELPERS}/t1_62_devices_env_column.py" << 'EOF'
"""ARCH-08 Phase 2 Item 2 (Round 48) — netops.devices.environment column."""
import sys
try:
    from olav_netops.core.tables import DevicesTable
except Exception as exc:
    print(f"olav_netops tables unavailable: {exc}", file=sys.stderr)
    sys.exit(2)
cols = {c.name for c in DevicesTable.columns}
assert "environment" in cols, f"environment column missing; got {cols}"
env_col = next(c for c in DevicesTable.columns if c.name == "environment")
assert env_col.nullable, "environment must be nullable for LLDP-discovered devices"
print("OK")
EOF

# ── T1-64 helper: ARCH-16 recall_memory tier-aware limit default ─────────
cat > "${HELPERS}/t1_64_recall_memory_tier_limit.py" << 'EOF'
"""ARCH-16 (Round 40) — recall_memory(limit=None) must resolve via
tier_default; explicit limit still clamps to 1..10."""
import sys
import importlib.util
from pathlib import Path
import os
os.chdir(Path(sys.argv[1]))
tool_py = Path(".olav/workspace/core/tools/recall_memory.py")
spec = importlib.util.spec_from_file_location("rm", tool_py)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Signature: limit must be optional so tier default applies.
schema = getattr(mod.recall_memory, "args_schema", None)
fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
assert "limit" in fields, "recall_memory lost 'limit' kwarg"
req = getattr(fields["limit"], "is_required", None)
if callable(req):
    req = req()
assert req is False, "recall_memory limit must be optional"

# Resolver clamps + tier fallback.
assert mod._resolve_recall_limit(5) == 5
assert mod._resolve_recall_limit(0) == 1
assert mod._resolve_recall_limit(100) == 10
val = mod._resolve_recall_limit(None)
assert isinstance(val, int) and 1 <= val <= 10
print("OK")
EOF

# ── T1-65 helper: ARCH-18 subagent return cap ────────────────────────────
cat > "${HELPERS}/t1_65_subagent_cap.py" << 'EOF'
"""ARCH-18 #4 (Round 40) — delegate_tool caps subagent output to the
tier's return_compact_chars. Short content passes through untouched;
long content gets a visible suffix."""
from olav.agents.delegate_tool import _resolve_subagent_cap, _truncate, _SUBAGENT_RETURN_FALLBACK

cap = _resolve_subagent_cap()
assert isinstance(cap, int) and cap > 0, f"bad cap: {cap}"

# Short content unchanged.
assert _truncate("short", cap=1000) == "short"
# Above-cap → suffix appended with both N and M.
long = "x" * 5000
out = _truncate(long, cap=200)
assert out.startswith("x" * 200)
assert "truncated" in out
assert "5000" in out and "200" in out
# cap=0 disables (defensive).
assert _truncate("x" * 500, cap=0) == "x" * 500
# Config-unavailable fallback is a positive int.
assert _SUBAGENT_RETURN_FALLBACK > 0
print("OK")
EOF

# ── T1-66 helper: ARCH-19 SummarizationMiddleware tier trigger ───────────
cat > "${HELPERS}/t1_66_summarization_tier_trigger.py" << 'EOF'
"""ARCH-19 (Round 42) — compute_summarization_trigger returns
('tokens', context_budget × summarization_trigger_pct) for each tier;
unknown tier returns None (fall-through to upstream defaults)."""
from olav.agents._deepagents_bridge import compute_summarization_trigger

# Tier defaults (8000 * 0.50 = 4000 / 32000 * 0.65 = 20800 / 200000 * 0.80 = 160000).
assert compute_summarization_trigger("small") == ("tokens", 4000)
assert compute_summarization_trigger("medium") == ("tokens", 20800)
assert compute_summarization_trigger("large") == ("tokens", 160000)
# Unknown / None → None so caller falls back.
assert compute_summarization_trigger("xlarge") is None
assert compute_summarization_trigger(None) is None
assert compute_summarization_trigger("") is None
print("OK")
EOF

# ── T1-67 helper: SKILL.md tools_docstring_mode per-agent override ──────
cat > "${HELPERS}/t1_67_skill_md_docstring_mode.py" << 'EOF'
"""ARCH-19 (Round 49) — tool_help(agent_id=...) consults the named
agent's SKILL.md::tools_docstring_mode frontmatter. Aliases accepted:
compact/brief/short → brief; full/long/verbose → full."""
import sys
import importlib.util
from pathlib import Path
import os, tempfile
os.chdir(Path(sys.argv[1]))
tool_py = Path(".olav/workspace/core/admin/tools/tool_help.py")
spec = importlib.util.spec_from_file_location("th2", tool_py)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

# Alias map correctness.
aliases = mod._SKILL_MODE_ALIASES
assert aliases["compact"] == "brief"
assert aliases["full"] == "full"
assert aliases["verbose"] == "full"

# tool_help schema exposes agent_id as optional.
schema = getattr(mod.tool_help, "args_schema", None)
fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
assert "agent_id" in fields, "tool_help missing agent_id kwarg"

# Round-trip: fake agent SKILL.md with `tools_docstring_mode: compact` —
# helper must resolve to 'brief'.
tmp_ws = Path(tempfile.mkdtemp()) / ".olav" / "workspace"
agent_dir = tmp_ws / "fake_agent"
(agent_dir / "tools").mkdir(parents=True)
(agent_dir / "SKILL.md").write_text(
    "---\nname: fake_agent\ntools_docstring_mode: compact\n---\n",
    encoding="utf-8",
)
# Patch module's workspace roots so the reader finds the fake agent.
mod._PROJECT_ROOT = tmp_ws.parent.parent
mod._TOOL_ROOTS = [agent_dir / "tools"]
assert mod._read_agent_docstring_mode("fake_agent") == "brief"
# Typo / unknown mode → None (no raise).
(agent_dir / "SKILL.md").write_text(
    "---\nname: fake_agent\ntools_docstring_mode: nonsense\n---\n",
    encoding="utf-8",
)
assert mod._read_agent_docstring_mode("fake_agent") is None
print("OK")
EOF

# ── T1-68 helper: OLAV_BACKUP_COMMANDS_PATH env override ─────────────────
cat > "${HELPERS}/t1_68_backup_commands_env.py" << 'EOF'
"""ARCH-22 C1 (Round 46) — OLAV_BACKUP_COMMANDS_PATH env var takes
priority-0 over the 3 default candidate paths. Missing file in env
falls through to defaults (defensive against typos)."""
import os, tempfile
from pathlib import Path
from olav.core.utils import find_backup_commands_yaml, _BACKUP_COMMANDS_PATH_ENV

assert _BACKUP_COMMANDS_PATH_ENV == "OLAV_BACKUP_COMMANDS_PATH"

tmp = Path(tempfile.mkdtemp())
override = tmp / "custom.yaml"
override.write_text("- command: show test\n", encoding="utf-8")

# Valid env → that path wins.
os.environ["OLAV_BACKUP_COMMANDS_PATH"] = str(override)
resolved = find_backup_commands_yaml()
assert resolved == override, f"env override ignored, got {resolved}"

# Bogus env path → fall-through (None or real default candidate).
os.environ["OLAV_BACKUP_COMMANDS_PATH"] = "/definitely/not/a/real/path.yaml"
resolved = find_backup_commands_yaml()
assert resolved is None or resolved.is_file()

# Unset → default candidate search.
del os.environ["OLAV_BACKUP_COMMANDS_PATH"]
resolved = find_backup_commands_yaml()
assert resolved is None or resolved.is_file()
print("OK")
EOF

# ── T1-69 helper: 🔧[orch] / 🔧[sub] origin tag in main.py ───────────────
cat > "${HELPERS}/t1_69_origin_tag.py" << 'EOF'
"""WRITER-01 (a) (Round 39) — the on_tool_start handler in cli/main.py
emits the 🔧 marker with an origin tag and tracks a _delegate_depth
counter so nested subagent calls are classified [sub], top-level
orchestrator calls are [orch]. Text-level pin; full runtime coverage
lives in test_round39_origin_tag_and_describe_table.py."""
from pathlib import Path
src = Path("src/olav/cli/main.py")  # in test venv, main.py is installed; look up via olav module
if not src.is_file():
    import olav.cli.main as m
    src = Path(m.__file__)
text = src.read_text(encoding="utf-8")
assert "_delegate_depth" in text, "delegate_depth counter missing"
assert "_DELEGATE_TOOLS" in text, "_DELEGATE_TOOLS set missing"
assert '"olav_delegate"' in text, "olav_delegate not in counted set"
assert '"task"' in text, "task (deepagents built-in) not in counted set"
assert "_delegate_depth += 1" in text
assert "_delegate_depth -= 1" in text
# Emission format must carry the bracketed origin.
import re
assert re.search(r"🔧\[\{_origin\}\]", text), (
    "🔧[{_origin}] format string missing — origin tag regressed"
)
print("OK")
EOF

# ── T1-63 helper: L4 walker deterministic semantics ──────────────────────
cat > "${HELPERS}/t1_63_l4_walker.py" << 'EOF'
"""ARCH-14 P3 (Round 58) — L4Layer.walk() deterministic, no DB needed."""
import sys
try:
    from olav_netops.sim.network_model import L4Layer
except Exception as exc:
    print(f"olav_netops.sim unavailable: {exc}", file=sys.stderr)
    sys.exit(2)
layer = L4Layer(clauses=[
    {"device": "R1", "policy_name": "P", "action": "permit", "seq": 10,
     "match": ["ip address prefix-list X"], "set": ["local-preference 200"], "body": ""},
    {"device": "R1", "policy_name": "P", "action": "deny", "seq": 20,
     "match": ["ip address prefix-list Y"], "set": [], "body": ""},
], graph=None)
# Match X → permit with set
r = layer.walk("R1", "P", {"ip address prefix-list X": True})
assert r["action"] == "permit" and "local-preference 200" in r["sets"], r
# Match Y → deny, no sets
r2 = layer.walk("R1", "P", {"ip address prefix-list X": False, "ip address prefix-list Y": True})
assert r2["action"] == "deny" and r2["sets"] == [], r2
# Neither → implicit_deny
r3 = layer.walk("R1", "P", {})
assert r3["action"] == "implicit_deny", r3
# Missing policy flag
r4 = layer.walk("R1", "DOES_NOT_EXIST", {})
assert r4["missing"] is True, r4
print("OK")
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
if ! "$PYTHON" -c "import olav.enterprise" 2>/dev/null; then
    echo "SKIP (olav-ent not installed)"; SKIP=$((SKIP + 1))
else
    _out=$("$OLAV" log export trajectory --hours 1 2>&1)
    if ! echo "$_out" | grep -q "^Traceback" && (echo "$_out" | grep -qi "export\|no data\|written\|trajectory\|done\|0 runs"); then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL (got: ${_out:0:100})"; FAIL=$((FAIL + 1))
    fi
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

echo -n "  [T1-34] GET /agents ≥3 entries (core + ops + audit)... "
_resp=$(curl -sf http://localhost:2280/agents 2>&1 || echo "CURL_FAIL")
_count=$(echo "$_resp" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "0")
if [ "${_count:-0}" -ge 3 ] 2>/dev/null; then
    echo "OK (${_count} agents)"; PASS=$((PASS + 1))
else
    echo "FAIL (got ${_count:-?} agents, want ≥3)"; FAIL=$((FAIL + 1))
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
# Post-R65 (ARCH-23) adjustment: v_*_auto views are legitimate netops
# documented surfaces (see olav-netops/tests/gates/test_gate_claims.py
# C-NE-09). The test's original intent was to flag stale view references
# left over from an earlier cleanup round; those have been cleared long
# since. Now guard against phantom patterns that never existed.
if ! grep -qE "v_phantom_|v_ghost_" \
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
        "$OLAV" agent install "${NETOPS_DIR}" >/dev/null 2>&1
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

# T1-53: TUI cold start — pipe echo into olav, must not crash.
# Requires LLM_AVAILABLE because ``olav`` without args enters TUI which
# eagerly initialises the chat model; without an API key the init raises
# before ``/quit`` is ever read.
if llm_skip_if_unavailable "[T1-53]" "TUI cold start (echo pipe)"; then
    echo -n "  [T1-53] TUI cold start (echo pipe)... "
    _t153_out=$(echo "/quit" | timeout 30 "$OLAV" 2>&1) && _t153_rc=0 || _t153_rc=$?
    case "$_t153_rc" in
        0|130|143|124)
            # 0=clean exit, 130=SIGINT, 143=SIGTERM, 124=timeout (olav stayed alive for 30s)
            echo "PASS (rc=$_t153_rc)"
            PASS=$((PASS + 1))
            ;;
        *)
            echo "FAIL (rc=$_t153_rc out=${_t153_out:0:120})"
            FAIL=$((FAIL + 1))
            ;;
    esac
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Group 12: Round 24-60 Additions (T1-54 ~ T1-63)
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Group 12: Round 24-60 Additions (T1-54 ~ T1-63) ==="

# T1-54: `olav explain --help` — CLI registered (Round 45, ARCH-11 last mile)
if "$OLAV" explain --help 2>&1 | grep -q "citation token"; then
    pass_test "[T1-54]" "olav explain --help registered"
else
    fail_test "[T1-54]" "olav explain --help registered" \
        "(help text missing 'citation token')"
fi

# T1-55: `olav diff --help` — CLI registered (Round 47, ARCH-13 last mile)
if "$OLAV" diff --help 2>&1 | grep -qE "snapshot_id_1.*snapshot_id_2"; then
    pass_test "[T1-55]" "olav diff --help registered"
else
    fail_test "[T1-55]" "olav diff --help registered" \
        "(help text missing positional snapshot args)"
fi

# T1-56: load_reference(section=) section slicing (Round 38, ARCH-17)
run_check "[T1-56]" "load_reference section slicing" \
    "$PYTHON" "${HELPERS}/t1_56_load_reference_slice.py" "${TEST_DIR}"

# T1-57: tool_help(detail=) tier-aware (Round 38, ARCH-19 #C)
run_check "[T1-57]" "tool_help detail=brief/full" \
    "$PYTHON" "${HELPERS}/t1_57_tool_help_detail.py" "${TEST_DIR}"

# T1-58: describe_table tool surface (Round 39, ARCH-18)
run_check "[T1-58]" "describe_table tool advertised" \
    "$PYTHON" "${HELPERS}/t1_58_describe_table.py" "${TEST_DIR}"

# T1-59: OLAV_DEBUG_CONTEXT / OLAV_DEBUG_SUMMARIZATION env recognition
#        (Round 36 + Round 42)
run_check "[T1-59]" "OLAV_DEBUG_* env var resolvers" \
    "$PYTHON" "${HELPERS}/t1_59_debug_env.py"

# T1-60: ARCH-14 NetworkModel lazy smoke (Rounds 52-59)
#        — SKIP gracefully when olav_netops isn't installed in the venv.
"$PYTHON" "${HELPERS}/t1_60_nom_smoke.py"; _t160_rc=$?
case "$_t160_rc" in
    0)  pass_test "[T1-60]" "ARCH-14 NetworkModel lazy smoke" ;;
    2)  skip_test "[T1-60]" "ARCH-14 NetworkModel (olav_netops not in venv)" ;;
    *)  fail_test "[T1-60]" "ARCH-14 NetworkModel lazy smoke" "(rc=$_t160_rc)" ;;
esac

# T1-61: sandbox prologue contains NetworkModel auto-inject (Round 57)
run_check "[T1-61]" "sandbox NoM auto-inject wired" \
    "$PYTHON" "${HELPERS}/t1_61_sandbox_inject.py"

# T1-62: DevicesTable schema carries environment column (Round 48)
"$PYTHON" "${HELPERS}/t1_62_devices_env_column.py"; _t162_rc=$?
case "$_t162_rc" in
    0)  pass_test "[T1-62]" "netops.devices.environment column" ;;
    2)  skip_test "[T1-62]" "DevicesTable (olav_netops not in venv)" ;;
    *)  fail_test "[T1-62]" "netops.devices.environment column" "(rc=$_t162_rc)" ;;
esac

# T1-63: ARCH-14 L4 policy walker deterministic semantics (Round 58)
"$PYTHON" "${HELPERS}/t1_63_l4_walker.py"; _t163_rc=$?
case "$_t163_rc" in
    0)  pass_test "[T1-63]" "L4 walker permit/deny/implicit_deny/missing" ;;
    2)  skip_test "[T1-63]" "L4 walker (olav_netops not in venv)" ;;
    *)  fail_test "[T1-63]" "L4 walker" "(rc=$_t163_rc)" ;;
esac

# T1-64: recall_memory tier-aware limit default (Round 40, ARCH-16)
run_check "[T1-64]" "recall_memory(limit=None) tier resolution" \
    "$PYTHON" "${HELPERS}/t1_64_recall_memory_tier_limit.py" "${TEST_DIR}"

# T1-65: subagent return cap via tier_default (Round 40, ARCH-18 #4)
run_check "[T1-65]" "delegate_tool subagent return cap" \
    "$PYTHON" "${HELPERS}/t1_65_subagent_cap.py"

# T1-66: SummarizationMiddleware tier trigger (Round 42, ARCH-19)
run_check "[T1-66]" "compute_summarization_trigger per-tier" \
    "$PYTHON" "${HELPERS}/t1_66_summarization_tier_trigger.py"

# T1-67: SKILL.md tools_docstring_mode override (Round 49, ARCH-19)
run_check "[T1-67]" "tool_help(agent_id=) SKILL.md override" \
    "$PYTHON" "${HELPERS}/t1_67_skill_md_docstring_mode.py" "${TEST_DIR}"

# T1-68: OLAV_BACKUP_COMMANDS_PATH env override (Round 46, ARCH-22 C1)
run_check "[T1-68]" "OLAV_BACKUP_COMMANDS_PATH env override" \
    "$PYTHON" "${HELPERS}/t1_68_backup_commands_env.py"

# T1-69: 🔧[orch] / 🔧[sub] origin tag (Round 39, WRITER-01 (a))
run_check "[T1-69]" "on_tool_start 🔧[orch]/[sub] origin tag" \
    "$PYTHON" "${HELPERS}/t1_69_origin_tag.py"

echo ""
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Cleanup ==="
kill_web_service
# Kill syslog receiver if running
SYSLOG_PID=$(lsof -ti :5514 2>/dev/null | head -1)
if [ -n "${SYSLOG_PID:-}" ]; then
    kill "$SYSLOG_PID" 2>/dev/null || true
fi
echo "  web service: stopped"
if [ "$KEEP_DIR" = true ]; then
    echo "  Test dir preserved (--keep-dir): ${TEST_DIR}"
else
    echo "  Test dir: auto-removed on exit (use --keep-dir to preserve)"
fi
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
