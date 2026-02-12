"""SubAgent Dynamic Loader - Load SubAgent configurations from OLAV.md.

This module provides dynamic loading of SubAgent configurations from the
centralized OLAV.md configuration file.

Architecture (v0.10.1):
- .olav/OLAV.md: SubAgent registry (who + what capabilities)
- .olav/skills/*/SKILL.md: Detailed agent configuration (how + tools)
- Orchestrator: Dynamic loading and routing

Configuration Format (OLAV.md):
    ### agent_name
    ```yaml
    ---
    name: agent_name
    agent_skill: skill-name  # References .olav/skills/skill-name/
    description: Agent description
    capabilities: [list of capabilities]
    enabled: true
    ---
    ```

Usage:
    from olav.core.subagent_loader import load_subagents_from_olav

    subagents = load_subagents_from_olav()
    # Returns list[SubAgent] ready for Orchestrator
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from deepagents.middleware.subagents import SubAgent

from config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)


def _setup_llm_environment() -> None:
    """Setup LLM environment variables for SubAgent initialization."""
    import os
    from config.settings import settings
    
    if settings.llm_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.llm_api_key
    if settings.llm_base_url and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
    if (
        settings.llm_base_url
        and "openrouter" in settings.llm_base_url.lower()
        and not os.getenv("OPENAI_MODEL_NAME")
    ):
        os.environ["OPENAI_MODEL_NAME"] = settings.llm_model_name


def load_subagents_from_olav(
    olav_path: Path | None = None,
) -> list[SubAgent]:
    """Load SubAgent configurations from OLAV.md."""
    _setup_llm_environment()
    
    if olav_path is None:
        olav_path = Path(PROJECT_ROOT) / ".olav" / "OLAV.md"

    if not olav_path.exists():
        raise FileNotFoundError(f"OLAV.md not found: {olav_path}")

    content = olav_path.read_text(encoding="utf-8")

    # Extract SubAgent section
    subagent_section = _extract_subagent_section(content)
    if not subagent_section:
        raise ValueError("No SubAgent Registry section found in OLAV.md")

    # Parse individual SubAgent configs
    subagent_configs = _parse_subagent_configs(subagent_section)

    # Build SubAgent instances
    subagents = []
    for config in subagent_configs:
        if not config.get("enabled", True):
            logger.debug(f"Skipping disabled SubAgent: {config.get('name')}")
            continue  # Skip disabled SubAgents

        try:
            subagent = _build_subagent(config)
            # SubAgent() returns a dict, check for required 'name' key
            if isinstance(subagent, dict) and 'name' in subagent:
                subagents.append(subagent)
                logger.debug(f"✓ SubAgent '{subagent['name']}' loaded successfully")
            else:
                logger.error(
                    f"SubAgent '{config['name']}' creation failed: {type(subagent)}"
                )
                raise ValueError(
                    f"SubAgent() must return dict with 'name' key"
                )
        except Exception as e:
            logger.error(
                f"Failed to build SubAgent '{config.get('name', 'UNKNOWN')}': {e}"
            )
            raise

    return subagents


def _extract_subagent_section(content: str) -> str:
    """Extract ## SubAgent Registry section from OLAV.md."""
    # Simple approach: Find "## SubAgent Registry" and capture until next "##" heading
    start_pattern = r"## SubAgent Registry"
    end_pattern = r"\n## "

    start_match = re.search(start_pattern, content)
    if not start_match:
        return ""

    start_pos = start_match.end()

    # Find next "##" heading
    end_match = re.search(end_pattern, content[start_pos:])
    if end_match:
        end_pos = start_pos + end_match.start()
        return content[start_pos:end_pos]
    else:
        # No more ## headings, take rest of file
        return content[start_pos:]


def _parse_subagent_configs(section: str) -> list[dict[str, Any]]:
    """Parse individual SubAgent configurations from section.

    Format (v0.10.1 - Simplified Registry):
        ### agent_name
        ```yaml
        ---
        name: agent_name
        agent_skill: skill-name
        description: ...
        capabilities: [...]
        enabled: true
        ---
        ```
    """
    configs = []

    # Match ### agent_name followed by yaml block (no system_prompt inside)
    pattern = r"### (\w+)\s*\n```yaml\s*\n---\s*\n(.*?)\n---\s*\n\s*```"
    matches = re.finditer(pattern, section, re.DOTALL)

    for match in matches:
        agent_name = match.group(1)
        yaml_content = match.group(2)

        # Parse YAML frontmatter
        try:
            metadata = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML for SubAgent '{agent_name}': {e}") from e

        # Validate required fields
        if metadata.get("name") != agent_name:
            raise ValueError(
                f"SubAgent name mismatch: heading='{agent_name}', "
                f"yaml.name='{metadata.get('name')}'"
            )

        # Build config (system_prompt will be loaded from skill file)
        configs.append(
            {
                "name": agent_name,
                "agent_skill": metadata.get("agent_skill"),
                "description": metadata.get("description", ""),
                "capabilities": metadata.get("capabilities", []),
                "enabled": metadata.get("enabled", True),
            }
        )

    return configs


