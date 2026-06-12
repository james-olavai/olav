"""Round 24 — ARCH-17 static_context_mode declaration pin.

Every top-level ``AGENT.md`` that declares ``static_context:`` in its
YAML frontmatter must **also** declare ``static_context_mode:`` explicitly.

Before Round 24, ``core/AGENT.md`` carried two heavy reference docs
(``SKILL_DEVELOPMENT.md`` ~3K tokens + ``REQUIRED_INFO_CHECK.md`` ~2K)
with no mode declaration. The resolver fell back to
``TIER_DEFAULTS[<tier>]["static_context_mode"]`` which worked for
small/medium tiers but broke silently on a mis-classified ``large``
tier (would push ~5K tokens at init unnecessarily).

Also pins the resolver's mode vocabulary and env-var name so
refactors that widen/rename don't silently drift from callers.

Note: AGENT.md files that have NO ``static_context:`` list do not need
a mode declaration — there's nothing to inject. Only agents with real
static context need an explicit mode.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"

_VALID_MODES: frozenset[str] = frozenset({"always", "on_intent", "lazy"})


def _parse_frontmatter(agent_md: Path) -> dict:
    text = agent_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    _, front, _rest = text.split("---", 2)
    return yaml.safe_load(front) or {}


def _iter_top_level_agent_mds():
    for p in WORKSPACE.iterdir():
        if not p.is_dir():
            continue
        md = p / "AGENT.md"
        if md.is_file():
            yield md


def _load_static_context_resolver():
    path = REPO / "src" / "olav" / "agents" / "static_context_resolver.py"
    spec = importlib.util.spec_from_file_location("static_context_resolver_for_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_every_agent_with_static_context_declares_a_mode():
    """An AGENT.md with a ``static_context:`` list must also declare
    ``static_context_mode:`` explicitly, rather than relying on the tier
    fallback (which is fragile: a mis-inferred tier silently degrades to
    'always')."""
    offenders: list[str] = []
    for agent_md in _iter_top_level_agent_mds():
        meta = _parse_frontmatter(agent_md)
        if not meta.get("static_context"):
            continue  # no static context → mode is moot
        if "static_context_mode" not in meta:
            offenders.append(str(agent_md.relative_to(REPO)))
    assert not offenders, (
        f"ARCH-17: AGENT.md files with static_context must explicitly "
        f"declare static_context_mode: {offenders}"
    )


def test_declared_modes_are_valid():
    """Whatever mode each agent declares must be one of the three supported
    values. Typos (``"lazyy"`` or ``"intent"``) would otherwise fall through
    to the fallback without warning."""
    offenders: list[str] = []
    for agent_md in _iter_top_level_agent_mds():
        meta = _parse_frontmatter(agent_md)
        if "static_context_mode" not in meta:
            continue
        mode = str(meta["static_context_mode"]).strip()
        if mode not in _VALID_MODES:
            offenders.append(f"{agent_md.relative_to(REPO)}: mode={mode!r}")
    assert not offenders, (
        f"ARCH-17: invalid static_context_mode values {_VALID_MODES} expected: "
        f"{offenders}"
    )


def test_resolver_valid_modes_pin():
    """Pin the resolver's ``_VALID_MODES`` constant — if it widens/narrows,
    this test (and the doc) should be updated together."""
    resolver_modes = _load_static_context_resolver()._VALID_MODES
    assert resolver_modes == _VALID_MODES, (
        f"resolver _VALID_MODES drifted: {resolver_modes} vs {_VALID_MODES}"
    )


def test_resolver_env_var_name_pin():
    """Pin the env-var name so ops runbooks / docs stay in sync with code."""
    _ENV_OVERRIDE = _load_static_context_resolver()._ENV_OVERRIDE
    assert _ENV_OVERRIDE == "OLAV_STATIC_CONTEXT_MODE", (
        f"resolver env var renamed: {_ENV_OVERRIDE!r}. Update ops runbooks / "
        "ARCH-17 doc."
    )


def test_tier_defaults_carry_static_context_mode():
    """ARCH-19: TIER_DEFAULTS must provide a ``static_context_mode`` for each
    tier — the resolver's tier-fallback path depends on it."""
    from olav.core.config import TIER_DEFAULTS
    for tier in ("small", "medium", "large"):
        assert tier in TIER_DEFAULTS, f"TIER_DEFAULTS missing tier {tier!r}"
        mode = TIER_DEFAULTS[tier].get("static_context_mode")
        assert mode in _VALID_MODES, (
            f"TIER_DEFAULTS[{tier!r}].static_context_mode = {mode!r}; "
            f"must be in {_VALID_MODES}"
        )
