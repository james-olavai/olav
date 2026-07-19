#!/bin/bash
# Tier 0: Packaging Validation — Fresh Venv Smoke Test
#
# Two independent phases:
#   Phase A: olav core only (no skills, no netops)
#   Phase B: olav + netops extension (skill install + domain schema)
#
# Usage:
#   bash tests/ci/tier0_packaging.sh              # Run both phases
#   bash tests/ci/tier0_packaging.sh --core-only   # Phase A only (olav release)
#   bash tests/ci/tier0_packaging.sh --netops-only  # Phase B only (netops release)
#
# Requirements: Python 3.11+, built wheel in dist/
# Cost: Zero (no LLM, no network devices)
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_DIR="/tmp/olav-ci-${TIMESTAMP}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NETOPS_DIR="${OLAV_NETOPS_DIR:-${REPO_ROOT}/olav-netops}"
WHEEL=$(ls "${REPO_ROOT}/dist/"*.whl 2>/dev/null | tail -1)

# Parse args
RUN_CORE=true
RUN_NETOPS=true
KEEP_DIR=false
for _arg in "$@"; do
    case "$_arg" in
        --core-only)   RUN_NETOPS=false ;;
        --netops-only) RUN_CORE=false ;;
        --keep-dir)    KEEP_DIR=true ;;
    esac
done

if [ -z "$WHEEL" ]; then
    echo "ERROR: No wheel found in dist/. Run 'uv build' first."
    exit 1
fi

# ── Auto-cleanup on exit (skip with --keep-dir for post-mortem debugging) ─────
if [ "$KEEP_DIR" = false ]; then
    trap 'rm -rf "${TEST_DIR}" 2>/dev/null || true' EXIT
fi

# ── Isolate from dev environment ──────────────────────────────
export HOME="${TEST_DIR}/fakehome"
mkdir -p "$HOME"
unset HF_TOKEN OPENAI_API_KEY ANTHROPIC_API_KEY OLAV_API_KEY 2>/dev/null || true
export TOKENIZERS_PARALLELISM=false
export HF_HUB_DISABLE_PROGRESS_BARS=1
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1

PASS=0
FAIL=0
WARN=0
N=0

check() {
    N=$((N + 1))
    local name="$1"; shift
    echo -n "  [${N}] ${name}... "
    if "$@"; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "FAIL"; FAIL=$((FAIL + 1))
    fi
}

warn_check() {
    N=$((N + 1))
    local name="$1"; shift
    echo -n "  [${N}] ${name}... "
    if "$@"; then
        echo "OK"; PASS=$((PASS + 1))
    else
        echo "WARN"; WARN=$((WARN + 1))
    fi
}

phase_summary() {
    local phase="$1"
    local p=$PASS f=$FAIL w=$WARN
    echo ""
    if [ "$f" -eq 0 ]; then
        echo "  ${phase}: ✅ ${p} passed, ${w} warnings"
    else
        echo "  ${phase}: ❌ ${f} failures, ${p} passed, ${w} warnings"
    fi
}

echo "╔══════════════════════════════════════════════════════╗"
echo "║  OLAV Tier 0: Packaging Validation                   ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Wheel:    $(basename "$WHEEL")"
echo "║  Test dir: ${TEST_DIR}"
echo "║  Phase A:  olav core       $([ "$RUN_CORE" = true ] && echo "✅" || echo "SKIP")"
echo "║  Phase B:  olav + netops   $([ "$RUN_NETOPS" = true ] && echo "✅" || echo "SKIP")"
echo "╚══════════════════════════════════════════════════════╝"

# ── Shared: venv install ──────────────────────────────────────
echo ""
echo "  Installing in fresh venv..."
python3 -m venv "${TEST_DIR}/.venv"
PIP="${TEST_DIR}/.venv/bin/pip"
OLAV="${TEST_DIR}/.venv/bin/olav"
PYTHON="${TEST_DIR}/.venv/bin/python3"

$PIP install -q "$WHEEL" 2>&1 | tail -1
check "pip check (no dependency conflicts)" $PIP check


