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
import os
import pwd
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
                        "shared": {
                            "api_key": "",
                        },
                        "llm": {
                            "provider": "openai",
                            "model": "gpt-4o",
                        },
                        "embedding": {
                            "mode": "api",
                            "api": {
                                "model": "openai/text-embedding-3-small",
                            },
                            "fallback": {"enabled": True},
                        },
                        "auth": {"mode": "none"},
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

        # api.json — store active_workspace alongside LLM/auth config (skip if already set)
        api_path = base_dir / "config" / "api.json"
        if api_path.exists():
            try:
                api_data = json.loads(api_path.read_text(encoding="utf-8"))
                if "active_workspace" not in api_data:
                    api_data["active_workspace"] = "core"
                    api_path.write_text(json.dumps(api_data, indent=2), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

        # Platform databases
        db_status = self._init_databases(base_dir / "databases")

        # Core workspace
        core_status = self._deploy_core_workspace(base_dir / "workspace" / "core")

        # LLM connectivity check
        llm_status = await self._check_llm()

        # M4: Auto-create admin user + set auth.mode=token
        user_status = self._init_admin_user(base_dir)

        return (
            "platform ready: created .olav scaffolding\n"
            f"llm: {llm_status}\n"
            f"db: {db_status}\n"
            f"workspace: {core_status}\n"
            f"auth: {user_status}"
        )

    def _init_admin_user(self, base_dir: Path) -> str:
        """Create an admin user for $USER, write token to ~/.olav/token, set auth.mode=token.

        Skipped gracefully if:
        - $USER is not set (headless/CI environment)
        - Username not in /etc/passwd (container environment)
        - users.duckdb already has the user (idempotent)
        """
        username = os.environ.get("USER", "").strip()
        if not username:
            return "⚠ skipped (USER env not set)"

        # Verify Linux user exists
        try:
            pwd.getpwnam(username)
        except KeyError:
            return f"⚠ skipped (Linux user '{username}' not found)"

        try:
            from olav.cli.commands.admin_users import AdminUsersCommand

            users_db = base_dir / "databases" / "users.duckdb"
            admin_cmd = AdminUsersCommand(users_db=users_db)

            # Check if user already exists (idempotent)
            import duckdb
            from olav.core.migrations.v0_12_users import apply_migration as _apply_users

            users_db.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(users_db)) as conn:
                _apply_users(conn)
                existing = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE username = ?", [username]
                ).fetchone()[0]

            if existing:
                return f"✓ admin user '{username}' already exists"

            # Create admin user
            result = admin_cmd._add_user([username, "--role", "admin", "--no-verify"])
            # Extract token from result string ("Token (shown once...)\n  olav_xxx")
            token = ""
            for line in result.splitlines():
                stripped = line.strip()
                if stripped.startswith("olav_"):
                    token = stripped
                    break

            # Write token to ~/.olav/token
            token_dir = Path.home() / ".olav"
            token_dir.mkdir(parents=True, exist_ok=True)
            token_path = token_dir / "token"
            token_path.write_text(token + "\n", encoding="utf-8")
            token_path.chmod(0o600)

            # Update api.json auth.mode → token
            api_json_path = base_dir / "config" / "api.json"
            if api_json_path.exists():
                try:
                    api_data = json.loads(api_json_path.read_text(encoding="utf-8"))
                    if api_data.get("auth", {}).get("mode") != "token":
                        api_data.setdefault("auth", {})["mode"] = "token"
                        api_json_path.write_text(
                            json.dumps(api_data, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                except Exception:  # noqa: BLE001
                    pass

            return (
                f"✓ admin user '{username}' created\n"
                f"  token → ~/.olav/token (chmod 600)\n"
                f"  web login: http://localhost:2280/?token={token}"
            )

        except Exception as exc:  # noqa: BLE001
            return f"⚠ user init skipped ({exc})"

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
        """Deploy .olav/workspace/core/ from bundled package data.

        Copies the full core workspace (AGENT.md, MANIFEST.yaml, SKILL.md,
        tools/, prompts/, references/) from ``olav/data/workspace/core/``.
        Existing files are never overwritten so user customisations survive
        repeated ``olav init`` calls.
        """
        import shutil

        try:
            from importlib.resources import files as _pkg_files
            bundled = _pkg_files("olav.data.workspace") / "core"
            bundled_path = Path(str(bundled))
        except Exception:  # noqa: BLE001
            bundled_path = None

        try:
            core_dir.mkdir(parents=True, exist_ok=True)

            if bundled_path and bundled_path.is_dir():
                for src in bundled_path.rglob("*"):
                    rel = src.relative_to(bundled_path)
                    dst = core_dir / rel
                    if src.is_dir():
                        dst.mkdir(parents=True, exist_ok=True)
                    elif not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                return "✓ core workspace deployed"

            # Fallback: write minimal stubs if package data is unavailable
            try:
                from olav.core.version import __version__ as ver
            except Exception:  # noqa: BLE001
                ver = "0.1.0"
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
            return "✓ core workspace deployed (stubs only — package data missing)"
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
