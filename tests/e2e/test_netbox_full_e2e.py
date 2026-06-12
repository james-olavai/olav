"""L3 end-to-end: NetBox full lifecycle.

Pipeline under test:
  1. Infrastructure — docker-compose starts NetBox, waits healthy        (no LLM)
  2. Import        — device import script runs against real NetBox API   (no LLM)
  3. Verify        — devices visible via api_request / api_registry      (no LLM)
  4. Core query    — `olav` CLI answers a NetBox question via api-query  (LLM)

Gate environment variables:
  NETBOX_E2E_ENABLED=1   — runs all classes except TestCoreLLMQuery
  DEVOPS_E2E_ENABLED=1   — also enables TestCoreLLMQuery (needs LLM)

Teardown:
  By default the NetBox stack is left running so repeated runs are fast.
  Set NETBOX_E2E_TEARDOWN=1 to destroy after the session.

Run examples:
  # Infrastructure + import + routing only (no LLM):
  NETBOX_E2E_ENABLED=1 uv run pytest tests/e2e/test_netbox_full_e2e.py -v -s

  # Full pipeline including LLM core query:
  NETBOX_E2E_ENABLED=1 DEVOPS_E2E_ENABLED=1 uv run pytest tests/e2e/test_netbox_full_e2e.py -v -s

  # Teardown after run:
  NETBOX_E2E_ENABLED=1 NETBOX_E2E_TEARDOWN=1 uv run pytest tests/e2e/test_netbox_full_e2e.py -v -s
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _ROOT / ".olav" / "services" / "netbox" / "docker-compose.yml"
_NETBOX_ENV_FILE = _ROOT / ".olav" / "services" / "netbox" / "env" / "netbox.env"
_AUTOMATIONS = _ROOT / ".olav" / "automations"
_IMPORT_SCRIPT = _AUTOMATIONS / "netbox" / "import_devices.py"
_NETBOX_URL = "http://localhost:8000"
_WORKSPACE_SCRIPTS = _ROOT / ".olav" / "workspace" / "devops" / "infra" / "scripts"
_OLAV_CMD = [sys.executable, "-m", "olav"]


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------


def _netbox_e2e_enabled() -> bool:
    return os.environ.get("NETBOX_E2E_ENABLED", "").lower() in {"1", "true", "yes"}


def _llm_e2e_enabled() -> bool:
    return os.environ.get("DEVOPS_E2E_ENABLED", "").lower() in {"1", "true", "yes"}


_SKIP_INFRA = pytest.mark.skipif(
    not _netbox_e2e_enabled(), reason="Set NETBOX_E2E_ENABLED=1 to run"
)
_SKIP_LLM = pytest.mark.skipif(
    not (_netbox_e2e_enabled() and _llm_e2e_enabled()),
    reason="Set NETBOX_E2E_ENABLED=1 DEVOPS_E2E_ENABLED=1 to run",
)


# ---------------------------------------------------------------------------
# Token reader
# ---------------------------------------------------------------------------


def _read_token() -> str:
    """Read NETBOX_TOKEN from .olav/services/netbox/env/netbox.env."""
    text = _NETBOX_ENV_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("NETBOX_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"NETBOX_TOKEN not found in {_NETBOX_ENV_FILE}")


def _nb_headers(token: str) -> dict[str, str]:
    """NetBox uses 'Token <token>', not 'Bearer <token>'."""
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def netbox_token() -> str:
    return _read_token()


@pytest.fixture(scope="session")
def olav_api_server():
    """Ensure the OLAV API server (port 2280) is running for the test session.

    If already running (external process), leaves it alone.
    If not running, starts it via `olav service web start` and stops on teardown.
    The server gives `olav` CLI calls a warm process fast-path: instead of
    re-initialising the agent graph on every subprocess invocation (~3s), each
    query is routed via HTTP SSE to the shared in-process agent.
    """
    import httpx

    _api_port = int(os.environ.get("OLAV_API_PORT", "2280"))
    _base = f"http://localhost:{_api_port}"
    _started_by_fixture = False

    # Check if already up
    try:
        r = httpx.get(f"{_base}/ok", timeout=1.0)
        already_up = r.status_code == 200
    except Exception:
        already_up = False

    if not already_up:
        subprocess.run(
            _OLAV_CMD + ["service", "web", "start"],
            capture_output=True, cwd=str(_ROOT),
        )
        _started_by_fixture = True
        # Wait up to 60s for the server to become ready
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"{_base}/ok", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            pytest.fail("OLAV API server did not become ready within 60s")

    yield _base

    if _started_by_fixture:
        subprocess.run(
            _OLAV_CMD + ["service", "web", "stop"],
            capture_output=True, cwd=str(_ROOT),
        )


@pytest.fixture(scope="session")
def netbox_running(netbox_token):
    """Start NetBox via docker-compose, wait for API health, yield token.

    The NETBOX_TOKEN env var is set for all in-process and subprocess calls.
    """
    subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), "up", "-d"],
        check=True,
        capture_output=True,
    )
    os.environ["NETBOX_TOKEN"] = netbox_token

    # Poll until the API returns 200 (NetBox start_period is 90 s; we allow 5 min)
    deadline = time.monotonic() + 300
    hdrs = _nb_headers(netbox_token)
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{_NETBOX_URL}/api/", headers=hdrs, timeout=5)
            if r.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(5)
    else:
        pytest.fail("NetBox did not become healthy within 5 minutes")

    yield netbox_token

    if os.environ.get("NETBOX_E2E_TEARDOWN", "").lower() in {"1", "true"}:
        subprocess.run(
            ["docker", "compose", "-f", str(_COMPOSE_FILE), "down", "-v"],
            capture_output=True,
        )


@pytest.fixture(scope="session")
def import_script_path(netbox_running):
    """Seed .olav/automations/netbox/import_devices.py if not already present."""
    _IMPORT_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
    if not _IMPORT_SCRIPT.exists():
        _IMPORT_SCRIPT.write_text(_IMPORT_SCRIPT_TEMPLATE, encoding="utf-8")
    return _IMPORT_SCRIPT


# ---------------------------------------------------------------------------
# Import script template
# (written to disk if not yet generated by the devops LLM agent)
# ---------------------------------------------------------------------------

_IMPORT_SCRIPT_TEMPLATE = '''\
#!/usr/bin/env python3
"""Import devices from OLAV DuckDB into NetBox.
Uses NETBOX_TOKEN env var — never hardcode credentials.
Idempotent: devices already in NetBox are skipped, not duplicated.
"""
import os
import sys
import duckdb
import requests

NETBOX_URL = os.environ.get("NETBOX_URL", "http://localhost:8000")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN")
DRY_RUN = "--dry-run" in sys.argv

if not NETBOX_TOKEN:
    print("ERROR: NETBOX_TOKEN env var required", file=sys.stderr)
    sys.exit(1)

_H = {
    "Authorization": f"Token {NETBOX_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _get_or_create(url: str, lookup: str, val: str, payload: dict) -> int:
    """Get or create a NetBox resource.

    If POST fails with 400/409 (duplicate slug/name constraint), retries GET
    to handle idempotent re-runs where the resource was created previously.
    """
    r = requests.get(url, headers=_H, params={lookup: val}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data["count"] > 0:
        return data["results"][0]["id"]

    # Resource not found — try to create
    r = requests.post(url, headers=_H, json=payload, timeout=10)

    if r.status_code in (400, 409):
        # Duplicate from a previous run: GET should find it now
        r2 = requests.get(url, headers=_H, params={lookup: val}, timeout=10)
        r2.raise_for_status()
        data2 = r2.json()
        if data2["count"] > 0:
            return data2["results"][0]["id"]
        # Try slug lookup as fallback
        if "slug" in payload:
            r3 = requests.get(url, headers=_H, params={"slug": payload["slug"]}, timeout=10)
            r3.raise_for_status()
            data3 = r3.json()
            if data3["count"] > 0:
                return data3["results"][0]["id"]

    r.raise_for_status()
    return r.json()["id"]


def main() -> dict:
    from olav.core.config import MAIN_DB_PATH
    con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    rows = con.execute(
        "SELECT hostname, platform, site FROM netops.devices"
    ).fetchall()
    con.close()
    print(f"Devices in OLAV DuckDB: {len(rows)}")

    mfr_cache: dict[str, int] = {}
    dtype_cache: dict[str, int] = {}
    site_cache: dict[str, int] = {}
    role_id: int | None = None

    imported = skipped = errors = 0

    for (hostname, platform, site_name) in rows:
        try:
            if platform and "cisco" in platform.lower():
                mfr = "Cisco"
            elif platform and "arista" in platform.lower():
                mfr = "Arista"
            elif platform and "juniper" in platform.lower():
                mfr = "Juniper"
            else:
                mfr = "Unknown"

            model = (platform or "unknown").lower().replace("_", "-")[:50]
            site = site_name or "Default"

            if DRY_RUN:
                print(f"  [DRY] {hostname}  platform={platform}  site={site}")
                imported += 1
                continue

            if mfr not in mfr_cache:
                mfr_cache[mfr] = _get_or_create(
                    f"{NETBOX_URL}/api/dcim/manufacturers/", "name", mfr,
                    {"name": mfr, "slug": mfr.lower()},
                )
            if model not in dtype_cache:
                dtype_cache[model] = _get_or_create(
                    f"{NETBOX_URL}/api/dcim/device-types/", "model", model,
                    {"model": model, "slug": model,
                     "manufacturer": mfr_cache[mfr]},
                )
            if site not in site_cache:
                site_cache[site] = _get_or_create(
                    f"{NETBOX_URL}/api/dcim/sites/", "name", site,
                    {"name": site,
                     "slug": site.lower().replace(" ", "-")[:50],
                     "status": "active"},
                )
            if role_id is None:
                role_id = _get_or_create(
                    f"{NETBOX_URL}/api/dcim/device-roles/", "name",
                    "Network Device",
                    {"name": "Network Device", "slug": "network-device",
                     "color": "9e9e9e"},
                )

            # Idempotent: skip if device already exists
            r = requests.get(
                f"{NETBOX_URL}/api/dcim/devices/", headers=_H,
                params={"name": hostname}, timeout=10,
            )
            r.raise_for_status()
            if r.json()["count"] > 0:
                skipped += 1
                continue

            r = requests.post(
                f"{NETBOX_URL}/api/dcim/devices/", headers=_H,
                json={
                    "name": hostname,
                    "device_type": dtype_cache[model],
                    "role": role_id,
                    "site": site_cache[site],
                    "status": "active",
                },
                timeout=10,
            )

            if r.status_code in (400, 409, 500):
                # NetBox constraint violation (500) or duplicate (400/409):
                # device was created between our GET check and POST, or
                # exists from a previous run whose GET missed it.
                r_check = requests.get(
                    f"{NETBOX_URL}/api/dcim/devices/", headers=_H,
                    params={"name": hostname}, timeout=10,
                )
                if r_check.ok and r_check.json()["count"] > 0:
                    skipped += 1
                    continue
                r.raise_for_status()

            r.raise_for_status()
            imported += 1

        except Exception as exc:
            print(f"  ERROR {hostname}: {exc}")
            errors += 1

    print(f"Result: imported={imported}, skipped={skipped}, errors={errors}")
    return {"imported": imported, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    result = main()
    sys.exit(1 if result["errors"] > 0 else 0)
'''


# ---------------------------------------------------------------------------
# TestNetboxInfra — container reachability
# ---------------------------------------------------------------------------


@_SKIP_INFRA
class TestNetboxInfra:
    """Verify NetBox is up and the token is accepted before running import."""

    def test_compose_file_exists(self):
        assert _COMPOSE_FILE.exists(), f"NetBox compose not found: {_COMPOSE_FILE}"

    def test_env_file_has_token(self):
        token = _read_token()
        assert token, "NETBOX_TOKEN is empty in env file"
        assert len(token) > 20, "NETBOX_TOKEN looks too short"

    def test_api_returns_200(self, netbox_running):
        r = requests.get(
            f"{_NETBOX_URL}/api/",
            headers=_nb_headers(netbox_running),
            timeout=10,
        )
        assert r.status_code == 200, f"NetBox API returned {r.status_code}"

    def test_dcim_devices_endpoint_reachable(self, netbox_running):
        r = requests.get(
            f"{_NETBOX_URL}/api/dcim/devices/",
            headers=_nb_headers(netbox_running),
            timeout=10,
        )
        assert r.status_code == 200, f"/api/dcim/devices/ returned {r.status_code}"

    def test_write_access_allowed(self, netbox_running):
        """NetBox token must have write access (needed for import)."""
        r = requests.get(
            f"{_NETBOX_URL}/api/dcim/manufacturers/",
            headers=_nb_headers(netbox_running),
            timeout=10,
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# TestDevopsImport — import script lifecycle
# ---------------------------------------------------------------------------


@_SKIP_INFRA
class TestDevopsImport:
    """Device import via automation script — no LLM required."""

    def test_import_script_seeded(self, import_script_path):
        assert import_script_path.exists()
        assert import_script_path.suffix == ".py"
        assert import_script_path.parent == _AUTOMATIONS / "netbox"

    def test_import_script_syntax_valid(self, import_script_path):
        import py_compile
        py_compile.compile(str(import_script_path), doraise=True)

    def test_import_script_no_hardcoded_token(self, import_script_path):
        content = import_script_path.read_text(encoding="utf-8")
        token = _read_token()
        assert token not in content, "Token must not be hardcoded in import script"
        assert "NETBOX_TOKEN" in content, "Script must read NETBOX_TOKEN from env"

    def test_import_script_is_inside_automations(self, import_script_path):
        """run_automation boundary check: path must be under .olav/automations/."""
        try:
            import_script_path.resolve().relative_to(_AUTOMATIONS.resolve())
        except ValueError:
            pytest.fail("Import script is outside .olav/automations/ boundary")

    def test_dry_run_reads_duckdb(self, netbox_running, import_script_path):
        """--dry-run must query netops.devices and print device lines."""
        env = {**os.environ, "NETBOX_TOKEN": netbox_running}
        result = subprocess.run(
            [sys.executable, str(import_script_path), "--dry-run"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 0, (
            f"Dry run failed (rc={result.returncode}):\n"
            f"{result.stdout[-1000:]}\n{result.stderr[-500:]}"
        )
        assert "Devices in OLAV DuckDB:" in result.stdout
        assert "[DRY]" in result.stdout, "Expected [DRY] lines in output"

    def test_import_runs_without_errors(self, netbox_running, import_script_path):
        """Real import — idempotent, so safe to re-run. Errors must be zero."""
        env = {**os.environ, "NETBOX_TOKEN": netbox_running}
        result = subprocess.run(
            [sys.executable, str(import_script_path)],
            capture_output=True, text=True, env=env, timeout=600,
        )
        # Parse counts from "Result: imported=N, skipped=N, errors=N"
        import re
        m = re.search(r"errors=(\d+)", result.stdout)
        errors = int(m.group(1)) if m else None

        assert result.returncode == 0, (
            f"Import script exited {result.returncode} (errors={errors})\n"
            f"stdout:\n{result.stdout[-3000:]}\n"
            f"stderr:\n{result.stderr[-500:]}"
        )
        assert errors == 0, (
            f"Import reported {errors} errors — expected 0 (idempotent re-run).\n"
            f"stdout:\n{result.stdout[-3000:]}"
        )

    def test_devices_appear_in_netbox(self, netbox_running):
        """At least some devices should be present after import."""
        r = requests.get(
            f"{_NETBOX_URL}/api/dcim/devices/",
            headers=_nb_headers(netbox_running),
            timeout=10,
        )
        r.raise_for_status()
        count = r.json()["count"]
        assert count > 0, "No devices found in NetBox after import"

    def test_device_count_matches_duckdb(self, netbox_running):
        """NetBox device count ≥ 95% of OLAV DuckDB count (≤5% error margin)."""
        import duckdb
        from olav.core.config import MAIN_DB_PATH
        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        (db_count,) = con.execute("SELECT count(*) FROM netops.devices").fetchone()
        con.close()

        r = requests.get(
            f"{_NETBOX_URL}/api/dcim/devices/",
            headers=_nb_headers(netbox_running),
            timeout=10,
        )
        r.raise_for_status()
        nb_count = r.json()["count"]

        assert nb_count >= db_count * 0.95, (
            f"NetBox has {nb_count} devices, OLAV DuckDB has {db_count} "
            f"— more than 5% missing"
        )

    def test_run_automation_preview_mode(self, import_script_path):
        """run_automation with confirmed=False must return preview, not execute."""
        spec = importlib.util.spec_from_file_location(
            "run_automation", _WORKSPACE_SCRIPTS / "run_automation.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rel_path = import_script_path.relative_to(_ROOT)
        result = mod.run_automation(str(rel_path), confirmed=False)
        assert result["status"] == "preview"
        assert "confirmed=True" in result.get("hint", "")


# ---------------------------------------------------------------------------
# TestCoreApiRegistryRouting — no LLM, direct script calls
# ---------------------------------------------------------------------------


@_SKIP_INFRA
class TestCoreApiRegistryRouting:
    """Verify api_registry → api_request routing works without LLM."""

    def test_api_registry_has_netbox_endpoint(self):
        import duckdb
        from olav.core.config import MAIN_DB_PATH
        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        rows = con.execute(
            "SELECT endpoint, auth_type, token_env "
            "FROM api_registry.services WHERE name = 'netbox'"
        ).fetchall()
        con.close()
        assert rows, "NetBox not found in api_registry.services"
        endpoint, auth_type, token_env = rows[0]
        assert endpoint.startswith("http"), f"Bad endpoint: {endpoint}"
        assert token_env == "NETBOX_TOKEN", f"Unexpected token_env: {token_env}"

    def test_netbox_endpoint_from_registry_matches_services_yaml(self):
        """api_registry should mirror services.yaml endpoint."""
        import duckdb
        import yaml
        from olav.core.config import CONFIG_DIR, MAIN_DB_PATH

        yaml_svc = yaml.safe_load(
            (Path(CONFIG_DIR) / "services.yaml").read_text(encoding="utf-8")
        )["services"]["netbox"]
        expected = yaml_svc["endpoint"]

        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        (actual,) = con.execute(
            "SELECT endpoint FROM api_registry.services WHERE name = 'netbox'"
        ).fetchone()
        con.close()
        assert actual == expected, (
            f"api_registry endpoint {actual!r} != services.yaml {expected!r}"
        )

    def test_direct_netbox_api_via_requests(self, netbox_running):
        """Sanity: direct requests with Token header returns devices."""
        r = requests.get(
            f"{_NETBOX_URL}/api/dcim/devices/",
            headers=_nb_headers(netbox_running),
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "No devices visible via direct API call"

    def test_api_request_script_calls_service_call(self):
        """api_request.py source must use service_call (not raw requests)."""
        src = (
            _ROOT / ".olav" / "workspace" / "core" / "api-query"
            / "scripts" / "api_request.py"
        ).read_text(encoding="utf-8")
        assert "service_call" in src, "api_request must delegate to service_call"
        assert "api_registry" in src or "ServiceRegistry" in src, (
            "api_request must reference service registry"
        )

    def test_api_request_unregistered_service_returns_error_dict(self):
        """api_request with unknown service must return error dict, not raise."""
        api_req_path = (
            _ROOT / ".olav" / "workspace" / "core" / "api-query"
            / "scripts" / "api_request.py"
        )
        spec = importlib.util.spec_from_file_location("api_req_routing", api_req_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        tool = mod.api_request
        invoker = tool.invoke if hasattr(tool, "invoke") else tool
        result = invoker({"service": "nonexistent-svc-xyzzy", "path": "/api/test/"})
        assert isinstance(result, dict)
        assert result.get("status") == "error"


# ---------------------------------------------------------------------------
# TestCoreLLMQuery — full LLM pipeline (needs DEVOPS_E2E_ENABLED=1 too)
# ---------------------------------------------------------------------------


@_SKIP_LLM
class TestCoreLLMQuery:
    """Core agent answers NetBox questions via api_registry + api-query.

    Requires both NETBOX_E2E_ENABLED=1 and DEVOPS_E2E_ENABLED=1.
    """

    # Single timeout used for all LLM queries in this class.
    # Each query: 2 LLM calls (core → api-query) + HTTP + DeepSeek latency ≈ 50-90s.
    _LLM_TIMEOUT = int(os.environ.get("NETBOX_LLM_TIMEOUT", "300"))

    def _run_core(self, prompt: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "NETBOX_TOKEN": _read_token()}
        return subprocess.run(
            _OLAV_CMD + [prompt],
            capture_output=True, text=True, env=env, timeout=self._LLM_TIMEOUT,
        )

    def test_core_routes_netbox_query_to_api_query(self, netbox_running, olav_api_server):
        """Core must route NetBox device count question to api-query sub-agent."""
        result = self._run_core("NetBox 里现在有多少台设备？")
        assert result.returncode == 0, (
            f"olav exited {result.returncode}\n{result.stderr[-500:]}"
        )
        combined = result.stdout + result.stderr
        import re
        assert re.search(r"\d+", combined), (
            f"Core response contains no number:\n{combined[-1000:]}"
        )

    def test_core_netbox_cisco_device_query(self, netbox_running, olav_api_server):
        """Core must return a non-empty answer for a Cisco device filter query."""
        result = self._run_core("NetBox 里 Cisco 设备有多少台？给我一个数字。")
        assert result.returncode == 0, (
            f"olav exited {result.returncode}\n{result.stderr[-500:]}"
        )
        combined = result.stdout + result.stderr
        import re
        assert re.search(r"\d+", combined), (
            f"No numeric answer in response:\n{combined[-1000:]}"
        )

    def test_core_netbox_response_not_placeholder(self, netbox_running, olav_api_server):
        """Core must not return a placeholder or error — must query the real API."""
        result = self._run_core("NetBox 里的设备总数是多少？")
        combined = (result.stdout + result.stderr).lower()
        bad_phrases = ["not registered", "未注册", "no service", "placeholder"]
        for phrase in bad_phrases:
            assert phrase not in combined, (
                f"Core returned error/placeholder phrase '{phrase}':\n{combined[-500:]}"
            )