def _build_subagent(config: dict[str, Any]) -> SubAgent:
    """Build SubAgent instance from configuration."""
    agent_name = config.get("name", "UNKNOWN")
    
    try:
        skill_name = config.get("agent_skill")
        if not skill_name:
            raise ValueError(
                f"SubAgent '{agent_name}' missing required 'agent_skill' in OLAV.md"
            )

        system_prompt, tools = _load_from_skill(skill_name, agent_name)
        
        # Ensure tools is a list
        if tools is None:
            tools = []
        elif not isinstance(tools, list):
            try:
                tools = list(tools) if hasattr(tools, '__iter__') and not isinstance(tools, str) else []
            except (TypeError, ValueError):
                tools = []
        
        # Build model string for DeepAgents compatibility
        from config.settings import settings
        
        if settings.llm_provider == "openai" and settings.llm_base_url and "openrouter" in settings.llm_base_url:
            model_str = f"openai:{settings.llm_model_name}"
        elif settings.llm_provider == "ollama":
            model_str = f"ollama:{settings.llm_model_name}"
        else:
            model_str = f"openai:{settings.llm_model_name}"
        
        subagent = SubAgent(
            name=agent_name,
            description=config.get("description", ""),
            system_prompt=system_prompt,
            tools=tools,
            model=model_str,
            middleware=[],
        )
        
        return subagent
    
    except Exception as e:
        logger.error(f"Error building SubAgent '{agent_name}': {e}")
        raise


