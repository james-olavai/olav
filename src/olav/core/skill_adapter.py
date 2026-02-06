"""
Skill Adapter - Dynamic Tool Registration

This module provides the SkillAdapter class for loading tools from Skills
and converting them into LangChain Tool objects.

Supports platform-agnostic script-based tools.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool, Tool

if TYPE_CHECKING:
    from olav.core.skill_loader import Skill


class SkillAdapter:
    """OLAV platform's Skill adapter (unified script-based tools)"""

    @staticmethod
    def load_tools_from_skill(skill: "Skill") -> list[Tool]:
        """Load tools from a Skill using native AgentSkills schemas.

        Args:
            skill: Skill object with frontmatter containing 'tools' field

        Returns:
            List of LangChain Tool objects
        """
        tools = []

        for tool_def in skill.frontmatter.get("tools", []):
            script_path = tool_def["script"]
            name = tool_def["name"]
            description = tool_def["description"]

            # Get skill directory for relative path resolution
            skill_file = Path(skill.file_path)
            skill_dir = skill_file.parent if skill_file.is_file() else Path(skill.file_path)

            # Create the executor
            executor = SkillAdapter._create_executor(script_path, skill_dir)

            # Use StructuredTool for proper Schema support
            # This prevents parameter hallucination (e.g., passing 'hostname' instead of 'device')
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
