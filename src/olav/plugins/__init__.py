"""OLAV Plugin 系统顶层包。

公共接口：
    load_builtin_plugins(registry)  — 从 plugins/middleware/ 和 plugins/callbacks/ 扫描并注册
    load_external_plugins(registry) — 从 Python entry points 加载外部（企业/用户）插件
"""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path

from olav.plugins.base import OLAVPlugin


def load_builtin_plugins(registry: PluginRegistry) -> None:  # noqa: F821
    """扫描内置 middleware/ 和 callbacks/ 目录，自动发现并注册所有 OLAVPlugin 子类。"""
    base = Path(__file__).parent
    for subdir in ("middleware", "callbacks"):
        for path in sorted((base / subdir).glob("*.py")):
            if path.stem.startswith("_"):
                continue
            module = import_module(f"olav.plugins.{subdir}.{path.stem}")
            for obj in vars(module).values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, OLAVPlugin)
                    and obj is not OLAVPlugin
                ):
                    try:
                        registry.register(obj())
                    except Exception:
                        pass  # 插件实例化失败时跳过，不阻断启动


def load_external_plugins(registry: PluginRegistry) -> None:  # noqa: F821
    """通过 entry points 加载外部（企业/用户）插件。

    entry point 组：olav.middleware，olav.callbacks
    若无外部插件安装，静默返回。
    """
    for group in ("olav.middleware", "olav.callbacks"):
        for ep in entry_points(group=group):
            try:
                plugin_cls = ep.load()
                registry.register(plugin_cls())
            except Exception:
                pass  # 外部插件加载失败时跳过


__all__ = ["load_builtin_plugins", "load_external_plugins"]
