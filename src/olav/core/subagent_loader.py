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


def load_subagents_from_olav(
    olav_path: Path | None = None,
) -> list[SubAgent]:
    """Load SubAgent configurations from OLAV.md.

    Args:
        olav_path: Path to OLAV.md (default: .olav/OLAV.md)

    Returns:
        List of SubAgent configurations

    Raises:
        FileNotFoundError: If OLAV.md not found
        ValueError: If configuration parsing fails
    """
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
            continue  # Skip disabled SubAgents

        subagent = _build_subagent(config)
        subagents.append(subagent)

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
    """Build SubAgent instance from configuration.

    Args:
        config: Parsed SubAgent configuration from OLAV.md

    Returns:
        SubAgent instance ready for Orchestrator

    Note:
        System prompt and tools are loaded from the agent's SKILL.md file.
        agent_skill is required in OLAV.md configuration.
    """
    # ENFORCE: agent_skill is mandatory (no fallback)
    skill_name = config.get("agent_skill")
    if not skill_name:
        raise ValueError(
            f"SubAgent '{config['name']}' missing required 'agent_skill' in OLAV.md. "
            f"Example: agent_skill: network-query"
        )

    # Load from skill (no fallback)
    system_prompt, tools = _load_from_skill(skill_name, config["name"])

    return SubAgent(
        name=config["name"],
        description=config["description"],
        system_prompt=system_prompt,
        tools=tools,
    )


