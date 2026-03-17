"""OLAV Platform — BaseDomainAgent optional base class.

Provides a concrete default implementation of the ``DomainAgent`` Protocol
(``olav.platform.extensions``) that domain packages can inherit from instead
of implementing the Protocol from scratch.

Design reference: dev_docs/olav_platform.md §11.2

Usage
-----
::

    # olav-k8sops: src/olav_k8sops/agent.py
    from olav.platform.agent_base import BaseDomainAgent

    class K8sOpsAgent(BaseDomainAgent):
        domain_name = "k8sops"
        _workspace_path = "k8sops"
        _version = "1.0.0"
        _description = "Kubernetes operations domain agent."

        def get_domain_prompt(self) -> str:
            return (
                "### Kubernetes Operations Domain\\n"
                "You assist with managing Kubernetes workloads, inspecting pods, "
                "deployments, and cluster health metrics stored in the k8sops schema."
            )
"""

from __future__ import annotations

from typing import Any

from olav.platform.extensions import DomainAgent


class BaseDomainAgent:
    """Optional concrete base class implementing the ``DomainAgent`` Protocol.

    Subclasses must set ``domain_name`` and optionally override ``_workspace_path``,
    ``_version``, and ``_description``.  At minimum, ``get_domain_prompt()``
    should be overridden to return a meaningful system-prompt fragment.

    Attributes
    ----------
    domain_name : str
        **Required.**  Short domain identifier (e.g. ``"k8sops"``).  Used as a
        routing key, DuckDB schema prefix, and LanceDB collection prefix.
    _workspace_path : str
        Relative path from ``.olav/workspace/`` to this agent's directory.
        Defaults to ``domain_name`` when not explicitly set.
    _version : str
        Semantic version string for this domain agent.  Used by
        ``olav workspace status`` to report installed vs available versions.
    _description : str
        One-sentence description of the domain.
    """

    # Subclasses override these class attributes
    domain_name: str = ""
    _workspace_path: str = ""
    _version: str = "0.1.0"
    _description: str = ""

    # ------------------------------------------------------------------
    # DomainAgent Protocol implementation
    # ------------------------------------------------------------------

    def get_domain_prompt(self) -> str:
        """Return a domain-specific system-prompt fragment.

        Override in subclasses to provide a meaningful description of the
        domain's capabilities.  The returned string is injected into the
        ``get_system_prompt()`` call in ``olav.cli.main``.

        Returns
        -------
        str
            Domain system prompt.  Should start with a Markdown ``###`` header.
        """
        return f"### {self.domain_name.capitalize()} Domain\nYou assist with {self.domain_name} operations."

    def get_workspace_path(self) -> str:
        """Return relative workspace path (defaults to ``domain_name``)."""
        return self._workspace_path or self.domain_name

    def describe(self) -> dict[str, Any]:
        """Return a machine-readable description of this domain agent."""
        return {
            "name": self.domain_name,
            "version": self._version,
            "description": self._description or f"{self.domain_name} domain agent",
            "workspace_path": self.get_workspace_path(),
        }

    # ------------------------------------------------------------------
    # Protocol compliance check
    # ------------------------------------------------------------------

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("domain_name"):
            # Warn (not error) so that abstract intermediary classes are allowed
            import warnings

            warnings.warn(
                f"{cls.__name__} does not set 'domain_name'. "
                "Set it as a class attribute, e.g. domain_name = 'k8sops'.",
                stacklevel=2,
            )

    # ------------------------------------------------------------------
    # Runtime type check
    # ------------------------------------------------------------------

    @classmethod
    def isinstance_check(cls, obj: Any) -> bool:
        """Check whether *obj* satisfies the ``DomainAgent`` Protocol."""
        return isinstance(obj, DomainAgent)
