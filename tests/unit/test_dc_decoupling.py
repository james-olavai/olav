"""Tests for DC-1 through DC-4: Platform/NetOps decoupling.

DC-1: _fast_reload uses extension points, no direct olav_netops import
DC-2: create_olav_directories() only creates platform-minimal directories
DC-3: _config_commands() and _get_config_command_names() use extension points
DC-4: Stale netops references removed from platform docstrings/comments
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[2] / "src"
_ADMIN_PY = _SRC / "olav" / "cli" / "admin.py"
_UTILS_PY = _SRC / "olav" / "core" / "utils.py"
_CALC_DIFFS_PY = _SRC / "olav" / "core" / "calculate_diffs.py"
_MIGRATIONS_PY = _SRC / "olav" / "core" / "migrations" / "v0_10_raw_diffs.py"


# ===========================================================================
# DC-1: _fast_reload extension point — no direct olav_netops import
# ===========================================================================


class TestDC1FastReloadDecoupled:
    """Verify _fast_reload does NOT directly import from olav_netops."""

    def _admin_source(self) -> str:
        return _ADMIN_PY.read_text(encoding="utf-8")

    def test_no_direct_olav_netops_import_in_admin(self):
        """admin.py must not contain 'from olav_netops' anywhere."""
        src = self._admin_source()
        assert "from olav_netops" not in src, (
            "admin.py still contains a direct import from olav_netops"
        )

    def test_no_import_olav_netops_in_admin(self):
        """admin.py must not contain 'import olav_netops' anywhere."""
        src = self._admin_source()
        assert "import olav_netops" not in src, "admin.py still contains 'import olav_netops'"

    def test_fast_reload_uses_entry_points(self):
        """_fast_reload must discover reload hooks via importlib entry_points."""
        src = self._admin_source()
        assert "entry_points" in src, (
            "_fast_reload should use importlib.metadata.entry_points for reload hooks"
        )

    def test_fast_reload_uses_reload_hooks_group(self):
        """_fast_reload must reference the 'olav.reload_hooks' entry point group."""
        src = self._admin_source()
        assert "olav.reload_hooks" in src, (
            "_fast_reload should discover hooks from 'olav.reload_hooks' group"
        )

    def test_fast_reload_returns_unavailable_when_no_hooks(self):
        """_fast_reload returns unavailable status when no reload hooks are registered."""
        import asyncio

        from olav.cli.admin import _fast_reload

        # With no hooks registered (test environment), it should return unavailable
        # OR a success with empty results — either is acceptable.
        result = asyncio.run(_fast_reload(""))
        assert result["status"] in ("unavailable", "success"), (
            f"_fast_reload returned unexpected status: {result['status']}"
        )

    def test_fast_reload_is_async(self):
        """_fast_reload must remain an async function."""
        from olav.cli.admin import _fast_reload

        assert inspect.iscoroutinefunction(_fast_reload), "_fast_reload must be an async function"

    def test_fast_reload_docstring_no_netops_specifics(self):
        """_fast_reload docstring should not mention netops-specific files."""
        from olav.cli.admin import _fast_reload

        doc = _fast_reload.__doc__ or ""
        for stale in [
            "TextFSM",
            "allowed_commands.json",
            "blacklisted_commands.json",
            ".olav/templates",
            "NETOPS-ONLY",
        ]:
            assert stale not in doc, (
                f"_fast_reload docstring still mentions netops-specific term: {stale!r}"
            )


# ===========================================================================
# DC-1 continued: olav-netops must register a reload_hooks entry point
# ===========================================================================


class TestDC1NetopsReloadHookRegistered:
    """Verify olav-netops registers its reload hook via entry point."""

    def _netops_pyproject(self) -> str:
        pyproject = Path(__file__).resolve().parents[2] / "olav-netops" / "pyproject.toml"
        return pyproject.read_text(encoding="utf-8")

    def test_netops_declares_reload_hooks_entry_point(self):
        """olav-netops/pyproject.toml must declare an olav.reload_hooks entry point."""
        src = self._netops_pyproject()
        assert "olav.reload_hooks" in src, (
            "olav-netops/pyproject.toml missing olav.reload_hooks entry point group"
        )

    def test_reload_hook_callable_exists(self):
        """The reload hook callable must exist in olav_netops."""
        from olav_netops.command_registry import reload_hook  # type: ignore[import]

        assert callable(reload_hook), "reload_hook must be callable"

    def test_reload_hook_returns_dict(self):
        """The reload hook should return a dict with expected shape."""
        from olav_netops.command_registry import reload_hook  # type: ignore[import]

        result = reload_hook()
        assert isinstance(result, dict), "reload_hook must return a dict"
        # Must have at minimum a 'status' or 'reloaded' key
        assert "reloaded" in result or "status" in result, (
            "reload_hook result must contain 'reloaded' or 'status'"
        )


# ===========================================================================
# DC-2: create_olav_directories() — platform-minimal directory set
# ===========================================================================


class TestDC2PlatformMinimalDirs:
    """Verify create_olav_directories() creates only platform-generic dirs."""

    def _utils_source(self) -> str:
        return _UTILS_PY.read_text(encoding="utf-8")

    def test_no_netops_domain_dir_in_source(self):
        """'config/domains/netops' must not appear in utils.py."""
        src = self._utils_source()
        assert "config/domains/netops" not in src, (
            "utils.py still hardcodes 'config/domains/netops' directory creation"
        )

    def test_no_nornir_dir_in_source(self):
        """'nornir' must not appear as a directory in utils.py subdir list."""
        src = self._utils_source()
        assert "nornir" not in src, "utils.py still references 'nornir' directory"

    def test_creates_platform_dirs(self, tmp_path):
        """create_olav_directories() must create core platform directories."""
        from olav.core.utils import create_olav_directories

        result = create_olav_directories(tmp_path)
        olav_dir = tmp_path / ".olav"

        # Core platform dirs that MUST exist
        for d in [
            "config",
            "databases",
            "logs",
            "logs/users",
            "cache",
            "workspace",
            "exports",
            "knowledge",
        ]:
            assert (olav_dir / d).is_dir(), f"Platform dir .olav/{d} not created"

    def test_does_not_create_netops_dirs(self, tmp_path):
        """create_olav_directories() must NOT create netops-specific dirs."""
        from olav.core.utils import create_olav_directories

        create_olav_directories(tmp_path)
        olav_dir = tmp_path / ".olav"

        # Netops-specific dirs that must NOT be created by platform
        for d in ["config/domains/netops", "config/domains/netops/nornir"]:
            assert not (olav_dir / d).exists(), f"Platform created netops-specific dir: .olav/{d}"

    def test_no_templates_custom_or_config(self, tmp_path):
        """templates/custom and templates/config are netops-specific."""
        from olav.core.utils import create_olav_directories

        create_olav_directories(tmp_path)
        olav_dir = tmp_path / ".olav"

        # These are netops-specific template directories
        for d in ["templates/custom", "templates/config"]:
            assert not (olav_dir / d).exists(), (
                f"Platform created netops-specific template dir: .olav/{d}"
            )

    def test_return_value_shape(self, tmp_path):
        """Return value must be a dict with status per directory."""
        from olav.core.utils import create_olav_directories

        result = create_olav_directories(tmp_path)
        assert isinstance(result, dict)
        assert "olav_root" in result
        assert result["olav_root"]["status"] == "created"


# ===========================================================================
# DC-3: _config_commands uses extension point, not hardcoded YAML path
# ===========================================================================


class TestDC3ConfigCommandsDecoupled:
    """Verify _config_commands() and _get_config_command_names() don't read netops YAML."""

    def _calc_diffs_source(self) -> str:
        return _CALC_DIFFS_PY.read_text(encoding="utf-8")

    def _migrations_source(self) -> str:
        return _MIGRATIONS_PY.read_text(encoding="utf-8")

    def test_calc_diffs_no_hardcoded_netops_yaml_path(self):
        """calculate_diffs.py must not reference domains/netops/backup_only_commands.yaml."""
        src = self._calc_diffs_source()
        assert "domains/netops/backup_only_commands" not in src, (
            "calculate_diffs.py still hardcodes the netops YAML path"
        )

    def test_migrations_no_hardcoded_netops_yaml_path(self):
        """v0_10_raw_diffs.py must not reference domains/netops/backup_only_commands.yaml."""
        src = self._migrations_source()
        assert "domains/netops/backup_only_commands" not in src, (
            "v0_10_raw_diffs.py still hardcodes the netops YAML path"
        )

    def test_calc_diffs_uses_entry_points(self):
        """calculate_diffs.py must use entry_points for config commands discovery."""
        src = self._calc_diffs_source()
        assert "entry_points" in src, (
            "calculate_diffs.py should use entry_points for config command discovery"
        )

    def test_calc_diffs_uses_config_commands_group(self):
        """calculate_diffs.py must reference the 'olav.config_commands' group."""
        src = self._calc_diffs_source()
        assert "olav.config_commands" in src, (
            "calculate_diffs.py should discover from 'olav.config_commands' group"
        )

    def test_migrations_uses_entry_points(self):
        """v0_10_raw_diffs.py must use entry_points for config commands."""
        src = self._migrations_source()
        assert "entry_points" in src, (
            "v0_10_raw_diffs.py should use entry_points for config command discovery"
        )

    def test_config_commands_returns_frozenset(self):
        """_config_commands() must return a frozenset."""
        from olav.core.calculate_diffs import _config_commands

        result = _config_commands()
        assert isinstance(result, frozenset), (
            f"_config_commands() returned {type(result).__name__}, expected frozenset"
        )

    def test_config_commands_fallback(self):
        """With no providers installed, _config_commands() returns sensible fallback."""
        from olav.core.calculate_diffs import _config_commands

        result = _config_commands()
        assert len(result) > 0, "Fallback config commands must not be empty"
        assert any("running-config" in c for c in result), (
            "Fallback must include 'show running-config' style commands"
        )

    def test_migrations_config_commands_returns_list(self):
        """_get_config_command_names() must still return a list."""
        from olav.core.migrations.v0_10_raw_diffs import _get_config_command_names

        result = _get_config_command_names()
        assert isinstance(result, list), (
            f"_get_config_command_names() returned {type(result).__name__}, expected list"
        )

    def test_no_yaml_import_in_calc_diffs_config_commands(self):
        """_config_commands() should not import yaml directly anymore."""
        src = self._calc_diffs_source()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_config_commands":
                func_src = ast.get_source_segment(src, node)
                assert isinstance(func_src, str)
                assert "import yaml" not in func_src, (
                    "_config_commands still directly imports yaml to read netops config"
                )


