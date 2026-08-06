"""The operator must be told when execute_sql withheld rows and wrote a file.

`execute_sql` follows a "cap to context, full to file" contract: past 50 rows
it writes the complete result to exports/queries/ and returns a preview plus a
note. That note is addressed to the MODEL. Whether a human ever learns that
rows were withheld, or that a full file exists, therefore depends on the model
choosing to repeat it.

Four core-agent runs on gemma4 did repeat it. That is not reassurance — it is
the measurement that the behaviour is luck. The same doctrine that produced the
ingest report (dev_docs/116, "import must not be silent") says a fact the user
needs should not be routed through a model's discretion.

So the notice is emitted deterministically by the middleware, and suppressed
only when the answer already names the same file — being told twice is its own
defect.
"""

from __future__ import annotations

import pytest

from olav.plugins.middleware.output_formatter import OutputFormatterPlugin

_EXPORT_MSG = (
    "FULL results (339 rows) exported to exports/queries/query_20260806_185519.csv. "
    "Only first 20 rows returned to context to prevent bloat."
)


@pytest.fixture
def plugin():
    return OutputFormatterPlugin()


def _tool(content: str, name: str = "execute_sql") -> dict:
    return {"name": name, "content": content}


class TestTheNoticeIsEmitted:
    def test_export_and_truncation_are_both_stated(self, plugin):
        [note] = plugin._sql_export_notices([_tool(_EXPORT_MSG)], "There are 339 devices.")
        assert "339 rows" in note, "the operator needs the full count, not the preview's"
        assert "query_20260806_185519.csv" in note
        assert "first 20" in note, (
            "withholding rows is the half a user is most likely to miss"
        )

    def test_export_without_truncation_still_reports_the_file(self, plugin):
        msg = "FULL results (60 rows) exported to exports/queries/q.csv."
        [note] = plugin._sql_export_notices([_tool(msg)], "done")
        assert "60 rows" in note and "q.csv" in note
        assert "context showed" not in note, "nothing was withheld; do not imply it was"

    def test_a_query_under_the_cap_produces_no_notice(self, plugin):
        """No file is written below the threshold — a notice would be a lie."""
        assert plugin._sql_export_notices([_tool("3 rows returned.")], "three") == []


class TestTheOperatorIsNotToldTwice:
    def test_silent_when_the_answer_already_cites_the_path(self, plugin):
        answer = "The full list has been exported to `exports/queries/query_20260806_185519.csv`."
        assert plugin._sql_export_notices([_tool(_EXPORT_MSG)], answer) == []

    def test_repeated_identical_exports_are_reported_once(self, plugin):
        """The observed failure: a model re-issues the same query, so two
        identical CSVs land 5s apart (1 run in 3 on core). One notice per
        distinct file — repeating it per copy makes the noise worse."""
        second = _EXPORT_MSG.replace("185519", "185524")
        notices = plugin._sql_export_notices(
            [_tool(_EXPORT_MSG), _tool(_EXPORT_MSG), _tool(second)], "339 devices"
        )
        assert len(notices) == 2, f"one per distinct path, got {notices}"
        assert sum("185519" in n for n in notices) == 1


class TestWiredIntoTheSupplementPath:
    async def test_notice_reaches_the_final_state_through_a_real_graph(self, tmp_path):
        """Wiring proof: the helper is worthless unless aafter_agent calls it
        and the supplement survives to where the CLI prints from."""
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage, ToolMessage

        llm = GenericFakeChatModel(messages=iter([AIMessage(content="There are 339 devices.")]))
        agent = create_agent(model=llm, tools=[], middleware=[OutputFormatterPlugin()])
        out = await agent.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": "show all devices"},
                    ToolMessage(_EXPORT_MSG, name="execute_sql", tool_call_id="t1"),
                ]
            }
        )
        sup = out.get("_output_supplements") or []
        assert any("query_20260806_185519.csv" in s for s in sup), (
            f"the export notice did not reach the state the CLI reads: {sup}"
        )

    def test_aafter_agent_calls_the_helper(self):
        """Source check — the branch is easy to drop in a refactor."""
        import inspect

        src = inspect.getsource(OutputFormatterPlugin.aafter_agent)
        assert "_sql_export_notices(" in src
