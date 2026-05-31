"""ARCH-20: context injection budget guards for uncovered vectors.

Fills three gaps left after the ARCH-16/17/18/19 audit:

  1. SKILL.md body size — all sub-agent SKILL.md bodies must be ≤ 350
     lines.  Body is injected as system prompt on every agent call.
     Previously only core/SKILL.md was checked (test_context_budget.py).

  2. static_context reference files — files listed in static_context:
     are baked directly into the system prompt (not gated by AutoRecall
     top_k).  Budget by injection mode:
       • always   → ≤ 200 lines (unconditional injection)
       • on_intent → ≤ 500 lines (injected on first model request)
       • lazy     → uncapped (fetched explicitly via get_static_context)

  3. execute_skill_script stdout cap — skill_runner._MAX_OUTPUT_BYTES
     must exist.  Regression guard: if the constant is removed, a
     runaway script can inject unbounded bytes into the message history.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / ".olav" / "workspace"

# ── budgets ───────────────────────────────────────────────────────────────────

_SKILL_BODY_BUDGET = 350        # lines — all SKILL.md bodies
_REF_ALWAYS_BUDGET = 200        # lines — static_context always-mode files
_REF_ON_INTENT_BUDGET = 500     # lines — static_context on_intent-mode files

# ── helpers ───────────────────────────────────────────────────────────────────


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Return (meta_dict, body_text) for a YAML-frontmatter file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return yaml.safe_load(text[3:]) or {}, ""
    fm = text[4:end]
    body = text[end + 4:].lstrip("\n")
    return yaml.safe_load(fm) or {}, body


def _iter_skill_mds() -> list[Path]:
    return sorted(WORKSPACE.rglob("SKILL.md"))


def _iter_agent_and_skill_mds() -> list[Path]:
    return sorted(WORKSPACE.rglob("SKILL.md")) + sorted(WORKSPACE.rglob("AGENT.md"))


# ── 1. SKILL.md body size ─────────────────────────────────────────────────────


def test_skill_md_body_within_budget():
    """All SKILL.md bodies must stay ≤ _SKILL_BODY_BUDGET lines.

    The body is injected verbatim as the system prompt on every agent
    invocation.  A 600-line SKILL.md body costs ~1800 tokens before the
    first tool call even runs — unacceptable for small-tier agents.
    """
    over_budget: list[str] = []
    for path in _iter_skill_mds():
        _meta, body = _parse_frontmatter(path)
        lines = len(body.splitlines())
        if lines > _SKILL_BODY_BUDGET:
            over_budget.append(
                f"{path.relative_to(REPO)} — {lines} lines (budget {_SKILL_BODY_BUDGET})"
            )
    assert not over_budget, (
        "One or more SKILL.md bodies exceed the system-prompt line budget.\n"
        "Trim the body or move detail into a static_context reference:\n"
        + "\n".join(over_budget)
    )


# ── 2. static_context reference file size ─────────────────────────────────────


def _collect_static_context_refs(md_path: Path) -> tuple[str, list[Path]]:
    """Return (mode, [resolved_paths]) for the static_context entries in md_path."""
    meta, _ = _parse_frontmatter(md_path)
    entries = meta.get("static_context") or []
    mode = meta.get("static_context_mode", "always")
    base = md_path.parent
    paths: list[Path] = []
    for entry in entries:
        if isinstance(entry, dict):
            p = entry.get("path", "")
        elif isinstance(entry, str):
            p = entry
        else:
            continue
        if p:
            paths.append((base / p).resolve())
    return mode, paths


def test_static_context_always_mode_files_within_budget():
    """Files injected unconditionally (mode=always) must be ≤ 200 lines.

    always-mode bakes every listed file into the system prompt on every
    agent invocation.  A single 500-line reference = ~1500 tokens of
    permanent overhead, paid even for trivial queries.
    """
    over_budget: list[str] = []
    for md_path in _iter_agent_and_skill_mds():
        mode, refs = _collect_static_context_refs(md_path)
        if mode != "always":
            continue
        for ref in refs:
            if not ref.exists():
                continue  # broken refs caught by audit_workspace
            lines = len(ref.read_text(encoding="utf-8").splitlines())
            if lines > _REF_ALWAYS_BUDGET:
                over_budget.append(
                    f"{md_path.relative_to(REPO)}: {ref.name} — {lines} lines "
                    f"(budget {_REF_ALWAYS_BUDGET} for always-mode)"
                )
    assert not over_budget, (
        "static_context always-mode reference files exceed the prompt budget.\n"
        "Switch to on_intent mode or split the file:\n"
        + "\n".join(over_budget)
    )



# Files that legitimately exceed the on_intent budget — generated from external
# schemas (OpenAPI specs, etc.) and kept whole for completeness.  Add entries
# sparingly; each must have a justification comment.
_KNOWN_LARGE_ON_INTENT_REFS: dict[str, str] = {
    # OpenAPI-generated from NetBox DCIM schema (olav registry register 2026-04-09).
    # 853 lines of endpoint docs; regenerating to a subset would break on new fields.
    # Accepted risk: on_intent fires only when DCIM keywords present (~2 K tokens).
    "netbox_dcim_api.md": "OpenAPI-generated DCIM reference; split would break completeness",
}


def test_static_context_on_intent_files_within_budget():
    """on_intent files injected by first-turn keyword match must be ≤ 500 lines.

    on_intent is less critical than always (only fires when relevant) but
    still bakes the full file into the message at injection time.  Very
    large on_intent references spike a single turn's context.

    Known exceptions are listed in _KNOWN_LARGE_ON_INTENT_REFS.
    """
    over_budget: list[str] = []
    for md_path in _iter_agent_and_skill_mds():
        mode, refs = _collect_static_context_refs(md_path)
        if mode != "on_intent":
            continue
        for ref in refs:
            if ref.name in _KNOWN_LARGE_ON_INTENT_REFS:
                continue  # explicitly accepted large file
            if not ref.exists():
                continue
            lines = len(ref.read_text(encoding="utf-8").splitlines())
            if lines > _REF_ON_INTENT_BUDGET:
                over_budget.append(
                    f"{md_path.relative_to(REPO)}: {ref.name} — {lines} lines "
                    f"(budget {_REF_ON_INTENT_BUDGET} for on_intent-mode)"
                )
    assert not over_budget, (
        "static_context on_intent reference files exceed the budget.\n"
        "Split the file, switch to lazy mode, or add to _KNOWN_LARGE_ON_INTENT_REFS "
        "with justification:\n"
        + "\n".join(over_budget)
    )


# ── 3. execute_skill_script stdout cap ────────────────────────────────────────


def _load_skill_runner_module():
    path = REPO / "src" / "olav" / "core" / "skill_runner.py"
    spec = importlib.util.spec_from_file_location("skill_runner_for_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_skill_runner_stdout_cap_constant_exists():
    """_MAX_OUTPUT_BYTES must exist in skill_runner — regression guard.

    Without this constant, a script returning 10 MB of text would inject
    the full 10 MB into the LangChain message history and OOM the agent.
    If this test fails, the cap was accidentally deleted.
    """
    path = REPO / "src" / "olav" / "core" / "skill_runner.py"
    src = path.read_text(encoding="utf-8")
    assert "_MAX_OUTPUT_BYTES" in src, (
        "skill_runner._MAX_OUTPUT_BYTES constant is missing — "
        "the stdout cap must be present to prevent unbounded injection"
    )


def test_skill_runner_stdout_cap_is_applied_to_both_streams():
    """The cap must be applied to stdout AND stderr, not just one stream."""
    path = REPO / "src" / "olav" / "core" / "skill_runner.py"
    src = path.read_text(encoding="utf-8")
    # Count how many times the slice is applied — expect at least 2 (stdout + stderr paths)
    cap_applications = src.count("[:_MAX_OUTPUT_BYTES]")
    assert cap_applications >= 2, (
        f"_MAX_OUTPUT_BYTES only applied {cap_applications} time(s) in skill_runner — "
        "must slice both stdout and stderr in all code paths"
    )


def test_skill_runner_stdout_cap_value_via_ast():
    """_MAX_OUTPUT_BYTES must be ≤ 512 KB.

    512 KB = 131 072 tokens at ~4 bytes/token.  The large-tier context
    is 200 K tokens — a single 512 KB tool result consumes 65 % of it.
    Beyond 512 KB the model cannot reason over the output anyway; the
    script must use internal pagination (see ARCH-16 row limits).

    If this test fails, lower _MAX_OUTPUT_BYTES in skill_runner.py or
    add internal row/size limits to the offending script.
    """
    path = REPO / "src" / "olav" / "core" / "skill_runner.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cap_value: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "_MAX_OUTPUT_BYTES":
                    if isinstance(node.value, ast.Constant):
                        cap_value = node.value.value
    assert cap_value is not None, "_MAX_OUTPUT_BYTES constant not found via AST"
    assert cap_value <= 524_288, (
        f"_MAX_OUTPUT_BYTES = {cap_value:,} bytes exceeds 512 KB ceiling "
        f"(current: {cap_value // 1024} KB, limit: 512 KB). "
        "Lower the constant or add per-script pagination."
    )
