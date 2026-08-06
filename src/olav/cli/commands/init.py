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

from olav.core.db_write import open_write_connection

import json
import os
import socket
import pwd
from pathlib import Path

from olav.cli.commands.base import BaseCommand
from olav.core.memory.guide_kb import prime_workspace_guides

_SERVICES_YAML_TEMPLATE = """\
# services.yaml — External service registry
# Run: olav registry register <name>
# Reference: dev_docs/archive/19. SERVICE_REGISTRY_DESIGN.md
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
        # Whether THIS run created the config. Only a genuinely fresh install may
        # have its auth.mode chosen for it; an existing api.json carries the
        # operator's decision (see _init_admin_user).
        self._wrote_fresh_api_json = not api_json_path.exists()
        if not api_json_path.exists():
            api_json_path.write_text(
                json.dumps(
                    {
                        "shared": {
                            "api_key": "",
                        },
                        "llm": {
                            "provider": "openai",
                            # model_provider is required by LangChain
                            # init_chat_model when the ``model`` name doesn't
                            # match a known provider prefix.  Default to
                            # "openai" since most OpenAI-compatible servers
                            # (llama.cpp, OpenRouter, Together, ...) speak
                            # the OpenAI Chat Completions API.  Override
                            # only when targeting a non-OpenAI dialect
                            # (anthropic / cohere / google_genai / ...).
                            "model_provider": "openai",
                            "model": "gpt-4o",
                        },
                        # Must match EmbeddingConfig.mode's default (core/
                        # config.py). Writing "local" here — as this did until
                        # 2026-08-04 — is worse than writing nothing: an
                        # explicit value in api.json *overrides* the default, so
                        # every fresh install landed on the on-CPU path whose
                        # package now ships only in the `[local-embed]` extra,
                        # i.e. silently no embedding at all. Guarded by
                        # test_init_skeleton_embedding_mode_matches_the_default.
                        "embedding": {
                            "mode": "api",
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

        # Platform workspaces (core, services, ...) — every dir under
        # ``src/olav/data/workspace/`` ships in the wheel and gets deployed
        # to ``.olav/workspace/<name>/`` on init.
        core_status = self._deploy_platform_workspaces(base_dir / "workspace")

        # Pre-download embedding model so first query doesn't hit HF Hub
        embedder_status = self._ensure_embedding_model()

        # Pre-warm semantic router + LanceDB memory table to eliminate first-query penalty
        index_status = self._warmup_indexes()

        # Prime every ``*.guide.yaml`` under the just-deployed workspace into
        # LanceDB ``usage_guide`` memory rows so AutoRecall surfaces them on
        # the first agent call.  Without this, core's routing / format /
        # diagnostic guides only land in memory after a separate
        # ``olav kb import-guides`` or as a side-effect of ``/netops_init``.
        # See dev_docs/00 § ISSUE-WORKSPACE-GUIDES-NOT-AUTO-PRIMED-AT-INIT.
        guides_status = prime_workspace_guides(base_dir / "workspace")

        # LLM connectivity check
        llm_status = await self._check_llm()

        # M4: Auto-create admin user + set auth.mode=token
        user_status = self._init_admin_user(base_dir)

        # Rebuild global agent registry (deterministic, no LLM)
        try:
            from olav.cli.commands.refresh import refresh_workspace

            refresh_status = refresh_workspace(base_dir / "workspace")
        except Exception as exc:  # noqa: BLE001
            refresh_status = f"⚠ skipped ({exc})"

        # Bootstrap api_registry.services in main.duckdb from services.yaml
        try:
            from olav.platform.services.registry_sync import bootstrap_from_yaml

            svc_result = bootstrap_from_yaml()
            svc_status = f"synced {svc_result.get('synced', 0)} services"
        except Exception as exc:  # noqa: BLE001
            svc_status = f"⚠ skipped ({exc})"

        return (
            "platform ready: created .olav scaffolding\n"
            f"llm: {llm_status}\n"
            f"db: {db_status}\n"
            f"workspace: {core_status}\n"
            f"embedder: {embedder_status}\n"
            f"indexes: {index_status}\n"
            f"guides: {guides_status}\n"
            f"auth: {user_status}\n"
            f"registry: {refresh_status}\n"
            f"services: {svc_status}\n"
            f"cron: {self._cron_hint()}"
        )

    def _cron_hint(self) -> str:
        """One-line, opt-in hint for scheduled self-management jobs.

        init deliberately does NOT write to the user's crontab (a recurring
        `olav --auto-approve` job is a daily LLM call, and `snapshot` SSHes to
        live devices) — so this only *points at* the explicit activation
        command. If jobs are already active, say so instead.
        """
        import subprocess

        try:
            out = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, timeout=5
            )
            active = sum(1 for ln in out.stdout.splitlines() if "olav:" in ln)
        except Exception:  # noqa: BLE001
            active = 0
        if active:
            return f"✓ {active} scheduled job(s) active (`olav cron list`)"
        return "○ optional — daily self-reflection etc. via `olav cron enable reflect`"

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
            from olav.core.auth.schema import apply_baseline

            users_db.parent.mkdir(parents=True, exist_ok=True)
            with open_write_connection(str(users_db)) as conn:
                apply_baseline(conn)
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

            # Persist the token — OS keyring preferred, ~/.olav/token fallback.
            # keyring_store uses a per-workspace service name derived from the
            # users.duckdb path, so dev / demo environments no longer clobber
            # one another's token.  See olav.core.auth.keyring_store.
            from olav.core.auth.keyring_store import save_token

            _token_storage = save_token(token, users_db_path=users_db)

            # Update api.json auth.mode → token, but ONLY if that mode can be
            # served. ``token`` lives in olav-ent (dev_docs/111 tiered model) and
            # get_auth_provider() raises NotImplementedError for it by design —
            # silently downgrading an intended login to OS identity would be a
            # security surprise. Writing the mode on a stock olav(+olav-netops)
            # install therefore bricks **every** query path: `olav init` and
            # `olav doctor` both still report success, and the first real
            # question dies with "auth.mode='token' requires olav-ent".
            #
            # Found on 2026-08-05 by installing the built wheels on a clean VM.
            # A dev machine cannot reproduce it: olav.enterprise is importable
            # there, so the mode resolves and the write looks harmless.
            try:
                from olav.enterprise.auth.token import (  # noqa: F401
                    TokenAuthProvider as _TokenProbe,
                )

                _token_mode_available = True
            except ImportError:
                _token_mode_available = False

            # Only choose the mode on a config this run created. The old
            # condition was `if mode != "token": set token`, which overwrote
            # ANY other value — including an explicit `"mode": "none"` the
            # operator had set — so re-bootstrapping after e.g. a model change
            # silently flipped the install's auth posture with no message.
            _fresh = getattr(self, "_wrote_fresh_api_json", False)
            api_json_path = base_dir / "config" / "api.json"
            if api_json_path.exists() and _token_mode_available and _fresh:
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

            try:
                host_ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                host_ip = "localhost"
            if _token_storage == "keyring":
                storage_line = "  token → OS keyring (shown once below)"
            else:
                from olav.core.auth.keyring_store import _per_env_token_path

                storage_line = (
                    f"  token → {_per_env_token_path(users_db)} "
                    "(chmod 600, keyring unavailable)"
                )
            mode_line = ""
            if not _token_mode_available:
                # The user + token are still created (they become usable the
                # moment olav-ent is installed), but say plainly that this
                # install authenticates by OS identity.
                mode_line = (
                    "  auth.mode stays 'none' (OS identity) — token login "
                    "needs olav-ent\n"
                )
            return (
                f"✓ admin user '{username}' created\n"
                f"{storage_line}\n"
                f"{mode_line}"
                f"  token (copy to save elsewhere): {token}\n"
                f"  web login: http://{host_ip}:2280/?token={token}"
            )

        except Exception as exc:  # noqa: BLE001
            return f"⚠ user init skipped ({exc})"

    @staticmethod
    def _ensure_embedding_model() -> str:
        """Download the local embedding model if not already cached.

        Runs the download with stderr suppressed so the user sees a clean
        status line instead of HuggingFace progress bars and warnings.
        """
        import logging as _logging
        import os as _os
        for _n in ("sentence_transformers", "transformers", "huggingface_hub"):
            _logging.getLogger(_n).setLevel(_logging.ERROR)
        _os.environ["SAFETENSORS_FAST_GPU"] = "0"
        _os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

        try:
            from olav.core.config import get_embedding_config

            cfg = get_embedding_config()
            if cfg.mode != "local":
                return "✓ embedder skipped (mode=api)"

            model_name = cfg.local_model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                # Ships in the `[local-embed]` extra since 2026-08-04, not the
                # default install. The generic handler below would report a
                # bare "No module named 'sentence_transformers'", which is a
                # dead end for someone who deliberately selected local mode.
                # `\[` escapes the bracket: both callers render this string
                # through rich, which would otherwise read "[local-embed]" as
                # a style tag and drop the extra's name from the message.
                return (
                    "⚠ mode=local but sentence-transformers is not installed — "
                    "`pip install 'olav\\[local-embed]'`, or set "
                    'embedding.mode = "api"'
                )

            # Suppress C-level stdout+stderr (safetensors shard reports come on fd 2)
            _saved1 = _os.dup(1)
            _saved2 = _os.dup(2)
            _devnull = _os.open(_os.devnull, _os.O_WRONLY)
            def _quiet():
                _os.dup2(_devnull, 1)
                _os.dup2(_devnull, 2)
            def _restore():
                _os.dup2(_saved1, 1)
                _os.dup2(_saved2, 2)
                _os.close(_devnull)
                _os.close(_saved1)
                _os.close(_saved2)

            # Try local cache first
            try:
                _quiet()
                try:
                    SentenceTransformer(model_name, local_files_only=True)
                finally:
                    _restore()
                return f"✓ {model_name} (cached)"
            except OSError:
                pass

            # Download
            print(f"  ⏳ downloading embedding model {model_name}...")
            _saved1b = _os.dup(1)
            _saved2b = _os.dup(2)
            _devnull2 = _os.open(_os.devnull, _os.O_WRONLY)
            _os.dup2(_devnull2, 1)
            _os.dup2(_devnull2, 2)
            try:
                SentenceTransformer(model_name)
            finally:
                _os.dup2(_saved1b, 1)
                _os.dup2(_saved2b, 2)
                _os.close(_devnull2)
                _os.close(_saved1b)
                _os.close(_saved2b)
            return f"✓ {model_name} downloaded"
        except Exception as exc:
            return f"⚠ embedder download failed ({exc})"

    def _warmup_indexes(self) -> str:
        """Pre-warm semantic router LanceDB index and memory table.

        Prevents ~2s first-query penalty by creating the LanceDB index at init
        time rather than lazily on the first user query.
        """
        results = []
        try:
            from olav.core.router import initialize_router
            init_result = initialize_router()
            n = init_result.get("count", 0)
            results.append(f"router({n} entries)")
        except Exception as exc:  # noqa: BLE001
            results.append(f"router(⚠ {exc})")
        try:
            from olav.core.memory import get_store
            get_store()  # ensures LanceDB memory table + index are created
            results.append("memory(ready)")
        except Exception as exc:  # noqa: BLE001
            results.append(f"memory(⚠ {exc})")
        return "✓ " + ", ".join(results)

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

    def _deploy_platform_workspaces(self, workspace_root: Path) -> str:
        """Deploy every platform agent workspace from bundled package data.

        Walks ``olav.data.workspace.*``  (every top-level dir under
        ``src/olav/data/workspace/``) and copies each into
        ``.olav/workspace/<name>/``.

        **Converges** the runtime dir onto the source: a file whose bytes
        differ is refreshed, not skipped. Until 2026-08-04 this was
        ``elif not dst.exists()`` — existing files were never overwritten, to
        protect user customisations. That predates the WORKSPACE-DUAL-COPY-DEBT
        Phase 3 dedup, which made ``.olav/workspace/*`` a *generated,
        git-ignored mirror* whose sole authority is the wheel source. Under
        that model skipping was a bug with two live symptoms: an edit to the
        authoritative source never reached any already-initialised install, and
        six platform Python files had silently diverged. ``olav skill install``
        (skill.py) already overwrote unconditionally for the netops mirror, so
        this also removes an inconsistency between the two deploy paths.

        Refreshing is **non-destructive**: the replaced file is first copied to
        ``.olav/backups/workspace/<timestamp>/<agent>/<rel>``. Backups live
        outside ``.olav/workspace/`` on purpose — a stray ``*.py`` inside a
        ``tools/`` pool would be picked up as a real ``@tool``.
        ``OLAV_INIT_PRESERVE_WORKSPACE=1`` restores the old skip-everything
        behaviour for anyone deliberately hand-editing the runtime copy.

        Replaces the earlier hard-coded ``_deploy_core_workspace``
        which only deployed ``core`` — services / future platform
        agents were silently dropped on fresh installs (see
        ``ISSUE-SERVICES-AGENT-NOT-PACKAGED``).
        """
        import os
        import shutil
        from datetime import UTC, datetime

        preserve_local = os.environ.get("OLAV_INIT_PRESERVE_WORKSPACE") == "1"
        backup_root = (
            workspace_root.parent / "backups" / "workspace"
            / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )

        try:
            from importlib.resources import files as _pkg_files
            bundled_root = _pkg_files("olav.data.workspace")
            bundled_root_path = Path(str(bundled_root))
        except Exception:  # noqa: BLE001
            bundled_root_path = None

        try:
            workspace_root.mkdir(parents=True, exist_ok=True)

            if bundled_root_path and bundled_root_path.is_dir():
                deployed: list[str] = []
                refreshed: list[str] = []
                # Iterate top-level subdirs only — each is an agent workspace.
                # Skip __pycache__ / dot-files / __init__.py.
                for agent_src in sorted(bundled_root_path.iterdir()):
                    if not agent_src.is_dir():
                        continue
                    if agent_src.name.startswith((".", "_")):
                        continue
                    agent_dst = workspace_root / agent_src.name
                    agent_dst.mkdir(parents=True, exist_ok=True)
                    for src in agent_src.rglob("*"):
                        rel = src.relative_to(agent_src)
                        if any(p.startswith("__pycache__") for p in rel.parts):
                            continue
                        dst = agent_dst / rel
                        if src.is_dir():
                            dst.mkdir(parents=True, exist_ok=True)
                            continue
                        if not dst.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            continue
                        if preserve_local:
                            continue
                        # Compare bytes, not mtime: an editable install and a
                        # wheel install produce unrelated timestamps for
                        # identical content, so mtime would churn every run.
                        if src.read_bytes() == dst.read_bytes():
                            continue
                        keep = backup_root / agent_src.name / rel
                        keep.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(dst, keep)
                        shutil.copy2(src, dst)
                        refreshed.append(f"{agent_src.name}/{rel}")
                    deployed.append(agent_src.name)
                if deployed:
                    msg = f"✓ platform workspaces deployed: {', '.join(deployed)}"
                    if refreshed:
                        # Named, not just counted: a refresh replaced content
                        # someone may have been editing, so it must be
                        # reviewable from the init output alone.
                        msg += (
                            f"\n  ↻ refreshed {len(refreshed)} drifted file(s) "
                            f"from the wheel source; previous copies in "
                            f"{backup_root}:\n"
                            + "\n".join(f"      {r}" for r in refreshed)
                        )
                    return msg

            # Fallback: bundle missing → write minimal core stubs only
            core_dir = workspace_root / "core"
            core_dir.mkdir(parents=True, exist_ok=True)
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

    # Back-compat alias — older code paths may still reference this name.
    def _deploy_core_workspace(self, core_dir: Path) -> str:
        return self._deploy_platform_workspaces(core_dir.parent)

    async def _check_llm(self) -> str:
        """Test LLM connectivity. Never raises — returns a human-readable status string."""
        try:
            from olav.core.config import ConfigLoader

            api_key = ConfigLoader().llm.api_key
            if not api_key:
                return "⚠ unavailable (no API key — edit .olav/config/api.json)"
        except Exception:  # noqa: BLE001
            return "⚠ unavailable (no API key — edit .olav/config/api.json)"
        try:
            from olav.core.llm import LLMFactory

            ok = LLMFactory.test_connectivity()
            if ok:
                return "✓ connected"
            return "⚠ unavailable (check api.json llm settings)"
        except Exception as exc:  # noqa: BLE001
            return f"⚠ unavailable ({exc})"
