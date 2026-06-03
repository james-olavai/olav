#!/usr/bin/env python3
# LEGACY-KEEP: the docstring below uses "legacy behaviour" to describe
# the full-docstring fallback when no tier/agent hint is available —
# that wording is load-bearing (contract with callers), not tech debt.
"""tool_help — return documentation for a named tool (tier-aware, ARCH-19 #C).

Small-model pattern (ARCH-19 #C): keep system prompts lean (one-line
descriptions for every tool) and let agents call ``tool_help('execute_cli')``
to pull the full schema / docstring only when they actually need to invoke
that tool. Saves tokens during routing and keeps the ambient context window
focused on the task at hand.

Detail levels (Round 38):

* ``brief`` — ``{name, description, args}`` only; drops ``full_docstring``.
  Saves tokens for short-context tiers.
* ``full``  — legacy behaviour; adds ``full_docstring``.
* auto     — resolved from ``get_llm_config().model_tier``:
  small/medium tiers get ``brief``, large gets ``full``. Controlled by
  :func:`olav.core.config.tier_default` so all ARCH-19 tier gates share
  one switchboard.

Usage::

    >>> tool_help('execute_cli')                   # auto — tier decides
    >>> tool_help('execute_cli', detail='brief')   # force brief
    >>> tool_help('execute_cli', detail='full')    # force full

Returns ``{'error': 'tool not found: <name>', 'available': [...]}`` when the
requested name is unknown — the ``available`` list lets the model retry with
a correct name without a second round-trip.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any


# ── Bootstrap (match sibling tool convention) ────────────────────────────────


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))


# ── Discovery ────────────────────────────────────────────────────────────────


# Workspace directories that contain `tools/` subdirs (legacy @tool pattern).
_TOOL_ROOTS = [
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "api-query" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "db-query" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "writer" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "admin" / "ops" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "admin" / "installer" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "admin" / "editor" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "author" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "curator" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "explorer" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "runner" / "tools",
    _PROJECT_ROOT / ".olav" / "workspace" / "devops" / "services" / "tools",
]

# Workspace directories that contain `scripts/` subdirs (scripts-化 pattern).
_SCRIPT_ROOTS = [
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "api-query" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "db-query" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "core" / "writer" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "admin" / "ops" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "admin" / "installer" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "admin" / "editor" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "author" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "curator" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "explorer" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit" / "runner" / "scripts",
    _PROJECT_ROOT / ".olav" / "workspace" / "devops" / "services" / "scripts",
]


class _ScriptProxy:
    """Thin wrapper around a plain Python function from a scripts/ dir."""
    __slots__ = ("name", "description", "func", "args_schema")

    def __init__(self, name: str, func: Any) -> None:
        self.name = name
        self.func = func
        self.description = (inspect.getdoc(func) or "").split("\n")[0]
        self.args_schema = None


def _discover_all_tools() -> list[Any]:
    """Collect every @tool-decorated BaseTool and scripts-化 plain function
    across all known workspace dirs.

    Uses :func:`olav.core.tool_discovery.discover_tools` for the @tool
    pattern and direct importlib loading for scripts/*.py plain functions.
    """
    import importlib.util as _ilu

    found: list[Any] = []
    seen: set[str] = set()

    # 1. Legacy @tool-decorated tools from tools/ dirs.
    try:
        from olav.core.tool_discovery import discover_tools
        for root in _TOOL_ROOTS:
            if not root.exists():
                continue
            try:
                for t in discover_tools(root):
                    name = getattr(t, "name", None)
                    if name and name not in seen:
                        seen.add(name)
                        found.append(t)
            except Exception:
                continue
    except Exception:
        pass

    # 2. Plain Python functions from scripts/ dirs (scripts-化 pattern).
    for root in _SCRIPT_ROOTS:
        if not root.exists():
            continue
        for script in sorted(root.glob("*.py")):
            if script.name.startswith("_"):
                continue
            fn_name = script.stem
            if fn_name in seen:
                continue
            try:
                spec = _ilu.spec_from_file_location(f"_tool_help_{fn_name}", script)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                func = getattr(mod, fn_name, None)
                if callable(func):
                    seen.add(fn_name)
                    found.append(_ScriptProxy(fn_name, func))
            except Exception:
                continue

    return found


def _serialise_args(tool_obj: Any) -> list[dict[str, Any]]:
    """Project tool args into a JSON-friendly list.

    Handles both @tool Pydantic args_schema and plain Python functions via
    inspect.signature (scripts-化 pattern).
    """
    schema = getattr(tool_obj, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None)
        if fields is None:
            fields = getattr(schema, "__fields__", None) or {}
        args: list[dict[str, Any]] = []
        for name, field in fields.items():
            annotation = getattr(field, "annotation", None)
            type_name = getattr(annotation, "__name__", None) or str(annotation)
            required = getattr(field, "is_required", None)
            if callable(required):
                required = required()
            if required is None:
                default = getattr(field, "default", None)
                required = default is None or default is ...
            description = getattr(field, "description", "") or ""
            args.append({
                "name": name,
                "type": type_name,
                "required": bool(required),
                "description": description,
            })
        return args

    # Fall back to inspect.signature for plain Python functions.
    func = getattr(tool_obj, "func", None) or tool_obj
    if not callable(func):
        return []
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return []
    args = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            type_name = "Any"
        else:
            type_name = getattr(annotation, "__name__", None) or str(annotation)
        required = param.default is inspect.Parameter.empty
        args.append({
            "name": param_name,
            "type": type_name,
            "required": required,
            "description": "",
        })
    return args


_VALID_DETAIL = frozenset({"brief", "full"})

_SKILL_MODE_ALIASES = {
    "brief": "brief",
    "compact": "brief",
    "short": "brief",
    "full": "full",
    "long": "full",
    "verbose": "full",
}


def _read_agent_docstring_mode(agent_id: str) -> str | None:
    """Peek the named agent's SKILL.md ``tools_docstring_mode`` frontmatter.

    ARCH-19 (Round 49): small-tier agents can declaratively pin a
    ``compact`` docstring mode in SKILL.md so the tier default doesn't
    surprise them if the deployment tier shifts.
    """
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None
    agent_id = agent_id.strip()

    candidates: list[Path] = []
    for root in _TOOL_ROOTS:
        if root.name != "tools":
            continue
        agent_dir = root.parent
        if agent_dir.name == agent_id:
            candidates.append(agent_dir / "SKILL.md")

    workspace_root = _PROJECT_ROOT / ".olav" / "workspace"
    candidates.append(workspace_root / agent_id / "SKILL.md")

    for skill_md in candidates:
        try:
            if not skill_md.is_file():
                continue
        except Exception:
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            import yaml
            meta = yaml.safe_load(parts[1]) or {}
        except Exception:
            continue
        raw = str(meta.get("tools_docstring_mode", "") or "").strip().lower()
        if not raw:
            continue
        return _SKILL_MODE_ALIASES.get(raw)
    return None


def _resolve_detail(detail: str | None, agent_id: str | None = None) -> str:
    """Map the ``detail=`` arg (or tier default) to ``brief`` or ``full``.

    Precedence:
    1. Explicit ``detail="brief"|"full"`` wins.
    2. If ``agent_id`` is supplied, look up that agent's SKILL.md.
    3. Consult ``TIER_DEFAULTS[<tier>]["tool_help_detail"]``.
    4. Fallback: ``"full"`` for unconfigured environments.
    """
    if isinstance(detail, str):
        d = detail.strip().lower()
        if d in _VALID_DETAIL:
            return d

    if agent_id:
        agent_mode = _read_agent_docstring_mode(agent_id)
        if agent_mode in _VALID_DETAIL:
            return agent_mode

    try:
        from olav.core.config import get_llm_config, tier_default
        tier = get_llm_config().model_tier
        per_tier_default = {"small": "brief", "medium": "brief", "large": "full"}.get(tier, "full")
        resolved = tier_default(tier, "tool_help_detail", per_tier_default)
        if isinstance(resolved, str) and resolved in _VALID_DETAIL:
            return resolved
    except Exception:
        pass
    return "full"


def _describe(tool_obj: Any, detail: str = "full") -> dict[str, Any]:
    name = getattr(tool_obj, "name", str(tool_obj))
    description = getattr(tool_obj, "description", "") or ""
    payload: dict[str, Any] = {
        "name": name,
        "description": description,
        "args": _serialise_args(tool_obj),
    }
    if detail == "full":
        func = getattr(tool_obj, "func", None) or getattr(tool_obj, "_run", None)
        full_doc = inspect.getdoc(func) if func is not None else description
        payload["full_docstring"] = full_doc or ""
    payload["_detail"] = detail
    return payload


# ── Public functions ──────────────────────────────────────────────────────────


def tool_help(
    name: str,
    detail: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return documentation for a named tool (tier-aware detail level).

    Args:
        name: Tool identifier (e.g. ``"execute_cli"``, ``"take_snapshot"``).
        detail: Optional detail level — ``"brief"`` drops ``full_docstring``
            to save tokens; ``"full"`` returns everything. Omit to auto-select
            based on ``model_tier`` / agent SKILL.md.
        agent_id: Optional caller agent identifier (e.g. ``"core"``,
            ``"ops"``). When supplied, the resolver consults that agent's
            ``SKILL.md::tools_docstring_mode`` frontmatter (``compact`` /
            ``brief`` / ``full``) as an override over the tier default.
            Ignored when an explicit ``detail`` is passed.

    Returns:
        Dict with ``name``, ``description``, ``args`` (list of
        ``{name, type, required, description}``), ``_detail`` ("brief"/"full"),
        and — only when ``detail="full"`` — ``full_docstring``.
        On unknown names returns ``{"error": "...", "available": [...]}``
        so the caller can correct its spelling without another round-trip.

    Example:
        >>> tool_help("tool_help")["name"]
        'tool_help'
        >>> tool_help("tool_help", detail="brief").get("full_docstring")
        None
    """
    if not name or not isinstance(name, str):
        return {"error": "tool_help requires a non-empty tool name"}

    tools = _discover_all_tools()
    by_name = {getattr(t, "name", ""): t for t in tools}

    target = by_name.get(name)
    if target is None:
        return {
            "error": f"tool not found: {name!r}",
            "available": sorted(by_name),
        }

    return _describe(target, detail=_resolve_detail(detail, agent_id=agent_id))


def list_tools(detail: str | None = None) -> dict[str, Any]:
    """List all discovered tools with their names and brief descriptions.

    Args:
        detail: Optional detail level passed through to each tool description.

    Returns:
        Dict with ``tools`` list of ``{name, description}`` entries,
        and ``count`` of total tools found.
    """
    all_tools = _discover_all_tools()
    resolved = _resolve_detail(detail)
    tool_list = []
    for t in all_tools:
        name = getattr(t, "name", "")
        description = getattr(t, "description", "") or ""
        tool_list.append({"name": name, "description": description})
    return {"tools": sorted(tool_list, key=lambda x: x["name"]), "count": len(tool_list)}


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    action = _args.pop("action", "help")
    if action == "list":
        result = list_tools(**_args)
    else:
        result = tool_help(**_args)
    print(_json.dumps(result, default=str))
