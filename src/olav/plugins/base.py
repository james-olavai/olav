"""OLAV Plugin 基类定义。

三个公开类：
- OLAVPlugin       — 所有插件的元数据基类
- OLAVMiddlewarePlugin — 可传入 create_deep_agent(middleware=[...]) 的插件
- OLAVCallbackPlugin   — 可注入 LangChain callbacks 列表的旁路观测插件
"""
from __future__ import annotations


import operator
from typing import Annotated

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.callbacks import AsyncCallbackHandler
from typing_extensions import NotRequired


class SupplementState(AgentState):
    """Agent state plus the trailing lines the CLI prints after an answer.

    langgraph silently DROPS state keys a node writes that no schema declares
    — the update simply does not appear in the result. That is why
    ``_output_supplements`` never reached the operator from inside the graph,
    and why ``main.py`` had to re-run every ``aafter_agent`` hook by hand after
    the stream just to collect them (dev_docs/115 §11). Declaring the key here
    is what makes the in-graph run sufficient, so the duplicate manual pass
    could be deleted.

    The reducer appends rather than overwrites: two middlewares can each add a
    note in the same run (an auto-export notice and a save-assertion warning),
    and whichever ran second would otherwise erase the first. Appending means
    the list also survives across turns on a persistent thread, so the CLI
    prints only the slice added by the current run rather than the whole
    history.
    """

    _output_supplements: NotRequired[Annotated[list[str], operator.add]]


class OLAVPlugin:
    """所有 OLAV 插件的元数据基类。

    子类以类属性沙声明方式设置元数据：

        class MyPlugin(OLAVMiddlewarePlugin):
            name = "my_plugin"
            version = "1.2.0"
            description = "我的插件"
            tags = ["builtin"]
    """

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    enabled: bool = True
    tags: list[str] = []


class OLAVMiddlewarePlugin(OLAVPlugin, AgentMiddleware):  # pyright: ignore[reportIncompatibleVariableOverride]
    """AgentMiddleware 插件 — 可修改 agent 执行链。

    传入 create_deep_agent(middleware=[...]) 时生效。
    实现任意 hook（before_agent / before_model / after_model / after_agent）即可，
    未实现的 hook 使用基类默认（no-op）。
    """


class OLAVCallbackPlugin(OLAVPlugin, AsyncCallbackHandler):
    """AsyncCallbackHandler 插件 — 旁路观测，零侵入。

    注入到 astream_events(config={"callbacks": [plugin]}) 后，
    能捕获所有 LangChain 生命周期事件（on_tool_start/end, on_llm_end, 等）。
    """
