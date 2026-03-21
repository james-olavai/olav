"""Platform init command skeleton.

Creates the minimal project scaffolding required by the platform control plane.
"""

from __future__ import annotations

import json
from pathlib import Path

from olav.cli.commands.base import BaseCommand
from olav.core.bootstrap_yang import ensure_bundled_openconfig_reference
from olav.core.config import MAIN_DB_PATH
from olav.core.views import ensure_semantic_views


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

        llm_status = await self._check_llm()
        yang_status = self._bootstrap_yang_reference()
        return (
            "platform ready: created .olav scaffolding and baseline api.json\n"
            f"llm: {llm_status}\n"
            f"yang: {yang_status}"
        )

    def _bootstrap_yang_reference(self) -> str:
        try:
            import duckdb

            MAIN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(MAIN_DB_PATH)) as con:
                result = ensure_bundled_openconfig_reference(con)
                try:
                    ensure_semantic_views(con)
                except Exception:  # noqa: BLE001
                    pass
            if result.get("status") == "already_populated":
                return f"✓ existing yang_leaves preserved ({result['existing_rows']} rows)"
            return f"✓ bundled OpenConfig reference loaded ({result['leaves_inserted']} leaves)"
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