# ===========================================================================
# DC-3 continued: olav-netops registers config_commands entry point
# ===========================================================================


class TestDC3NetopsConfigCommandsRegistered:
    """Verify olav-netops registers its config commands via entry point."""

    def _netops_pyproject(self) -> str:
        pyproject = Path(__file__).resolve().parents[2] / "olav-netops" / "pyproject.toml"
        return pyproject.read_text(encoding="utf-8")

    def test_netops_declares_config_commands_entry_point(self):
        """olav-netops/pyproject.toml must declare an olav.config_commands entry point."""
        src = self._netops_pyproject()
        assert "olav.config_commands" in src, (
            "olav-netops/pyproject.toml missing olav.config_commands entry point group"
        )

    def test_config_commands_provider_callable_exists(self):
        """The config commands provider must exist in olav_netops."""
        from olav_netops.command_registry import get_config_commands  # type: ignore[import]

        assert callable(get_config_commands), "get_config_commands must be callable"

    def test_config_commands_provider_returns_list(self):
        """The provider should return a list of command name strings."""
        from olav_netops.command_registry import get_config_commands  # type: ignore[import]

        result = get_config_commands()
        assert isinstance(result, list), "get_config_commands must return a list"


# ===========================================================================
# DC-4: Stale netops references removed from platform files
# ===========================================================================


