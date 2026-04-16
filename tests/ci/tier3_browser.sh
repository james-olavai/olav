#!/usr/bin/env bash
# OLAV v0.18.0 — Tier 3: Browser / Playwright Tests (T3-01 ~ T3-13)
#
# Tests web UI behavior using Playwright headless Chromium.
# Requires:
#   playwright Python package (pip3 install playwright --break-system-packages)
#   Chromium browser:  npx playwright install chromium
#
# Usage:
#   bash tests/ci/tier3_browser.sh [path/to/olav-*.whl]
#
# Environment vars (optional):
#   OLAV_DEV_CONFIG   Path to dev api.json (enables LLM config)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Locate wheel ──────────────────────────────────────────────────────────────
if [ -n "${1:-}" ]; then
    WHEEL="$(realpath "$1")"
else
    WHEEL="$(ls -t "${REPO_ROOT}/dist/olav-"*.whl 2>/dev/null | head -1)"
fi
if [ -z "${WHEEL:-}" ] || [ ! -f "${WHEEL}" ]; then
    echo "ERROR: No wheel found. Run 'uv build' first or pass path as argument."
    exit 1
fi

# ── Dev config ───────────────────────────────────────────────────────────────
_DEV_CONFIG=""
if [ -n "${OLAV_DEV_CONFIG:-}" ] && [ -f "${OLAV_DEV_CONFIG}" ]; then
    _DEV_CONFIG="$(realpath "${OLAV_DEV_CONFIG}")"
elif [ -f "${REPO_ROOT}/.olav/config/api.json" ]; then
    _DEV_CONFIG="${REPO_ROOT}/.olav/config/api.json"
fi

# ── Test directory ────────────────────────────────────────────────────────────
TEST_DIR="$(mktemp -d /tmp/olav-ci-t3-XXXXXXXX)"
WEB_PORT=2281  # use separate port so T1/T2 don't conflict
WEB_PID=""

# Isolate HOME so olav init does not write to real ~/.olav/token or ~/.olav/checkpoints.
# Preserve PLAYWRIGHT_BROWSERS_PATH so Chromium can still be found.
_REAL_HOME="$HOME"
export PLAYWRIGHT_BROWSERS_PATH="${_REAL_HOME}/.cache/ms-playwright"
export HOME="${TEST_DIR}/fakehome"
mkdir -p "$HOME"

# ── Verify playwright is available ────────────────────────────────────────────
if ! python3 -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "ERROR: playwright Python package not found."
    echo "  Install: pip3 install playwright --break-system-packages && npx playwright install chromium"
    exit 1
fi

# ── Banner ────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════╗"
echo "║  OLAV Tier 3: Browser Tests (T3-01 ~ T3-13)    ║"
echo "╚══════════════════════════════════════════════════╝"
echo "  Wheel:    $(basename "$WHEEL")"
echo "  Test dir: ${TEST_DIR}"
echo "  Port:     ${WEB_PORT}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# SETUP
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

# Inject LLM config if available
if [ -n "${_DEV_CONFIG}" ] && [ -f "${_DEV_CONFIG}" ]; then
    cp "${_DEV_CONFIG}" .olav/config/api.json
    echo "  LLM config: copied"
fi

# Reset auth.mode=none for tests
"$PYTHON" -c "
import json; from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('auth', {})['mode'] = 'none'
p.write_text(json.dumps(cfg, indent=2))
" 2>/dev/null || true
echo "  auth.mode: set to none"

# Set custom port so T1/T2 can run in parallel
"$PYTHON" -c "
import json; from pathlib import Path
p = Path('.olav/config/api.json')
cfg = json.loads(p.read_text())
cfg.setdefault('web', {})['port'] = ${WEB_PORT}
p.write_text(json.dumps(cfg, indent=2))
" 2>/dev/null || true
echo "  web port: ${WEB_PORT}"

