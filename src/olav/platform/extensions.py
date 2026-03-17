"""OLAV Platform — Domain Extension Protocols.

Defines the stable public interface that third-party domain packages must
implement.  Domain packages should import *only* from ``olav.platform``,
never from ``olav.core`` or ``olav.agents`` directly.

Design reference: dev_docs/olav_platform.md §11.2

Stability guarantee
-------------------
``src/olav/platform/`` is the **Stable Public API** for domain packages.
It follows SemVer and maintains backward compatibility within minor versions.
``src/olav/core/`` and ``src/olav/agents/`` are internal and may change at
any time without a major version bump.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DomainAgent(Protocol):
    """Protocol that every OLAV domain agent must satisfy.

    Domain packages implement this Protocol either by:

    1. Subclassing ``BaseDomainAgent`` (from ``olav.platform.agent_base``), or
    2. Implementing the interface directly (duck-typing).

    The Protocol is ``@runtime_checkable`` so callers can use
    ``isinstance(obj, DomainAgent)`` for introspection when needed.

    Attributes
    ----------
    domain_name : str
        Short identifier for this domain, e.g. ``"netops"``, ``"k8sops"``.
        Used as a routing key and as a namespace prefix for LanceDB collections
        and DuckDB schemas.

    Methods
    -------
    get_domain_prompt() -> str
        Return a domain-specific system-prompt string injected into the main
        OLAV system prompt.  Keep it concise — it becomes part of every LLM
        call's system context.

    get_workspace_path() -> str
        Return the relative path (from the project root ``.olav/workspace/``)
        to this agent's workspace directory.
        Example: ``"netops"`` → resolves to ``.olav/workspace/netops/``.

    describe() -> dict[str, Any]
        Return a machine-readable description of this domain agent, including
        at minimum: ``name``, ``version``, ``description``, ``workspace_path``.
    """

    @property
    def domain_name(self) -> str:
        """Short domain identifier, e.g. ``"netops"``."""
        ...

    def get_domain_prompt(self) -> str:
        """Return domain-specific system prompt fragment."""
        ...

    def get_workspace_path(self) -> str:
        """Return relative workspace path, e.g. ``"netops"``."""
        ...

    def describe(self) -> dict[str, Any]:
        """Return a dict describing this domain agent."""
        ...