class TestDC4StaleReferencesRemoved:
    """Verify platform files don't contain stale netops path references."""

    def _admin_source(self) -> str:
        return _ADMIN_PY.read_text(encoding="utf-8")

    def _utils_source(self) -> str:
        return _UTILS_PY.read_text(encoding="utf-8")

    def test_admin_no_textfsm_reference(self):
        """admin.py should not mention TextFSM (netops-specific)."""
        from olav.cli.admin import _fast_reload

        doc = _fast_reload.__doc__ or ""
        assert "TextFSM" not in doc, "_fast_reload docstring still mentions TextFSM"

    def test_admin_no_allowed_commands_json(self):
        """admin.py docstring should not mention allowed_commands.json."""
        from olav.cli.admin import _fast_reload

        doc = _fast_reload.__doc__ or ""
        assert "allowed_commands.json" not in doc, (
            "_fast_reload docstring still mentions allowed_commands.json"
        )

    def test_admin_no_blacklisted_commands_json(self):
        """admin.py docstring should not mention blacklisted_commands.json."""
        from olav.cli.admin import _fast_reload

        doc = _fast_reload.__doc__ or ""
        assert "blacklisted_commands.json" not in doc, (
            "_fast_reload docstring still mentions blacklisted_commands.json"
        )

    def test_admin_no_olav_templates_path(self):
        """admin.py docstring should not mention .olav/templates (netops path)."""
        from olav.cli.admin import _fast_reload

        doc = _fast_reload.__doc__ or ""
        assert ".olav/templates" not in doc, "_fast_reload docstring still mentions .olav/templates"

    def test_utils_no_netops_domain_reference(self):
        """utils.py should not mention 'netops' in comments."""
        src = self._utils_source()
        assert "netops" not in src.lower(), "utils.py still contains 'netops' reference"

    def test_calc_diffs_no_backup_only_commands_in_docstring(self):
        """Module docstring of calculate_diffs.py should not mention backup_only_commands.yaml."""
        src = _CALC_DIFFS_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, (ast.Constant, ast.Str))
        ):
            docstring = (
                tree.body[0].value.value
                if isinstance(tree.body[0].value, ast.Constant)
                else tree.body[0].value.s
            )
            assert isinstance(docstring, str)
            assert "backup_only_commands" not in docstring, (
                "calculate_diffs.py module docstring still mentions backup_only_commands.yaml"
            )


