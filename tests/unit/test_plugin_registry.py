"""Phase 1-2 TDD: PluginRegistry

断言：
- register() 后能通过 get_middleware_plugins() / get_callback_plugins() 取回
- disabled 列表中的插件不出现在结果中
- 同名插件注册两次，后者覆盖前者（幂等）
"""
import dataclasses

import pytest


def test_registry_get_middleware_plugins():
    """注册 OLAVMiddlewarePlugin 后，get_middleware_plugins() 返回该实例。"""
    from olav.plugins.base import OLAVMiddlewarePlugin
    from olav.plugins.registry import PluginRegistry

    class MyMiddleware(OLAVMiddlewarePlugin):
        name = "my_mw"

    registry = PluginRegistry()
    plugin = MyMiddleware()
    registry.register(plugin)

    result = registry.get_middleware_plugins()
    assert plugin in result, "Registered middleware plugin must appear in get_middleware_plugins()."


def test_registry_get_callback_plugins():
    """注册 OLAVCallbackPlugin 后，get_callback_plugins() 返回该实例。"""
    from olav.plugins.base import OLAVCallbackPlugin
    from olav.plugins.registry import PluginRegistry

    class MyCallback(OLAVCallbackPlugin):
        name = "my_cb"

    registry = PluginRegistry()
    plugin = MyCallback()
    registry.register(plugin)

    result = registry.get_callback_plugins()
    assert plugin in result, "Registered callback plugin must appear in get_callback_plugins()."


def test_registry_disabled_plugins_excluded():
    """disabled 列表中的插件名注册后不出现在任何 get_*_plugins() 结果中。"""
    from olav.plugins.base import OLAVMiddlewarePlugin
    from olav.plugins.registry import PluginRegistry

    class FooPlugin(OLAVMiddlewarePlugin):
        name = "foo"

    registry = PluginRegistry(disabled=["foo"])
    registry.register(FooPlugin())

    assert not registry.get_middleware_plugins(), (
        "Plugin named 'foo' should be excluded when 'foo' is in disabled list."
    )


def test_registry_deduplicates_by_name():
    """同名插件注册两次，后注册的覆盖前者（幂等）。"""
    from olav.plugins.base import OLAVMiddlewarePlugin
    from olav.plugins.registry import PluginRegistry

    class V1(OLAVMiddlewarePlugin):
        name = "same"
        version = "1.0.0"

    class V2(OLAVMiddlewarePlugin):
        name = "same"
        version = "2.0.0"

    registry = PluginRegistry()
    registry.register(V1())
    registry.register(V2())

    result = registry.get_middleware_plugins()
    assert len(result) == 1, "Duplicate-named plugins should be deduplicated (last wins)."
    assert result[0].version == "2.0.0", "Last registered plugin should win."


def test_registry_separates_middleware_and_callbacks():
    """Middleware 和 Callback 插件不互相出现在对方的列表中。"""
    from olav.plugins.base import OLAVMiddlewarePlugin, OLAVCallbackPlugin
    from olav.plugins.registry import PluginRegistry

    class MW(OLAVMiddlewarePlugin):
        name = "mw_only"

    class CB(OLAVCallbackPlugin):
        name = "cb_only"

    registry = PluginRegistry()
    registry.register(MW())
    registry.register(CB())

    for plugin in registry.get_middleware_plugins():
        assert not isinstance(plugin, OLAVCallbackPlugin), "Callback plugin leaked into middleware list."

    for plugin in registry.get_callback_plugins():
        assert not isinstance(plugin, OLAVMiddlewarePlugin), "Middleware plugin leaked into callback list."
