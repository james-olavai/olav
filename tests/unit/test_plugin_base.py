"""Phase 1-1 TDD: Plugin 目录结构与基类

断言：
- 能 import olav.plugins.base 中的三个类
- OLAVMiddlewarePlugin 是 AgentMiddleware 的子类
- OLAVCallbackPlugin 是 AsyncCallbackHandler 的子类
- OLAVPlugin 有 name/version/enabled/tags 字段
"""


def test_plugin_base_importable():
    """olav.plugins.base 必须可导入，三个基类必须存在。"""
    from olav.plugins.base import OLAVPlugin, OLAVMiddlewarePlugin, OLAVCallbackPlugin

    assert OLAVPlugin is not None
    assert OLAVMiddlewarePlugin is not None
    assert OLAVCallbackPlugin is not None


def test_middleware_plugin_is_agent_middleware_subclass():
    """OLAVMiddlewarePlugin 必须是 AgentMiddleware 的子类，可传入 create_deep_agent。"""
    from langchain.agents.middleware.types import AgentMiddleware
    from olav.plugins.base import OLAVMiddlewarePlugin

    assert issubclass(OLAVMiddlewarePlugin, AgentMiddleware), (
        "OLAVMiddlewarePlugin must inherit from langchain AgentMiddleware "
        "to be usable in create_deep_agent(middleware=[...])."
    )


def test_callback_plugin_is_async_callback_handler_subclass():
    """OLAVCallbackPlugin 必须是 AsyncCallbackHandler 的子类。"""
    from langchain_core.callbacks import AsyncCallbackHandler
    from olav.plugins.base import OLAVCallbackPlugin

    assert issubclass(OLAVCallbackPlugin, AsyncCallbackHandler), (
        "OLAVCallbackPlugin must inherit from AsyncCallbackHandler "
        "to be injectable into LangChain callbacks."
    )


def test_olav_plugin_has_required_metadata_fields():
    """OLAVPlugin 必须有 name、version、enabled、tags、description 属性。"""
    from olav.plugins.base import OLAVPlugin

    for attr in ("name", "version", "enabled", "tags", "description"):
        assert hasattr(OLAVPlugin, attr), (
            f"OLAVPlugin is missing attribute '{attr}'. "
            "All plugins need these metadata attributes for registry management."
        )


def test_plugin_module_structure_exists():
    """plugins/ 子包目录结构必须完整。"""
    import importlib

    for mod_path in (
        "olav.plugins",
        "olav.plugins.base",
        "olav.plugins.middleware",
        "olav.plugins.callbacks",
    ):
        mod = importlib.import_module(mod_path)
        assert mod is not None, f"Module '{mod_path}' could not be imported."
