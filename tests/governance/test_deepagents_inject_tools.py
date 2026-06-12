"""Governance: _DEEPAGENTS_INJECT_TOOLS 与 deepagents 实际注入工具集的对应关系。

`_DEEPAGENTS_INJECT_TOOLS` 是 agent.py 中的 frozenset，驱动 sub-agent
post-compile 剪枝。如果 deepagents 在升级中重命名或新增工具，frozenset
会静默失效（工具泄漏到 sub-agent）。这个测试让不对齐变成显性断言。

IMPORTANT: 升级 deepagents 后如果这个测试失败，更新
  `src/olav/agents/agent.py::_DEEPAGENTS_INJECT_TOOLS`
  而不是删除测试。
"""
from __future__ import annotations

import pytest


def _build_injected_tools() -> frozenset[str]:
    """Build a minimal create_agent graph with full middleware stack and return
    the set of tool names it exposes in the ToolNode."""
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain.agents.middleware import TodoListMiddleware
    from deepagents.middleware.filesystem import FilesystemMiddleware

    model = ChatOpenAI(model="gpt-4", api_key="test")
    graph = create_agent(
        model,
        tools=[],
        middleware=[TodoListMiddleware(), FilesystemMiddleware()],
    )
    names: set[str] = set()
    for _node_name, node in graph.nodes.items():
        runnable = getattr(node, "bound", None) or getattr(node, "node", None)
        for attr in ("tools_by_name", "tools", "_tools"):
            val = getattr(runnable, attr, None)
            if not val:
                continue
            if hasattr(val, "keys"):
                names.update(val.keys())
            else:
                names.update(getattr(t, "name", str(t)) for t in val)
    return frozenset(names)


def test_inject_tools_frozenset_is_complete():
    """_DEEPAGENTS_INJECT_TOOLS 必须包含 deepagents 注入的每一个工具名。

    若失败 → deepagents 添加了新工具，frozenset 未跟上，
    工具会泄漏到 sub-agent（LLM 能调用它但 OLAV 没有授权）。
    """
    from olav.agents.agent import _DEEPAGENTS_INJECT_TOOLS

    injected = _build_injected_tools()
    leaked = injected - _DEEPAGENTS_INJECT_TOOLS
    assert not leaked, (
        f"deepagents 注入了以下工具但 _DEEPAGENTS_INJECT_TOOLS 未覆盖: {sorted(leaked)}\n"
        f"在 src/olav/agents/agent.py 中将它们加入 _DEEPAGENTS_INJECT_TOOLS，\n"
        f"或确认这些工具应该对 sub-agent 可见（从 _DEEPAGENTS_INJECT_TOOLS 移除剪枝逻辑）。"
    )


def test_inject_tools_frozenset_has_no_stale_entries():
    """_DEEPAGENTS_INJECT_TOOLS 不能包含 deepagents 不再注入的工具名（stale entry）。

    若失败 → deepagents 重命名或删除了工具，frozenset 有死条目，
    pruning 静默空转（无害但令人困惑）。
    """
    from olav.agents.agent import _DEEPAGENTS_INJECT_TOOLS

    injected = _build_injected_tools()
    stale = _DEEPAGENTS_INJECT_TOOLS - injected
    assert not stale, (
        f"_DEEPAGENTS_INJECT_TOOLS 包含 deepagents 已不再注入的工具: {sorted(stale)}\n"
        f"从 src/olav/agents/agent.py 的 _DEEPAGENTS_INJECT_TOOLS 中移除它们。"
    )


def test_task_tool_not_in_prune_set():
    """'task' 工具（sub-agent 委托工具）不能在 _DEEPAGENTS_INJECT_TOOLS 中。

    'task' 是 deepagents SubAgentMiddleware 注入的合法工具，OLAV orchestrator
    必须保留它以调用 sub-agent。一旦误加入 frozenset 会导致 sub-agent 委托失败。
    """
    from olav.agents.agent import _DEEPAGENTS_INJECT_TOOLS

    assert "task" not in _DEEPAGENTS_INJECT_TOOLS, (
        "'task' 出现在 _DEEPAGENTS_INJECT_TOOLS 中 — 这会使 orchestrator 无法调用 sub-agent。\n"
        "从 frozenset 中删除 'task'。"
    )