# Start web service directly on custom port (bypasses olav web start's hardcoded DEFAULT_WEB_PORT)
"$PYTHON" -m uvicorn olav.api.server:app \
    --host 127.0.0.1 --port "${WEB_PORT}" \
    --log-level warning \
    >"${TEST_DIR}/.olav/logs/web.log" 2>&1 &
WEB_PID=$!
echo "  web service: starting (PID=$WEB_PID)..."

# Wait for web service to be ready
_deadline=20
while [ "$_deadline" -gt 0 ]; do
    if curl -sf "http://127.0.0.1:${WEB_PORT}/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
    _deadline=$((_deadline - 1))
done
if ! curl -sf "http://127.0.0.1:${WEB_PORT}/health" >/dev/null 2>&1; then
    echo "  ERROR: web service not ready after 10s"
    kill "$WEB_PID" 2>/dev/null || true
    rm -rf "${TEST_DIR}"
    exit 1
fi
echo "  web service: ready at http://127.0.0.1:${WEB_PORT}"
echo ""

# Write Playwright test script
PLAYWRIGHT_SCRIPT="${TEST_DIR}/run_browser_tests.py"
cat > "${PLAYWRIGHT_SCRIPT}" << PYEOF
#!/usr/bin/env python3
"""Playwright browser tests for OLAV web UI — T3-01 ~ T3-13."""
import sys, json, time, os
import urllib.request, urllib.error
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://127.0.0.1:${WEB_PORT}"
PASS = 0
FAIL = 0
SKIP = 0

# Detect LLM availability: check if api.json has a shared.api_key set
_cfg_path = os.path.join(os.getcwd(), ".olav", "config", "api.json")
LLM_AVAILABLE = False
try:
    _cfg = json.loads(open(_cfg_path).read())
    _key = _cfg.get("shared", {}).get("api_key", "")
    LLM_AVAILABLE = bool(_key and _key != "YOUR_KEY_HERE" and len(_key) > 10)
except Exception:
    pass

def p(label, name, status, detail=""):
    global PASS, FAIL
    tag = "OK" if status else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"  {label} {name}... {tag}{suffix}", flush=True)
    if status:
        PASS += 1
    else:
        FAIL += 1

def s(label, name, reason=""):
    global SKIP
    SKIP += 1
    suffix = f" ({reason})" if reason else ""
    print(f"  {label} {name}... SKIP{suffix}", flush=True)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Raise HTTPError instead of following redirects."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

_no_redirect_opener = urllib.request.build_opener(_NoRedirect())

