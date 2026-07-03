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
        return "\n".join(lines)

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
