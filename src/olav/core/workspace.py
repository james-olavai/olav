"""workspace.py — WorkspaceDeclaration (workspace.yaml parser) and binary checks.

WorkspaceDeclaration is the parsed form of a workspace.yaml file bundled in a
skill git repo. It drives `olav skill install` to create the workspace directory
structure under .olav/workspace/<name>/.

Reference: dev_docs/18. ECOSYSTEM_SPLIT_PLAN.md §1.2
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RequiresDeclaration:
    packages: list[str] = field(default_factory=list)
    binaries: list[str] = field(default_factory=list)
    env_hint: list[str] = field(default_factory=list)


@dataclass
class AgentDeclaration:
    name: str
    kind: str = "Agent"
    description: str = ""
    route_keywords: list[str] = field(default_factory=list)
    agents: list["AgentDeclaration"] = field(default_factory=list)


@dataclass
class WorkspaceDeclaration:
    name: str
    version: str = "0.1.0"
    description: str = ""
    source: str | None = None
    set_active: bool = False
    requires: RequiresDeclaration = field(default_factory=RequiresDeclaration)
    db_schema: str | None = None
    init_command: str | None = None
    agents: list[AgentDeclaration] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "WorkspaceDeclaration":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        requires_raw = data.get("requires") or {}
        requires = RequiresDeclaration(
            packages=list(requires_raw.get("packages") or []),
            binaries=list(requires_raw.get("binaries") or []),
            env_hint=list(requires_raw.get("env_hint") or []),
        )
        agents = [_parse_agent(a) for a in (data.get("agents") or [])]
        return cls(
            name=data["name"],  # required — raises KeyError if absent
            version=str(data.get("version", "0.1.0")),
            description=str(data.get("description", "")),
            source=data.get("source"),
            set_active=bool(data.get("set_active", False)),
            requires=requires,
            db_schema=data.get("db_schema"),
            init_command=data.get("init_command"),
            agents=agents,
        )


def _parse_agent(data: dict) -> AgentDeclaration:
    nested = [_parse_agent(a) for a in (data.get("agents") or [])]
    return AgentDeclaration(
        name=data["name"],
        kind=str(data.get("kind", "Agent")),
        description=str(data.get("description", "")),
        route_keywords=list(data.get("route_keywords") or []),
        agents=nested,
    )


def check_binary_requirements(requires: RequiresDeclaration) -> list[str]:
    """Return list of binary names that are not on PATH."""
    return [b for b in requires.binaries if shutil.which(b) is None]