# ===========================================================================
# DC-1 (tracking §2.1): config.py must NOT export netops-specific symbols
# ===========================================================================

_CONFIG_PY = _SRC / "olav" / "core" / "config.py"

# Netops-specific symbols that must NOT be in config.py
_NETOPS_SYMBOLS = [
    "NETOPS_CONFIG_DIR",
    "BLACKLIST_CONFIG_PATH",
    "REPAIR_QUEUE_PATH",
    "CATEGORY_STRATEGY_PATH",
    "COMMAND_STRATEGY_PATH",
    "scrapli_timeout_ops",
]


class TestTrackingDC1ConfigNetopsExportsRemoved:
    """§2.1 DC-1: config.py must not export any netops-specific constants or properties."""

    def _config_source(self) -> str:
        return _CONFIG_PY.read_text(encoding="utf-8")

    def _config_ast(self) -> ast.Module:
        return ast.parse(self._config_source())

    # ── Symbol-level checks ──────────────────────────────────────────────

    @pytest.mark.parametrize("symbol", _NETOPS_SYMBOLS[:5])  # The 5 module-level constants
    def test_symbol_not_in_module_namespace(self, symbol: str):
        """Module-level netops constant must not exist in config.py source."""
        tree = self._config_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == symbol:
                        pytest.fail(f"config.py still defines netops-specific constant: {symbol}")
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == symbol:
                    pytest.fail(f"config.py still defines netops-specific constant: {symbol}")

    def test_scrapli_timeout_ops_property_removed(self):
        """RuntimeConfig must not have a scrapli_timeout_ops property."""
        tree = self._config_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "RuntimeConfig":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "scrapli_timeout_ops":
                        pytest.fail("RuntimeConfig still defines scrapli_timeout_ops property")

    def test_netops_comment_removed(self):
        """The NETOPS-ONLY comment about templates_dir must be removed."""
        src = self._config_source()
        assert "NETOPS-ONLY" not in src, "config.py still contains a NETOPS-ONLY comment"

    # ── __all__ checks ───────────────────────────────────────────────────

    @pytest.mark.parametrize("symbol", _NETOPS_SYMBOLS[:5])
    def test_symbol_not_in_dunder_all(self, symbol: str):
        """Netops symbols must not appear in __all__."""
        tree = self._config_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        # Check the list elements
                        if isinstance(node.value, ast.List):
                            names = [
                                elt.value
                                for elt in node.value.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]
                            assert symbol not in names, (
                                f"__all__ still contains netops symbol: {symbol}"
                            )

    # ── Import checks (runtime) ──────────────────────────────────────────

    @pytest.mark.parametrize("symbol", _NETOPS_SYMBOLS[:5])
    def test_symbol_not_importable(self, symbol: str):
        """Netops symbols must not be importable from olav.core.config."""
        import olav.core.config as cfg

        assert not hasattr(cfg, symbol), f"olav.core.config still exposes netops symbol: {symbol}"

    def test_scrapli_timeout_ops_not_on_runtime_config(self):
        """RuntimeConfig instances must not have scrapli_timeout_ops."""
        from olav.core.config import get_runtime_config

        rc = get_runtime_config()
        assert not hasattr(rc, "scrapli_timeout_ops"), (
            "RuntimeConfig still exposes scrapli_timeout_ops"
        )

    # ── Positive check: generic symbols REMAIN ───────────────────────────

    def test_get_domain_config_dir_still_exists(self):
        """get_domain_config_dir must remain (it's generic)."""
        from olav.core.config import get_domain_config_dir

        assert callable(get_domain_config_dir)

    def test_config_dir_still_exists(self):
        """CONFIG_DIR must remain (it's generic)."""
        from olav.core.config import CONFIG_DIR

        assert CONFIG_DIR is not None


