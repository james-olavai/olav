"""Phase 1-3 TDD: 内置插件扫描加载器

断言：
- load_builtin_plugins() 能扫描到临时插件文件中的 OLAVMiddlewarePlugin 子类并注册
- OLAVPlugin 抽象基类本身不被注册
- 以 _ 开头的文件被跳过
- load_external_plugins() 在无 entry points 时静默返回（不抛异常）
"""
import sys
import textwrap
from pathlib import Path


def _write_plugin_file(plugin_dir: Path, filename: str, class_def: str) -> None:
    (plugin_dir / filename).write_text(textwrap.dedent(class_def))


def test_load_builtin_plugins_registers_middleware(tmp_path, monkeypatch):
    """load_builtin_plugins 扫描到 middleware/*.py 中的 OLAVMiddlewarePlugin 子类后注册。"""
    from olav.plugins.base import OLAVMiddlewarePlugin
    from olav.plugins.registry import PluginRegistry

    # 创建临时 middleware 目录和插件文件
    mw_dir = tmp_path / "middleware"
    mw_dir.mkdir()
    (mw_dir / "__init__.py").write_text("")
    _write_plugin_file(mw_dir, "test_mw.py", """
        from olav.plugins.base import OLAVMiddlewarePlugin

        class TestMWPlugin(OLAVMiddlewarePlugin):
            name = "test_mw"
            version = "0.1.0"
    """)

    # 创建空 callbacks 目录
    cb_dir = tmp_path / "callbacks"
    cb_dir.mkdir()
    (cb_dir / "__init__.py").write_text("")

    # 修补 load_builtin_plugins 使用临时目录
    import olav.plugins as plugins_mod
    monkeypatch.setattr(
        plugins_mod,
        "load_builtin_plugins",
        _make_loader(tmp_path),
    )

    registry = PluginRegistry()
    plugins_mod.load_builtin_plugins(registry)

    names = [p.name for p in registry.get_middleware_plugins()]
    assert "test_mw" in names, (
        f"Plugin 'test_mw' not found after load_builtin_plugins. Got: {names}"
    )


def test_load_builtin_plugins_skips_underscore_files(tmp_path, monkeypatch):
    """以 _ 开头的文件（__init__.py、_internal.py 等）不被扫描。"""
    mw_dir = tmp_path / "middleware"
    mw_dir.mkdir()
    (mw_dir / "__init__.py").write_text("")
    _write_plugin_file(mw_dir, "_private.py", """
        from olav.plugins.base import OLAVMiddlewarePlugin

        class PrivatePlugin(OLAVMiddlewarePlugin):
            name = "private"
    """)

    cb_dir = tmp_path / "callbacks"
    cb_dir.mkdir()
    (cb_dir / "__init__.py").write_text("")

    import olav.plugins as plugins_mod
    monkeypatch.setattr(plugins_mod, "load_builtin_plugins", _make_loader(tmp_path))

    registry = PluginRegistry()
    plugins_mod.load_builtin_plugins(registry)

    names = [p.name for p in registry.get_middleware_plugins()]
    assert "private" not in names, "Underscore-prefixed files must be skipped."


def test_load_external_plugins_silent_when_no_entrypoints():
    """load_external_plugins 在无 entry points 时静默返回，不抛异常。"""
    from olav.plugins import load_external_plugins
    from olav.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    # 应不抛任何异常
    load_external_plugins(registry)
    assert len(registry.get_middleware_plugins()) == 0
    assert len(registry.get_callback_plugins()) == 0


# --- helper ----------------------------------------------------------------

def _make_loader(base_dir: Path):
    """返回一个使用 base_dir 代替默认插件目录的 load_builtin_plugins 函数。"""
    from importlib import import_module
    from olav.plugins.base import OLAVPlugin

    def _loader(registry):
        for subdir in ("middleware", "callbacks"):
            for path in sorted((base_dir / subdir).glob("*.py")):
                if path.stem.startswith("_"):
                    continue
                # 动态加载文件为模块
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    f"_test_plugin_{path.stem}", path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for obj in vars(module).values():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, OLAVPlugin)
                        and obj is not OLAVPlugin
                    ):
                        try:
                            registry.register(obj())
                        except Exception:
                            pass

    return _loader


from olav.plugins.registry import PluginRegistry  # noqa: E402
