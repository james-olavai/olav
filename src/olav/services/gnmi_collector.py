"""gNMI Collector service for OpenConfig-native network data collection (OC-2).

Wraps `pygnmi` to provide a clean interface for gNMI Get/Set operations
against network devices that support OpenConfig YANG models.

Usage::

    collector = GnmiCollector(
        target=("10.0.0.1", 57400),
        username="admin",
        password="admin",
        vendor="srlinux",
        insecure=True,
    )
    data = collector.collect("interfaces")
    all_data = collector.collect_all()
    result = collector.set_config("openconfig-interfaces:.../config", {"enabled": True})
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from pygnmi.client import gNMIclient
except ImportError:  # pragma: no cover
    gNMIclient = None  # type: ignore[assignment, misc]

# ---------------------------------------------------------------------------
# Vendor defaults — port and encoding per NOS
# ---------------------------------------------------------------------------

VENDOR_DEFAULTS: dict[str, dict[str, Any]] = {
    "srlinux": {"port": 57400, "encoding": "json_ietf"},
    "arista": {"port": 6030, "encoding": "json"},
    "iosxr": {"port": 57400, "encoding": "json_ietf"},
    "junos": {"port": 32767, "encoding": "json_ietf"},
}

GNMI_ROOT_PATH = "/"

# ---------------------------------------------------------------------------
# OpenConfig path definitions — one per domain
# ---------------------------------------------------------------------------

OPENCONFIG_PATHS: dict[str, str] = {
    "interfaces": "openconfig-interfaces:interfaces",
    "bgp": "openconfig-bgp:bgp",
    "lldp": "openconfig-lldp:lldp",
    "ospf": "openconfig-network-instance:network-instances/network-instance/protocols/protocol/ospfv2",
    "platform": "openconfig-platform:components",
}


# ---------------------------------------------------------------------------
# GnmiCollector
# ---------------------------------------------------------------------------


class GnmiCollector:
    """Thin wrapper around pygnmi for OpenConfig gNMI operations.

    Parameters
    ----------
    target:
        ``(host, port)`` tuple for the gNMI target.
    username:
        gNMI authentication username.
    password:
        gNMI authentication password.
    vendor:
        Optional vendor name (``srlinux``, ``arista``, ``iosxr``, ``junos``)
        to auto-fill encoding from :data:`VENDOR_DEFAULTS`.
    encoding:
        Explicit encoding override (``json``, ``json_ietf``, ``proto``).
        Takes precedence over vendor default.
    insecure:
        If ``True``, skip TLS verification.
    path_cert:
        Path to client certificate file.
    path_key:
        Path to client key file.
    path_root:
        Path to root CA certificate file.
    """

    def __init__(
        self,
        target: tuple[str, int],
        username: str,
        password: str,
        vendor: str | None = None,
        encoding: str | None = None,
        insecure: bool = False,
        path_cert: str | None = None,
        path_key: str | None = None,
        path_root: str | None = None,
    ) -> None:
        self.target = target
        self.username = username
        self.password = password
        self.vendor = vendor
        self.insecure = insecure
        self.path_cert = path_cert
        self.path_key = path_key
        self.path_root = path_root

        # Resolve encoding: explicit > vendor default > "json_ietf"
        if encoding is not None:
            self.encoding = encoding
        elif vendor and vendor in VENDOR_DEFAULTS:
            self.encoding = VENDOR_DEFAULTS[vendor]["encoding"]
        else:
            self.encoding = "json_ietf"

    # ------------------------------------------------------------------
    # Internal: build gNMIclient kwargs
    # ------------------------------------------------------------------

    def _client_kwargs(self) -> dict[str, Any]:
        """Build kwargs dict for ``gNMIclient`` constructor."""
        kwargs: dict[str, Any] = {
            "target": self.target,
            "username": self.username,
            "password": self.password,
            "insecure": self.insecure,
        }
        if self.path_cert:
            kwargs["path_cert"] = self.path_cert
        if self.path_key:
            kwargs["path_key"] = self.path_key
        if self.path_root:
            kwargs["path_root"] = self.path_root
        return kwargs

    def _path_to_string(self, path: Any) -> str:
        """Convert a gNMI path payload to a comparable string form."""
        if isinstance(path, str):
            return path

        if isinstance(path, dict):
            elem = path.get("elem")
            if isinstance(elem, list):
                parts: list[str] = []
                for item in elem:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name")
                    if not name:
                        continue
                    keys = item.get("key")
                    if isinstance(keys, dict) and keys:
                        key_expr = "".join(
                            f"[{key}={value}]" for key, value in sorted(keys.items())
                        )
                        parts.append(f"{name}{key_expr}")
                    else:
                        parts.append(name)
                if parts:
                    return "/".join(parts)

            for key in ("path", "target"):
                value = path.get(key)
                if isinstance(value, str):
                    return value

        return ""

    def _detect_domain(self, update: dict[str, Any]) -> str:
        """Best-effort domain detection for updates returned from root gNMI Get."""
        path_str = self._path_to_string(update.get("path"))

        for domain, oc_path in OPENCONFIG_PATHS.items():
            module_name, _, path_suffix = oc_path.partition(":")
            root_container = path_suffix.split("/")[0]

            if path_str.startswith(oc_path) or path_str.startswith(f"{module_name}:"):
                return domain
            if path_str == root_container or path_str.startswith(f"{root_container}/"):
                return domain

        value = update.get("val")
        if isinstance(value, dict):
            for domain, oc_path in OPENCONFIG_PATHS.items():
                module_name, _, path_suffix = oc_path.partition(":")
                root_container = path_suffix.split("/")[0]
                if module_name in value or oc_path in value or root_container in value:
                    return domain

        return "root"

    def _split_root_response(self, result: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
        """Split a root gNMI response into per-domain payloads when possible."""
        notifications = result.get("notification")
        if not isinstance(notifications, list):
            return {}

        grouped_updates: dict[str, list[dict[str, Any]]] = {}
        for notification in notifications:
            if not isinstance(notification, dict):
                continue
            updates = notification.get("update")
            if not isinstance(updates, list):
                continue
            for update in updates:
                if not isinstance(update, dict):
                    continue
                domain = self._detect_domain(update)
                grouped_updates.setdefault(domain, []).append(update)

        if not grouped_updates:
            return {}

        return {
            domain: {"notification": [{"update": updates}]}
            for domain, updates in grouped_updates.items()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self, domain: str) -> dict[str, Any] | None:
        """Perform a gNMI Get for a single OpenConfig domain.

        Parameters
        ----------
        domain:
            One of the keys in :data:`OPENCONFIG_PATHS` (e.g. ``"interfaces"``).

        Returns
        -------
        dict or None:
            The raw gNMI response dict, or ``None`` on failure.
        """
        path = OPENCONFIG_PATHS.get(domain, domain)
        try:
            with gNMIclient(**self._client_kwargs()) as gc:
                result = gc.get(path=[path], encoding=self.encoding)
                return result  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning("gNMI collect(%s) failed: %s", domain, exc)
            return None

    def collect_root(self) -> dict[str, Any] | None:
        """Fetch the device root path to discover all supported native schema data."""
        try:
            with gNMIclient(**self._client_kwargs()) as gc:
                result = gc.get(path=[GNMI_ROOT_PATH], encoding=self.encoding)
                return result  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning("gNMI collect_root() failed: %s", exc)
            return None

    def collect_all(self, prefer_root: bool = True) -> dict[str, dict[str, Any] | None]:
        """Collect all configured OpenConfig domains.

        When ``prefer_root`` is enabled, the collector first attempts a root
        ``/`` fetch and then groups the returned updates by detected domain.
        If that fails, it falls back to the fixed per-domain OpenConfig paths.

        Returns
        -------
        dict:
            ``{domain: response_or_None}`` for each domain in
            :data:`OPENCONFIG_PATHS`.
        """
        if prefer_root:
            root_result = self.collect_root()
            if root_result is not None:
                split_result = self._split_root_response(root_result)
                if split_result:
                    return split_result
                return {"root": root_result}

        results: dict[str, dict[str, Any] | None] = {}
        for domain in OPENCONFIG_PATHS:
            results[domain] = self.collect(domain)
        return results

    def set_config(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Push configuration via gNMI Set (update operation).

        Parameters
        ----------
        path:
            Full OpenConfig path string (e.g.
            ``"openconfig-interfaces:interfaces/interface[name=eth0]/config"``).
        payload:
            JSON-serializable dict to set at the path.

        Returns
        -------
        dict or None:
            The gNMI Set response, or ``None`` on failure.
        """
        try:
            with gNMIclient(**self._client_kwargs()) as gc:
                result = gc.set(update=[(path, payload)])
                return result  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning("gNMI set_config(%s) failed: %s", path, exc)
            return None
