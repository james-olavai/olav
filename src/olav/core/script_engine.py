"""Script Execution Engine for OLAV v0.9.

This module provides the ability to execute scripts defined in Skill files,
enabling "Skill-as-a-Tool" functionality. Scripts can be written in bash or
Python and are dynamically loaded into LangChain Tools.

Roadmap: Task 12.1-12.3 - Universal Compatibility (Script Engine)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


# =============================================================================
# Script Parser
# =============================================================================


class ScriptMetadata:
    """Metadata extracted from a Skill file.

    Attributes:
        name: Skill name
        description: Skill description
        runtime: Script runtime (bash, python)
        script: Script code to execute
        input_schema: Input parameter schema (optional)
        output_schema: Output format schema (optional)
        version: Skill version
    """

    def __init__(
        self,
        name: str,
        description: str,
        runtime: str,
        script: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        version: str = "1.0.0",
    ) -> None:
        self.name = name
        self.description = description
        self.runtime = runtime.lower()
        self.script = script
        self.input_schema = input_schema or {}
        self.output_schema = output_schema or {}
        self.version = version


def parse_skill_file(skill_path: Path) -> ScriptMetadata | None:
    """Parse a Skill file to extract script metadata.

    Args:
        skill_path: Path to SKILL.md file

    Returns:
        ScriptMetadata if script block found, None otherwise
    """
    if not skill_path.exists():
        return None

    content = skill_path.read_text(encoding="utf-8")

    # Extract YAML frontmatter
    frontmatter_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not frontmatter_match:
        return None

    frontmatter = frontmatter_match.group(1)

    # Parse basic metadata
    name = _extract_yaml_field(frontmatter, "name") or skill_path.parent.name
    description = _extract_yaml_field(frontmatter, "description") or ""
    version = _extract_yaml_field(frontmatter, "version") or "1.0.0"

    # Extract script block
    script_match = re.search(
        r"```script\n(.*?)\n```",
        content,
        re.DOTALL,
    )

    if not script_match:
        # No script block found
        return None

    script = script_match.group(1).strip()

    # Determine runtime from first line or default to bash
    runtime = "bash"
    first_line = script.split("\n")[0].strip()
    if first_line.startswith("#!"):
        if "python" in first_line.lower():
            runtime = "python"
        elif "bash" in first_line.lower() or "sh" in first_line.lower():
            runtime = "bash"

    # Extract input/output schemas (optional)
    input_schema = _extract_schema_block(content, "input")
    output_schema = _extract_schema_block(content, "output")

    return ScriptMetadata(
        name=name,
        description=description,
        runtime=runtime,
        script=script,
        input_schema=input_schema,
        output_schema=output_schema,
        version=version,
    )


def _extract_yaml_field(yaml_content: str, field: str) -> str | None:
    """Extract a field value from YAML content.

    Args:
        yaml_content: YAML content as string
        field: Field name to extract

    Returns:
        Field value or None if not found
    """
    match = re.search(rf"{field}:\s*(.+)", yaml_content)
    if match:
        value = match.group(1).strip()
        # Remove quotes if present
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        return value
    return None


def _extract_schema_block(content: str, block_name: str) -> dict[str, Any] | None:
    """Extract input or output schema block from skill file.

    Args:
        content: Skill file content
        block_name: Block name (input or output)

    Returns:
        Schema as dict or None if not found
    """
    # Look for ```input or ```output blocks
    pattern = rf"```{block_name}\n(.*?)\n```"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        return None

    block_content = match.group(1).strip()

    # Simple YAML-like parsing for key-value pairs
    schema: dict[str, Any] = {}
    for line in block_content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            schema[key.strip()] = value.strip()

    return schema if schema else None


# =============================================================================
# Script Executor
# =============================================================================


class ScriptExecutor:
    """Execute scripts in a controlled environment.

    Supports bash and Python runtimes with safety restrictions.
    """

    def execute_bash(self, script: str, **kwargs: str) -> str:
        """Execute a bash script.

        Args:
            script: Bash script code
            **kwargs: Variables to substitute in script

        Returns:
            Script output (stdout + stderr)
        """
        import subprocess

        # Substitute variables
        for key, value in kwargs.items():
            script = script.replace(f"${key}", str(value))
            script = script.replace(f"{{{key}}}", str(value))

        try:
            result = subprocess.run(  # noqa: S603
                ["bash", "-c", script],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            return output

        except subprocess.TimeoutExpired:
            return "Error: Script execution timeout (>30s)"
        except Exception as e:
            return f"Error: {e}"

    def execute_python(self, script: str, **kwargs: str) -> str:
        """Execute a Python script in a restricted environment.

        Args:
            script: Python script code
            **kwargs: Variables to inject into script namespace

        Returns:
            Script output (captured stdout)
        """
        import io
        from contextlib import redirect_stdout

        # Prepare restricted globals
        safe_globals = {
            "__builtins__": {
                "print": print,
                "range": range,
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "sum": sum,
                "max": max,
                "min": min,
                "abs": abs,
                "round": round,
                "enumerate": enumerate,
                "zip": zip,
                "sorted": sorted,
                "reversed": reversed,
            },
            **kwargs,
        }

        # Capture stdout
        output = io.StringIO()

        try:
            with redirect_stdout(output):
                exec(script, safe_globals, {})  # noqa: S102

            return output.getvalue()

        except Exception as e:
            return f"Error: {e}"

    def execute(self, metadata: ScriptMetadata, **kwargs: str) -> str:
        """Execute a script based on its runtime.

        Args:
            metadata: Script metadata
            **kwargs: Input parameters

        Returns:
            Script output
        """
        if metadata.runtime == "python":
            return self.execute_python(metadata.script, **kwargs)
        else:
            return self.execute_bash(metadata.script, **kwargs)


# =============================================================================
# Tool Factory
# =============================================================================


def create_script_tool(metadata: ScriptMetadata) -> StructuredTool:
    """Create a LangChain Tool from script metadata.

    Args:
        metadata: Script metadata

    Returns:
        LangChain StructuredTool
    """
    executor = ScriptExecutor()

    def run_script(**kwargs: str) -> str:
        """Execute the script with provided parameters."""
        return executor.execute(metadata, **kwargs)

    # Build args schema from input_schema
    args_schema: dict[str, Any] = {}
    if metadata.input_schema:
        # Convert simple schema to types
        type_map = {
            "string": str,
            "str": str,
            "integer": int,
            "int": int,
            "float": float,
            "boolean": bool,
            "bool": bool,
        }

        for key, value_type in metadata.input_schema.items():
            python_type = type_map.get(value_type.lower(), str)
            args_schema[key] = (python_type, ...)

    return StructuredTool.from_function(
        func=run_script,
        name=metadata.name.lower().replace(" ", "_").replace("-", "_"),
        description=metadata.description,
        args_schema=args_schema if args_schema else None,
    )


# =============================================================================
# Skill Loader
# =============================================================================


class SkillLoader:
    """Load skills from .olav/skills or .claude/ directories.

    Implements Alias Compatibility (Task 12.3):
    - Supports loading from .olav/skills (primary)
    - Falls back to .claude/skills if .olav/ not found
    """

    def __init__(self, agent_dir: Path | None = None) -> None:
        """Initialize the skill loader.

        Args:
            agent_dir: Path to agent directory (defaults to .agent)
        """
        if agent_dir is None:
            from config.settings import settings

            agent_dir = Path(settings.agent_dir)

        self.primary_dir = agent_dir / "skills"
        self.fallback_dir = agent_dir.parent / ".claude" / "skills"

    def load_all_skills(self) -> list[StructuredTool]:
        """Load all executable skills as tools.

        Returns:
            List of LangChain tools
        """
        tools = []

        # Try primary directory first
        skill_dirs = [self.primary_dir]
        if self.fallback_dir.exists():
            skill_dirs.append(self.fallback_dir)

        for skill_dir in skill_dirs:
            if not skill_dir.exists():
                continue

            for skill_file in skill_dir.glob("*/SKILL.md"):
                metadata = parse_skill_file(skill_file)
                if metadata:
                    try:
                        tool = create_script_tool(metadata)
                        tools.append(tool)
                        logger.info(f"Loaded skill: {metadata.name}")
                    except Exception as e:
                        logger.warning(f"Failed to load skill {skill_file}: {e}")

        return tools

    def load_skill(self, skill_name: str) -> StructuredTool | None:
        """Load a specific skill by name.

        Args:
            skill_name: Name of the skill to load

        Returns:
            LangChain tool or None if not found
        """
        # Try primary directory first
        for skill_dir in [self.primary_dir, self.fallback_dir]:
            skill_file = skill_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                metadata = parse_skill_file(skill_file)
                if metadata:
                    return create_script_tool(metadata)
        return None


# =============================================================================
# Convenience Functions
# =============================================================================


def get_script_tools() -> list[StructuredTool]:
    """Get all available script tools.

    Returns:
        List of LangChain tools from executable skills
    """
    loader = SkillLoader()
    return loader.load_all_skills()


def load_script_tool(skill_name: str) -> StructuredTool | None:
    """Load a specific script tool.

    Args:
        skill_name: Name of the skill

    Returns:
        LangChain tool or None if not found
    """
    loader = SkillLoader()
    return loader.load_skill(skill_name)


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    # Test script engine
    loader = SkillLoader()
    tools = loader.load_all_skills()

    print(f"Loaded {len(tools)} script tools")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description}")
