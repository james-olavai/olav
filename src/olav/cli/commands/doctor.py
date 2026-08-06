"""``olav doctor`` — zero-LLM-judgement preflight / health check.

Per dev_docs/99 §3.1: a shared, deterministic health check for LLM and
embedding config, reused by (a) this command and (b) any future
config-write gate. Must not depend on the LLM being configured correctly,
since that is precisely what it checks — every step here is a filesystem
check or a live connectivity probe, never an LLM call asked to "judge"
anything.

Every failing check comes with an actionable next step, not just a status
flag — the point is to tell the user what to *do*, not just what is broken.
"""

from __future__ import annotations

import os
import json
from pathlib import Path

from olav.cli.commands.base import BaseCommand


class DoctorCommand(BaseCommand):
    """Report the health of the local OLAV installation."""

    def __init__(self) -> None:
        super().__init__(
            name="doctor",
            description="Check platform, LLM, and embedding health — zero LLM calls to judge itself",
        )

    async def execute(self, args: str = "") -> str:
        argv = args.split()
        as_json = "--json" in argv
        # `--verify` is the production answer to "does my lab validation
        # actually work?". Readiness (endpoint up, credentials set, images
        # present) is not the same question, and until now only a developer
        # running pytest with an env var nobody documents could answer it —
        # a hidden incantation is exactly what dev_docs/99 exists to remove.
        # Consent lives on a flag that `--help` describes, not in the
        # environment, because a switch nobody can discover is not a choice.
        deep = "--verify" in argv
        checks = [
            self._check_scaffolding(),
            self._check_workspace_integrity(),
            self._check_llm(),
            self._check_embedding(),
            self._check_auth(),
            self._check_context_budget(),
            self._check_agents(),
            self._check_subagents(),
            self._check_tools(),
            self._check_memory(),
            self._check_recall(),
            *self._check_services(deep=deep),
        ]

        if as_json:
            return json.dumps({"checks": checks, "ok": all(c["ok"] for c in checks)}, indent=2)

        return self._render_report(checks)

    def _render_report(self, checks: list[dict]) -> str:
        """Human-readable, colour-highlighted report (rich markup — the CLI
        prints this via ``console.print`` so tags render; dynamic strings are
        escaped so a path/detail containing ``[`` can't break markup)."""
        from rich.markup import escape

        name_w = max((len(c["name"]) for c in checks), default=8)
        n_pass = sum(1 for c in checks if c["ok"])
        lines = ["", "[bold]OLAV doctor[/bold] — local installation health", ""]
        for c in checks:
            if c["ok"]:
                glyph, colour = "✓", "green"
            else:
                # actionable failure (has a fix) reads as an error; a bare
                # not-ok with no fix is a soft warning.
                glyph, colour = ("✗", "red") if c.get("fix") else ("⚠", "yellow")
            name = escape(c["name"]).ljust(name_w)
            detail = escape(str(c["detail"]))
            lines.append(f"  [{colour}]{glyph}[/{colour}] [bold]{name}[/bold]  [dim]{detail}[/dim]")
            if not c["ok"] and c.get("fix"):
                lines.append(f"      [yellow]→ fix:[/yellow] {escape(str(c['fix']))}")

        all_ok = n_pass == len(checks)
        bar = "─" * (name_w + 40)
        lines.append(f"  [dim]{bar}[/dim]")
        if all_ok:
            verdict = f"[bold green]✓ healthy[/bold green]  [dim]({n_pass}/{len(checks)} checks passed)[/dim]"
        else:
            verdict = (
                f"[bold red]✗ needs attention[/bold red]  "
                f"[dim]({n_pass}/{len(checks)} passed — see → fix lines above)[/dim]"
            )
        lines.append(f"  {verdict}")
        lines.append(f"  [dim]cron:[/dim] {escape(self._cron_hint())}")
        lines.append("")
        return "\n".join(lines)

    def _cron_hint(self) -> str:
        """Opt-in pointer for scheduled self-management jobs — never auto-enabled
        (a recurring `olav --auto-approve` is a daily LLM call)."""
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
        return "○ optional — enable daily self-reflection via `olav cron enable reflect`"

    def _check_scaffolding(self) -> dict:
        try:
            from olav.core.config import get_paths_config

            base_dir = Path(get_paths_config().project_root).resolve() / ".olav"
        except Exception:  # noqa: BLE001
            base_dir = Path(".olav")
        required = [base_dir / "config" / "api.json", base_dir / "workspace"]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            return {
                "name": "scaffolding",
                "ok": False,
                "detail": f"missing: {', '.join(missing)}",
                "fix": "run `olav init`",
            }
        return {"name": "scaffolding", "ok": True, "detail": ".olav/ deployed"}

    def _check_workspace_integrity(self) -> dict:
        """Detect a split-workspace: a second, competing ``~/.olav`` holding
        real workspace state (config / databases / workspace) distinct from the
        one the runtime resolves. This is the failure that silently splits data
        when ``olav`` runs without ``OLAV_HOME`` from a home directory: device
        imports and users land in ``~/.olav`` while the deployed workspace is
        elsewhere (ISSUE-PROJECT-ROOT-STRAY-DOTOLAV). Only competing WORKSPACE
        artifacts flag it — the cache/checkpoints/sessions that ``~/.olav``
        legitimately holds by design are ignored, so a correct install stays
        green. Never raises."""
        import os

        try:
            from olav.core.config import get_paths_config

            resolved_root = Path(get_paths_config().project_root).resolve()
        except Exception:  # noqa: BLE001
            resolved_root = Path.cwd().resolve()
        resolved_olav = (resolved_root / ".olav").resolve()
        home_olav = (Path.home() / ".olav").resolve()

        olav_home_env = os.environ.get("OLAV_HOME")

        # A stray workspace = ~/.olav that (a) is NOT the resolved workspace and
        # (b) holds workspace-level state, not just the by-design cache dirs.
        workspace_markers = ["config/api.json", "workspace", "databases"]
        if home_olav != resolved_olav and home_olav.is_dir():
            competing = [m for m in workspace_markers if (home_olav / m).exists()]
            if competing:
                return {
                    "name": "workspace",
                    "ok": False,
                    "detail": (
                        f"two workspaces on disk — runtime uses {resolved_olav}, "
                        f"but a competing ~/.olav holds {', '.join(competing)} "
                        "(imports/users/config can split between them)"
                    ),
                    "fix": (
                        f"set OLAV_HOME={resolved_root} in your shell profile "
                        "(or always run from that dir); if ~/.olav is unwanted, "
                        "remove it after confirming it has no data you need"
                    ),
                }

        if not olav_home_env:
            return {
                "name": "workspace",
                "ok": True,
                "detail": (
                    f"{resolved_olav} (resolved from cwd — set OLAV_HOME to pin it "
                    "and avoid a stray ~/.olav)"
                ),
            }
        return {"name": "workspace", "ok": True,
                "detail": f"{resolved_olav} (OLAV_HOME pinned)"}

    def _check_llm(self) -> dict:
        try:
            from olav.core.config import ConfigLoader

            api_key = ConfigLoader().llm.api_key
        except Exception as exc:  # noqa: BLE001
            return {
                "name": "llm",
                "ok": False,
                "detail": f"config unreadable ({exc})",
                "fix": "run `olav init` to create .olav/config/api.json",
            }

        if not api_key:
            return {
                "name": "llm",
                "ok": False,
                "detail": "no API key configured",
                "fix": "set llm.api_key in .olav/config/api.json",
            }

        from olav.core.llm import LLMFactory

        ok, detail = LLMFactory.check_connectivity()
        # Name WHAT is configured, not just whether it answered — doctor is
        # the one-stop health view (dev_docs/99 §3.1). Never raises: a fake
        # or partial config yields whatever fields it has.
        summary = self._llm_config_summary()
        if summary:
            detail = f"{detail} — {summary}"
        return {
            "name": "llm",
            "ok": ok,
            "detail": detail,
            "fix": "check llm.model / llm.base_url / llm.api_key in .olav/config/api.json" if not ok else None,
        }

    @staticmethod
    def _llm_config_summary() -> str:
        try:
            from olav.core.config import get_llm_config

            cfg = get_llm_config()
            model = cfg.model
            endpoint = cfg.base_url or f"{cfg.model_provider or 'openai'} default endpoint"
            parts = [f"{model} @ {endpoint}"]
            tier = getattr(cfg, "model_tier", "")
            if tier:
                parts.append(f"tier={tier}")
            parts.append(f"timeout={cfg.timeout}s")
            return " · ".join(parts)
        except Exception:  # noqa: BLE001 — summary is best-effort decoration
            return ""

    def _check_auth(self) -> dict:
        """Is the configured auth mode one this install can actually serve?

        `auth.mode` lives in .olav/config/api.json (env override:
        OLAV_AUTH_MODE, default "none"). The token/server/ldap providers moved
        to olav-ent, and get_auth_provider raises for them by design rather than
        silently downgrading to OS identity — so a config naming one of those on
        a stock install makes every query path fail while init and the rest of
        doctor still report success. That is exactly how a clean-VM install came
        out bricked (dev_docs/115 §1).

        It also surfaces the mode itself, because `olav init` sets token when it
        creates the admin user: an operator who expects "none" needs to be able
        to see that it changed without reading api.json.
        """
        try:
            from olav.core.config import ConfigLoader

            mode = ConfigLoader().auth.mode
        except Exception as exc:  # noqa: BLE001
            return {
                "name": "auth",
                "ok": False,
                "detail": f"config unreadable ({exc})",
                "fix": "run `olav init` to create .olav/config/api.json",
            }

        source = "api.json"
        if os.environ.get("OLAV_AUTH_MODE"):
            source = "OLAV_AUTH_MODE env"

        try:
            from olav.core.auth.provider import get_auth_provider

            provider = type(get_auth_provider(mode)).__name__
        except NotImplementedError as exc:
            return {
                "name": "auth",
                "ok": False,
                "detail": f"mode={mode!r} ({source}) cannot be served — {exc}",
                "fix": "install olav-ent, or set auth.mode to 'none' "
                       "(OS identity) in .olav/config/api.json",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "name": "auth",
                "ok": False,
                "detail": f"mode={mode!r} ({source}) failed to load ({exc})",
                "fix": "check auth.mode in .olav/config/api.json",
            }

        return {
            "name": "auth",
            "ok": True,
            "detail": f"mode={mode} ({source}) → {provider}",
            "fix": None,
        }

    @staticmethod
    def _server_ctx_size(base_url: str, model: str) -> int | None:
        """Best-effort: the serving context window, discovered without inference.

        llama-swap's /v1/models carries each model's preset, which includes
        ``ctx-size``. Free to read and exact. Returns None when the endpoint does
        not expose it (a plain OpenAI endpoint, a different server), and the
        caller then reports only what OLAV is configured for.
        """
        import json as _json
        import re as _re
        import urllib.request as _u

        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        try:
            with _u.urlopen(f"{url}/v1/models", timeout=8) as r:
                data = _json.loads(r.read())
        except Exception:  # noqa: BLE001
            return None
        for entry in data.get("data") or []:
            if entry.get("id") != model:
                continue
            preset = ((entry.get("status") or {}).get("preset")) or ""
            m = _re.search(r"^\s*ctx-size\s*=\s*(\d+)", preset, _re.M)
            if m:
                return int(m.group(1))
        return None

    def _check_context_budget(self) -> dict:
        """Does OLAV's context budget fit inside what the server will accept?

        An agent run that overruns the server's window fails with HTTP 400
        ``exceed_context_size_error`` — "request (N tokens) exceeds the available
        context size (M tokens)" — which surfaces to the user as a bare agent
        error. The budget is what makes summarisation fire in time: deepagents
        falls back to a 170000-token trigger when the model profile carries no
        ``max_input_tokens``, so on a local endpoint nothing would compact before
        the wall (agent.py sets it from llm.context_budget or the tier default).

        Budget > server ctx is therefore a latent 400 on every long run, and it
        is checkable without inference.
        """
        try:
            from olav.core.config import TIER_DEFAULTS, get_llm_config

            cfg = get_llm_config()
        except Exception as exc:  # noqa: BLE001
            return {
                "name": "context",
                "ok": False,
                "detail": f"config unreadable ({exc})",
                "fix": "run `olav init` to create .olav/config/api.json",
            }

        explicit = cfg.context_budget
        budget = explicit or int(
            TIER_DEFAULTS.get(cfg.model_tier, {}).get("context_budget") or 0
        )
        source = "llm.context_budget" if explicit else f"tier={cfg.model_tier} default"
        served = self._server_ctx_size(cfg.base_url or "", cfg.model or "")

        if not budget:
            return {
                "name": "context",
                "ok": False,
                "detail": f"no context budget resolved ({source})",
                "fix": "set llm.context_budget in .olav/config/api.json",
            }
        if served is None:
            return {
                "name": "context",
                "ok": True,
                "detail": f"budget {budget} tok ({source}); server window not advertised",
                "fix": None,
            }
        if budget > served:
            return {
                "name": "context",
                "ok": False,
                "detail": (
                    f"budget {budget} tok ({source}) exceeds the server window "
                    f"{served} tok — long runs will fail with HTTP 400 "
                    "exceed_context_size_error"
                ),
                "fix": (
                    f"set llm.context_budget below {served} in "
                    ".olav/config/api.json, or raise the server's ctx-size"
                ),
            }
        return {
            "name": "context",
            "ok": True,
            "detail": f"budget {budget} tok ({source}) fits server window {served} tok",
            "fix": None,
        }

    def _check_embedding(self) -> dict:
        try:
            from olav.core.config import get_embedding_config

            config = get_embedding_config()
        except Exception as exc:  # noqa: BLE001
            return {
                "name": "embedding",
                "ok": False,
                "detail": f"config unreadable ({exc})",
                "fix": "run `olav init` to create .olav/config/api.json",
            }

        if config.mode == "api" and not config.api_key:
            return {
                "name": "embedding",
                "ok": False,
                "detail": "mode=api but no API key configured",
                "fix": "set embedding.api.api_key in .olav/config/api.json, or "
                       "switch embedding.mode to 'local' (needs "
                       "`pip install 'olav[local-embed]'`)",
            }

        # mode=local without the extra embeds nothing and says nothing: since
        # 2026-08-04 sentence-transformers ships in `[local-embed]`, so this is
        # a reachable misconfiguration rather than a theoretical one, and its
        # only symptom is memory/recall quietly returning nothing.
        if config.mode == "local":
            from olav.core.embedder import local_embed_available

            if not local_embed_available():
                return {
                    "name": "embedding",
                    "ok": False,
                    "detail": "mode=local but sentence-transformers is not installed",
                    "fix": "pip install 'olav[local-embed]', or set "
                           "embedding.mode to 'api' and point "
                           "embedding.api.base_url at an embedding endpoint",
                }

        from olav.core.llm import LLMFactory

        ok, detail = LLMFactory.check_embedding_connectivity()
        summary = self._embedding_config_summary(config, probe_dim=ok)
        if summary:
            detail = f"{detail} — {summary}"
        return {
            "name": "embedding",
            "ok": ok,
            "detail": detail,
            "fix": "check embedding.mode / embedding.api.* in .olav/config/api.json" if not ok else None,
        }

    @staticmethod
    def _embedding_config_summary(config, probe_dim: bool) -> str:
        try:
            if config.mode == "api":
                summary = f"api/{config.api_model} @ {config.openai_base_url or 'provider default endpoint'}"
            elif config.mode == "local":
                summary = f"local/{config.local_model}"
            else:
                return f"mode={config.mode}"
            if probe_dim:
                # Cached probe (embed_text of one string) — only when the
                # backend just answered, so this never adds a hang.
                try:
                    from olav.core.embedder import detect_embedding_dim

                    _dim = detect_embedding_dim()
                    # None means "could not probe" — say that rather than
                    # rendering "None-dim", and never a substituted number.
                    summary += f" · {_dim}-dim" if _dim else " · dim unknown (probe failed)"
                except Exception:  # noqa: BLE001
                    pass
            return summary
        except Exception:  # noqa: BLE001 — summary is best-effort decoration
            return ""

    # ── stack health (agents / subagents / tools / experience / recall) ──
    # All zero-LLM, filesystem + store reads only. Each is defensive — a
    # failure to introspect returns a ⚠ check, never crashes doctor.

    def _workspace_root(self) -> Path:
        try:
            from olav.core.config import get_paths_config

            return Path(get_paths_config().project_root) / ".olav" / "workspace"
        except Exception:  # noqa: BLE001
            return Path(".olav") / "workspace"

    @staticmethod
    def _frontmatter(skill_md: Path) -> dict:
        import yaml

        parts = skill_md.read_text(encoding="utf-8").split("---", 2)
        if len(parts) < 3:
            raise ValueError("no frontmatter")
        return yaml.safe_load(parts[1]) or {}

    def _check_agents(self) -> dict:
        """Top-level agents (<workspace>/<agent>/SKILL.md) parse cleanly."""
        root = self._workspace_root()
        if not root.is_dir():
            return {"name": "agents", "ok": False,
                    "detail": "no workspace deployed", "fix": "run `olav init`"}
        loaded, broken = [], []
        for p in sorted(root.glob("*/SKILL.md")):
            try:
                fm = self._frontmatter(p)
                (loaded if fm.get("name") else broken).append(
                    fm.get("name") or f"{p.parent.name} (no name)"
                )
            except Exception as exc:  # noqa: BLE001
                broken.append(f"{p.parent.name} ({exc})")
        detail = f"{len(loaded)} loaded, {len(broken)} failed"
        if broken:
            detail += " — " + ", ".join(broken[:3])
        return {"name": "agents", "ok": not broken, "detail": detail,
                "fix": "fix the flagged SKILL.md frontmatter" if broken else None}

    def _check_subagents(self) -> dict:
        """Every sub-agent (<agent>/<sub>/SKILL.md) is declared by its parent,
        and every declared subagents: path resolves. Mirrors the reachability
        governance gate, at runtime against the deployed workspace."""
        root = self._workspace_root()
        if not root.is_dir():
            return {"name": "subagents", "ok": False,
                    "detail": "no workspace", "fix": "run `olav init`"}
        # One definition, beside the scan that makes it true (agent.py).
        from olav.agents.agent import AUTODISCOVERED_SKILLS as auto
        total, orphans, unresolved = 0, [], []
        for parent in sorted(root.glob("*/SKILL.md")):
            try:
                fm = self._frontmatter(parent)
            except Exception:  # noqa: BLE001
                continue
            declared_paths = [
                s["path"] for s in (fm.get("subagents") or [])
                if isinstance(s, dict) and s.get("path")
            ]
            declared_names = {Path(p).parent.name for p in declared_paths}
            for rel in declared_paths:
                if not (parent.parent / rel).exists():
                    unresolved.append(f"{parent.parent.name}:{rel}")
            for sub in sorted(parent.parent.glob("*/SKILL.md")):
                total += 1
                name = sub.parent.name
                if name not in declared_names and name not in auto:
                    orphans.append(f"{parent.parent.name}/{name}")
        ok = not orphans and not unresolved
        detail = f"{total} wired, {len(orphans)} orphaned"
        if unresolved:
            detail += f", {len(unresolved)} unresolved"
        if orphans:
            detail += " — " + ", ".join(orphans[:3])
        return {"name": "subagents", "ok": ok, "detail": detail,
                "fix": "declare orphans in the parent's subagents: list" if not ok else None}

    def _check_tools(self) -> dict:
        """@tool files under <workspace>/**/tools/ compile (a broken tool file
        breaks the agent that loads it). Syntax-check only — no import (fast,
        no side effects)."""
        root = self._workspace_root()
        if not root.is_dir():
            return {"name": "tools", "ok": False, "detail": "no workspace"}
        count, errors = 0, []
        for tp in root.rglob("tools/*.py"):
            if tp.name.startswith("_"):
                continue
            count += 1
            try:
                compile(tp.read_text(encoding="utf-8"), str(tp), "exec")
            except SyntaxError as exc:
                errors.append(f"{tp.name}:{exc.lineno}")
        detail = f"{count} registered, {len(errors)} syntax error(s)"
        if errors:
            detail += " — " + ", ".join(errors[:3])
        return {"name": "tools", "ok": not errors, "detail": detail,
                "fix": "fix the flagged tool file(s)" if errors else None}

    # ── registered services ──────────────────────────────────────────────
    #
    # services.yaml is already the registry of "what I have"; doctor derives a
    # probe from each entry, so a service the user registers (NetBox, gitea)
    # is checked with no extra step. A skill that knows more about its own
    # readiness ships a `healthcheck.yaml` naming the service — discovered,
    # never written back into services.yaml, which is user-owned.
    #
    # Severity uses doctor's existing convention: not-ok WITHOUT a fix renders
    # as a soft ⚠ (the environment is down — not your install), not-ok WITH a
    # fix renders as ✗ (actionable misconfiguration). A service nobody
    # registered produces no check at all, so an unused integration cannot
    # turn `olav doctor` red.

    @staticmethod
    def _service_specs() -> dict:
        """service name → (skill dir, spec) for every installed healthcheck."""
        import yaml as _yaml

        out: dict[str, tuple[Path, dict]] = {}
        root = Path(".olav") / "workspace"
        if not root.is_dir():
            return out
        for spec_path in root.glob("*/*/healthcheck.yaml"):
            try:
                spec = _yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                continue
            name = spec.get("service")
            if name:
                out[str(name)] = (spec_path.parent, spec)
        return out

    def _check_services(self, deep: bool = False) -> list[dict]:
        import socket
        from urllib.parse import urlparse

        import yaml as _yaml

        path = Path(".olav") / "config" / "services.yaml"
        if not path.is_file():
            return []
        try:
            doc = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            return [{"name": "services", "ok": False,
                     "detail": f"services.yaml unparseable ({exc})",
                     "fix": "fix or remove .olav/config/services.yaml"}]

        services = doc.get("services") or {}
        # LEGACY-KEEP: pre-v0.15 services.yaml stored `services` as a list of
        # dicts. `_prime_lab_services_from_config` tolerates the same shape, so
        # doctor must too — reading a config the installer still accepts and
        # calling it unparseable would report a fault that is not there.
        if isinstance(services, list):
            services = {e.get("name", f"unnamed_{i}"): e
                        for i, e in enumerate(services) if isinstance(e, dict)}
        if not services:
            return []

        specs = self._service_specs()
        checks: list[dict] = []
        for name in sorted(services):
            entry = services[name] or {}
            checks.append(self._probe_service(name, entry, socket, urlparse))
            skill = specs.get(name)
            if skill:
                checks.extend(self._skill_health(name, *skill))
                if deep:
                    checks.extend(self._skill_verify(name, *skill))
        return checks

    @staticmethod
    def _probe_service(name: str, entry: dict, socket, urlparse) -> dict:
        """Endpoint reachable + declared credential env vars actually set."""
        label = f"service:{name}"
        endpoint = entry.get("endpoint")
        if not endpoint:
            return {"name": label, "ok": False,
                    "detail": "no endpoint configured",
                    "fix": f"set services.{name}.endpoint in "
                           f".olav/config/services.yaml"}
        u = urlparse(endpoint if "//" in endpoint else f"//{endpoint}")
        port = u.port or (443 if u.scheme == "https" else 80)
        try:
            with socket.create_connection((u.hostname, port), timeout=4):
                reachable = True
        except OSError:
            reachable = False
        if not reachable:
            # Environment, not installation: soft ⚠ (no fix key on purpose).
            return {"name": label, "ok": False,
                    "detail": f"{u.hostname}:{port} unreachable"}

        auth = entry.get("auth") or {}
        missing = [
            v for k, v in auth.items()
            if k.endswith("_env") and v and not os.environ.get(v)
        ]
        if missing:
            return {"name": label, "ok": False,
                    "detail": f"reachable; credential env unset: "
                              f"{', '.join(sorted(missing))}",
                    "fix": f"export {' and '.join(sorted(missing))}"}
        return {"name": label, "ok": True,
                "detail": f"{u.hostname}:{port} reachable"
                          + (f", {auth.get('type')} creds set" if auth else "")}

    @classmethod
    def _skill_health(cls, name: str, skill_dir: Path, spec: dict) -> list[dict]:
        """Run the skill's read-only readiness script and adopt its checks."""
        script = spec.get("script")
        if not script:
            return []
        return cls._run_skill_script(name, skill_dir, str(script), label="readiness")

    @staticmethod
    def _run_skill_script(
        name: str, skill_dir: Path, script: str, *, label: str, timeout: int = 60
    ) -> list[dict]:
        """Execute one skill-supplied check script and adopt its findings.

        Shared by the readiness and verify paths — they differ only in which
        script they name and how long it may take, and duplicating the
        error handling is how one of them ends up silently swallowing a
        crash while the other reports it.
        """
        import subprocess
        import sys as _sys

        target = skill_dir / "scripts" / script
        if not target.is_file():
            return [{"name": f"{name}: {label}", "ok": False,
                     "detail": f"healthcheck.yaml names {script!r}, which is "
                               f"not in {skill_dir.name}/scripts/",
                     "fix": "reinstall the skill providing this service"}]
        try:
            proc = subprocess.run([_sys.executable, str(target)],
                                  capture_output=True, text=True, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return [{"name": f"{name}: {label}", "ok": False,
                     "detail": f"{label} script failed to run "
                               f"({type(exc).__name__}: {exc})"}]
        # A script that dies prints nothing, and `json.loads("{}")` succeeds —
        # so without these branches a CRASHED check produces no output at all
        # and reads exactly like a healthy one.
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            return [{"name": f"{name}: {label}", "ok": False,
                     "detail": f"{label} script exited {proc.returncode}"
                               + (f": {tail[-1][:120]}" if tail else "")}]
        try:
            payload = json.loads(proc.stdout or "{}")
        except ValueError as exc:
            return [{"name": f"{name}: {label}", "ok": False,
                     "detail": f"{label} script emitted non-JSON ({exc})"}]
        reported = payload.get("checks")
        if not reported:
            return [{"name": f"{name}: {label}", "ok": False,
                     "detail": f"{label} script returned no checks"}]
        out = []
        for c in reported:
            c = dict(c)
            c["name"] = f"{name}: {c.get('name', label)}"
            out.append(c)
        return out

    @classmethod
    def _skill_verify(cls, name: str, skill_dir: Path, spec: dict) -> list[dict]:
        """Run the skill's end-to-end proof (``verify_script``), if it has one.

        Separate from the readiness script on purpose: that one is read-only
        and runs on every `olav doctor`, this one creates and destroys real
        resources and runs only when asked.
        """
        script = spec.get("verify_script")
        if not script:
            return [{"name": f"{name}: verify", "ok": True,
                     "detail": "this service ships no end-to-end proof"}]
        return cls._run_skill_script(
            name, skill_dir, str(script), label="verify", timeout=1800)

    def _check_memory(self) -> dict:
        """Experience layer primed? Counts per category; ⚠ when no guides."""
        try:
            from olav.core.memory import MEMORY_TABLE, get_store

            store = get_store()
            if store is None or not store.table_exists(MEMORY_TABLE):
                return {"name": "memory", "ok": False,
                        "detail": "not primed (no memory table)",
                        "fix": "run `olav skill install <pack>` or `olav kb import-kb`"}
            import collections

            counts: collections.Counter = collections.Counter()
            for m in store.get_memories(limit=10000, table_name=MEMORY_TABLE):
                counts[m.get("category") or "?"] += 1
            order = ["usage_guide", "reflection", "expert_knowledge",
                     "query_pattern", "fact"]
            shown = [f"{counts[c]} {c}" for c in order if counts.get(c)]
            shown += [f"{n} {c}" for c, n in counts.items() if c not in order]
            guides = counts.get("usage_guide", 0)
            primed = guides > 0
            detail = ("primed — " if primed else "not primed — ") + (
                " · ".join(shown) if shown else "0 memories")
            return {"name": "memory", "ok": primed, "detail": detail,
                    "fix": "run `olav skill install <pack>` to prime guides" if not primed else None}
        except Exception as exc:  # noqa: BLE001
            return {"name": "memory", "ok": False, "detail": f"store unreadable ({exc})",
                    "fix": "run `olav init`"}

    def _check_recall(self) -> dict:
        """Recall SMOKE (not a benchmark): embed one probe + run one search →
        confirms the embedder+store+recall path is wired. For accuracy metrics
        use `olav kb bench`."""
        try:
            from olav.core.memory import MEMORY_TABLE, get_store

            store = get_store()
            if store is None or not store.table_exists(MEMORY_TABLE):
                return {"name": "recall", "ok": True, "detail": "skipped (empty KB)"}
            try:
                if store.get_table(MEMORY_TABLE).count_rows() == 0:
                    return {"name": "recall", "ok": True, "detail": "skipped (empty KB)"}
            except Exception:  # noqa: BLE001
                pass
            from olav.core.embedder import embed_text

            vec = embed_text("recall health probe")
            if not vec:
                return {"name": "recall", "ok": False,
                        "detail": "embedder returned no vector",
                        "fix": "check embedding config (see embedding check above)"}
            hits = store.search_by_vector(vec, limit=3, table_name=MEMORY_TABLE)
            return {"name": "recall", "ok": True,
                    "detail": f"responsive ({len(hits)} hit(s) for probe) — "
                              f"`olav kb bench` for accuracy"}
        except Exception as exc:  # noqa: BLE001
            return {"name": "recall", "ok": False, "detail": f"recall path error ({exc})",
                    "fix": "check embedder + memory store"}
