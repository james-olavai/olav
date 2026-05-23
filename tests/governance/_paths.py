from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _first_existing(*candidates: Path) -> Path:
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


ROOT_WORKSPACE = REPO / ".olav" / "workspace"
NETOPS_WORKSPACE = REPO / "olav-netops" / ".olav" / "workspace" / "netops"

AUDIT_RUNNER_TOOLS = _first_existing(
    ROOT_WORKSPACE / "audit" / "audit-runner" / "scripts",
    ROOT_WORKSPACE / "audit" / "audit-runner" / "tools",
    ROOT_WORKSPACE / "audit" / "runner" / "scripts",
    ROOT_WORKSPACE / "audit" / "runner" / "tools",
)

NETOPS_TOOLS = _first_existing(
    NETOPS_WORKSPACE / "scripts",
    NETOPS_WORKSPACE / "tools",
    ROOT_WORKSPACE / "ops" / "scripts",
    ROOT_WORKSPACE / "ops" / "tools",
)

NETOPS_INIT_DIR = _first_existing(
    NETOPS_WORKSPACE / "netops_init",
    ROOT_WORKSPACE / "ops" / "netops_init",
)

ROUTING_EXPERT_GUIDE = _first_existing(
    NETOPS_WORKSPACE / "analyzer" / "references" / "ROUTING_EXPERT_GUIDE.md",
)
