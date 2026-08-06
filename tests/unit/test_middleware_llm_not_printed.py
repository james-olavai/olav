"""A middleware's own LLM call must not be printed as the agent's answer.

Regression from the per-turn capture fix (dev_docs/115 §9).  Replacing the
`not _chunks` guard with a per-turn one made the CLI print *every* depth-0
chat-model turn that produced no stream chunks — and `MemoryCapturePlugin`
runs an LLM inside `aafter_agent`, so every demo answer was followed by
capture's raw ```json block:

    We just imported **339 devices** ... on the **cisco_ios** platform.
    ```json
    [ { "text": "When execute_sql exports full results to CSV, ...",
        "category": "decision", "importance": 1.0 }, ... ]

Depth cannot separate the two: both are depth 0.  The node can —
`langchain.agents.factory` compiles the agent's call into a node named
`model` and each middleware hook into `f"{m.name}.after_agent"`.

These tests replay a recorded event sequence through the real predicate taken
out of `main.py` by AST, rather than asserting on prose: three earlier guards
in this file's history passed against a substring while the behaviour they
described was broken.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import olav.cli.main as _main

_SRC = Path(_main.__file__).read_text(encoding="utf-8")


def _extract(fn_name: str):
    """Compile the real nested function out of main.py.

    It lives inside `execute_task`, so it cannot be imported.  Lifting it by
    AST keeps the test bound to shipped code: rewording the docstring changes
    nothing, deleting the node check fails the test.
    """
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns: dict = {}
            exec(compile(mod, "<main.py>", "exec"), ns)  # noqa: S102
            return ns[fn_name]
    raise AssertionError(f"{fn_name} not found in main.py — was it renamed?")


@pytest.fixture
def is_agent_turn():
    return _extract("_is_agent_turn")


def _ev(node):
    return {"metadata": {"langgraph_node": node} if node is not None else {}}


class TestTurnAttribution:
    def test_the_agents_own_model_node_is_accepted(self, is_agent_turn):
        assert is_agent_turn(_ev("model")) is True

    @pytest.mark.parametrize(
        "node",
        [
            "memory_capture.after_agent",
            "query_pattern_capture.after_agent",
            "output_formatter.after_agent",
            "audit.after_agent",
            "guardrails.before_model",
        ],
    )
    def test_middleware_hook_nodes_are_rejected(self, is_agent_turn, node):
        """The leak: any LLM invoked inside a hook runs under the hook's node."""
        assert is_agent_turn(_ev(node)) is False, (
            f"{node} would be printed to the user as the agent's answer"
        )

    def test_missing_node_metadata_fails_open(self, is_agent_turn):
        """Dropping unattributed turns would resurrect the silent-run bug that
        the per-turn guard was written to fix — a worse failure than a stray
        block, so the predicate must accept them."""
        assert is_agent_turn(_ev(None)) is True
        assert is_agent_turn({}) is True


class TestNodeNamesMatchLangchain:
    """The predicate hardcodes 'model'. If langchain renames the node the
    filter silently rejects every turn, so pin the assumption at its source."""

    def test_langchain_still_names_the_agent_node_model(self):
        import langchain.agents.factory as factory

        src = inspect.getsource(factory)
        assert 'graph.add_node("model"' in src, (
            "langchain no longer names the agent's model node 'model' — "
            "_is_agent_turn in main.py must be updated with it"
        )

    def test_langchain_still_suffixes_hook_nodes_with_the_hook_name(self):
        import langchain.agents.factory as factory

        src = inspect.getsource(factory)
        assert 'f"{m.name}.after_agent"' in src, (
            "hook node naming changed — a middleware LLM may no longer be "
            "distinguishable from the agent's own turn"
        )


class TestGuardIsAppliedAtEveryPrintSite:
    """A predicate that exists but guards one of three call sites is how this
    class of bug survives review (dev_docs Definition of Done)."""

    @pytest.mark.parametrize(
        "kind", ["on_chat_model_stream", "on_chat_model_start", "on_chat_model_end"]
    )
    def test_each_chat_model_branch_calls_the_predicate(self, kind):
        tree = ast.parse(_SRC)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_is_agent_turn"
        )
        # Find the enclosing async loop body by scanning the source of the
        # branch that compares `kind` to this event name.
        marker = f'== "{kind}"'
        idx = _SRC.index(marker)
        # the branch body runs until the next `elif kind ==` at the same level
        nxt = _SRC.find("elif kind ==", idx + len(marker))
        body = _SRC[idx: nxt if nxt != -1 else idx + 2000]
        assert "_is_agent_turn(event)" in body, (
            f"{kind} branch does not check _is_agent_turn — a middleware LLM "
            f"reaching this branch is printed or miscounts the turn"
        )
        assert fn is not None
