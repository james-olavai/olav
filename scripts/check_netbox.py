"""NetBox environment validation script.

Checks:
1. Environment variables presence (NETBOX_URL, NETBOX_TOKEN)
2. API root reachable (GET /api/)
3. Token authorization (expects HTTP 200 and non-empty results)
4. Required objects existence: at least one Site, Device Role, Tag
5. Optional: prints counts of primary models for quick baseline

Exit codes:
0 - Success, all required checks passed
1 - Missing environment variables
2 - Connectivity failure (cannot reach API root)
3 - Authentication failure (401/403)
4 - Required objects missing (empty sets)

Usage:
    uv run python scripts/check_netbox.py

Can be integrated into CI or pre-init pipeline before running OLAV schema ETL.
"""
from __future__ import annotations

import os
import sys
import json
from typing import Any, Dict, Tuple

import requests

REQUIRED_ENDPOINTS = {
    "sites": "/api/dcim/sites/",
    "device_roles": "/api/dcim/device-roles/",
    "tags": "/api/extras/tags/",
}

# Auto-create baseline objects if missing when AUTOCREATE=1 or --autocreate passed.
BASELINE_CREATE = {
    "site": {"name": "lab", "slug": "lab"},
    "device_role": {"name": "core", "slug": "core"},
    "tag": {"name": "olav-managed", "slug": "olav-managed"},
}

OPTIONAL_ENDPOINTS = {
    "devices": "/api/dcim/devices/",
    "interfaces": "/api/dcim/interfaces/",
}

TIMEOUT = 10


def fail(code: int, msg: str, context: Dict[str, Any] | None = None) -> None:
    payload = {"success": False, "code": code, "error": msg, "context": context or {}}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(code)


def get_env() -> Tuple[str, str]:
    url = os.getenv("NETBOX_URL")
    token = os.getenv("NETBOX_TOKEN")
    if not url or not token:
        fail(1, "Missing NETBOX_URL or NETBOX_TOKEN in environment", {"NETBOX_URL": url, "NETBOX_TOKEN": bool(token)})
    return url.rstrip("/"), token.strip()


def request(url: str, token: str) -> requests.Response:
    return requests.get(url, headers={"Authorization": f"Token {token}"}, timeout=TIMEOUT)


def check_root(url: str, token: str) -> None:
    resp = request(f"{url}/api/", token)
    if resp.status_code >= 500:
        fail(2, f"Server error {resp.status_code} reaching /api/", {"status": resp.status_code})
    if resp.status_code == 404:
        fail(2, "API root 404 - wrong NETBOX_URL?", {"url": url})
    if resp.status_code in (401, 403):
        fail(3, f"Authentication failed status={resp.status_code}", {})
    if resp.status_code != 200:
        fail(2, f"Unexpected status {resp.status_code}", {})


def fetch_count(url: str, token: str) -> int:
    resp = request(url, token)
    if resp.status_code == 404:
        return -1
    if resp.status_code in (401, 403):
        fail(3, f"Auth failed {resp.status_code} for {url}", {})
    if resp.status_code >= 500:
        fail(2, f"Server error {resp.status_code} for {url}", {})
    try:
        data = resp.json()
    except ValueError:
        fail(2, "Invalid JSON in response", {"url": url, "text": resp.text[:200]})
    # NetBox paginated response has 'count'
    return data.get("count", -1)


def auto_create_baseline(base_url: str, token: str) -> None:
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    # Site
    if fetch_count(base_url + REQUIRED_ENDPOINTS["sites"], token) <= 0:
        requests.post(base_url + REQUIRED_ENDPOINTS["sites"], headers=headers, json=BASELINE_CREATE["site"], timeout=TIMEOUT)
    # Device role
    if fetch_count(base_url + REQUIRED_ENDPOINTS["device_roles"], token) <= 0:
        requests.post(base_url + REQUIRED_ENDPOINTS["device_roles"], headers=headers, json=BASELINE_CREATE["device_role"], timeout=TIMEOUT)
    # Tag
    if fetch_count(base_url + REQUIRED_ENDPOINTS["tags"], token) <= 0:
        requests.post(base_url + REQUIRED_ENDPOINTS["tags"], headers=headers, json=BASELINE_CREATE["tag"], timeout=TIMEOUT)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--autocreate", action="store_true", help="Auto-create baseline site/role/tag if missing")
    args = parser.parse_args()

    base_url, token = get_env()
    check_root(base_url, token)

    if args.autocreate or os.getenv("AUTOCREATE_BASELINE") == "1":
        auto_create_baseline(base_url, token)

    results: Dict[str, Any] = {"base_url": base_url}
    missing: Dict[str, int] = {}

    for name, endpoint in REQUIRED_ENDPOINTS.items():
        count = fetch_count(base_url + endpoint, token)
        results[name] = count
        if count <= 0:
            missing[name] = count

    for name, endpoint in OPTIONAL_ENDPOINTS.items():
        count = fetch_count(base_url + endpoint, token)
        results[name] = count

    if missing:
        fail(4, "Required NetBox objects missing", {"missing": missing, "results": results, "hint": "Run with --autocreate or create objects manually."})

    print(json.dumps({"success": True, "code": 0, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
