"""
olav.platform.services — Declarative external service registry

Manages external services (ContainerLab, NetBox, Grafana, etc.) via a
services.yaml configuration file.  Replaces ad-hoc MCP wrappers with native
schema-aware tool generation backed by api_registry.

Components:
  ServiceRegistry  — loads services.yaml, exposes ServiceConfig objects
  service_call     — authenticated HTTP client with schema-aware trimming
  register_service — full registration flow: fetch spec → api_registry → generate tools
"""

from olav.platform.services.registry import ServiceConfig, ServiceRegistry
from olav.platform.services.client import service_call

__all__ = [
    "ServiceConfig",
    "ServiceRegistry",
    "service_call",
]
