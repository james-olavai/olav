"""
Skill Adapter - Dynamic Tool Registration

This module provides the SkillAdapter class for loading tools from Skills
and converting them into LangChain Tool objects.

Convention: Each skill has a tools/ directory containing Python scripts.
SKILL.md references tools by name (string), resolved to skill_dir/tools/{name}.py

Supports platform-agnostic script-based tools.
"""

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool, Tool

if TYPE_CHECKING:
    from olav.core.skill_loader import Skill

logger = logging.getLogger(__name__)

# Default tool metadata for convention-based resolution
# Used when SKILL.md references tools as simple strings (e.g., "- query_database")
_TOOL_METADATA: dict[str, dict[str, Any]] = {
    "query_database": {
        "description": "Execute SQL queries against the network database",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query to execute"}
            },
            "required": ["sql"],
        },
    },
    "inspect_schema": {
        "description": "Inspect database schema - list tables or describe a specific table",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "Table name to describe (optional)"}
            },
            "required": [],
        },
    },
    "discover_data": {
        "description": "Discover available data in the network database",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern to filter tables (optional)"}
            },
            "required": [],
        },
    },
    "nornir_execute": {
        "description": "Execute a CLI command on a network device via Nornir",
        "parameters": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device name from inventory"},
                "command": {"type": "string", "description": "CLI command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
            },
            "required": ["device", "command"],
        },
    },
    "list_devices": {
        "description": "List network devices from Nornir inventory",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Filter by role (e.g., core, access)"},
                "site": {"type": "string", "description": "Filter by site"},
                "platform": {"type": "string", "description": "Filter by platform (e.g., cisco_ios)"},
            },
            "required": [],
        },
    },
}


