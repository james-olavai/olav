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
        as_json = "--json" in args.split()
        checks = [
            self._check_scaffolding(),
            self._check_llm(),
            self._check_embedding(),
            self._check_agents(),
            self._check_subagents(),
            self._check_tools(),
            self._check_memory(),
            self._check_recall(),
        ]

        if as_json:
            return json.dumps({"checks": checks, "ok": all(c["ok"] for c in checks)}, indent=2)

        lines = []
        for check in checks:
            mark = "✓" if check["ok"] else "⚠"
            lines.append(f"{mark} {check['name']}: {check['detail']}")
            if not check["ok"] and check.get("fix"):
                lines.append(f"    fix: {check['fix']}")
        overall = "healthy" if all(c["ok"] for c in checks) else "needs attention"
        lines.append(f"\noverall: {overall}")
        lines.append(f"cron: {self._cron_hint()}")
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
        return {
            "name": "llm",
            "ok": ok,
            "detail": detail,
            "fix": "check llm.model / llm.base_url / llm.api_key in .olav/config/api.json" if not ok else None,
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
                "fix": "set embedding.api.api_key in .olav/config/api.json, or switch embedding.mode to 'local'",
            }

        from olav.core.llm import LLMFactory

        ok, detail = LLMFactory.check_embedding_connectivity()
        return {
            "name": "embedding",
            "ok": ok,
            "detail": detail,
            "fix": "check embedding.mode / embedding.api.* in .olav/config/api.json" if not ok else None,
        }

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
        auto = {"memory-curator"}  # auto-discovered via SkillsMiddleware, not declared
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
