"""Platform init command skeleton.

Creates the minimal project scaffolding required by the platform control plane.
"""

from __future__ import annotations

import json
from pathlib import Path

from olav.cli.commands.base import BaseCommand


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
        return (
            "platform ready: created .olav scaffolding and baseline api.json\n"
            f"llm: {llm_status}"
        )

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
