"""
registry.py — Declarative service registry

Loads .olav/config/services.yaml and exposes ServiceConfig objects.
Singleton pattern: use ServiceRegistry.get_instance() to avoid repeated
YAML parsing across tool calls in the same process.

Reference: dev_docs/16. SERVICE_REGISTRY_DESIGN.md §Phase1
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuthConfig:
    type: str = "none"           # jwt | bearer | basic | api_key | none
    login_path: str = "/login"
    username_env: str = ""
    password_env: str = ""
    token_env: str = ""
    header_name: str = "Authorization"  # for api_key: header name (e.g. 'Authorization', 'X-Api-Key')


@dataclass
class ExecutionConfig:
    backend: str = "local"       # local | ssh
    host_env: str = ""
    user_env: str = ""


@dataclass
class LifecycleConfig:
    compose_file: str = ""
    service_name: str = ""
    health_check: str = ""
    health_timeout: int = 30


@dataclass
class ToolGroupConfig:
    tag: str = ""
    tool_prefix: str = ""
    description: str = ""


@dataclass
class ToolGenerationConfig:
    """Legacy config — retained for backward-compat parsing of old services.yaml.
    New services use ReferenceGenerationConfig instead."""
    output_dir: str = ".olav/workspace/infra/references"
    groups: list[ToolGroupConfig] = field(default_factory=list)


@dataclass
class ReferenceGenerationConfig:
    output_dir: str = ".olav/workspace/infra/references"
    groups: list[ToolGroupConfig] = field(default_factory=list)


@dataclass
class PermissionEntry:
    actions: list[str] = field(default_factory=list)
    operation_filter: str = ""   # regex to restrict operations (e.g. "^GET ")


@dataclass
class ServiceConfig:
    """Complete configuration for a registered external service."""

    name: str
    display_name: str = ""
    description: str = ""
    endpoint: str = ""
    schema_url: str = ""
    readonly_only: bool = True   # When True, tool_generator only imports GET ops
    # POST paths that are semantically read-only (e.g. InfluxDB /query, GraphQL /graphql)
    # These are included even when readonly_only=True
    readonly_post_paths: list[str] = field(default_factory=list)
    auth: AuthConfig = field(default_factory=AuthConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    lifecycle: LifecycleConfig = field(default_factory=LifecycleConfig)
    tool_generation: ToolGenerationConfig = field(default_factory=ToolGenerationConfig)
    reference_generation: ReferenceGenerationConfig = field(default_factory=ReferenceGenerationConfig)
    permissions: dict[str, PermissionEntry] = field(default_factory=dict)

    # ── convenience accessors ────────────────────────────────────────────────

    def get_token(self) -> str | None:
        """Read auth token: env var first, then service env file fallback."""
        if not self.auth.token_env:
            return None
        token = os.environ.get(self.auth.token_env)
        if token:
            return token
        # Fallback: load from .olav/services/<name>/env/<name>.env
        env_file = Path(f".olav/services/{self.name}/env/{self.name}.env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith(f"{self.auth.token_env}="):
                    token = line.split("=", 1)[1].strip()
                    if token:
                        os.environ[self.auth.token_env] = token  # cache in env
                        return token
        return None

    def get_ssh_host(self) -> str | None:
        """Read SSH host from configured env var."""
        if self.execution.host_env:
            return os.environ.get(self.execution.host_env)
        return None

    def get_ssh_user(self) -> str:
        """Read SSH user from configured env var (fallback: 'olav')."""
        if self.execution.user_env:
            return os.environ.get(self.execution.user_env, "olav")
        return "olav"

    def get_credentials(self) -> tuple[str, str]:
        """Return (username, password) from env vars."""
        user = os.environ.get(self.auth.username_env, "") if self.auth.username_env else ""
        pw = os.environ.get(self.auth.password_env, "") if self.auth.password_env else ""
        return user, pw


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = Path(".olav/config/services.yaml")


def _parse_auth(raw: dict) -> AuthConfig:
    return AuthConfig(
        type=raw.get("type", "none"),
        login_path=raw.get("login_path", "/login"),
        username_env=raw.get("username_env", ""),
        password_env=raw.get("password_env", ""),
        token_env=raw.get("token_env", ""),
        header_name=raw.get("header_name", "Authorization"),
    )


def _parse_execution(raw: dict) -> ExecutionConfig:
    return ExecutionConfig(
        backend=raw.get("backend", "local"),
        host_env=raw.get("host_env", ""),
        user_env=raw.get("user_env", ""),
    )


def _parse_lifecycle(raw: dict) -> LifecycleConfig:
    return LifecycleConfig(
        compose_file=raw.get("compose_file", ""),
        service_name=raw.get("service_name", ""),
        health_check=raw.get("health_check", ""),
        health_timeout=int(raw.get("health_timeout", 30)),
    )


def _parse_tool_generation(raw: dict) -> ToolGenerationConfig:
    groups = [
        ToolGroupConfig(
            tag=g.get("tag", ""),
            tool_prefix=g.get("tool_prefix", ""),
            description=g.get("description", ""),
        )
        for g in raw.get("groups", [])
    ]
    return ToolGenerationConfig(
        output_dir=raw.get("output_dir", ".olav/workspace/infra/references"),
        groups=groups,
    )


def _parse_reference_generation(raw: dict) -> ReferenceGenerationConfig:
    groups = [
        ToolGroupConfig(
            tag=g.get("tag", ""),
            tool_prefix=g.get("tool_prefix", ""),
            description=g.get("description", ""),
        )
        for g in raw.get("groups", [])
    ]
    return ReferenceGenerationConfig(
        output_dir=raw.get("output_dir", ".olav/workspace/infra/references"),
        groups=groups,
    )


def _parse_permissions(raw: dict) -> dict[str, PermissionEntry]:
    result: dict[str, PermissionEntry] = {}
    for role, entry in raw.items():
        result[role] = PermissionEntry(
            actions=list(entry.get("actions", [])),
            operation_filter=entry.get("operation_filter", ""),
        )
    return result


def _parse_service(name: str, raw: dict) -> ServiceConfig:
    import warnings

    tool_gen_raw = raw.get("tool_generation", {})
    ref_gen_raw = raw.get("reference_generation", {})

    # Backward compat: if only tool_generation present, migrate with deprecation warning
    if tool_gen_raw and not ref_gen_raw:
        warnings.warn(
            f"Service '{name}': 'tool_generation' is deprecated. "
            "Migrate to 'reference_generation'. "
            "Run: uv run python scripts/migrate_services_yaml.py --write",
            DeprecationWarning,
            stacklevel=3,
        )
        ref_gen_raw = tool_gen_raw  # use same groups/output_dir as fallback

    return ServiceConfig(
        name=name,
        display_name=raw.get("display_name", name),
        description=raw.get("description", ""),
        endpoint=raw.get("endpoint", ""),
        schema_url=raw.get("schema_url", ""),
        readonly_only=bool(raw.get("readonly_only", True)),
        readonly_post_paths=list(raw.get("readonly_post_paths", [])),
        auth=_parse_auth(raw.get("auth", {})),
        execution=_parse_execution(raw.get("execution", {})),
        lifecycle=_parse_lifecycle(raw.get("lifecycle", {})),
        tool_generation=_parse_tool_generation(tool_gen_raw),
        reference_generation=_parse_reference_generation(ref_gen_raw),
        permissions=_parse_permissions(raw.get("permissions", {})),
    )


class ServiceRegistry:
    """Loads and exposes service configs from services.yaml.

    Usage::

        registry = ServiceRegistry.get_instance()
        clab = registry.get("containerlab")
        print(clab.endpoint)
    """

    _instance: ServiceRegistry | None = None

    def __init__(self, config_path: Path = _DEFAULT_CONFIG) -> None:
        self._config_path = Path(config_path)
        self._services: dict[str, ServiceConfig] = {}
        self._loaded = False

    @classmethod
    def get_instance(cls, config_path: Path = _DEFAULT_CONFIG) -> ServiceRegistry:
        """Return singleton, loading from config_path on first call.

        Respects OLAV_SERVICES_PATH env var override (useful in tests).
        """
        if cls._instance is None:
            env_path = os.environ.get("OLAV_SERVICES_PATH")
            resolved = Path(env_path) if env_path else config_path
            cls._instance = cls(resolved)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (useful in tests)."""
        cls._instance = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._config_path.exists():
            self._loaded = True
            return
        with open(self._config_path) as f:
            doc: dict[str, Any] = yaml.safe_load(f) or {}
        for name, raw in doc.get("services", {}).items():
            self._services[name] = _parse_service(name, raw)
        self._loaded = True

    def get(self, name: str) -> ServiceConfig:
        """Return ServiceConfig for a named service. Raises KeyError if not found."""
        self._ensure_loaded()
        if name not in self._services:
            raise KeyError(
                f"Service '{name}' not found in {self._config_path}. "
                f"Available: {sorted(self._services)}"
            )
        return self._services[name]

    def list(self) -> list[ServiceConfig]:
        """Return all configured services."""
        self._ensure_loaded()
        return list(self._services.values())

    def reload(self) -> None:
        """Force reload from disk."""
        self._loaded = False
        self._services.clear()
        self._ensure_loaded()
