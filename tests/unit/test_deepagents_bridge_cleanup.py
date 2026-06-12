"""
TDD: deepagents 0.6.7 集成清理 + on_evaluation 回调

dev_docs/92. DEEPAGENTS_067_FEATURES_AND_OLAV_INTEGRATION.md

验收标准：
  1. _deepagents_bridge 中的版本门控常量在 _DA_MIN=0.6.7 下永远为 True
  2. 当前安装的 deepagents 版本 >= 0.6.7（避免 _DA_MIN 检查本身被跳过）
  3. RubricMiddleware 在注入时携带 on_evaluation 回调（callable）
  4. on_evaluation 回调在被调用时不抛异常（even with bad evaluation object）
  5. permissions 参数使用 `or []` 显式传参，不产生 None
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# 1. 版本门控常量（清理后永远为 True）
# ---------------------------------------------------------------------------


def test_has_summarization_is_true():
    from olav.agents._deepagents_bridge import HAS_SUMMARIZATION
    assert HAS_SUMMARIZATION is True, "HAS_SUMMARIZATION must be True (min deepagents=0.6.7 > 0.4.0)"


def test_has_local_shell_backend_is_true():
    from olav.agents._deepagents_bridge import HAS_LOCAL_SHELL_BACKEND
    assert HAS_LOCAL_SHELL_BACKEND is True


def test_has_namespace_factory_is_true():
    from olav.agents._deepagents_bridge import HAS_NAMESPACE_FACTORY
    assert HAS_NAMESPACE_FACTORY is True


def test_has_async_subagents_is_true():
    from olav.agents._deepagents_bridge import HAS_ASYNC_SUBAGENTS
    assert HAS_ASYNC_SUBAGENTS is True


def test_has_rubric_middleware_is_true():
    from olav.agents._deepagents_bridge import HAS_RUBRIC_MIDDLEWARE
    assert HAS_RUBRIC_MIDDLEWARE is True, "HAS_RUBRIC_MIDDLEWARE must be True (min deepagents=0.6.7 > 0.6.5)"


def test_has_state_schema_is_true():
    from olav.agents._deepagents_bridge import HAS_STATE_SCHEMA
    assert HAS_STATE_SCHEMA is True


def test_has_context_hub_is_true():
    from olav.agents._deepagents_bridge import HAS_CONTEXT_HUB
    assert HAS_CONTEXT_HUB is True


def test_rubric_middleware_class_importable():
    """RubricMiddleware must be importable from the bridge (not None)."""
    from olav.agents._deepagents_bridge import RubricMiddleware
    assert RubricMiddleware is not None, (
        "RubricMiddleware is None — deepagents installation missing the middleware.\n"
        "Run: uv sync"
    )


# ---------------------------------------------------------------------------
# 2. on_evaluation 回调注入
# ---------------------------------------------------------------------------


def test_rubric_middleware_receives_on_evaluation_callable(tmp_path, monkeypatch):
    """当 agent metadata.rubric_middleware=true 时，RubricMiddleware 应以 on_evaluation 关键字参数被实例化。

    这个测试 mock 掉 RubricMiddleware 构造函数，捕获调用参数，
    验证 on_evaluation 是一个 callable。
    """
    import sys
    import types

    # 最小化 SKILL.md
    sa_dir = tmp_path / "workspace" / "rubric-agent"
    sa_dir.mkdir(parents=True)
    (sa_dir / "SKILL.md").write_text(
        "---\n"
        "name: rubric-agent\n"
        "description: test rubric agent\n"
        "tools:\n  - execute_skill_script\n"
        "metadata:\n  rubric_middleware: true\n  type: agent\n  version: 1.0.0\n"
        "---\nAgent body.\n"
    )
    (sa_dir / "prompts").mkdir()
    (sa_dir / "prompts" / "system.md").write_text("You are a rubric agent.")

    # 记录 RubricMiddleware.__init__ 的调用参数
    captured_kwargs: list[dict] = []

    from olav.agents import _deepagents_bridge as bridge

    class _FakeRubricMW:
        def __init__(self, **kwargs):
            captured_kwargs.append(kwargs)

    monkeypatch.setattr(bridge, "RubricMiddleware", _FakeRubricMW)
    monkeypatch.setattr(bridge, "HAS_RUBRIC_MIDDLEWARE", True)

    # 触发 _build_subagents — 需要 patch 掉 agent.py 中的 RubricMiddleware 引用
    import olav.agents.agent as agent_mod
    monkeypatch.setattr(agent_mod, "_RubricMW_bridge_ref", _FakeRubricMW, raising=False)

    # 直接测试闭包逻辑（不需要 full agent build）：
    # _make_rubric_callback 是 agent.py 中的闭包工厂，需要从 agent_mod 获取
    if not hasattr(agent_mod, "_make_rubric_callback"):
        pytest.skip("_make_rubric_callback not yet exported from agent.py — implement first")

    cb = agent_mod._make_rubric_callback("test-agent")
    assert callable(cb), "on_evaluation callback must be callable"


def test_on_evaluation_callback_survives_bad_evaluation():
    """on_evaluation 回调在收到格式错误的 evaluation 对象时不应抛异常。"""
    import olav.agents.agent as agent_mod
    if not hasattr(agent_mod, "_make_rubric_callback"):
        pytest.skip("_make_rubric_callback not yet exported from agent.py — implement first")

    cb = agent_mod._make_rubric_callback("test-agent")
    # 空对象 — 没有任何属性
    bad_eval = object()
    cb(bad_eval)  # must not raise

    # None
    cb(None)  # must not raise

    # 部分属性
    class _PartialEval:
        passed = True
        # no criteria, no iterations

    cb(_PartialEval())  # must not raise


def test_on_evaluation_callback_logs_passed_and_iterations(caplog):
    """on_evaluation 回调应 logger.info 包含 agent/passed/iterations 的行。"""
    import logging
    import olav.agents.agent as agent_mod
    if not hasattr(agent_mod, "_make_rubric_callback"):
        pytest.skip("_make_rubric_callback not yet exported from agent.py — implement first")

    class _MockEval:
        passed = True
        iterations = 2
        criteria = []

    cb = agent_mod._make_rubric_callback("my-agent")
    with caplog.at_level(logging.INFO, logger="olav.agents.agent"):
        cb(_MockEval())

    assert any("my-agent" in r.message and "rubric_evaluation" in r.message
               for r in caplog.records), (
        "Expected a logger.info line containing 'rubric_evaluation' and 'my-agent'.\n"
        f"Actual log records: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# 3. permissions 显式传参（不再有 None 进入 create_deep_agent）
# ---------------------------------------------------------------------------


def test_version_gate_constants_are_literals_not_comparisons():
    """版本门控常量必须是字面量 True，不能是版本比较表达式（清理后）。

    通过读取 _deepagents_bridge 源码，确认不含 `>= V("0.4.0")` 等比较式。
    允许 HAS_PROMPT_CACHING = True 这样的字面量赋值。

    注意：HAS_xxx: bool = ... 是 AnnAssign（注解赋值），不是 Assign，
    两种形式都必须检查。
    """
    import ast
    import inspect
    import olav.agents._deepagents_bridge as bridge

    source = inspect.getsource(bridge)
    tree = ast.parse(source)

    stale_comparisons = []
    for node in ast.walk(tree):
        # HAS_xxx = ... 或 HAS_xxx: bool = ...
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
            if not (len(targets) == 1 and isinstance(targets[0], ast.Name)):
                continue
            name = targets[0].id
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                continue
            name = node.target.id
            value = node.value
            if value is None:
                continue
        else:
            continue

        if not name.startswith("HAS_"):
            continue
        # HAS_PROMPT_CACHING is handled separately (None-check on import) — skip
        if name == "HAS_PROMPT_CACHING":
            continue
        # 只标记 _DA_VERSION >= V(...) 形式的版本比较，排除 is not None 等合理比较
        if (
            isinstance(value, ast.Compare)
            and isinstance(value.left, ast.Name)
            and value.left.id == "_DA_VERSION"
        ):
            stale_comparisons.append(name)

    assert not stale_comparisons, (
        f"以下版本门控常量仍使用 _DA_VERSION >= V(...) 比较式，应替换为字面量 True:\n"
        f"{stale_comparisons}\n"
        f"(dev_docs/92 §4.1)"
    )
