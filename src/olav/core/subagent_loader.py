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

import re
from pathlib import Path
from typing import Any

import yaml
from deepagents.middleware.subagents import SubAgent

from config.paths import PROJECT_ROOT


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
            raise ValueError(f"Invalid YAML for SubAgent '{agent_name}': {e}")
        
        # Validate required fields
        if metadata.get("name") != agent_name:
            raise ValueError(
                f"SubAgent name mismatch: heading='{agent_name}', "
                f"yaml.name='{metadata.get('name')}'"
            )
        
        # Build config (system_prompt will be loaded from skill file)
        configs.append({
            "name": agent_name,
            "agent_skill": metadata.get("agent_skill"),
            "description": metadata.get("description", ""),
            "capabilities": metadata.get("capabilities", []),
            "enabled": metadata.get("enabled", True),
        })
    
    return configs


def _build_subagent(config: dict[str, Any]) -> SubAgent:
    """Build SubAgent instance from configuration.
    
    Args:
        config: Parsed SubAgent configuration from OLAV.md
        
    Returns:
        SubAgent instance ready for Orchestrator
        
    Note:
        System prompt and tools are loaded from the agent's SKILL.md file
        referenced by config["agent_skill"].
    """
    # Load system prompt and tools from skill file
    skill_name = config.get("agent_skill")
    if skill_name:
        system_prompt, tools = _load_from_skill(skill_name, config["name"])
    else:
        # Fallback: use hardcoded logic
        system_prompt = _generate_default_prompt(config)
        tools = _resolve_legacy_tools(config["name"])
    
    return SubAgent(
        name=config["name"],
        description=config["description"],
        system_prompt=system_prompt,
        tools=tools,
    )


def _load_from_skill(skill_name: str, agent_name: str) -> tuple[str, list[Any]]:
    """Load system prompt and tools from agent's SKILL.md file.
    
    v0.10.1+: Also loads skill-level configuration (thresholds, command_mode, etc.)
    
    Args:
        skill_name: Skill directory name (e.g., "network-query")
        agent_name: Agent name for logging
        
    Returns:
        Tuple of (system_prompt, tools_list)
        
    Note:
        Skill-level configs are automatically loaded from skill/config/*.yaml
        and accessible via skill_loader.load_skill_config()
    """
    from config.paths import PROJECT_ROOT
    from olav.core.skill_loader import get_skill_loader
    
    skill_path = Path(PROJECT_ROOT) / ".olav" / "skills" / skill_name / "SKILL.md"
    
    if not skill_path.exists():
        # Fallback to hardcoded
        return _generate_default_prompt({"name": agent_name}), _resolve_legacy_tools(agent_name)
    
    try:
        # Load skill configuration
        loader = get_skill_loader()
        skill = loader.load_skill(skill_name)
        
        # Get system prompt from skill
        system_prompt = skill.get("system_prompt", "")
        if not system_prompt:
            # Use frontmatter description as fallback
            system_prompt = f"You are a {skill.get('description', 'specialist agent')}."
        
        # Get tools from skill or agent module
        tools = _resolve_agent_tools(agent_name)
        
        # v0.10.1: Load skill-level configs (automatic, cached by loader)
        # Configs are now accessible via loader.load_skill_config(skill_name, "config_name")
        # Examples:
        # - network-inspection/config/thresholds.yaml
        # - guard/config/command_mode.yaml
        # - textfsm-generator/config/textfsm/
        
        return system_prompt, tools
        
    except Exception as e:
        # Fallback
        return _generate_default_prompt({"name": agent_name}), _resolve_legacy_tools(agent_name)


def _generate_default_prompt(config: dict[str, Any]) -> str:
    """Generate default system prompt from config."""
    name = config.get("name", "agent")
    description = config.get("description", "specialist agent")
    capabilities = config.get("capabilities", [])
    
    prompt = f"You are a {description}.\n\n"
    
    if capabilities:
        prompt += "Your capabilities:\n"
        for cap in capabilities:
            prompt += f"- {cap}\n"
    
    return prompt.strip()


def _resolve_legacy_tools(agent_name: str) -> list[Any]:
    """Resolve tools using legacy module-based approach.
    
    Args:
        agent_name: Agent name (query, analysis, cli, expert)
        
    Returns:
        List of tool functions
    """
    # Map agent names to tool getter functions
    if agent_name == "query":
        from olav.tools.react_query import query_database, inspect_schema, discover_data
        return [query_database, inspect_schema, discover_data]
    
    elif agent_name == "analysis":
        # Use orchestrator's _get_analyzer_tools
        try:
            from olav.agents.orchestrator import _get_analyzer_tools
            return _get_analyzer_tools()
        except (ImportError, AttributeError):
            return []
    
    elif agent_name == "cli":
        # Reuse query tools for now
        from olav.tools.react_query import query_database, inspect_schema, discover_data
        return [query_database, inspect_schema, discover_data]
    
    elif agent_name == "expert":
        # Use orchestrator's _get_expert_tools
        try:
            from olav.agents.orchestrator import _get_expert_tools
            return _get_expert_tools()
        except (ImportError, AttributeError):
            return []
    
    return []


def _resolve_agent_tools(agent_name: str) -> list[Any]:
    """Resolve tools for agent from its module.
    
    Tries to call get_{agent_name}_tools() function from the agent's module.
    Falls back to _resolve_legacy_tools if not found.
    """
    try:
        # Try to import agent module and get tools
        if agent_name == "query":
            module = __import__("olav.agents.query_agent", fromlist=["get_query_tools"])
        elif agent_name == "analysis":
            module = __import__("olav.agents.analyzer", fromlist=["get_analyzer_tools"])
        elif agent_name == "expert":
            module = __import__("olav.agents.expert", fromlist=["get_expert_tools"])
        else:
            return _resolve_legacy_tools(agent_name)
        
        # Call get_{agent}_tools() function
        tools_func = getattr(module, f"get_{agent_name}_tools", None)
        if tools_func and callable(tools_func):
            return tools_func()
        
    except (ImportError, AttributeError):
        pass
    
    # Fallback
    return _resolve_legacy_tools(agent_name)