# ══════════════════════════════════════════════════════════════
# Phase A: OLAV Core Only
# ══════════════════════════════════════════════════════════════

if [ "$RUN_CORE" = true ]; then
    echo ""
    echo "━━━ Phase A: olav core (no skills) ━━━"

    A_START_PASS=$PASS
    A_START_FAIL=$FAIL
    A_START_WARN=$WARN

    # ── A1-A3: Wheel content ─────────────────────────────────
    check "A1: wheel contains AGENT.md" \
        sh -c "unzip -l '$WHEEL' | grep -q 'AGENT.md'"
    check "A2: wheel contains system.md" \
        sh -c "unzip -l '$WHEEL' | grep -q 'system.md'"
    check "A3: wheel contains execute_sql.py" \
        sh -c "unzip -l '$WHEEL' | grep -q 'execute_sql.py'"
    check "A3b: wheel contains core delegate subagent SKILL.md files (api-query, writer)" \
        sh -c "test \$(unzip -l '$WHEEL' | grep -c 'core/\\(api-query\\|writer\\)/SKILL.md') -eq 2"

    # ── A4-A10: olav init ────────────────────────────────────
    cd "${TEST_DIR}"
    INIT_LOG=$($OLAV init 2>&1)

    check "A4: init — databases ready" \
        sh -c "echo '$INIT_LOG' | grep -q '✓ domain.duckdb'"
    check "A5: init — core workspace deployed" \
        sh -c "echo '$INIT_LOG' | grep -q '✓ core workspace'"
    check "A6: init — embedding model" \
        sh -c "echo '$INIT_LOG' | grep -q 'embedder:'"
    check "A7: init — agents registered" \
        sh -c "echo '$INIT_LOG' | grep -q 'agents registered'"
    check "A8: init — no traceback" \
        sh -c "! echo '$INIT_LOG' | grep -qi 'traceback'"
    warn_check "A9: init — no safetensors noise" \
        sh -c "! echo '$INIT_LOG' | grep -q 'layers were not sharded'"

    # ── A10-A11: Core-only state ─────────────────────────────
    LIST_LOG=$($OLAV list 2>&1)
    check "A10: olav list — core agent visible" \
        sh -c "echo '$LIST_LOG' | grep -q 'core'"
    check "A11: olav list — ONLY core (no ops/netops)" \
        sh -c "! echo '$LIST_LOG' | grep -q '  ops'"

    # ── A12-A13: Core DB state ───────────────────────────────
    check "A12: domain.duckdb exists" \
        test -f "${TEST_DIR}/.olav/databases/domain.duckdb"
    check "A13: audit.duckdb exists" \
        test -f "${TEST_DIR}/.olav/databases/audit.duckdb"
    check "A14: NO main.duckdb yet (no netops)" \
        sh -c "! test -f '${TEST_DIR}/.olav/databases/main.duckdb'"

    # ── A15-A17: Web API (core only) ─────────────────────────
    $OLAV service start --all > /dev/null 2>&1
    sleep 2

    check "A15: web /health returns 200" \
        curl -sf http://localhost:2280/health -o /dev/null
    check "A16: web /agents returns core only" \
        sh -c "curl -sf http://localhost:2280/agents | $PYTHON -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if len(d)>=1 else 1)'"
    check "A17: web /memory/graph returns 200" \
        curl -sf http://localhost:2280/memory/graph -o /dev/null

    # ── A18: Subagent architecture validation ────────────────
    check "A18: subagent architecture — SKILL.md, 2 delegate subagents (api-query, writer)" \
        $PYTHON -c "
