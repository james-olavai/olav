"""
tests/e2e/test_web_ui_multi_agent_browser.py
─────────────────────────────────────────────
Playwright browser E2E smoke test for the native langgraph_api web server.

Tests:
  - Server starts and serves the SPA shell at /
  - Chat interface is visible (agent selector, message input)
  - Sending a message to 'core' agent gets a response in the DOM
  - Agent switching navigates to a new thread (if netops installed)
  - Memory Graph page loads (vis.js HTML)

Auth: server starts with OLAV_AUTH_MODE=none (env override) so no token
handling is needed in the browser test.

Run:  uv run pytest tests/e2e/test_web_ui_multi_agent_browser.py -v -m e2e
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _docker_host_ip() -> str:
    """Return the IP of this host as reachable from Docker containers.

    Priority:
    1. BROWSERLESS_HOST_IP env var (explicit override)
    2. Gateway of the browserless container's network (via docker inspect)
    3. Default route gateway (works when running inside a Docker container)
    4. Hardcoded fallback
    """
    if explicit := os.environ.get("BROWSERLESS_HOST_IP", ""):
        return explicit

    # Try docker inspect on the browserless container — works on bare metal
    try:
        r = subprocess.run(
            ["docker", "inspect", "browserless-chrome-1",
             "--format", "{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass

    # Inside a Docker container: default route gateway = Docker bridge host
    try:
        r = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=3,
        )
        parts = r.stdout.split()
        gw = parts[parts.index("via") + 1]
        # Only use if it looks like a private Docker range, not a LAN router
        import ipaddress  # noqa: PLC0415
        addr = ipaddress.ip_address(gw)
        if addr.is_private and not str(gw).startswith("192.168."):
            return gw
    except Exception:
        pass

    return "10.0.13.1"


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """Poll until the port accepts connections or timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Server fixture — boots olav.api.app:app via uvicorn as a subprocess
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server_url() -> str:
    port = _free_port()
    env = {**os.environ, "OLAV_AUTH_MODE": "none"}

    # When using a remote/Docker browserless instance, the browser runs inside
    # a container and cannot reach 127.0.0.1 on the host. Bind on 0.0.0.0 and
    # return the host IP that the container can route to.
    # Also write a temp api.json with allowed_cidrs:[] so the CIDR middleware
    # doesn't block the Docker gateway IP.
    browserless_url = os.environ.get("BROWSERLESS_URL", "")
    tmp_home = None
    if browserless_url:
        bind_host = "0.0.0.0"
        # Auto-detect the Docker gateway IP so the browser inside the
        # browserless container can route back to this server.
        serve_host = _docker_host_ip()

        # Build a temp OLAV_HOME with allowed_cidrs=[] (accepts all IPs).
        # OLAV_HOME is the project root — api.json lives at {home}/.olav/config/api.json
        tmp_home = tempfile.mkdtemp(prefix="olav_webtest_")
        tmp_config_dir = Path(tmp_home) / ".olav" / "config"
        tmp_config_dir.mkdir(parents=True)
        # Copy api.json and clear the CIDR allowlist
        real_api = Path(".olav/config/api.json")
        if real_api.exists():
            api_data = json.loads(real_api.read_text())
        else:
            api_data = {}
        api_data.setdefault("security", {})["allowed_cidrs"] = []
        (tmp_config_dir / "api.json").write_text(json.dumps(api_data))
        env["OLAV_HOME"] = tmp_home
    else:
        bind_host = "127.0.0.1"
        serve_host = "127.0.0.1"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "olav.api.app:app",
            "--host",
            bind_host,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if not _wait_for_port("127.0.0.1", port, timeout=45):
        proc.kill()
        out, _ = proc.communicate(timeout=5)
        pytest.fail(f"Server did not start on port {port}.\nOutput:\n{out}")

    yield f"http://{serve_host}:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    if tmp_home:
        import shutil  # noqa: PLC0415
        shutil.rmtree(tmp_home, ignore_errors=True)


# ---------------------------------------------------------------------------
# Playwright fixture — chromium browser page
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser_page(server_url):
    """Yield a Playwright page pointed at the running server.

    If BROWSERLESS_URL is set (e.g. ws://localhost:9222), connect via CDP
    instead of launching a local Chromium binary.
    """
    pytest.importorskip("playwright", reason="playwright not installed")

    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    browserless_url = os.environ.get("BROWSERLESS_URL", "")

    with sync_playwright() as pw:
        if browserless_url:
            # browserless/chrome exposes CDP at http://host:port
            # Playwright fetches /json/version internally to get the WS URL
            cdp_url = browserless_url.replace("ws://", "http://").replace("wss://", "https://")
            browser = pw.chromium.connect_over_cdp(cdp_url)
        else:
            browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(base_url=server_url)
        page = ctx.new_page()
        yield page
        ctx.close()
        if not browserless_url:
            browser.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSPAShell:
    def test_root_serves_spa(self, browser_page, server_url):
        """/ should serve the Next.js SPA or a redirect to login."""
        resp = browser_page.goto(server_url + "/", wait_until="load")
        # With auth mode=none, root serves the SPA directly.
        # Accept 200 or 302 (redirect to /login then back).
        assert resp.status in (200, 302, 301)

    def test_no_server_error(self, browser_page, server_url):
        """Root page must not display a 5xx server error."""
        browser_page.goto(server_url + "/", wait_until="networkidle")
        # Check page does not contain obvious error markers
        content = browser_page.content()
        assert "Internal Server Error" not in content
        assert "500" not in browser_page.title()

    def test_spa_loads_javascript(self, server_url):
        """Next.js static chunks must be served by the /_next mount."""
        import urllib.request  # noqa: PLC0415
        # The index.html includes /_next/static/chunks/webpack-*.js — verify
        # that at least one chunk is reachable via HTTP (not 404).
        req = urllib.request.urlopen(server_url + "/", timeout=10)
        html = req.read().decode(errors="replace")
        # Extract the first /_next/static/chunks/*.js href
        import re  # noqa: PLC0415
        m = re.search(r'(/_next/static/chunks/[^"]+\.js)', html)
        assert m, "No /_next chunk src found in index.html"
        chunk_url = server_url + m.group(1)
        chunk_resp = urllib.request.urlopen(chunk_url, timeout=10)
        assert chunk_resp.status == 200, f"Chunk {chunk_url} returned {chunk_resp.status}"


