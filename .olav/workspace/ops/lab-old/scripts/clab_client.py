"""Registry-backed ContainerLab API client.

Uses the OLAV platform api_registry (DuckDB-based) to verify all required
operations exist before making any calls. The registry is bootstrapped via
subprocess on first use — no direct import of olav.core modules here.

Registry DB: ~/.olav/api_registry.duckdb
Bootstrap:   python -m olav.core.api_registry load clab <schema_url> ...
"""

from __future__ import annotations

import json as _json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb
import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry constants
# ---------------------------------------------------------------------------

_REGISTRY_DB = Path.home() / ".olav" / "olav_registry.duckdb"
_CLAB_API_NAME = "clab"
# .agent/skills/containerlab-e2e/scripts → up 4 levels → Olav/src
_OLAV_SRC = Path(__file__).parents[4] / "src"

# ---------------------------------------------------------------------------
# Operations registry — verified against DuckDB registry at build() time.
# URL building still uses this dict (fast, no DB hit per request).
# ---------------------------------------------------------------------------

_OPS: dict[str, tuple[str, str]] = {
    "login":        ("POST",   "/login"),
    "list_labs":    ("GET",    "/api/v1/labs"),
    "deploy_lab":   ("POST",   "/api/v1/labs"),
    "inspect_lab":  ("GET",    "/api/v1/labs/{labName}"),
    "destroy_lab":  ("DELETE", "/api/v1/labs/{labName}"),
    "exec_command": ("POST",   "/api/v1/labs/{labName}/exec"),
    "get_version":  ("GET",    "/api/v1/version"),
}


# ---------------------------------------------------------------------------
# CLABAPIError
# ---------------------------------------------------------------------------