def _load_from_skill(skill_name: str, agent_name: str) -> tuple[str, list[Any]]:
    """Load system prompt and tools from agent's SKILL.md file.

    SKILL.md is skill-centric source of truth at .olav/skills/{skill_name}/SKILL.md

    Args:
        skill_name: Skill directory name (e.g., "network-query")
        agent_name: Agent name for logging

    Returns:
        Tuple of (system_prompt, tools_list)
    """
    import yaml

    from config.paths import PROJECT_ROOT

    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"

    if not skill_path.exists():
        raise FileNotFoundError(
            f"Required SKILL.md not found: {skill_path}\n"
            f"Create {skill_path} with prompts.system and tools"
        )

    try:
        # Read SKILL.md file
        content = skill_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise ValueError("SKILL.md must start with --- for frontmatter")

        # Parse frontmatter: lines between first --- and second ---
        lines = content.split("\n")
        fm_start = 0
        fm_end = 0
        dashes = 0

        for i, line in enumerate(lines):
            if line.strip() == "---":
                dashes += 1
                if dashes == 1:
                    fm_start = i
                elif dashes == 2:
                    fm_end = i
                    break

        if dashes < 2:
            raise ValueError("SKILL.md frontmatter not properly closed (missing second ---)")

        # Extract YAML lines, stopping at markdown headers (##)
        # This handles SKILL.md files with embedded markdown documentation
        yaml_lines = []
        for i in range(fm_start + 1, fm_end):
            line = lines[i]
            # Stop if we hit markdown headers (but not shebang #!)
            if line.strip().startswith("#") and not line.strip().startswith("#!"):
                break
            yaml_lines.append(line)

        # Parse YAML frontmatter
        yaml_content = "\n".join(yaml_lines)
        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in SKILL.md frontmatter: {e}")

        if not isinstance(frontmatter, dict):
            raise ValueError("SKILL.md frontmatter must be valid YAML dict")

        # Extract prompts.system (REQUIRED)
        prompts = frontmatter.get("prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError("prompts must be dictionary in SKILL.md")

        system_prompt = prompts.get("system", "")

        if not system_prompt:
            raise ValueError(
                f"Skill '{skill_name}' missing prompts.system in SKILL.md\n"
                f"Add to frontmatter: prompts:\n  system: |\n    Your prompt here"
            )

        # Resolve file path references
        if system_prompt and "\n" not in system_prompt and len(system_prompt) <= 200:
            prompt_file = Path.cwd() / system_prompt
            if prompt_file.exists():
                try:
                    system_prompt = prompt_file.read_text()
                    logger.info(f"Loaded system prompt from file: {prompt_file}")
                except Exception as e:
                    logger.warning(f"Failed to load prompt file {prompt_file}: {e}")

        # Inject schema for database agents
        if agent_name in ("query", "cli"):
            system_prompt = _inject_schema_context(system_prompt)

        # Extract tools (optional)
        tools = frontmatter.get("tools", {})

        if not tools:
            logger.warning(f"Skill '{skill_name}' has no tools configured")

        logger.info(
            f"Loaded skill '{skill_name}' for agent '{agent_name}': "
            f"prompt={len(system_prompt)} chars, tools={len(tools) if isinstance(tools, dict) else tools}"
        )

        return system_prompt, tools

    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(f"Error loading skill '{skill_name}': {e}") from e


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
    """Load caching configuration from SKILL.md.

    Phase 3: Consolidate caching configuration into SKILL.md.

    Args:
        skill_name: Skill directory name (e.g., "network-cli")

    Returns:
        Dictionary with caching configuration from SKILL.md 'caching' section

    Raises:
        FileNotFoundError: If SKILL.md not found
        ValueError: If 'caching' section not found or invalid

    Examples:
        # Load caching config for network-cli
        cache_cfg = load_caching_config("network-cli")
        if cache_cfg.get("enabled"):
            ttl = cache_cfg.get("default_ttl_seconds", 3600)
            print(f"Cache enabled with TTL: {ttl}s")
    """
    import yaml

    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"

    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found for skill '{skill_name}' at {skill_path}")

    try:
        # Read SKILL.md file
        content = skill_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise ValueError("SKILL.md must start with --- for frontmatter")

        # Parse frontmatter boundaries
        lines = content.split("\n")
        fm_start = 0
        fm_end = 0
        dashes = 0

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

        # Extract YAML lines, stopping at markdown headers
        yaml_lines = []
        for i in range(fm_start + 1, fm_end):
            line = lines[i]
            if line.strip().startswith("#") and not line.strip().startswith("#!"):
                break
            yaml_lines.append(line)

        # Parse YAML frontmatter
        yaml_content = "\n".join(yaml_lines)
        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in SKILL.md: {e}")

        # Extract caching config (optional)
        caching_config = frontmatter.get("caching", {})

        if not isinstance(caching_config, dict):
            raise ValueError("caching section in SKILL.md must be dictionary")

        logger.info(
            f"Loaded caching config from '{skill_name}': "
            f"enabled={caching_config.get('enabled', False)}, "
            f"ttl={caching_config.get('default_ttl_seconds', 'N/A')}s"
        )

        return caching_config

    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(f"Error loading caching config from skill '{skill_name}': {e}") from e


def load_skill_prompt(skill_name: str, prompt_field: str = "system") -> str:
    """Load prompt from skill SKILL.md file.

    Phase 2: Consolidate hardcoded prompts into SKILL.md.
    This function loads prompts from SKILL.md frontmatter for agents
    that are not loaded via SubAgent (e.g., Analyzer, TextFSM).

    Args:
        skill_name: Skill directory name (e.g., "network-analysis")
        prompt_field: Which prompt to load (system, generation, analysis, etc.)

    Returns:
        Prompt string from SKILL.md

    Raises:
        FileNotFoundError: If SKILL.md not found
        ValueError: If prompt_field not found in SKILL.md

    Examples:
        # Load system prompt for analyzer
        system_prompt = load_skill_prompt("network-analysis", "system")

        # Load generation prompt for textfsm
        gen_prompt = load_skill_prompt("textfsm-generator", "generation")
    """
    import yaml

    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"

    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found for skill '{skill_name}' at {skill_path}")

    try:
        # Read SKILL.md file
        content = skill_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise ValueError("SKILL.md must start with --- for frontmatter")

        # Parse frontmatter boundaries
        lines = content.split("\n")
        fm_start = 0
        fm_end = 0
        dashes = 0

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

        # Extract YAML lines, stopping at markdown headers
        yaml_lines = []
        for i in range(fm_start + 1, fm_end):
            line = lines[i]
            if line.strip().startswith("#") and not line.strip().startswith("#!"):
                break
            yaml_lines.append(line)

        # Parse YAML frontmatter
        yaml_content = "\n".join(yaml_lines)
        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in SKILL.md: {e}")

        # Navigate to prompt field (supports nested fields like prompts.system)
        if "." in prompt_field:
            # Handle nested access like "prompts.system"
            keys = prompt_field.split(".")
            value = frontmatter
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    value = None
                if value is None:
                    break
            prompt = value
        else:
            # Direct field access
            prompt = frontmatter.get(prompt_field)

        # Special case: if prompt_field is simple name and not found,
        # try nested "prompts" structure
        if not prompt and "." not in prompt_field:
            prompts = frontmatter.get("prompts", {})
            if isinstance(prompts, dict):
                prompt = prompts.get(prompt_field)

        if not prompt:
            raise ValueError(
                f"Prompt field '{prompt_field}' not found in {skill_name}/SKILL.md. "
                f"Available fields: {list(frontmatter.keys())}"
            )

        if not isinstance(prompt, str):
            raise ValueError(
                f"Prompt field '{prompt_field}' must be string, got {type(prompt).__name__}"
            )

        logger.info(
            f"Loaded prompt '{prompt_field}' from skill '{skill_name}' ({len(prompt)} chars)"
        )
        return prompt

    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(
            f"Error loading prompt '{prompt_field}' from skill '{skill_name}': {e}"
        ) from e