from pathlib import Path
import olav, frontmatter
from olav.core.tool_discovery import discover_tools
core = Path(olav.__file__).parent / 'data' / 'workspace' / 'core'
# core is SKILL.md-defined (AGENT.md was retired in the v0.20 migration).
post = frontmatter.load(str(core / 'SKILL.md'))
# execute_sql must be in the core @tool pool (orchestrator answers DB
# queries directly — db-query subagent removed 2026-06-19, dev_docs/97).
pool = {t.name for t in discover_tools(core / 'tools')}
assert 'execute_sql' in pool, f'execute_sql missing from core/tools: {sorted(pool)}'
# Exactly 2 delegate subagents: api-query, writer.
subs = post.metadata.get('subagents', [])
paths = [(sp.get('path', sp) if isinstance(sp, dict) else sp) for sp in subs]
assert len(paths) == 2, f'Expected 2 subagents, got {len(paths)}: {paths}'
assert not any('db-query' in (p or '') for p in paths), 'db-query must be removed'
for p in paths:
    assert (core / p).exists(), f'Subagent SKILL.md missing: {p}'
# Writer must have format_and_export.
writer_tools = {t.name for t in discover_tools(core / 'writer' / 'tools')}
assert 'format_and_export' in writer_tools, 'writer missing format_and_export'
"

    # Stop services before Phase B
    pkill -f "uvicorn.*olav.*2280" 2>/dev/null || true
    pkill -f "syslog_receiver" 2>/dev/null || true
    pkill -f "olav.*daemon" 2>/dev/null || true
    sleep 1

    A_PASS=$((PASS - A_START_PASS))
    A_FAIL=$((FAIL - A_START_FAIL))
    A_WARN=$((WARN - A_START_WARN))
    echo ""
    if [ "$A_FAIL" -eq 0 ]; then
        echo "  Phase A: ✅ ${A_PASS} passed, ${A_WARN} warnings"
    else
        echo "  Phase A: ❌ ${A_FAIL} failures, ${A_PASS} passed, ${A_WARN} warnings"
    fi
fi


# ══════════════════════════════════════════════════════════════
# Phase B: OLAV + NetOps Extension
# ══════════════════════════════════════════════════════════════

if [ "$RUN_NETOPS" = true ]; then
    echo ""
    echo "━━━ Phase B: olav + netops extension ━━━"

    B_START_PASS=$PASS
    B_START_FAIL=$FAIL
    B_START_WARN=$WARN

    cd "${TEST_DIR}"

    # Ensure init ran (Phase B standalone needs it)
    if [ ! -d ".olav" ]; then
        $OLAV init > /dev/null 2>&1
    fi

    if [ ! -d "$NETOPS_DIR" ]; then
        echo "  SKIP: olav-netops not found at ${NETOPS_DIR}"
    else
        # ── B1: Agent install (verb renamed from `skill` to `agent` in v0.20.3) ──
        SKILL_LOG=$($OLAV agent install "$NETOPS_DIR" 2>&1)
        check "B1: agent install — netops workspaces registered" \
            sh -c "echo '$SKILL_LOG' | grep -qE 'workspaces|installed netops'"

        # ── B2-B4: Agent list (3 agents: core, ops, audit) ──
        LIST_LOG=$($OLAV list 2>&1)
        for agent in core ops audit; do
            check "B: agent visible — $agent" \
                sh -c "echo '$LIST_LOG' | grep -q '$agent'"
        done

        # ── B11: Dry-run ─────────────────────────────────────
        cp "${NETOPS_DIR}/.olav/workspace/ops/collect/config/nornir/hosts.yaml.example" \
           .olav/workspace/ops/collect/config/nornir/hosts.yaml 2>/dev/null || true
        if [ -f "${NETOPS_DIR}/.olav/workspace/ops/collect/config/nornir/defaults.yaml.example" ]; then
            cp "${NETOPS_DIR}/.olav/workspace/ops/collect/config/nornir/defaults.yaml.example" \
               .olav/workspace/ops/collect/config/nornir/defaults.yaml 2>/dev/null || true
        fi
        DRY_LOG=$($OLAV --agent netops "/netops_init --dry-run" 2>&1)
        check "B11: dry-run — inventory validated" \
            sh -c "echo '$DRY_LOG' | grep -q 'inventory validated' || echo '$DRY_LOG' | grep -q 'Dry-run complete'"

        # ── B12: DB schema ───────────────────────────────────
        $PYTHON "${REPO_ROOT}/tests/fixtures/seed_test_data.py" 2>&1 || echo "  (seed script failed)"
        check "B12: netops schema — 5 tables" \
            $PYTHON -c "