def _parse_skill_frontmatter(skill_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from SKILL.md file."""
    content = skill_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError("SKILL.md must start with ---")

    lines = content.split("\n")
    fm_start = fm_end = dashes = 0
    
    for i, line in enumerate(lines):
        if line.strip() == "---":
            dashes += 1
            if dashes == 1:
                fm_start = i
            elif dashes == 2:
                fm_end = i
                break
    
    if dashes < 2:
        raise ValueError("SKILL.md frontmatter not properly closed")

    yaml_lines = []
    for i in range(fm_start + 1, fm_end):
        line = lines[i]
        if line.strip().startswith("#") and not line.strip().startswith("#!"):
            break
        yaml_lines.append(line)

    yaml_content = "\n".join(yaml_lines)
    try:
        frontmatter = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in SKILL.md: {e}") from e

    if not isinstance(frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be valid YAML dict")
    
    return frontmatter


def _load_from_skill(skill_name: str, agent_name: str) -> tuple[str, list[Any]]:
    """Load system prompt and tools from agent's SKILL.md file."""
    from config.paths import PROJECT_ROOT

    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"

    if not skill_path.exists():
        raise FileNotFoundError(
            f"Required SKILL.md not found: {skill_path}\n"
            f"Create {skill_path} with prompts.system and tools"
        )

    try:
        frontmatter = _parse_skill_frontmatter(skill_path)

        # Extract prompts.system (REQUIRED)
        prompts = frontmatter.get("prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError("prompts must be dictionary in SKILL.md")

        system_prompt = prompts.get("system", "")
        if not system_prompt:
            raise ValueError(
                f"Skill '{skill_name}' missing prompts.system in SKILL.md"
            )

        # Resolve file path references
        if system_prompt and "\n" not in system_prompt and len(system_prompt) <= 200:
            prompt_file = Path.cwd() / system_prompt
            if prompt_file.exists():
                try:
                    system_prompt = prompt_file.read_text()
                except Exception as e:
                    logger.warning(f"Failed to load prompt file {prompt_file}: {e}")

        # Inject schema for database agents
        if agent_name in ("query", "cli"):
            system_prompt = _inject_schema_context(system_prompt)

        # Extract and resolve tools
        tool_defs = frontmatter.get("tools", [])
        resolved_tools = []
        for tool_def in tool_defs:
            try:
                resolved = _resolve_tool(tool_def, skill_name)
                if resolved:
                    resolved_tools.append(resolved)
            except Exception as e:
                logger.warning(
                    f"Failed to load tool '{tool_def}' in skill '{skill_name}': {e}"
                )

        return system_prompt, resolved_tools

    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(f"Error loading skill '{skill_name}': {e}") from e


def _resolve_tool(tool_def: Any, skill_name: str) -> Any | None:
    """Resolve a tool definition to an actual Tool object."""
    try:
        if isinstance(tool_def, str):
            return _load_tool_by_name(tool_def)
        elif isinstance(tool_def, dict):
            module_name = tool_def.get("module")
            function_name = tool_def.get("function")
            if module_name and function_name:
                return _load_tool_from_module(module_name, function_name)
        elif hasattr(tool_def, 'name') and hasattr(tool_def, 'func'):
            return tool_def
        
        logger.warning(f"Could not resolve tool in {skill_name}: {tool_def}")
        return None
    except Exception as e:
        logger.warning(f"Error resolving tool in {skill_name}: {e}")
        return None


def _load_tool_by_name(tool_name: str) -> Any | None:
    """Load a tool by name (deprecated - using convention-based resolution)."""
    logger.debug(f"Tool '{tool_name}' using convention-based resolution")
    return None


def _load_tool_from_module(module_name: str, function_name: str) -> Any | None:
    """Load a tool function from a module."""
    try:
        import importlib

        module = importlib.import_module(module_name)
        tool_func = getattr(module, function_name, None)
        if not tool_func:
            logger.warning(f"Function '{function_name}' not found in {module_name}")
            return None

        if hasattr(tool_func, 'name') and hasattr(tool_func, 'func'):
            return tool_func
        
        logger.warning(f"Function {function_name} in {module_name} is not a Tool object")
        return None
    except ImportError as e:
        logger.warning(f"Could not import {module_name}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error loading tool {function_name} from {module_name}: {e}")
        return None


def _inject_schema_context(prompt: str) -> str:
    """Inject current database schema into system prompt.

    This ensures the LLM knows exactly which tables/views exist,
    avoiding guesswork and unnecessary inspect_schema calls.
    """
    try:
        from olav.lib.data_gateway import get_gateway

        gw = get_gateway()

        # Get available views from snapshot database
        views = gw.query_snapshots(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'VIEW'"
        )
        view_list = ", ".join([v["table_name"] for v in views]) if views else ""

        # Get available tables from main database
        tables = gw.query_main(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
        table_list = ", ".join([t["table_name"] for t in tables]) if tables else ""

        # Get snapshot metadata (no schema prefix for standalone DB)
        meta = gw.query_snapshots(
            "SELECT snapshot_date, device_count "
            "FROM snapshot_metadata "
            "ORDER BY snapshot_date DESC LIMIT 1"
        )
        date_str = str(meta[0]["snapshot_date"]) if meta else "Unknown"
        devices = meta[0]["device_count"] if meta else 0

        context = "\n\n### Current Database Context (Auto-injected)\n"
        context += f"- **Latest Snapshot**: {date_str} ({devices} devices)\n"
        if view_list:
            context += f"- **Available Views**: {view_list}\n"
        if table_list:
            context += f"- **Available Tables (main.duckdb)**: {table_list}\n"
        context += (
            "Use these views/tables directly in SQL queries. "
            "Call inspect_schema('table_name') only if you need column details.\n"
        )

        return prompt + context

    except Exception as e:
        logger.debug(f"Schema injection failed (database may not be initialized): {e}")
        return prompt


def load_caching_config(skill_name: str) -> dict[str, Any]:
    """Load caching configuration from SKILL.md."""
    from config.paths import PROJECT_ROOT

    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found for skill '{skill_name}'")

    try:
        frontmatter = _parse_skill_frontmatter(skill_path)
        caching_config = frontmatter.get("caching", {})
        if not isinstance(caching_config, dict):
            raise ValueError("caching section must be dictionary")
        return caching_config
    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(f"Error loading caching config from '{skill_name}': {e}") from e


def load_skill_prompt(skill_name: str, prompt_field: str = "system") -> str:
    """Load prompt from skill SKILL.md file."""
    from config.paths import PROJECT_ROOT

    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found for skill '{skill_name}'")

    try:
        frontmatter = _parse_skill_frontmatter(skill_path)
        
        # Navigate to prompt field (supports nested fields like prompts.system)
        if "." in prompt_field:
            keys = prompt_field.split(".")
            value = frontmatter
            for key in keys:
                value = value.get(key) if isinstance(value, dict) else None
                if value is None:
                    break
            prompt = value
        else:
            prompt = frontmatter.get(prompt_field)
            if not prompt:
                prompts = frontmatter.get("prompts", {})
                prompt = prompts.get(prompt_field) if isinstance(prompts, dict) else None

        if not prompt:
            raise ValueError(f"Prompt field '{prompt_field}' not found")
        if not isinstance(prompt, str):
            raise ValueError(f"Prompt must be string, got {type(prompt).__name__}")

        return prompt

    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(f"Error loading prompt '{prompt_field}' from '{skill_name}': {e}") from e