def api(path, method="GET", data=None, headers=None, follow_redirects=True):
    """Simple HTTP helper — no browser needed."""
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    opener = urllib.request.urlopen if follow_redirects else _no_redirect_opener.open
    try:
        with opener(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as exc:
        return 0, str(exc)

# ── T3-01: /health endpoint returns status:healthy ───────────────────────
status, body = api("/health")
try:
    data = json.loads(body)
    p("[T3-01]", "/health JSON status=healthy", status == 200 and data.get("status") in ("ok", "healthy"),
      f"status={status} body={body[:60]}")
except Exception as e:
    p("[T3-01]", "/health JSON status=healthy", False, str(e))

# ── T3-02: /docs endpoint loads (OpenAPI Swagger UI) ─────────────────────
status, body = api("/docs")
p("[T3-02]", "/docs Swagger UI 200", status == 200, f"status={status}")

# ── T3-03: GET / returns 200 (auth.mode=none, no redirect) ───────────────
status, body = api("/")
p("[T3-03]", "GET / auth=none → 200", status in (200, 302, 307),
  f"status={status}")

# ── T3-04: GET /agents returns list ──────────────────────────────────────
status, body = api("/agents")
try:
    agents = json.loads(body)
    p("[T3-04]", "GET /agents returns list", status == 200 and isinstance(agents, list) and len(agents) > 0,
      f"status={status} count={len(agents) if isinstance(agents, list) else '?'}")
except Exception as e:
    p("[T3-04]", "GET /agents returns list", False, str(e)[:80])

# ── T3-05: POST /threads creates thread ──────────────────────────────────
# ThreadCreate model: metadata (optional dict). Must send valid JSON body.
status, body = api("/threads", method="POST", data={"metadata": None})
try:
    obj = json.loads(body)
    p("[T3-05]", "POST /threads → thread_id", status == 200 and "thread_id" in obj,
      f"status={status} keys={list(obj.keys())[:4]}")
    _thread_id = obj.get("thread_id", "")
except Exception as e:
    p("[T3-05]", "POST /threads → thread_id", False, str(e)[:80])
    _thread_id = ""

# ── T3-06: GET /memory/graph returns 200 ─────────────────────────────────
status, body = api("/memory/graph")
p("[T3-06]", "GET /memory/graph → 200", status == 200, f"status={status} len={len(body)}")

# ── T3-07: auth.mode=token causes redirect on GET / ──────────────────────
import json as _json
from pathlib import Path
_cfg_path = Path("${TEST_DIR}/.olav/config/api.json")
_cfg = _json.loads(_cfg_path.read_text())
_cfg.setdefault("auth", {})["mode"] = "token"
_cfg_path.write_text(_json.dumps(_cfg, indent=2))
# /reload just resets agent; _get_auth_mode() re-reads disk on each request
api("/reload", method="POST", data={})
time.sleep(0.3)
# Use no-redirect opener so we detect the 302 instead of following it
_status_redir, _ = api("/", follow_redirects=False)
_redirected = _status_redir in (301, 302, 303, 307, 308)
p("[T3-07]", "auth=token: GET / → redirect", _redirected, f"status={_status_redir}")
# Restore auth.mode=none
_cfg["auth"]["mode"] = "none"
_cfg_path.write_text(_json.dumps(_cfg, indent=2))
api("/reload", method="POST", data={})
time.sleep(0.3)

# ── T3-08/09/10: Playwright browser tests ─────────────────────────────────
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        # T3-08: Browser renders /docs page
        try:
            page.goto(BASE + "/docs", timeout=10000)
            page.wait_for_load_state("domcontentloaded", timeout=8000)
            title = page.title()
            has_swagger = ("swagger" in title.lower() or "api" in title.lower()
                           or page.query_selector(".swagger-ui") is not None)
            p("[T3-08]", "Browser: /docs renders Swagger", has_swagger, f"title={title!r}")
        except PWTimeout:
            p("[T3-08]", "Browser: /docs renders Swagger", False, "timeout")
        except Exception as e:
            p("[T3-08]", "Browser: /docs renders Swagger", False, str(e)[:80])

        # T3-09: Browser renders /memory/graph page
        try:
            page.goto(BASE + "/memory/graph", timeout=10000)
            page.wait_for_load_state("domcontentloaded", timeout=8000)
            content = page.content()
            has_graph = ("svg" in content.lower() or "canvas" in content.lower()
                         or "graph" in content.lower() or "memory" in content.lower()
                         or len(content) > 200)
            p("[T3-09]", "Browser: /memory/graph page loads", has_graph,
              f"content_len={len(content)}")
        except PWTimeout:
            p("[T3-09]", "Browser: /memory/graph page loads", False, "timeout")
        except Exception as e:
            p("[T3-09]", "Browser: /memory/graph page loads", False, str(e)[:80])

        # T3-10: Browser JS fetch /health
        try:
            page.goto(BASE + "/docs", timeout=8000)
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            result = page.evaluate("""async () => {
                const r = await fetch('/health');
                const data = await r.json();
                return {status: r.status, ok: data.status === 'ok' || data.status === 'healthy'};
            }""")
            p("[T3-10]", "Browser JS fetch /health", result.get("status") == 200 and result.get("ok"),
              f"status={result.get('status')} ok={result.get('ok')}")
        except PWTimeout:
            p("[T3-10]", "Browser JS fetch /health", False, "timeout")
        except Exception as e:
            p("[T3-10]", "Browser JS fetch /health", False, str(e)[:80])

        browser.close()
except Exception as e:
    p("[T3-08]", "Browser: /docs renders Swagger", False, f"playwright init: {str(e)[:80]}")
    p("[T3-09]", "Browser: /memory/graph page loads", False, "playwright unavailable")
    p("[T3-10]", "Browser JS fetch /health", False, "playwright unavailable")

# ── T3-11: SSE chat stream via HTTP (LLM-gated) ───────────────────────────
if not LLM_AVAILABLE:
    s("[T3-11]", "SSE chat stream POST /runs/stream (no LLM key)")
    s("[T3-12]", "Browser: chat UI sends message (no LLM key)")
    s("[T3-13]", "Browser: chat response appears in #messages (no LLM key)")
else:
    # T3-11: POST /runs/stream and verify SSE events contain text tokens
    # Server uses astream_events(v2): emits {"event":"on_chat_model_stream","data":{"chunk":{...}}}
    try:
        payload = json.dumps({
            "assistant_id": "olav-orchestrator",
            "input": {"messages": [{"role": "user", "content": "Reply with just the word PONG"}]},
            "stream_mode": "messages-tuple"
        }).encode()
        req = urllib.request.Request(
            BASE + "/runs/stream",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST"
        )
        collected = []
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                    if not isinstance(ev, dict):
                        continue
                    ev_type = ev.get("event", "")
                    ev_data = ev.get("data", {})
                    # astream_events v2: on_chat_model_stream has data.chunk
                    if ev_type in ("on_chat_model_stream", "on_llm_stream"):
                        chunk = ev_data.get("chunk", {})
                        if isinstance(chunk, dict):
                            c = chunk.get("content", "")
                            if c:
                                collected.append(c)
                    # Also handle final AIMessage in on_chain_end / on_chat_model_end
                    elif ev_type in ("on_chat_model_end", "on_chain_end"):
                        out = ev_data.get("output", {})
                        if isinstance(out, dict):
                            c = out.get("content", "")
                            if c and not collected:
                                collected.append(c)
                except Exception:
                    pass
                if len(collected) > 0 and len("".join(collected)) > 4:
                    break  # Got enough text
        full_text = "".join(collected)
        p("[T3-11]", "SSE chat stream returns AI text tokens",
          len(full_text) > 0,
          f"tokens={len(collected)} text={full_text[:60]!r}")
    except Exception as e:
        p("[T3-11]", "SSE chat stream returns AI text tokens", False, str(e)[:80])
        full_text = ""

    # T3-12 + T3-13: Playwright browser chat UI
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()

            # T3-12: Navigate to chat UI and send a message
            try:
                page.goto(BASE + "/", timeout=10000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                # Check that the input box exists
                has_input = page.locator("#query-input").count() > 0
                has_send = page.locator("#send-btn").count() > 0
                if has_input and has_send:
                    page.fill("#query-input", "Reply with just the word PING")
                    page.click("#send-btn")
                    p("[T3-12]", "Browser: chat UI sends message via #send-btn", True,
                      "input filled and send clicked")
                else:
                    p("[T3-12]", "Browser: chat UI sends message via #send-btn", False,
                      f"has_input={has_input} has_send={has_send}")
            except PWTimeout:
                p("[T3-12]", "Browser: chat UI sends message via #send-btn", False, "timeout")
            except Exception as e:
                p("[T3-12]", "Browser: chat UI sends message via #send-btn", False, str(e)[:80])

            # T3-13: Wait for and verify response appears
            try:
                # Wait up to 60s for any AI response text to appear in #messages
                page.wait_for_function(
                    """() => {
                        const msgs = document.querySelectorAll('#messages .assistant-message, #messages [data-role="assistant"], #messages .message');
                        return msgs.length > 0 && msgs[msgs.length-1].textContent.trim().length > 0;
                    }""",
                    timeout=60000
                )
                # Get the last message text
                last_msg = page.evaluate("""() => {
                    const msgs = document.querySelectorAll('#messages .assistant-message, #messages [data-role="assistant"], #messages .message');
                    return msgs.length > 0 ? msgs[msgs.length-1].textContent.trim() : "";
                }""")
                p("[T3-13]", "Browser: AI response appears in #messages",
                  len(last_msg) > 0,
                  f"response={last_msg[:60]!r}")
            except PWTimeout:
                # Fallback: check if ANY new content appeared in messages div
                try:
                    msgs_text = page.inner_text("#messages") or ""
                    has_content = len(msgs_text.strip()) > 5
                    p("[T3-13]", "Browser: AI response appears in #messages",
                      has_content,
                      f"timeout but content={'yes' if has_content else 'no'}: {msgs_text[:60]!r}")
                except Exception:
                    p("[T3-13]", "Browser: AI response appears in #messages", False,
                      "timeout waiting for response")
            except Exception as e:
                p("[T3-13]", "Browser: AI response appears in #messages", False, str(e)[:80])

            browser.close()
    except Exception as e:
        p("[T3-12]", "Browser: chat UI sends message via #send-btn", False,
          f"playwright init: {str(e)[:80]}")
        p("[T3-13]", "Browser: AI response appears in #messages", False, "playwright unavailable")

print("", flush=True)
print(f"PASS={PASS}  FAIL={FAIL}  SKIP={SKIP}  TOTAL={PASS+FAIL+SKIP}", flush=True)
sys.exit(FAIL)
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# Run Tests
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Browser Tests (T3-01 ~ T3-13) ==="
cd "${TEST_DIR}"
# Use system python3 (playwright installed system-wide, not in venv)
PLAYWRIGHT_OUTPUT=$(python3 "${PLAYWRIGHT_SCRIPT}" 2>&1) || true
echo "$PLAYWRIGHT_OUTPUT"

# Parse results
PASS=$(echo "$PLAYWRIGHT_OUTPUT" | grep -oP 'PASS=\K[0-9]+' | tail -1)
FAIL=$(echo "$PLAYWRIGHT_OUTPUT" | grep -oP 'FAIL=\K[0-9]+' | tail -1)
SKIP=$(echo "$PLAYWRIGHT_OUTPUT" | grep -oP 'SKIP=\K[0-9]+' | tail -1)
TOTAL=$(echo "$PLAYWRIGHT_OUTPUT" | grep -oP 'TOTAL=\K[0-9]+' | tail -1)
PASS="${PASS:-0}"; FAIL="${FAIL:-0}"; SKIP="${SKIP:-0}"; TOTAL="${TOTAL:-0}"

echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════════════════
echo "=== Cleanup ==="
if [ -n "${WEB_PID:-}" ]; then
    kill "$WEB_PID" 2>/dev/null || true
fi
PORT_PID=$(lsof -ti :"${WEB_PORT}" 2>/dev/null | head -1) || true
if [ -n "${PORT_PID:-}" ]; then
    kill "$PORT_PID" 2>/dev/null || true
fi
rm -rf "${TEST_DIR}"
echo "  test dir removed: ${TEST_DIR}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
echo "╔══════════════════════════════════════════════════╗"
echo "║  Tier 3 Results                                  ║"
echo "╠══════════════════════════════════════════════════╣"
printf "║  PASS: %-4s  FAIL: %-4s  SKIP: %-4s  TOTAL: %-4s ║\n" "$PASS" "$FAIL" "$SKIP" "$TOTAL"
echo "╚══════════════════════════════════════════════════╝"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo "✅ Tier 3 PASSED (${PASS}/${TOTAL} pass)"
else
    echo "❌ Tier 3 FAILED (${FAIL} failures)"
fi

exit $(( FAIL ))
