"""Generic HTTP client for the CLAB REST API.

Tool: call_api

Args (JSON):
    api_name:  str         — API name, always "clab"
    method:    str         — HTTP method ("GET", "POST", "DELETE", ...)
    path:      str         — API path (e.g. "/api/v1/labs")
    body:      dict | None — JSON request body (optional)
    params:    dict | None — query parameters (optional)

Returns: JSON string
    {"status_code": 200, "body": {...}}
    {"status_code": 401, "body": {...}}    ← HTTP errors returned, not raised
    {"error": "connection refused"}        ← network/exception errors

Auth: reads CLAB_TOKEN env var first. If missing or expired, auto-logs in
using credentials from .olav/config.json (clab.username / clab.password).
Base URL: http://192.168.100.12:8080 (from config or hardcoded fallback).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

_DEFAULT_BASE_URL = "http://192.168.100.12:8080"
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"


def _load_config() -> dict:
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        # Support both flat {"base_url": ...} and wrapped {"clab": {"base_url": ...}}
        return data.get("clab", data)
    except Exception:
        return {}


def _login(base_url: str, username: str, password: str) -> str | None:
    """Login to CLAB API and return JWT token."""
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/login",
            json={"username": username, "password": password},
            timeout=10.0,
            verify=False,
        )
        data = resp.json()
        return data.get("token")
    except Exception:
        return None


def _get_token(base_url: str) -> str:
    """Get a valid token: env var → auto-login from config."""
    token = os.environ.get("CLAB_TOKEN", "")
    if token:
        return token

    cfg = _load_config()
    username = cfg.get("username", "admin")
    password = cfg.get("password", "clab")
    token = _login(base_url, username, password) or ""
    if token:
        # Cache in env for subsequent calls in this process
        os.environ["CLAB_TOKEN"] = token
    return token


def call_api(args: dict) -> str:
    """Make an HTTP request to the CLAB REST API."""
    method: str = args["method"].upper()
    path: str = args["path"]
    body: dict | None = args.get("body")
    params: dict | None = args.get("params")

    cfg = _load_config()
    base_url = cfg.get("base_url", _DEFAULT_BASE_URL)
    url = base_url.rstrip("/") + path

    token = _get_token(base_url)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            json=body,
            params=params,
            timeout=30.0,
        )
        # If 401 and we used auto-login, the token may have expired — refresh once
        if response.status_code == 401 and "CLAB_TOKEN" in os.environ:
            os.environ.pop("CLAB_TOKEN", None)
            token = _get_token(base_url)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                response = httpx.request(
                    method, url, headers=headers, json=body, params=params, timeout=30.0
                )

        try:
            body_data = response.json()
        except Exception:
            body_data = response.text
        return json.dumps({"status_code": response.status_code, "body": body_data})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    print(call_api(json.loads(parsed.args_json)))