# ===========================================================================
# DC-2 (tracking §2.1): Platform layer must NOT contain netops default text
# ===========================================================================

_VERSION_PY = _SRC / "olav" / "core" / "version.py"
_INIT_PY = _SRC / "olav" / "__init__.py"
_BANNER_PY = _SRC / "olav" / "cli" / "banner.py"
_MAIN_PY = _SRC / "olav" / "cli" / "main.py"
_AGENT_PY = _SRC / "olav" / "agents" / "agent.py"
_INDEX_HTML = _SRC / "olav" / "api" / "static" / "index.html"
_GUARDRAILS_PY = _SRC / "olav" / "core" / "memory" / "guardrails.py"
_MEMORY_INIT_PY = _SRC / "olav" / "core" / "memory" / "__init__.py"
_ADMIN_DC2_PY = _SRC / "olav" / "cli" / "admin.py"
_ROUTER_PY = _SRC / "olav" / "core" / "router.py"
_LLM_SANDBOX_PY = _SRC / "olav" / "core" / "simulation" / "llm_sandbox.py"

# Netops-specific terms that should not appear in user-facing platform strings
_NETOPS_TERMS_STRICT = [
    "Network Operations",
    "network operations",
    "NetAIOps",
    "Agentic Networking",
]

# Terms that should not appear in docstrings/examples (case-insensitive check)
_NETOPS_EXAMPLE_TERMS = [
    "show bgp",
    "show interfaces brief",
    "enabling OSPF",
    "BGP flap",
    "OSPF adjacency",
    "interface Gi0/1",
    "Nornir",
    "网络仿真",
    "执行网络仿真",
]


