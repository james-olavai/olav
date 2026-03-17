"""OLAV Plugin Registry — 运行时插件注册表。

使用方式：
    registry = PluginRegistry(disabled=["audit"])
    registry.register(MyMiddlewarePlugin())
    registry.register(MyCallbackPlugin())

    mws = registry.get_middleware_plugins()   # -> List[OLAVMiddlewarePlugin]
    cbs = registry.get_callback_plugins()      # -> List[OLAVCallbackPlugin]
"""
from __future__ import annotations

from collections.abc import Sequence

from olav.plugins.base import OLAVCallbackPlugin, OLAVMiddlewarePlugin, OLAVPlugin


class PluginRegistry:
    """运行时插件注册表，维护 middleware 和 callback 两条独立列表。

    Args:
        disabled: 应跳过的插件名列表（来自 api.json 的 plugins.disabled）。
    """

    def __init__(self, disabled: Sequence[str] | None = None) -> None:
        self._disabled: frozenset[str] = frozenset(disabled or [])
        # 用 dict 保持注册顺序且按 name 去重（后注册覆盖前者）
        self._middleware: dict[str, OLAVMiddlewarePlugin] = {}
        self._callbacks: dict[str, OLAVCallbackPlugin] = {}

    def register(self, plugin: OLAVPlugin) -> None:
        """注册一个插件实例。disabled 列表中的插件静默忽略。"""
        if plugin.name in self._disabled:
            return

        if isinstance(plugin, OLAVMiddlewarePlugin):
            self._middleware[plugin.name] = plugin
        elif isinstance(plugin, OLAVCallbackPlugin):
            self._callbacks[plugin.name] = plugin

    def get_middleware_plugins(self) -> list[OLAVMiddlewarePlugin]:
        """返回所有已注册且未被禁用的 middleware 插件（有序）。"""
        return list(self._middleware.values())

    def get_callback_plugins(self) -> list[OLAVCallbackPlugin]:
        """返回所有已注册且未被禁用的 callback 插件（有序）。"""
        return list(self._callbacks.values())

    def __len__(self) -> int:
        return len(self._middleware) + len(self._callbacks)