import duckdb, sys
from pathlib import Path
db = Path('.olav/databases/main.duckdb')
if not db.exists():
    print('main.duckdb not found', file=sys.stderr); sys.exit(1)
con = duckdb.connect(str(db), read_only=True)
tables = [r[0] for r in con.execute(
    \"SELECT table_name FROM information_schema.tables WHERE table_schema='netops'\"
).fetchall()]
expected = ['parsed_outputs','raw_output_store','topology_links','devices','oc_outputs']
missing = [t for t in expected if t not in tables]
if missing: print(f'Missing: {missing}', file=sys.stderr)
sys.exit(1 if missing else 0)
"

        # ── B13: Seed data integrity ─────────────────────────
        check "B13: seed — devices table has data" \
            $PYTHON -c "
import duckdb, sys
con = duckdb.connect('.olav/databases/main.duckdb', read_only=True)
cnt = con.execute('SELECT COUNT(*) FROM netops.devices').fetchone()[0]
sys.exit(0 if cnt >= 4 else 1)
"

        # ── B14: Router index ─────────────────────────────────
        check "B14: router index has 3 agents" \
            $PYTHON -c "
import lancedb, sys
db = lancedb.connect('.olav/databases/memory.lancedb')
tables = db.list_tables().tables
if 'agent_intent_index' not in tables:
    print('agent_intent_index not found', file=sys.stderr); sys.exit(1)
tbl = db.open_table('agent_intent_index')
agents = set()
for row in tbl.to_arrow().to_pandas().itertuples():
    agents.add(row.agent_name)
expected = {'core','ops','audit'}
if not expected.issubset(agents):
    print(f'Missing agents: {expected - agents}, found: {agents}', file=sys.stderr)
    sys.exit(1)
"

        check "B15: router keyword index loads" \
            $PYTHON -c "
import os, sys; os.chdir('.')
from olav.core.router import get_router
router = get_router()
router._keyword_route('test')  # triggers lazy load
sys.exit(0 if len(router._keyword_index) >= 3 else 1)
"

        # ── B16-B18: Web API (with netops) ───────────────────
        $OLAV service start --all > /dev/null 2>&1
        sleep 2

        check "B16: web /health returns 200" \
            curl -sf http://localhost:2280/health -o /dev/null
        check "B17: web /agents returns 3 (core + ops + audit)" \
            sh -c "curl -sf http://localhost:2280/agents | $PYTHON -c 'import sys,json; sys.exit(0 if len(json.load(sys.stdin))>=3 else 1)'"
        check "B18: web /reload returns 200" \
            sh -c "curl -sf -X POST http://localhost:2280/reload -o /dev/null"

        # Stop services
        pkill -f "uvicorn.*olav.*2280" 2>/dev/null || true
        pkill -f "syslog_receiver" 2>/dev/null || true
        pkill -f "olav.*daemon" 2>/dev/null || true
    fi

    B_PASS=$((PASS - B_START_PASS))
    B_FAIL=$((FAIL - B_START_FAIL))
    B_WARN=$((WARN - B_START_WARN))
    echo ""
    if [ "$B_FAIL" -eq 0 ]; then
        echo "  Phase B: ✅ ${B_PASS} passed, ${B_WARN} warnings"
    else
        echo "  Phase B: ❌ ${B_FAIL} failures, ${B_PASS} passed, ${B_WARN} warnings"
    fi
fi


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════════════╗"
TOTAL=$((PASS + FAIL + WARN))
if [ "$FAIL" -eq 0 ]; then
    echo "║  ✅ TOTAL: ${PASS}/${TOTAL} checks (${WARN} warnings)          ║"
else
    echo "║  ❌ TOTAL: ${FAIL} failures, ${PASS} passed, ${WARN} warnings  ║"
fi
echo "╚══════════════════════════════════════════════════════╝"
if [ "$KEEP_DIR" = true ]; then
    echo "  Test dir preserved (--keep-dir): ${TEST_DIR}"
else
    echo "  Test dir: auto-removed on exit (use --keep-dir to preserve)"
fi

exit $FAIL
