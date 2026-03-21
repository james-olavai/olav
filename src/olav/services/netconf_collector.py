"""NETCONF collector service for OpenConfig-native fallback collection (OC-11).

Provides a small wrapper around ``ncclient`` for capability discovery and
subtree retrieval of OpenConfig data. This service is intentionally separate
from the runtime sync workflow so it can be introduced and validated before
the full Diamond Path is switched to gNMI -> NETCONF -> SSH.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast

logger = logging.getLogger(__name__)


class _NetconfSession(Protocol):
    server_capabilities: list[str]

    def get_config(self, source: str, filter: tuple[str, str]) -> Any: ...

    def get(self, filter: tuple[str, str]) -> Any: ...


class _NetconfManager(Protocol):
    def __enter__(self) -> _NetconfSession: ...

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None: ...


class _ManagerModule(Protocol):
    def connect(self, **kwargs: Any) -> _NetconfManager: ...

try:
    from ncclient import manager
except ImportError:  # pragma: no cover
    manager = None  # type: ignore[assignment]

try:
    import xmltodict
except ImportError:  # pragma: no cover
    xmltodict = None  # type: ignore[assignment]


NETCONF_DEFAULT_PORT = 830

OPENCONFIG_NETCONF_FILTERS: dict[str, tuple[str, str]] = {
    "interfaces": (
        "openconfig-interfaces",
        '<interfaces xmlns="http://openconfig.net/yang/interfaces"/>',
    ),
    "bgp": (
        "openconfig-bgp",
        '<bgp xmlns="http://openconfig.net/yang/bgp"/>',
    ),
    "lldp": (
        "openconfig-lldp",
        '<lldp xmlns="http://openconfig.net/yang/lldp"/>',
    ),
    "platform": (
        "openconfig-platform",
        '<components xmlns="http://openconfig.net/yang/platform"/>',
    ),
}


_DOMAIN_ROOT_KEYS: dict[str, str] = {
    "interfaces": "interfaces",
    "bgp": "bgp",
    "lldp": "lldp",
    "platform": "components",
}


_OC_MODULE_KEYS: dict[str, str] = {
    "interfaces": "openconfig-interfaces",
    "bgp": "openconfig-bgp",
    "lldp": "openconfig-lldp",
    "platform": "openconfig-platform",
}


def _wrap_oc_domain(domain: str, content: dict[str, Any]) -> dict[str, Any]:
    module_key = _OC_MODULE_KEYS.get(domain)
    root_key = _DOMAIN_ROOT_KEYS.get(domain, domain)
    if module_key is None:
        return {root_key: content}
    return {module_key: {root_key: content}}


def empty_oc_domain(domain: str) -> dict[str, Any]:
    """Return an empty OC-shaped payload for a collected domain."""
    return _wrap_oc_domain(domain, {})


class NetconfCollector:
    """Thin NETCONF wrapper for capability-driven OpenConfig collection."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = NETCONF_DEFAULT_PORT,
        hostkey_verify: bool = False,
        timeout: int = 30,
        device_params: dict[str, Any] | None = None,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.hostkey_verify = hostkey_verify
        self.timeout = timeout
        self.device_params = device_params or {}

    def _connect_kwargs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "hostkey_verify": self.hostkey_verify,
            "timeout": self.timeout,
            "device_params": self.device_params,
        }

    def _parse_xml(self, payload: str) -> dict[str, Any] | None:
        if xmltodict is None:
            logger.warning("xmltodict is not installed")
            return None

        try:
            parsed = xmltodict.parse(payload)
        except Exception as exc:
            logger.warning("NETCONF XML parsing failed: %s", exc)
            return None

        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _has_meaningful_data(payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        current: Any = payload
        if "rpc-reply" in current and isinstance(current["rpc-reply"], dict):
            current = current["rpc-reply"]
        if "data" in current:
            data = current["data"]
            if data is None:
                return False
            if isinstance(data, dict):
                return bool(data)
            return True
        return bool(current)

    def get_capabilities(self) -> list[str]:
        """Return server capabilities reported by the NETCONF endpoint."""
        if manager is None:
            logger.warning("ncclient is not installed")
            return []

        manager_module = cast(_ManagerModule, manager)
        if manager_module is None:
            return []

        try:
            with manager_module.connect(**self._connect_kwargs()) as session:
                capabilities = getattr(session, "server_capabilities", [])
                return list(capabilities)
        except Exception as exc:
            logger.warning("NETCONF capability discovery failed: %s", exc)
            return []

    def collect(self, domain: str) -> dict[str, Any] | None:
        """Collect a single OpenConfig subtree via NETCONF.

        Tries ``get-config`` against running first, then falls back to ``get`` for
        operational/state data when the running datastore is empty.
        """
        if manager is None:
            logger.warning("ncclient is not installed")
            return None

        filter_info = OPENCONFIG_NETCONF_FILTERS.get(domain)
        if filter_info is None:
            logger.warning("Unsupported NETCONF domain: %s", domain)
            return None

        _, subtree_filter = filter_info
        manager_module = cast(_ManagerModule, manager)
        if manager_module is None:
            return None

        try:
            with manager_module.connect(**self._connect_kwargs()) as session:
                reply = session.get_config(source="running", filter=("subtree", subtree_filter))
                payload = getattr(reply, "xml", None)
                parsed = self._parse_xml(payload) if isinstance(payload, str) else None
                if self._has_meaningful_data(parsed):
                    return parsed

                get_method = getattr(session, "get", None)
                if callable(get_method):
                    reply = get_method(filter=("subtree", subtree_filter))
                    payload = getattr(reply, "xml", None)
                    parsed = self._parse_xml(payload) if isinstance(payload, str) else None
                    if self._has_meaningful_data(parsed):
                        return parsed

                if parsed is not None:
                    return parsed
        except Exception as exc:
            logger.warning("NETCONF collect(%s) failed: %s", domain, exc)
            return None

        logger.warning("NETCONF collect(%s) returned no XML payload", domain)
        return None

    def collect_all(self) -> dict[str, dict[str, Any] | None]:
        """Discover supported OpenConfig modules and collect matching subtrees."""
        capabilities = self.get_capabilities()
        results: dict[str, dict[str, Any] | None] = {}

        for domain, (module_name, _) in OPENCONFIG_NETCONF_FILTERS.items():
            if any(module_name in capability for capability in capabilities):
                results[domain] = self.collect(domain)

        return results


def resolve_oc_domains(
    raw_results: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    """Merge ``collect_all()`` raw xmltodict results into a flat {domain: oc_content} dict.

    Handles two common ncclient xmltodict wrapping patterns:
    * ``{"data": {"<domain>": <content>}}``
    * ``{"rpc-reply": {..., "data": {"<domain>": <content>}}}``

    If neither wrapper is found the value is kept as-is.  None entries (failed
    collections) are silently dropped.

    Returns
    -------
    dict mapping each successfully collected domain name to its OpenConfig content.
    """
    resolved: dict[str, Any] = {}
    for domain, payload in raw_results.items():
        if payload is None:
            continue
        resolved[domain] = _unwrap_oc_payload(domain, payload)
    return resolved


def _unwrap_oc_payload(domain: str, payload: dict[str, Any]) -> Any:
    """Peel off xmltodict/ncclient envelope layers to reach the OC content."""
    # Layer 1: rpc-reply wrapper
    if "rpc-reply" in payload:
        inner = payload["rpc-reply"]
        if isinstance(inner, dict):
            payload = inner

    # Layer 2: data wrapper
    if "data" in payload:
        data = payload["data"]
        if data is None:
            return empty_oc_domain(domain)
        if isinstance(data, dict):
            # The OC domain root key lives inside data (e.g. {"data": {"interfaces": {...}}})
            if domain in data and isinstance(data[domain], dict):
                return _wrap_oc_domain(domain, data[domain])
            root_key = _DOMAIN_ROOT_KEYS.get(domain, domain)
            if root_key in data and isinstance(data[root_key], dict):
                return _wrap_oc_domain(domain, data[root_key])
            return _wrap_oc_domain(domain, data)

    # No recognisable wrapper — return as-is when already canonical, else wrap.
    if any(isinstance(k, str) and k.startswith('openconfig-') for k in payload):
        return payload
    return _wrap_oc_domain(domain, payload)