class SkillAdapter:
    """OLAV platform's Skill adapter (unified script-based tools).

    Convention: SKILL.md lists tools as strings → resolved to skill_dir/tools/{name}.py
    """

    @staticmethod
    def load_tools_from_skill(skill: "Skill") -> list[Tool]:
        """Load tools from a Skill's tools/ directory.

        Resolution order for tool name "query_database":
        1. skill_dir/tools/query_database.py  (convention path)
        2. Raise error if not found

        Supports two formats in SKILL.md frontmatter:
        1. String: "query_database" → convention-based resolution
        2. Dict: {"name": "...", "script": "...", ...} → explicit path

        Args:
            skill: Skill object with frontmatter containing 'tools' field

        Returns:
            List of LangChain Tool objects
        """
        tools = []
        skill_file = Path(skill.file_path)
        skill_dir = skill_file.parent if skill_file.is_file() else Path(skill.file_path)

        for tool_item in skill.frontmatter.get("tools", []):
            if isinstance(tool_item, str):
                # Convention: resolve "query_database" → skill_dir/tools/query_database.py
                tool_def = SkillAdapter._resolve_string_tool(tool_item, skill_dir)
            elif isinstance(tool_item, dict):
                tool_def = tool_item
            else:
                logger.warning(f"Skipping invalid tool definition: {tool_item}")
                continue

            name = tool_def["name"]
            description = tool_def["description"]
            script_path = tool_def["script"]

            # Create the executor
            executor = SkillAdapter._create_executor(script_path, skill_dir)

            # Use StructuredTool for proper Schema support if parameters defined
            parameters = tool_def.get("parameters")
            if parameters and parameters.get("properties"):
                from pydantic import create_model

                properties = parameters.get("properties", {})
                required = parameters.get("required", [])

                # Build field definitions for create_model
                # We use (type, default) or (type, ...) for required
                fields = {}
                for prop_name, prop_def in properties.items():
                    prop_type = Any  # Default
                    t = prop_def.get("type")
                    if t == "string":
                        prop_type = str
                    elif t == "integer":
                        prop_type = int
                    elif t == "boolean":
                        prop_type = bool
                    elif t == "array":
                        prop_type = list
                    elif t == "object":
                        prop_type = dict

                    default_val = ... if prop_name in required else None
                    fields[prop_name] = (prop_type, default_val)

                # Create dynamic Pydantic model for schema enforcement
                args_model = create_model(f"{name}Args", **fields)

                tools.append(
                    StructuredTool.from_function(
                        func=executor, name=name, description=description, args_schema=args_model
                    )
                )
            else:
                # Fallback to standard Tool
                tools.append(
                    Tool(
                        name=name,
                        description=description,
                        func=executor,
                    )
                )

        return tools

    @staticmethod
    def _resolve_string_tool(tool_name: str, skill_dir: Path) -> dict[str, Any]:
        """Resolve a string tool reference to a full tool definition.

        Convention: "query_database" → skill_dir/tools/query_database.py

        Args:
            tool_name: Tool name string (e.g., "query_database")
            skill_dir: Path to the skill directory

        Returns:
            Full tool definition dict with name, description, script, parameters

        Raises:
            FileNotFoundError: If tool script not found in skill_dir/tools/
        """
        script_path = skill_dir / "tools" / f"{tool_name}.py"

        if not script_path.exists():
            raise FileNotFoundError(
                f"Tool script not found: {script_path}\n"
                f"Expected: {skill_dir}/tools/{tool_name}.py\n"
                f"Hint: Create the script or check SKILL.md tool references."
            )

        # Get metadata from registry, or use defaults
        metadata = _TOOL_METADATA.get(tool_name, {})
        description = metadata.get("description", f"Tool: {tool_name}")
        parameters = metadata.get("parameters")

        tool_def: dict[str, Any] = {
            "name": tool_name,
            "description": description,
            "script": str(script_path),
        }
        if parameters:
            tool_def["parameters"] = parameters

        logger.debug(f"Resolved tool '{tool_name}' → {script_path}")
        return tool_def

    @staticmethod
    def _create_executor(script_path: str, skill_dir: Path | None = None) -> Callable:
        """Create script executor function

        Args:
            script_path: Path to the script (e.g., '.olav/scripts/query_database.py' or 'scripts/query_database.py')
            skill_dir: Skill directory path (for resolving relative scripts/ paths)

        Returns:
            Callable function that executes the script
        """

        def executor(
            arg: str | dict[str, Any] | None = None,
            **kwargs: Any,  # noqa: ANN401
        ) -> dict[str, Any]:
            """Execute script with strict parameter passing.

            Args:
                arg: Single positional argument (if called by LangChain)
                **kwargs: Parameters passed from the Agent (should match SKILL.md schema)

            Returns:
                Script output as dict
            """
            # Strict mode: parameters are passed as kwargs.
            # If LangChain passes a single 'arg' (common for simple Tools),
            # we don't try to guess its name unless we have to.
            # With proper SKILL.md schemas, ReAct agents will pass named kwargs.

            params = kwargs.copy()
            if arg:
                if isinstance(arg, dict):
                    params.update(arg)
                else:
                    # Fallback for simple tools that might still pass a single string
                    params["__arg1"] = arg

            # Resolve script path
            project_root = Path.cwd()
            full_script_path = project_root / script_path

            # Handle relative scripts/ paths within skill directory
            if skill_dir and not Path(script_path).is_absolute():
                # Check if this is a relative path like "scripts/query_database.py"
                if script_path.startswith("scripts/"):
                    # Resolve relative to skill directory
                    full_script_path = skill_dir / script_path
                    if not full_script_path.exists():
                        raise RuntimeError(f"Script not found: {full_script_path}")
                elif not full_script_path.exists():
                    # Try resolving from skill directory as fallback
                    full_script_path = skill_dir / script_path

            if not full_script_path.exists():
                raise RuntimeError(f"Script not found: {full_script_path}")

            # 1. Attempt Native Execution (In-Process) if it's a Python script
            if str(full_script_path).endswith(".py"):
                try:
                    import importlib.util

                    # Use a unique module name for the script
                    module_name = f"olav.tools.{full_script_path.stem}"

                    # Always reload to pick up changes (no stale cache)
                    if module_name in sys.modules:
                        del sys.modules[module_name]

                    spec = importlib.util.spec_from_file_location(
                        module_name, str(full_script_path)
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)
                    else:
                        module = None

                    if module and hasattr(module, "main"):
                        # Call the main function directly
                        result = module.main(params)
                        if isinstance(result, dict):
                            return result
                        else:
                            # Heuristic: if it's not a dict, wrap it
                            return {"status": "success", "result": result}
                except Exception as e:
                    # Log failure and fall back to subprocess
                    print(f"DEBUG: Native execution failed for {script_path}: {e}, falling back...")

            # 2. Fallback to Subprocess Execution
            try:
                input_data = json.dumps(params)
                result = subprocess.run(  # noqa: S603, S607
                    ["uv", "run", "python3", str(full_script_path)],  # noqa: S607
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=project_root,
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip()
                    if not error_msg and result.stdout:
                        # Sometimes errors are printed to stdout as JSON
                        try:
                            error_json = json.loads(result.stdout)
                            if "error" in error_json:
                                error_msg = error_json["error"]
                            else:
                                error_msg = result.stdout.strip()
                        except json.JSONDecodeError:
                            error_msg = result.stdout.strip()

                    if not error_msg:
                        error_msg = f"Exit code {result.returncode}"

                    raise RuntimeError(f"Script failed: {error_msg}")

                return json.loads(result.stdout)

            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"Script timeout after 30s: {script_path}") from e
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON output from script: {result.stdout}") from e
            except Exception as e:
                raise RuntimeError(f"Script execution error: {str(e)}") from e

        return executor
