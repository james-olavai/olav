import asyncio
import json
from pathlib import Path


def test_init_command_creates_platform_scaffolding(tmp_path, monkeypatch) -> None:
    from olav.cli.commands.init import InitCommand

    monkeypatch.chdir(tmp_path)

    result = asyncio.run(InitCommand().execute())

    assert "platform ready" in result
    assert (tmp_path / ".olav" / "config" / "api.json").exists()
    assert (tmp_path / ".olav" / "workspace").exists()
    assert (tmp_path / ".olav" / "databases").exists()
    assert (tmp_path / "exports" / "snapshots" / "json").exists()

    api_json = json.loads((tmp_path / ".olav" / "config" / "api.json").read_text(encoding="utf-8"))
    assert "llm" in api_json