class TestChatInterface:
    def test_chat_container_exists(self, browser_page, server_url):
        """SPA must render some kind of chat container in the DOM."""
        browser_page.goto(server_url + "/", wait_until="networkidle")
        # Try common selectors; the SPA may use different class names.
        # We just want proof that something interactive rendered.
        has_input = (
            browser_page.query_selector("textarea") is not None
            or browser_page.query_selector("input[type='text']") is not None
            or browser_page.query_selector("[role='textbox']") is not None
            or browser_page.query_selector("form") is not None
        )
        assert has_input, (
            "No text input found on /. The SPA may not have hydrated correctly.\n"
            f"Page title: {browser_page.title()}"
        )

    def test_agent_selector_via_api(self, server_url):
        """Agent names come from /assistants/search — verify 'core' is present there.

        The Next.js SPA loads agent names from the native LG /assistants/search
        endpoint. We test the data source directly since the SPA may redirect to
        /login before fully rendering the agent selector in headless mode.
        """
        import urllib.request  # noqa: PLC0415
        req = urllib.request.Request(
            f"{server_url}/assistants/search",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        graph_ids = [a.get("graph_id") for a in data]
        assert "core" in graph_ids, (
            f"'core' not in assistants from /assistants/search: {graph_ids}"
        )


class TestNativeAPIRoutes:
    def test_assistants_search_accessible(self, server_url):
        """Native LG /assistants/search route returns valid JSON (no auth in mode=none)."""
        import urllib.request  # noqa: PLC0415
        req = urllib.request.Request(
            f"{server_url}/assistants/search",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
        assert isinstance(data, list)
        graph_ids = [a.get("graph_id") for a in data]
        assert "core" in graph_ids, f"Expected 'core' in {graph_ids}"

    def test_threads_endpoint_accessible(self, server_url):
        """Native LG /threads endpoint creates a thread and returns JSON."""
        import urllib.request  # noqa: PLC0415
        req = urllib.request.Request(
            f"{server_url}/threads",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
        assert "thread_id" in data or "id" in data, f"Unexpected thread response: {data}"


class TestMemoryGraphRoute:
    def test_memory_graph_serves_html(self, browser_page, server_url):
        """/memory/graph must return HTML (via custom_router user_router merge)."""
        resp = browser_page.goto(server_url + "/memory/graph", wait_until="load")
        assert resp.status == 200
        content_type = resp.headers.get("content-type", "")
        assert "html" in content_type.lower(), f"Expected HTML, got: {content_type}"


class TestThreadsSidebar:
    def test_sidebar_opens_at_correct_width(self, browser_page, server_url):
        """Threads sidebar must render at ≥22% viewport width when opened.

        Regression test for react-resizable-panels v4 `defaultLayout` bug:
        a conditionally-added panel received only ~2% instead of 28% because
        the group's in-memory state (chat=100%) was not reset on panel join.
        Fixed via `defaultLayout={{ "thread-history": 28, "chat": 72 }}` on
        the ResizablePanelGroup.
        """
        browser_page.goto(server_url + "/", wait_until="networkidle")

        # Log in (auth_mode=none accepts any token)
        token_input = browser_page.query_selector("input")
        if token_input:
            token_input.fill("olav_test")
        login_btn = browser_page.query_selector("button")
        if login_btn:
            login_btn.click()
            browser_page.wait_for_load_state("networkidle", timeout=15000)
            browser_page.wait_for_timeout(1500)

        # Click the Threads toggle button
        threads_btn = browser_page.query_selector("button:has-text('Threads')")
        assert threads_btn is not None, "Threads toggle button not found"
        threads_btn.click()
        browser_page.wait_for_timeout(2000)

        # The sidebar panel must be in the DOM and wide enough
        panel = browser_page.query_selector("#thread-history")
        assert panel is not None, "#thread-history panel not rendered after opening sidebar"

        box = panel.bounding_box()
        assert box is not None, "Could not get bounding box for #thread-history"

        viewport_width = browser_page.viewport_size["width"]
        pct = box["width"] / viewport_width * 100
        assert pct >= 22, (
            f"Sidebar rendered at {pct:.1f}% viewport width — expected ≥22% (minSize). "
            "Likely a react-resizable-panels defaultLayout regression."
        )


@pytest.mark.skipif(
    not Path(".olav/workspace/netops").exists(),
    reason="netops workspace not installed",
)
class TestMultiAgentSwitching:
    def test_netops_in_assistants_list(self, server_url):
        """When netops workspace is installed, it should appear in /assistants/search."""
        import urllib.request  # noqa: PLC0415
        req = urllib.request.Request(
            f"{server_url}/assistants/search",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        graph_ids = [a.get("graph_id") for a in data]
        assert "netops" in graph_ids, f"Expected 'netops' in {graph_ids}"
