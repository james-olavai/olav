"""Self-configuration tools — change LLM/embedding config via conversation
instead of manually editing api.json (dev_docs/99 §3.4/§3.5).

Field-level args, not a JSON blob (small models lose the round-trip
re-emitting JSON-encoded content as a tool's args — CLAUDE.md Tool
Architecture). Every write is gated by a live validate-before-commit probe
using the exact same ``LLMFactory.check_connectivity`` /
``check_embedding_connectivity`` ``olav doctor`` and ``check_health`` use
(dev_docs/99 §3.1) — one shared validator, no duplicated logic. A rejected
candidate never touches the file; a committed change snapshots the prior
config first so ``rollback_config`` can undo it.
"""

import sys
from pathlib import Path


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import json  # noqa: E402

from langchain_core.tools import tool  # noqa: E402


def _bust_config_cache() -> None:
    """Force the process-wide ``ConfigLoader`` singleton to re-read
    api.json on its next access, so a committed change takes effect on
    the very next LLM/embedding call instead of requiring a restart."""
    from olav.core.config import ConfigLoader

    ConfigLoader._loaded = False


@tool
def update_llm_config(
    api_key: str | None = None,
    model: str | None = None,
    model_provider: str | None = None,
    base_url: str | None = None,
) -> str:
    """Change the LLM provider/model — tests the candidate before saving.

    Live-probes the new config first; on failure nothing is written and
    the current config keeps running. On success, snapshots the previous
    config (undo via ``rollback_config``) and applies immediately, no
    restart needed. Full usage: tool_help('update_llm_config').

    Args:
        api_key:        New API key, or omit to keep the current one.
        model:          New model name, or omit to keep the current one.
        model_provider: Provider hint (openai/anthropic/deepseek/...), or omit.
        base_url:       Custom endpoint URL, or omit to keep the current one.

    Returns:
        Success message naming what changed, or a rejection reason.
    """
    overrides = {
        k: v
        for k, v in {
            "api_key": api_key,
            "model": model,
            "model_provider": model_provider,
            "base_url": base_url,
        }.items()
        if v is not None
    }
    if not overrides:
        return "Error: provide at least one of api_key/model/model_provider/base_url."

    from olav.core.llm import LLMFactory

    ok, detail = LLMFactory.check_connectivity(overrides=overrides)
    if not ok:
        return f"Rejected — candidate config failed to connect: {detail}. Current config unchanged."

    from olav.core.config_snapshot import API_JSON_PATH, snapshot_api_json

    try:
        api_data = json.loads(API_JSON_PATH.read_text(encoding="utf-8")) if API_JSON_PATH.exists() else {}
    except Exception:
        api_data = {}

    snapshot_api_json()
    api_data.setdefault("llm", {}).update(overrides)
    API_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    API_JSON_PATH.write_text(
        json.dumps(api_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _bust_config_cache()

    changed = ", ".join(sorted(overrides))
    return (
        f"✓ LLM config updated ({changed}) — verified working, active immediately. "
        "Previous config snapshotted; use rollback_config() to undo."
    )


@tool
def update_embedding_config(
    mode: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Change the embedding backend (local/api) — tests before saving.

    mode="local" needs no key (bundled model, zero-config). mode="api"
    needs api_key. Live-probes the candidate first; rejects on failure
    without writing anything. Full usage: tool_help('update_embedding_config').

    Args:
        mode:    "local" or "api", or omit to keep the current mode.
        api_key: New API key for mode="api", or omit to keep current.
        model:   New embedding model name, or omit to keep current.

    Returns:
        Success message, or a rejection reason (current config untouched).
    """
    overrides = {
        k: v
        for k, v in {"mode": mode, "api_key": api_key, "model": model}.items()
        if v is not None
    }
    if not overrides:
        return "Error: provide at least one of mode/api_key/model."

    from olav.core.llm import LLMFactory

    ok, detail = LLMFactory.check_embedding_connectivity(overrides=overrides, strict=True)
    if not ok:
        return f"Rejected — candidate embedding config failed: {detail}. Current config unchanged."

    from olav.core.config_snapshot import API_JSON_PATH, snapshot_api_json

    try:
        api_data = json.loads(API_JSON_PATH.read_text(encoding="utf-8")) if API_JSON_PATH.exists() else {}
    except Exception:
        api_data = {}

    snapshot_api_json()
    embedding_section = api_data.setdefault("embedding", {})
    if "mode" in overrides:
        embedding_section["mode"] = overrides["mode"]
    if "api_key" in overrides or "model" in overrides:
        api_section = embedding_section.setdefault("api", {})
        if "api_key" in overrides:
            api_section["api_key"] = overrides["api_key"]
        if "model" in overrides:
            api_section["model"] = overrides["model"]
    API_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    API_JSON_PATH.write_text(
        json.dumps(api_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _bust_config_cache()

    changed = ", ".join(sorted(overrides))
    return (
        f"✓ Embedding config updated ({changed}) — verified working, active immediately. "
        "Previous config snapshotted; use rollback_config() to undo."
    )


@tool
def rollback_config() -> str:
    """Undo the most recent update_llm_config/update_embedding_config change.

    Restores api.json from the snapshot taken right before that change and
    applies immediately, no restart needed. Only one snapshot slot exists
    — this undoes the single most recent change, not a history.

    Returns:
        Confirmation with when the snapshot was taken, or a message that
        there is nothing to restore.
    """
    from olav.core.config_snapshot import restore_last_known_good

    result = restore_last_known_good()
    if result["restored"]:
        _bust_config_cache()
    return result["message"]
