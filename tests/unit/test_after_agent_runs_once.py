"""Every `aafter_agent` hook must fire exactly once per query.

It fired twice for as long as deepagents 0.6.x has been installed. `agent.py`
recorded that "deepagents 0.5.2 accepts the `middleware` kwarg but doesn't
mount it", so `main.py` re-ran every hook by hand after the stream. The note
went stale at the 0.6 upgrade — `create_deep_agent` now does
`deepagent_middleware.extend(middleware)` — and nothing noticed, because a
hook running twice looks exactly like a hook running once unless you count.

The cost was not cosmetic: `MemoryCapturePlugin.aafter_agent` invokes an LLM,
so every query paid a second capture round-trip and wrote duplicate memories
(observed n=3 for one text on the demo VM).

Deleting the manual pass required two facts to change, and both are pinned
below, because either one regressing silently restores the old behaviour:

1. langgraph DROPS state keys no schema declares — that is why the in-graph
   `_output_supplements` write never reached the operator, and why the manual
   pass was load-bearing rather than merely redundant.
2. The manual pass fed a synthetic message log with tool args on tool-role
   dicts, while `query_pattern_capture` reads `AIMessage.tool_calls`. The
   in-graph run is not just sufficient, it is the *correct* input.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from olav.plugins.base import OLAVMiddlewarePlugin, SupplementState


def _agent(*middleware):
    llm = GenericFakeChatModel(messages=iter([AIMessage(content="done")]))
    return create_agent(model=llm, tools=[], middleware=list(middleware))


class _Counting(OLAVMiddlewarePlugin):
    name = "counting"
    state_schema = SupplementState

    def __init__(self):
        super().__init__()
        self.calls = 0

    async def aafter_agent(self, state, runtime=None):
        self.calls += 1
        return {"_output_supplements": [f"📁 note {self.calls}"]}


class _Second(OLAVMiddlewarePlugin):
    name = "second"
    state_schema = SupplementState

    async def aafter_agent(self, state, runtime=None):
        return {"_output_supplements": ["⚠️ second note"]}


class TestHookFiresOncePerRun:
    async def test_a_single_run_invokes_the_hook_once(self):
        mw = _Counting()
        await _agent(mw).ainvoke({"messages": [{"role": "user", "content": "hi"}]})
        assert mw.calls == 1, (
            f"aafter_agent ran {mw.calls}x. Each extra run is another "
            f"memory-capture LLM round-trip on every query."
        )

    async def test_deepagents_still_mounts_the_middleware_kwarg(self):
        """The assumption whose staleness caused the double run.

        If a future deepagents stops mounting `middleware=`, the in-graph pass
        disappears and NOTHING replaces it — the manual pass is gone. That is a
        silent loss of capture, so pin the library behaviour rather than
        trusting the comment.
        """
        import inspect

        from deepagents import create_deep_agent

        src = inspect.getsource(create_deep_agent)
        assert "deepagent_middleware.extend(middleware)" in src, (
            "deepagents no longer mounts the middleware kwarg — OLAV's "
            "aafter_agent hooks are now dead. Restore an explicit invocation."
        )


class TestSupplementsSurviveTheGraph:
    async def test_declared_key_reaches_the_final_state(self):
        out = await _agent(_Counting()).ainvoke(
            {"messages": [{"role": "user", "content": "hi"}]}
        )
        assert out.get("_output_supplements") == ["📁 note 1"], (
            "an undeclared key is silently dropped by langgraph; this is the "
            "whole reason the manual pass existed"
        )

    async def test_two_middlewares_do_not_erase_each_other(self):
        """Why the reducer appends instead of overwriting."""
        out = await _agent(_Counting(), _Second()).ainvoke(
            {"messages": [{"role": "user", "content": "hi"}]}
        )
        got = out.get("_output_supplements") or []
        assert len(got) == 2, f"expected both notes, got {got}"
        assert any("📁" in s for s in got) and any("⚠️" in s for s in got)

    async def test_an_undeclared_key_is_still_dropped(self):
        """Proof the test above can tell the difference — without it, a
        regression that removed `state_schema` would still look green."""

        class _Undeclared(OLAVMiddlewarePlugin):
            name = "undeclared"

            async def aafter_agent(self, state, runtime=None):
                return {"_output_supplements": ["lost"]}

        out = await _agent(_Undeclared()).ainvoke(
            {"messages": [{"role": "user", "content": "hi"}]}
        )
        assert "_output_supplements" not in out


class TestTheManualPassIsGone:
    """Source-level, because re-adding it is the exact regression."""

    def _main_src(self) -> str:
        import olav.cli.main as _m

        return Path(_m.__file__).read_text(encoding="utf-8")

    def test_main_no_longer_reinvokes_the_hooks(self):
        src = self._main_src()
        tree = ast.parse(src)
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_hook"
        ]
        assert not offenders, (
            f"main.py calls a middleware hook directly at line(s) {offenders} — "
            f"the graph already runs them, so this doubles every hook again"
        )
        assert 'getattr(_mw, "aafter_agent", None)' not in src

    def test_supplements_are_read_from_graph_state(self):
        src = self._main_src()
        assert '(_final_state or {}).get("_output_supplements")' in src, (
            "supplements must come from the graph's final state now that the "
            "manual pass that used to collect them is gone"
        )

    def test_only_this_runs_additions_are_printed(self):
        """A persistent session keeps the thread, and the reducer appends —
        printing the whole list would replay every earlier note."""
        src = self._main_src()
        assert "_supplements[_supplements_before:]" in src
        assert "_supplements_before = len(" in src


class TestTheRealPluginStillDelivers:
    """End-to-end for the path whose only consumer was deleted.

    The manual pass in main.py was the sole thing printing supplements to the
    operator; removing it is only safe if the in-graph write now arrives. The
    tests above prove that with a stub middleware, which would still pass if
    OutputFormatterPlugin itself had been mis-wired — so mount the real plugin
    and make it produce a real supplement.
    """

    async def test_output_formatter_supplement_reaches_the_final_state(
        self, tmp_path, monkeypatch
    ):
        from olav.plugins.middleware.output_formatter import OutputFormatterPlugin

        # A fenced python block with no export path is the auto-export branch.
        content = (
            "Here is the script:\n\n```python\n#!/usr/bin/env python3\n"
            "import argparse\n\ndef main():\n    print('hi')\n```\n"
        )
        monkeypatch.chdir(tmp_path)
        agent = _agent_with(OutputFormatterPlugin(), reply=content)
        out = await agent.ainvoke({"messages": [{"role": "user", "content": "write a script"}]})

        sup = out.get("_output_supplements") or []
        assert len(sup) == 1, f"expected the auto-export notice, got {sup}"
        assert "Script auto-exported" in sup[0]

        # Check the path the notice actually names, rather than a path this
        # test guessed: the export root is resolved by the plugin, not from
        # cwd, so asserting on tmp_path failed even though the file was
        # written. A notice pointing at nothing would be the real defect.
        named = sup[0].split("Script auto-exported:")[-1].strip()
        assert Path(named).is_file(), (
            f"the notice names {named!r}, which does not exist — the operator "
            f"would be told about a file that was never written"
        )


def _agent_with(middleware, reply: str):
    llm = GenericFakeChatModel(messages=iter([AIMessage(content=reply)]))
    return create_agent(model=llm, tools=[], middleware=[middleware])
