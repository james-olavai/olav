"""R83.4 / Chapter 4: olav_delegate alias resolution + best-match hint.

Background: ops orchestrator was misrouting ``olav_delegate("topology",
…)`` because the LLM keyword-matched a top-level agent name (registered
globally as ``.olav/workspace/topology/``) rather than picking the
declared sub-agent ``ops-analyze`` that owns topology visualisation.
The bare "not found" error didn't recover — small models would just
fall back to ad-hoc SQL and hallucinate the save step.

This test pins:
1. Known cross-workspace aliases auto-route to the correct sub-agent
   when present in the orchestrator's runnables.
2. Unknown names return a "Did you mean X?" suggestion instead of a
   flat list, so retry is explicit rather than implicit.
3. Aliases that don't have any of their targets registered fall back
   to best-match (rather than blindly succeeding into a missing target).
"""

from __future__ import annotations


def test_alias_routes_topology_to_ops_analyze():
    from olav.agents.delegate_tool import _resolve_alias

    runnables = {
        "ops-analyze": object(),
        "ops-collect": object(),
        "ops-lab": object(),
    }
    assert _resolve_alias("topology", runnables) == "ops-analyze"


def test_alias_routes_diagram_to_writer_first():
    from olav.agents.delegate_tool import _resolve_alias

    # Both writer and ops-analyze present — diagram preference is writer
    runnables = {"writer": object(), "ops-analyze": object()}
    assert _resolve_alias("diagram", runnables) == "writer"


def test_alias_falls_through_when_target_missing():
    from olav.agents.delegate_tool import _resolve_alias

    # Only ops-collect — no analyze / writer to route topology to
    runnables = {"ops-collect": object()}
    assert _resolve_alias("topology", runnables) is None


def test_alias_case_insensitive():
    from olav.agents.delegate_tool import _resolve_alias

    runnables = {"ops-analyze": object()}
    assert _resolve_alias("Topology", runnables) == "ops-analyze"
    assert _resolve_alias("TOPOLOGY", runnables) == "ops-analyze"


def test_alias_unknown_name_returns_none():
    from olav.agents.delegate_tool import _resolve_alias

    runnables = {"ops-analyze": object(), "writer": object()}
    assert _resolve_alias("not-a-real-name", runnables) is None


def test_best_match_substring():
    from olav.agents.delegate_tool import _best_match

    available = ["ops-analyze", "ops-collect", "ops-lab", "writer"]
    # Substring "analyze" matches ops-analyze
    assert _best_match("analyze", available) == "ops-analyze"


def test_best_match_token_overlap():
    from olav.agents.delegate_tool import _best_match

    available = ["ops-analyze", "ops-collect", "writer"]
    # "ops" token overlaps all ops-* entries — first/highest wins
    suggestion = _best_match("ops", available)
    assert suggestion in ("ops-analyze", "ops-collect")


def test_best_match_empty_returns_none():
    from olav.agents.delegate_tool import _best_match

    assert _best_match("anything", []) is None


def test_olav_delegate_uses_alias(monkeypatch):
    """End-to-end: build_delegate_tool with no 'topology' runnable
    should auto-route to 'ops-analyze' when LLM passes 'topology'."""
    from olav.agents.delegate_tool import build_delegate_tool

    invocations = {}

    class _FakeRunnable:
        def __init__(self, name):
            self.name = name

        def invoke(self, payload):
            invocations["name"] = self.name
            invocations["payload"] = payload

            # langchain message-list result shape
            class _Msg:
                content = "ok from " + self.name

            return {"messages": [_Msg()]}

    runnables = {"ops-analyze": _FakeRunnable("ops-analyze")}
    tool = build_delegate_tool(runnables)
    out = tool.invoke({
        "subagent_name": "topology",
        "task_description": "render mermaid",
    })

    # Got routed to ops-analyze — invocation recorded against that name
    assert invocations["name"] == "ops-analyze"
    assert "ok from ops-analyze" in out


def test_olav_delegate_unknown_suggests(monkeypatch):
    """Unknown name with no alias match should yield a 'Did you mean' hint."""
    from olav.agents.delegate_tool import build_delegate_tool

    class _Stub:
        def invoke(self, _):
            raise AssertionError("should not run")

    runnables = {"ops-analyze": _Stub(), "writer": _Stub()}
    tool = build_delegate_tool(runnables)
    out = tool.invoke({
        "subagent_name": "ops-analyz",  # typo
        "task_description": "x",
    })
    assert "not found" in out
    assert "Did you mean 'ops-analyze'?" in out
