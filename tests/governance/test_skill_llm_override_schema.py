"""Governance — every SKILL.md / AGENT.md ``llm:`` block must use
only the supported per-skill override fields, with correct types.

Catches typos (`temperture: 0.0`) and rogue keys before they silently
drop in `LLMFactory.get_chat_model`.  Source-of-truth for the
allowed schema is :func:`olav.core.llm.LLMFactory.get_chat_model`'s
``overrides`` docstring + the two read sites in
``src/olav/agents/agent.py`` (orchestrator + sub-agent).

Tested manifests:
* ``src/olav/data/workspace/**/{AGENT,SKILL}.md`` (platform-bundled)
* ``olav-netops/.olav/workspace/**/{AGENT,SKILL}.md`` (netops mirror)

If you add a new override key (e.g. ``presence_penalty``), update
:data:`ALLOWED_LLM_KEYS` and document it in the ``get_chat_model``
docstring.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_LLM_KEYS: dict[str, type] = {
    "model": str,
    "temperature": (int, float),
    "max_tokens": int,
    "base_url": str,
    "model_provider": str,
    "num_ctx": int,
    "num_predict": int,
}

MANIFEST_GLOBS = (
    "src/olav/data/workspace/**/AGENT.md",
    "src/olav/data/workspace/**/SKILL.md",
    "olav-netops/.olav/workspace/**/AGENT.md",
    "olav-netops/.olav/workspace/**/SKILL.md",
)


def _discover_manifests() -> list[Path]:
    paths: list[Path] = []
    for pattern in MANIFEST_GLOBS:
        paths.extend(REPO_ROOT.glob(pattern))
    # Stable order so failures point at the same path on every CI run.
    return sorted(paths)


def _frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        pytest.fail(f"{path}: invalid YAML frontmatter — {exc}")


_MANIFESTS_WITH_LLM = [
    p for p in _discover_manifests()
    if (fm := _frontmatter(p)) is not None and "llm" in fm
]


@pytest.mark.parametrize("manifest", _MANIFESTS_WITH_LLM, ids=str)
def test_llm_override_keys_are_known(manifest: Path) -> None:
    """Reject typo'd keys (`temperture`, `max_token`, ...) at lint time."""
    fm = _frontmatter(manifest) or {}
    block = fm.get("llm") or {}
    assert isinstance(block, dict), (
        f"{manifest}: `llm:` must be a mapping, got {type(block).__name__}"
    )
    unknown = sorted(set(block) - set(ALLOWED_LLM_KEYS))
    assert not unknown, (
        f"{manifest}: unknown llm override key(s) {unknown}.  "
        f"Allowed: {sorted(ALLOWED_LLM_KEYS)}.  "
        f"Did you mean a typo? Add to ALLOWED_LLM_KEYS if intentional."
    )


@pytest.mark.parametrize("manifest", _MANIFESTS_WITH_LLM, ids=str)
def test_llm_override_value_types(manifest: Path) -> None:
    """Reject ``max_tokens: "32768"`` (string), ``num_ctx: 65536.5``, etc."""
    fm = _frontmatter(manifest) or {}
    block = fm.get("llm") or {}
    for key, value in block.items():
        expected = ALLOWED_LLM_KEYS.get(key)
        if expected is None:
            continue  # covered by the keys test
        assert isinstance(value, expected), (
            f"{manifest}: `llm.{key}` must be {expected}, "
            f"got {type(value).__name__}({value!r})"
        )


@pytest.mark.parametrize("manifest", _MANIFESTS_WITH_LLM, ids=str)
def test_llm_override_value_ranges(manifest: Path) -> None:
    """Sanity bounds — catches accidental ``temperature: 10`` (model rejects)."""
    fm = _frontmatter(manifest) or {}
    block = fm.get("llm") or {}
    if "temperature" in block:
        t = block["temperature"]
        assert 0.0 <= t <= 2.0, (
            f"{manifest}: temperature {t} out of typical [0.0, 2.0] range"
        )
    if "max_tokens" in block:
        m = block["max_tokens"]
        assert 1 <= m <= 200000, (
            f"{manifest}: max_tokens {m} out of plausible range"
        )
    if "num_ctx" in block:
        c = block["num_ctx"]
        assert 1024 <= c <= 1048576, (
            f"{manifest}: num_ctx {c} out of plausible range"
        )
    if "num_predict" in block:
        n = block["num_predict"]
        assert 1 <= n <= 200000, (
            f"{manifest}: num_predict {n} out of plausible range"
        )


def test_at_least_one_manifest_uses_llm_block() -> None:
    """If this fails, the override mechanism shipped but nothing exercises it
    — the unit tests stop being meaningful.  Add a real-skill consumer or
    delete the mechanism."""
    assert _MANIFESTS_WITH_LLM, (
        "No SKILL.md / AGENT.md declares an `llm:` block; the per-skill "
        "override mechanism is shipped but unused.  "
        "Either restore at least one consumer or remove the feature."
    )