def test_small_tier_profile_excluded_tools_covers_inject_set():
    """小模型 HarnessProfile 的 excluded_tools 必须完整覆盖 _DEEPAGENTS_INJECT_TOOLS。

    小模型 profile 的 excluded_tools 是 belt（配置层），
    _DEEPAGENTS_INJECT_TOOLS pruning 是 suspenders（post-compile 层）。
    如果 belt 漏掉某个工具，小模型 orchestrator 仍能见到它，
    而 suspenders 只保护 sub-agent，不保护 orchestrator 本身。
    """
    from olav.agents.profiles import register_olav_profiles
    register_olav_profiles()

    from deepagents.profiles.harness.harness_profiles import _get_harness_profile
    profile = _get_harness_profile("gemma4:31b")
    assert profile is not None, "gemma4:31b 没有注册 profile — tier_small 注册失败"

    from olav.agents.agent import _DEEPAGENTS_INJECT_TOOLS
    not_excluded = _DEEPAGENTS_INJECT_TOOLS - profile.excluded_tools
    assert not not_excluded, (
        f"小模型 profile.excluded_tools 漏掉了以下工具: {sorted(not_excluded)}\n"
        f"这些工具会出现在小模型 orchestrator 的工具列表里（orchestrator 无 post-compile prune）。\n"
        f"在 tier_small.py::_SMALL_TIER_EXCLUDED_TOOLS 中加入它们。"
    )


def test_active_model_has_harness_profile():
    """api.json 当前配置的 small/medium 模型必须已注册 OLAV HarnessProfile。

    若失败 → 当前 LLM 没有任何 tier profile，orchestrator 不会获得
    system_prompt_suffix 和 excluded_tools。将模型 spec 加入对应的
    tier_small.py 或 tier_medium.py 的 _MODEL_SPECS 列表。

    tier-large 模型按设计**不**注册自定义 profile —— 它们用 deepagents
    原生行为（见 olav/agents/profiles/__init__.py: "tier_large: deepagents
    stock behavior is fine — large models …"）。给大模型套 medium 的
    "每轮一个工具调用 / 答案 3-5 行" 约束反而有害。故 tier-large 跳过此检查。
    """
    try:
        from olav.core.config import get_llm_config
        cfg = get_llm_config()
    except Exception:
        pytest.skip("api.json 不可用，跳过 active-model 检查")

    # tier-large uses deepagents stock behavior by design — no custom profile.
    if "large" in str(getattr(cfg, "model_tier", "")).lower():
        pytest.skip(
            f"active model '{cfg.model}' is tier-large — uses deepagents stock "
            "behavior by design (profiles/__init__.py); no custom OLAV profile expected."
        )

    from olav.agents.profiles import register_olav_profiles
    register_olav_profiles()

    try:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model=cfg.model, api_key="test")
    except Exception:
        pytest.skip("ChatOpenAI 初始化失败（可能缺少依赖），跳过")

    from deepagents._models import get_model_identifier, get_model_provider
    from deepagents.profiles.harness.harness_profiles import _get_harness_profile

    identifier = get_model_identifier(model)
    provider = get_model_provider(model)

    # Mirror deepagents' own lookup chain
    profile = None
    if provider and identifier and ":" not in identifier:
        profile = _get_harness_profile(f"{provider}:{identifier}")
    if profile is None and identifier and ":" in identifier:
        profile = _get_harness_profile(identifier)
    if profile is None and provider:
        profile = _get_harness_profile(provider)

    has_olav_content = profile is not None and (
        bool(profile.system_prompt_suffix) or bool(profile.excluded_tools)
    )
    assert has_olav_content, (
        f"当前 LLM '{cfg.model}'（provider={provider}, identifier={identifier}）"
        f"没有注册 OLAV HarnessProfile。\n"
        f"将 '{provider}:{identifier}' 加入 tier_small.py 或 tier_medium.py 的 _MODEL_SPECS。"
    )
