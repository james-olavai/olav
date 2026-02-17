#!/usr/bin/env python3
"""
Tool 2: Analyze Output (LLM-powered field detection)

Uses LLM to analyze command output and identify extractable fields.
"""

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def analyze_output(command: str, output: str, platform: str) -> dict[str, Any]:
    """Analyze command output and identify fields (LLM-powered).
    
    Args:
        command: Original command executed
        output: Raw command output
        platform: Device platform (e.g., cisco_ios)
    
    Returns:
        dict: {
            "fields": list[dict],  # [{"name": str, "type": str, "example": str, "description": str}]
            "coverage_estimate": float,  # 0.0-1.0
            "structure": str  # "tabular", "key-value", "mixed"
        }
    
    Example:
        >>> analyze_output("show ip bgp summary", output, "cisco_ios")
        {"fields": [{"name": "router_id", "type": "string", ...}], "coverage_estimate": 0.85}
    """
    from config.settings import settings  # 确保 .env 被加载
    from langchain_openai import ChatOpenAI
    from pathlib import Path
    
    # Load analysis prompt
    prompt_path = Path(".olav/skills/command_learner/reference/textfsm_analysis.md")
    if not prompt_path.exists():
        logger.warning(f"Analysis prompt not found: {prompt_path}")
        analysis_prompt = "Analyze this network command output and identify all extractable fields."
    else:
        analysis_prompt = prompt_path.read_text()
    
    # Create LLM with explicit API key from settings
    llm_kwargs = {
        "model": settings.llm_model_name,
        "temperature": 0.1,  # Low temperature for analysis
        "timeout": 60,
    }
    if settings.llm_api_key:
        llm_kwargs["api_key"] = settings.llm_api_key
    if settings.llm_base_url:
        llm_kwargs["base_url"] = settings.llm_base_url
    
    llm = ChatOpenAI(**llm_kwargs)
    
    # Build analysis request
    user_prompt = f"""
Command: {command}
Platform: {platform}

Output:
```
{output[:2000]}  # Truncate to first 2000 chars
```

Analyze this output and identify all extractable fields. For each field, provide:
1. name (lowercase_with_underscores)
2. type (string, int, float, ipv4, ipv6, mac_address, etc.)
3. example (actual value from output)
4. description (brief explanation)

Also estimate:
- coverage_estimate (0.0-1.0): How much of the output can be parsed
- structure: "tabular", "key-value", or "mixed"

Return JSON format:
{{
    "fields": [
        {{"name": "field_name", "type": "string", "example": "value", "description": "..."}}
    ],
    "coverage_estimate": 0.85,
    "structure": "tabular"
}}
"""
    
    try:
        # Call LLM
        messages = [
            {"role": "system", "content": analysis_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = llm.invoke(messages)
        
        # Parse JSON response
        import json
        result = json.loads(response.content)
        
        logger.info(f"Analyzed output: {len(result.get('fields', []))} fields detected")
        return result
        
    except Exception as e:
        logger.error(f"Failed to analyze output: {e}")
        # Return fallback
        return {
            "fields": [],
            "coverage_estimate": 0.0,
            "structure": "unknown",
            "error": str(e)
        }
