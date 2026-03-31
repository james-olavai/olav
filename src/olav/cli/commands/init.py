"""Platform init command.

Creates the minimal project scaffolding required by the platform control plane.

Per design §0.3, init is ONLY for platform initialization:
  1. mkdir .olav/{config, workspace, databases, logs}
  2. Write .olav/config/api.json       (LLM skeleton)
  3. Write .olav/config/services.yaml  (empty service registry template)
  4. Write .olav/config/settings.json  (default: active_workspace=core)
  5. Initialize domain.duckdb + audit.duckdb
  6. Deploy .olav/workspace/core/      (core workspace, always present)
  7. Test LLM connectivity

NOT performed: YANG compilation, network views, device tables, syslog setup.
"""

from __future__ import annotations

import json
from pathlib import Path

from olav.cli.commands.base import BaseCommand

_SERVICES_YAML_TEMPLATE = """\
# services.yaml — External service registry
# Run: olav registry register <name>
# Reference: dev_docs/16. SERVICE_REGISTRY_DESIGN.md
services: {}
"""

_CORE_AGENT_MD = """\
---
name: core
kind: Agent
description: "Core OLAV platform agent"
version: "{version}"
---

# Core Workspace

Platform-level agent providing built-in capabilities.
Always present; cannot be uninstalled.

## Built-in Tools

- Memory recall
- Web search
- Format and export
"""

_CORE_MANIFEST_YAML = """\
kind: Agent
name: core
version: "{version}"
description: "Core OLAV platform agent (built-in)"
route_keywords:
  - help
  - version
  - status
  - workspace
managed: true
"""


class InitCommand(BaseCommand):
    """Create the minimal OLAV platform directory structure."""

    def __init__(self) -> None:
        super().__init__(name="init", description="Initialize platform scaffolding")

    async def execute(self, args: str = "") -> str:
        base_dir = Path(".olav")
        required_dirs = [
            base_dir / "config",
            base_dir / "workspace",
            base_dir / "databases",
            base_dir / "logs",
            Path("exports") / "snapshots" / "json",
            Path("exports") / "snapshots" / "raw",
        ]
        for directory in required_dirs:
            directory.mkdir(parents=True, exist_ok=True)

        # api.json — LLM skeleton (skip if already exists)
        api_json_path = base_dir / "config" / "api.json"
        if not api_json_path.exists():
            api_json_path.write_text(
                json.dumps(
                    {
                        "llm": {"provider": "openai", "model": "gpt-4-turbo"},
                        "embedding": {"mode": "local"},
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

        # services.yaml template (skip if already exists)
        services_yaml_path = base_dir / "config" / "services.yaml"
        if not services_yaml_path.exists():
            services_yaml_path.write_text(_SERVICES_YAML_TEMPLATE, encoding="utf-8")

        # settings.json — default active workspace (skip if already exists)
        settings_path = base_dir / "config" / "settings.json"
        if not settings_path.exists():
            settings_path.write_text(
                json.dumps({"active_workspace": "core"}, indent=2),
                encoding="utf-8",
            )

        # Platform databases
        db_status = self._init_databases(base_dir / "databases")

        # Core workspace
        core_status = self._deploy_core_workspace(base_dir / "workspace" / "core")

        # LLM connectivity check
        llm_status = await self._check_llm()

        return (
            "platform ready: created .olav scaffolding\n"
            f"llm: {llm_status}\n"
            f"db: {db_status}\n"
            f"workspace: {core_status}"
        )

    def _init_databases(self, db_dir: Path) -> str:
        """Create domain.duckdb and audit.duckdb (empty, just open+close)."""
        try:
            import duckdb

            for name in ("domain.duckdb", "audit.duckdb"):
                db_path = db_dir / name
                if not db_path.exists():
                    with duckdb.connect(str(db_path)):
                        pass  # creates the file
            return "✓ domain.duckdb + audit.duckdb ready"
        except Exception as exc:  # noqa: BLE001
            return f"⚠ skipped ({exc})"

    def _deploy_core_workspace(self, core_dir: Path) -> str:
        """Write .olav/workspace/core/ with AGENT.md and MANIFEST.yaml."""
        try:
            from olav.core.version import __version__ as ver
        except Exception:  # noqa: BLE001
            ver = "0.1.0"

        try:
            core_dir.mkdir(parents=True, exist_ok=True)
            agent_md = core_dir / "AGENT.md"
            if not agent_md.exists():
                agent_md.write_text(
                    _CORE_AGENT_MD.format(version=ver), encoding="utf-8"
                )
            manifest = core_dir / "MANIFEST.yaml"
            if not manifest.exists():
                manifest.write_text(
                    _CORE_MANIFEST_YAML.format(version=ver), encoding="utf-8"
                )
            return "✓ core workspace deployed"
        except Exception as exc:  # noqa: BLE001
            return f"⚠ skipped ({exc})"

    async def _check_llm(self) -> str:
        """Test LLM connectivity. Never raises — returns a human-readable status string."""
        try:
            from olav.core.llm import LLMFactory

            ok = LLMFactory.test_connectivity()
            if ok:
                return "✓ connected"
            return "⚠ unavailable (check api.json llm settings)"
        except Exception as exc:  # noqa: BLE001
            return f"⚠ skipped ({exc})"
