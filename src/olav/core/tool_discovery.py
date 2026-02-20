"""Tool Discovery - Auto-discover @tool decorated functions.

This replaces manual tool_specs with automatic LangChain discovery.
Keeps SKILL.md as documentation/validation, not loading mechanism.

Philosophy: Use LangChain native features, avoid over-engineering.
"""

import importlib
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def discover_tools(
    tools_path: Path,
    modules: list[str] | None = None
) -> list[BaseTool]:
    """Auto-discover all @tool decorated functions.

    This is the SIMPLE, LangChain-native way:
    - Import modules from tools directory
    - Find all @tool decorated functions
    - Return them as a list
    
    No hardcoding, no tool_specs, just pure LangChain.

    Args:
        tools_path: Path to tools directory (.olav/tools/)
        modules: Optional list of module names to load
                (if None, loads from tools_path directory)

    Returns:
        List of discovered BaseTool objects

    Example:
        >>> tools = discover_tools(Path(".olav/tools"))
        >>> tools  # [execute_sql, execute_cli, ...]
    """
    discovered_tools = []

    if not tools_path.exists():
        logger.warning(f"Tools directory not found: {tools_path}")
        return discovered_tools

    # If no modules specified, discover from directory
    if modules is None:
        modules = _discover_modules_from_dir(tools_path)

    # Add tools_path to sys.path for imports
    import sys
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))

    # Deduplicate by tool name (aliases create multiple names for same object)
    seen_names: set[str] = set()

    # Load each module and extract @tool functions
    for module_name in modules:
        try:
            # Import module via file path to avoid sys.modules collision between
            # tools from different skill directories that share the same filename
            py_file = tools_path / f"{module_name}.py"
            spec = importlib.util.spec_from_file_location(
                f"_olav_tool_{tools_path.name}_{module_name}", py_file
            )
            if spec is None:
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except ImportError as e:
                if "attempted relative import" in str(e):
                    logger.debug(f"Skipping relative imports in {module_name}")
                    continue
                raise

            # Find all @tool decorated functions; skip aliases (same name already seen)
            for name, obj in inspect.getmembers(module):
                if isinstance(obj, BaseTool):
                    if obj.name not in seen_names:
                        seen_names.add(obj.name)
                        discovered_tools.append(obj)
                        logger.debug(f"✓ tool: {obj.name} from {module_name}")
                    else:
                        logger.debug(f"  skip alias: {obj.name} (already loaded)")

        except ImportError as e:
            logger.debug(f"Could not import '{module_name}': {e}")
        except Exception as e:
            logger.error(f"Error discovering tools in '{module_name}': {e}")

    logger.info(f"✓ Discovered {len(discovered_tools)} tools")
    return discovered_tools


def _discover_modules_from_dir(tools_path: Path) -> list[str]:
    """Discover Python modules in tools directory.

    Simple approach: find all .py files, exclude __pycache__ and special files.

    Args:
        tools_path: Path to tools directory

    Returns:
        List of module names (without .py extension)
    """
    modules = []

    for py_file in tools_path.glob("*.py"):
        if py_file.name.startswith("_"):  # Skip __init__, __pycache__, etc
            continue

        module_name = py_file.stem
        modules.append(module_name)
        logger.debug(f"Found module: {module_name}")

    return modules


def validate_tools_against_skill(
    tools: list[BaseTool],
    skill_config: dict[str, Any]
) -> dict[str, Any]:
    """Validate discovered tools against SKILL.md tool list.

    This is where SKILL.md comes in - for validation and documentation.
    But the ACTUAL loading is done by LangChain discovery above.

    Args:
        tools: Discovered tools
        skill_config: Parsed SKILL.md frontmatter (should have 'tools' key)

    Returns:
        Validation report:
        {
            "valid": bool,
            "discovered": [tool names],
            "documented": [tool names from SKILL.md],
            "missing": [undocumented tools],
            "extra": [documented but not discovered]
        }
    """
    discovered_names = {tool.name for tool in tools}
    documented_names = set(skill_config.get("tools", []))

    missing = discovered_names - documented_names
    extra = documented_names - discovered_names
    valid = len(missing) == 0 and len(extra) == 0

    report = {
        "valid": valid,
        "discovered": sorted(list(discovered_names)),
        "documented": sorted(list(documented_names)),
        "missing": sorted(list(missing)) if missing else None,
        "extra": sorted(list(extra)) if extra else None,
    }

    if not valid:
        logger.warning(
            f"Tool validation failed:\n"
            f"  Missing from SKILL.md: {missing or 'None'}\n"
            f"  Extra in SKILL.md: {extra or 'None'}"
        )

    return report


# Example usage (commented out, for documentation)
"""
# OLD WAY (OVER-ENGINEERED):
tool_specs = [
    ("execute_sql", "database"),
    ("execute_cli", "network"),
]
for tool_name, module_name in tool_specs:
    module = __import__(module_name)
    tool = getattr(module, tool_name)
    tools.append(tool)

# NEW WAY (SIMPLE, LANGCHAIN-NATIVE):
from tool_discovery import discover_tools

tools = discover_tools(Path(".olav/tools"))
# Done! No hardcoding, LangChain handles everything.
"""