class TestTrackingDC2PlatformNetopsTextCleaned:
    """§2.1 DC-2: Platform files must not contain netops-specific default text."""

    # ── version.py ───────────────────────────────────────────────────────

    def test_version_project_full_name_generic(self):
        """PROJECT_FULL_NAME must not mention 'Network Operations'."""
        src = _VERSION_PY.read_text(encoding="utf-8")
        assert "Network Operations" not in src, (
            "version.py PROJECT_FULL_NAME still says 'Network Operations'"
        )

    # ── __init__.py ──────────────────────────────────────────────────────

    def test_init_docstring_generic(self):
        """Module docstring must not mention 'Network'."""
        src = _INIT_PY.read_text(encoding="utf-8")
        assert "Network AI Operations" not in src, (
            "__init__.py docstring still mentions 'Network AI Operations'"
        )

    # ── banner.py ────────────────────────────────────────────────────────

    def test_banner_no_netaiops_comment(self):
        """banner.py must not contain 'NetAIOps' in comments."""
        src = _BANNER_PY.read_text(encoding="utf-8")
        assert "NetAIOps" not in src, "banner.py still mentions NetAIOps"

    def test_banner_tagline_no_agentic_networking(self):
        """Tagline must not contain 'Agentic Networking'."""
        src = _BANNER_PY.read_text(encoding="utf-8")
        assert "Agentic Networking" not in src, "banner.py tagline still says 'Agentic Networking'"

    # ── main.py ──────────────────────────────────────────────────────────

    def test_main_docstring_no_network_operations(self):
        """main.py module docstring must not say 'network operations'."""
        src = _MAIN_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
        ):
            docstring = tree.body[0].value.value
            assert isinstance(docstring, str)
            assert "network operations" not in docstring.lower(), (
                "main.py module docstring still mentions 'network operations'"
            )

    def test_main_no_network_operations_ai_assistant(self):
        """main.py must not contain 'Network Operations AI Assistant'."""
        src = _MAIN_PY.read_text(encoding="utf-8")
        assert "Network Operations AI Assistant" not in src, (
            "main.py still says 'Network Operations AI Assistant'"
        )

    def test_main_no_netops_examples(self):
        """main.py example queries must not mention devices/BGP."""
        src = _MAIN_PY.read_text(encoding="utf-8")
        for term in ["How many devices are in the network", "Analyze BGP neighbors"]:
            assert term not in src, f"main.py still has netops example: {term!r}"

    # ── agent.py ─────────────────────────────────────────────────────────

    def test_agent_system_prompt_no_network_operations(self):
        """Fallback system prompt must not say 'network operations'."""
        src = _AGENT_PY.read_text(encoding="utf-8")
        assert "network operations ai assistant" not in src.lower(), (
            "agent.py still has 'network operations ai assistant' in system prompt"
        )

    # ── index.html ───────────────────────────────────────────────────────

    def test_index_title_no_network(self):
        """HTML title must not say 'Network Operations'."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "Network Operations AI" not in src, (
            "index.html title still says 'Network Operations AI'"
        )

    def test_index_no_network_ai_heading(self):
        """index.html heading must not say 'Network AI'."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "OLAV Network AI" not in src, "index.html still has 'OLAV Network AI' heading"

    def test_index_no_topology_chip(self):
        """Quick-action chips must not mention topology."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "Topology overview" not in src, "index.html still has 'Topology overview' chip"

    def test_index_no_bgp_chip(self):
        """Quick-action chips must not mention BGP."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "BGP neighbor status" not in src, "index.html still has 'BGP neighbor status' chip"

    def test_index_no_ospf_chip(self):
        """Quick-action chips must not mention OSPF."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "OSPF neighbors" not in src, "index.html still has 'OSPF neighbors' chip"

    def test_index_no_devices_chip(self):
        """Quick-action chips must not say 'Show all devices'."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "Show all devices" not in src, "index.html still has 'Show all devices' chip"

    def test_index_placeholder_no_network(self):
        """Input placeholder must not mention 'network'."""
        src = _INDEX_HTML.read_text(encoding="utf-8")
        assert "about your network" not in src, (
            "index.html placeholder still says 'about your network'"
        )

    # ── guardrails.py (docstrings) ───────────────────────────────────────

    def test_guardrails_no_bgp_example(self):
        """guardrails.py docstring must not use 'show bgp' examples."""
        src = _GUARDRAILS_PY.read_text(encoding="utf-8")
        assert "show bgp" not in src.lower(), "guardrails.py still has 'show bgp' example"

    def test_guardrails_no_ospf_example(self):
        """guardrails.py docstring must not mention 'OSPF'."""
        src = _GUARDRAILS_PY.read_text(encoding="utf-8")
        assert "OSPF" not in src, "guardrails.py still mentions OSPF"

    def test_guardrails_no_show_interfaces_brief(self):
        """guardrails.py must not mention 'show interfaces brief'."""
        src = _GUARDRAILS_PY.read_text(encoding="utf-8")
        assert "show interfaces brief" not in src, (
            "guardrails.py still has 'show interfaces brief' example"
        )

    # ── memory/__init__.py ───────────────────────────────────────────────

    def test_memory_no_store_network_event_function(self):
        """store_network_event must be renamed to store_event."""
        src = _MEMORY_INIT_PY.read_text(encoding="utf-8")
        assert "def store_network_event(" not in src, (
            "memory/__init__.py still has store_network_event (should be store_event)"
        )

    def test_memory_store_event_exists(self):
        """store_event function must exist in memory module."""
        src = _MEMORY_INIT_PY.read_text(encoding="utf-8")
        assert "def store_event(" in src, "memory/__init__.py missing store_event function"

    def test_memory_no_bgp_flap_example(self):
        """memory docstrings must not mention BGP flaps."""
        src = _MEMORY_INIT_PY.read_text(encoding="utf-8")
        assert "BGP flap" not in src, "memory/__init__.py still has BGP flap example"

    def test_memory_no_ospf_adjacency_example(self):
        """memory docstrings must not mention OSPF adjacency."""
        src = _MEMORY_INIT_PY.read_text(encoding="utf-8")
        assert "OSPF adjacency" not in src, "memory/__init__.py still has OSPF adjacency example"

    # ── admin.py ─────────────────────────────────────────────────────────

    def test_admin_no_bgp_troubleshooting_example(self):
        """admin.py example must not mention BGP."""
        src = _ADMIN_DC2_PY.read_text(encoding="utf-8")
        assert "BGP troubleshooting" not in src, "admin.py still has 'BGP troubleshooting' example"

    # ── router.py ────────────────────────────────────────────────────────

    def test_router_no_device_data_reference(self):
        """router.py must not say 'querying device data, running commands'."""
        src = _ROUTER_PY.read_text(encoding="utf-8")
        assert "querying device data" not in src, "router.py still says 'querying device data'"

    def test_router_no_network_operations_routing(self):
        """router.py must not say 'Network operations, routing, topology'."""
        src = _ROUTER_PY.read_text(encoding="utf-8")
        assert "Network operations, routing, topology" not in src, (
            "router.py still has netops-specific agent description"
        )

    # ── llm_sandbox.py ───────────────────────────────────────────────────

    def test_llm_sandbox_no_network_simulation(self):
        """llm_sandbox.py must not say '执行网络仿真' or mention Nornir."""
        src = _LLM_SANDBOX_PY.read_text(encoding="utf-8")
        assert "执行网络仿真" not in src, "llm_sandbox.py still says '执行网络仿真'"

    def test_llm_sandbox_no_nornir(self):
        """llm_sandbox.py must not mention Nornir."""
        src = _LLM_SANDBOX_PY.read_text(encoding="utf-8")
        assert "Nornir" not in src, "llm_sandbox.py still mentions Nornir"
