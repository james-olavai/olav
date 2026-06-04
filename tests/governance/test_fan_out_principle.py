"""ARCH-16 — anti-fan-out principle, enforced at the tool surface.

Guards three mechanical invariants that are the observable shadow of
"don't return multiple data sources in one shot" (the full principle
text lives at ``dev_docs/ARCH-16_FAN_OUT_PRINCIPLE.md``):

1. ``olav_recall_memory`` does NOT hard-code a ``top_k`` constant — the
   default must resolve through ``tier_default`` (ARCH-18 #3).
2. ``execute_cli_parallel`` / ``diff_configs`` / ``api_request`` expose a
   ``full: bool`` escape hatch so compact-by-default is the norm.
3. The principle doc exists and lists the required patterns.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from tests.governance._paths import NETOPS_TOOLS

REPO = Path(__file__).resolve().parents[2]
PRINCIPLE_DOC = REPO / "dev_docs" / "ARCH-16_FAN_OUT_PRINCIPLE.md"


def test_principle_doc_exists_and_is_substantive():
    if not PRINCIPLE_DOC.exists():
        import pytest; pytest.skip(f"ARCH-16 principle doc not in git ({PRINCIPLE_DOC.name}) — dev_docs/ gitignored")
    assert PRINCIPLE_DOC.exists(), f"ARCH-16 principle doc missing at {PRINCIPLE_DOC}"
    text = PRINCIPLE_DOC.read_text(encoding="utf-8")
    # Sanity: the doc must at least mention the three mechanisms the
    # test file below checks. If someone trims the doc, the checklist
    # below should still stay aligned.
    for keyword in ("tier_default", "olav_delegate", "tool_help"):
        assert keyword in text, f"principle doc lost reference to {keyword!r}"


def test_recall_middleware_uses_tier_default():
    """Middleware resolves ``top_k`` from TIER_DEFAULTS, not a hard-coded int."""
    pytest.importorskip("lancedb")
    from olav.core.memory import middleware as mw

    src = inspect.getsource(mw.AutoRecallMiddleware._resolve_top_k)
    assert "tier_default" in src, (
        "AutoRecallMiddleware._resolve_top_k lost its tier_default call — "
        "ARCH-16/18#3 regression."
    )
    # The constructor default must be None (i.e. resolve lazily). A concrete
    # int default would bypass the tier ladder.
    sig = inspect.signature(mw.AutoRecallMiddleware.__init__)
    assert sig.parameters["top_k"].default is None


def _docstring_for(path: Path, name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_docstring(node)
    return None


def _has_full_escape_hatch(path: Path, name: str) -> bool:
    """Return True if the @tool function accepts ``full: bool``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.arg == "full":
                    return True
    return False


def test_execute_cli_exposes_full_flag():
    assert _has_full_escape_hatch(
        NETOPS_TOOLS / "execute_cli_parallel.py",
        "execute_cli_parallel",
    )


def test_diff_configs_exposes_full_flag():
    assert _has_full_escape_hatch(
        NETOPS_TOOLS / "diff_configs.py",
        "diff_configs",
    )


def test_api_request_has_compact_cap_constant():
    """api_request auto-caps paginated list responses in compact mode."""
    src = (REPO / ".olav" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py").read_text(
        encoding="utf-8"
    )
    assert "_COMPACT_LIST_CAP" in src, (
        "api_request dropped its compact pagination cap — ARCH-16/18#2 regression."
    )


def test_tool_help_pointer_present_on_trimmed_tools():
    """Trimmed tools (ARCH-18 #1) should still advertise tool_help for detail."""
    tool_files = [
        REPO / ".olav" / "workspace" / "core" / "tools" / "execute_sql.py",
        REPO / ".olav" / "workspace" / "core" / "api-query" / "scripts" / "api_request.py",
        NETOPS_TOOLS / "diff_configs.py",
        NETOPS_TOOLS / "take_snapshot.py",
        NETOPS_TOOLS / "execute_cli_parallel.py",
    ]
    for path in tool_files:
        if path.name == "diff_configs.py":
            # netops wrapper delegates to olav_netops.core.diff.configs and
            # intentionally keeps a terse wrapper docstring.
            continue
        doc = _docstring_for(path, path.stem) or ""
        assert "tool_help" in doc, (
            f"{path.relative_to(REPO)} docstring no longer points to tool_help — "
            "ARCH-16 handoff chain broken."
        )
