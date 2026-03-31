"""Phase 2-5 TDD: OLAVAgent should no longer hold manual _auto_recall/_auto_capture/_guardrail_injector.

Since the three plugins (MemoryRecallPlugin, MemoryCapturePlugin, GuardrailsPlugin)
are now registered automatically via load_builtin_plugins(), OLAVAgent must NOT
duplicate the functionality through instance attributes.

Also validates: MemoryRecallPlugin / MemoryCapturePlugin / GuardrailsPlugin
are found in the builtin scan (plugin files exist and are importable).
"""
from __future__ import annotations

import ast
from pathlib import Path

AGENT_SOURCE = Path("/home/yhvh/Olav/src/olav/agents/agent.py")


def test_agent_has_no_auto_recall_attribute():
    """OLAVAgent.__init__ must NOT assign self._auto_recall."""
    tree = ast.parse(AGENT_SOURCE.read_text())

    init_method = next(
        (node for node in ast.walk(tree)
         if isinstance(node, ast.FunctionDef) and node.name == "__init__"),
        None,
    )
    assert init_method is not None, "__init__ not found in agent.py"

    bad_assigns = [
        node for node in ast.walk(init_method)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_auto_recall"
            for t in node.targets
        )
    ]
    assert not bad_assigns, (
        f"agent.py __init__ still assigns self._auto_recall at lines "
        f"{[n.lineno for n in bad_assigns]}. Remove it — MemoryRecallPlugin handles this."
    )


def test_agent_has_no_auto_capture_attribute():
    """OLAVAgent.__init__ must NOT assign self._auto_capture."""
    tree = ast.parse(AGENT_SOURCE.read_text())

    init_method = next(
        (node for node in ast.walk(tree)
         if isinstance(node, ast.FunctionDef) and node.name == "__init__"),
        None,
    )
    bad_assigns = [
        node for node in ast.walk(init_method)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_auto_capture"
            for t in node.targets
        )
    ]
    assert not bad_assigns, (
        f"agent.py __init__ still assigns self._auto_capture at lines "
        f"{[n.lineno for n in bad_assigns]}. Remove it — MemoryCapturePlugin handles this."
    )


def test_agent_has_no_guardrail_injector_attribute():
    """OLAVAgent.__init__ must NOT assign self._guardrail_injector."""
    tree = ast.parse(AGENT_SOURCE.read_text())

    init_method = next(
        (node for node in ast.walk(tree)
         if isinstance(node, ast.FunctionDef) and node.name == "__init__"),
        None,
    )
    bad_assigns = [
        node for node in ast.walk(init_method)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_guardrail_injector"
            for t in node.targets
        )
    ]
    assert not bad_assigns, (
        f"agent.py __init__ still assigns self._guardrail_injector at lines "
        f"{[n.lineno for n in bad_assigns]}. Remove it — GuardrailsPlugin handles this."
    )


def test_builtin_plugins_include_memory_and_guardrails():
    """load_builtin_plugins should discover all three memory/guardrail plugins."""
    from olav.plugins import load_builtin_plugins
    from olav.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    load_builtin_plugins(registry)

    names = {p.name for p in registry.get_middleware_plugins()}
    assert "memory_recall" in names, "MemoryRecallPlugin not found in builtin scan"
    assert "memory_capture" in names, "MemoryCapturePlugin not found in builtin scan"
    assert "guardrails" in names, "GuardrailsPlugin not found in builtin scan"