class CLABAPIError(Exception):
    """Raised when the ContainerLab API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


# ---------------------------------------------------------------------------
# Registry helpers (skill-side: subprocess bootstrap + direct DuckDB reads)
# ---------------------------------------------------------------------------

def _ensure_registry(api_server: str) -> None:
    """Bootstrap registry if not loaded. Uses subprocess to call platform api_registry."""
    # Fast check: already loaded?
    if _REGISTRY_DB.exists():
        try:
            with duckdb.connect(str(_REGISTRY_DB), read_only=True) as con:
                n = con.execute(
                    "SELECT COUNT(*) FROM api_registry.operations WHERE api_name=?",
                    [_CLAB_API_NAME],
                ).fetchone()[0]
                if n > 0:
                    logger.debug("api_registry: %s already loaded (%d ops)", _CLAB_API_NAME, n)
                    return
        except Exception:
            pass

    # Derive schema_url from api_server
    root = api_server.rstrip("/")
    if "/api/v1" in root:
        root = root.split("/api/v1")[0]
    schema_url = f"{root}/swagger/doc.json"

    logger.info("api_registry: bootstrapping %s from %s", _CLAB_API_NAME, schema_url)
    result = subprocess.run(
        [
            sys.executable, "-m", "olav.core.api_registry",
            "load", _CLAB_API_NAME, schema_url,
            "--base-url", api_server,
            "--db", str(_REGISTRY_DB),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(_OLAV_SRC)},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"api_registry bootstrap failed:\n{result.stderr}"
        )
    logger.info("api_registry: %s", result.stdout.strip())


def _verify_ops_in_registry() -> None:
    """Verify all _OPS entries exist in registry. Raise KeyError if any missing."""
    missing: list[str] = []
    with duckdb.connect(str(_REGISTRY_DB), read_only=True) as con:
        for name, (method, path) in _OPS.items():
            row = con.execute(
                "SELECT 1 FROM api_registry.operations WHERE api_name=? AND method=? AND path=?",
                [_CLAB_API_NAME, method, path],
            ).fetchone()
            if not row:
                missing.append(f"{method} {path}")
    if missing:
        raise KeyError(f"Operations missing from registry: {missing}")


def _field_names(def_name: str) -> set[str]:
    """Query registry for field names of a definition."""
    with duckdb.connect(str(_REGISTRY_DB), read_only=True) as con:
        row = con.execute(
            "SELECT fields FROM api_registry.definitions WHERE api_name=? AND def_name=?",
            [_CLAB_API_NAME, def_name],
        ).fetchone()
    if not row:
        return set()
    return set(_json.loads(row[0]).keys())


# ---------------------------------------------------------------------------
# CLabClient
# ---------------------------------------------------------------------------

class CLabClient:
    """Registry-backed HTTP client for the ContainerLab REST API."""

    def __init__(self, api_server: str, token: str) -> None:
        self._base = api_server.rstrip("/")
        root = self._base.split("/api/v1")[0] if "/api/v1" in self._base else self._base
        self._root = root
        self._headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    async def build(cls, api_server: str, token: str) -> "CLabClient":
        """Bootstrap registry if needed, verify operations, return client."""
        _ensure_registry(api_server)
        _verify_ops_in_registry()
        logger.debug("CLabClient: registry verified for %s", _CLAB_API_NAME)
        return cls(api_server=api_server.rstrip("/"), token=token)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _url(self, op: str, **path_params: str) -> str:
        """Build absolute URL. /login is at server root, not api_server."""
        method, path_template = _OPS[op]

        path = path_template
        for key, value in path_params.items():
            path = path.replace("{" + key + "}", value)

        if op == "login":
            # /login lives at server root, not under /api/v1
            server_root = re.sub(r"/api/v1/?$", "", self._base.rstrip("/"))
            return f"{server_root}{path}"

        # All other ops are under /api/v1; strip /api/v1 from base to avoid doubling
        base = re.sub(r"/api/v1/?$", "", self._base.rstrip("/"))
        return f"{base}{path}"

    async def _request(
        self,
        op: str,
        body: Any = None,
        path_params: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Execute a single request. Raise CLABAPIError on non-2xx."""
        method, _ = _OPS[op]
        url = self._url(op, **(path_params or {}))

        kwargs: dict[str, Any] = {
            "headers": self._headers,
            "timeout": timeout,
        }
        if body is not None:
            kwargs["json"] = body

        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, **kwargs)

        if not (200 <= resp.status_code < 300):
            raise CLABAPIError(resp.status_code, resp.text[:500])

        content_type = resp.headers.get("content-type", "")
        if resp.content and "json" in content_type:
            return resp.json()
        if resp.content:
            try:
                return resp.json()
            except Exception:
                return resp.text
        return {}

    # -----------------------------------------------------------------------
    # Typed operation methods
    # -----------------------------------------------------------------------

    async def list_labs(self) -> dict[str, list[dict]]:
        """GET /api/v1/labs"""
        return await self._request("list_labs")

    async def deploy(
        self,
        topology_content: dict,
        reconfigure: bool = False,
    ) -> dict[str, list[dict]]:
        """POST /api/v1/labs with topologyContent from DeployRequest schema. timeout=120."""
        fields = _field_names("DeployRequest")
        if fields:
            assert "topologyContent" in fields, (
                f"DeployRequest missing topologyContent, got: {fields}"
            )
        body: dict[str, Any] = {"topologyContent": topology_content}
        if reconfigure:
            body["reconfigure"] = True
        return await self._request("deploy_lab", body=body, timeout=120.0)

    async def inspect(self, lab_name: str) -> list[dict]:
        """GET /api/v1/labs/{labName}"""
        return await self._request("inspect_lab", path_params={"labName": lab_name})

    async def destroy(self, lab_name: str) -> dict:
        """DELETE /api/v1/labs/{labName}"""
        return await self._request("destroy_lab", path_params={"labName": lab_name})

    async def exec_command(
        self,
        lab_name: str,
        command: str,
        timeout: float = 30.0,
    ) -> dict[str, list[dict]]:
        """POST /api/v1/labs/{labName}/exec.

        Uses the 'command' field from the ExecRequest schema (lowercase).
        Returns {node_name: [{stdout, stderr, return-code, cmd}]}.

        IMPORTANT: If stdout is valid JSON, the API bypasses the normal envelope.
        Callers must NOT produce JSON stdout (use text output commands only).
        """
        fields = _field_names("ExecRequest")
        if fields:
            assert "command" in fields, f"ExecRequest missing 'command', got: {fields}"
        body = {"command": command}
        return await self._request(
            "exec_command",
            body=body,
            path_params={"labName": lab_name},
            timeout=timeout,
        )

    async def get_version(self) -> dict:
        """GET /api/v1/version"""
        return await self._request("get_version")
