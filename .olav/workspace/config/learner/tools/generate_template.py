#!/usr/bin/env python3
"""
Tool 6: Generate Template (LLM-powered)

Generates TextFSM template using LLM with NTC references.
"""

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def test_template(template_content: str, output_sample: str) -> dict[str, Any]:
    """Test TextFSM template against actual output."""
    try:
        import io

        import textfsm

        # Parse template
        template_file = io.StringIO(template_content)
        fsm = textfsm.TextFSM(template_file)

        # Parse output
        parsed = fsm.ParseText(output_sample)

        # Calculate coverage
        output_lines = [line for line in output_sample.splitlines() if line.strip()]
        coverage = len(parsed) / max(len(output_lines), 1) if output_lines else 0.0

        return {
            "success": True,
            "parsed_records": len(parsed),
            "coverage": round(coverage, 2),
            "error": None
        }

    except Exception as e:
        return {
            "success": False,
            "parsed_records": 0,
            "coverage": 0.0,
            "error": str(e)
        }


@tool
def generate_template(
    command: str,
    platform: str,
    approved_fields: list[dict],
    output_sample: str,
    ntc_references: list[dict],
    max_iterations: int = 3
) -> dict[str, Any]:
    """Generate TextFSM template (LLM-powered).
    
    Args:
        command: Command to create template for
        platform: Device platform
        approved_fields: Fields from Step 3 (user-approved)
        output_sample: Actual command output for testing
        ntc_references: Top NTC templates from Step 4 (full content from read_template_file)
        max_iterations: Maximum generation attempts (default: 3)
    
    Returns:
        dict: {
            "template": str,  # TextFSM template content
            "filename": str,  # Suggested filename
            "test_result": dict,  # Template test result
            "iteration": int  # 1-3 attempts
        }
    
    LLM Prompt includes:
    - Approved fields
    - NTC reference templates (full content)
    - Output sample for testing
    - TextFSM best practices
    
    Example:
        >>> generate_template("show version", "cisco_ios", fields, output, [ntc_ref1, ntc_ref2])
        {"template": "Value VERSION (\\S+)\\n...", "filename": "cisco_ios_show_version.textfsm"}
    """
    from langchain_openai import ChatOpenAI

    from olav.core.config import (
        SKILL_BASE_PATH,
        settings,  # 确保 .env 被加载
    )

    # Load generation prompt (absolute path via config.paths — CWD-independent)
    prompt_path = SKILL_BASE_PATH / "command_learner" / "reference" / "textfsm_generation.md"
    if not prompt_path.exists():
        logger.warning(f"Generation prompt not found: {prompt_path}")
        generation_prompt = "Generate a TextFSM template for this network command output."
    else:
        generation_prompt = prompt_path.read_text()

    # Create LLM with explicit API key from settings
    llm_kwargs = {
        "model": settings.llm_model_name,
        "temperature": 0.2,  # Low temperature for code generation
        "timeout": 120,
    }
    if settings.llm_api_key:
        llm_kwargs["api_key"] = settings.llm_api_key
    if settings.llm_base_url:
        llm_kwargs["base_url"] = settings.llm_base_url

    llm = ChatOpenAI(**llm_kwargs)

    # Build user prompt
    fields_desc = "\n".join([
        f"- {field['name']} ({field['type']}): {field['example']} - {field['description']}"
        for field in approved_fields
    ])

    ntc_examples = "\n\n".join([
        f"### NTC Reference: {ref['template_name']}\n```\n{ref['content'][:1000]}...\n```"
        for ref in ntc_references[:2]  # Limit to top 2 to save tokens
    ]) if ntc_references else "No NTC references found."

    user_prompt = f"""
Generate a TextFSM template for:

**Command**: {command}
**Platform**: {platform}

**Fields to Extract (User-Approved)**:
{fields_desc}

**NTC Reference Templates** (for pattern examples):
{ntc_examples}

**Sample Output to Parse**:
```
{output_sample[:1500]}  # Truncate to save tokens
```

Requirements:
1. Extract ALL approved fields
2. Use regex patterns similar to NTC examples
3. Template must pass test against sample output
4. Follow TextFSM best practices
5. Return ONLY the template code (no explanations)

Return the template code directly.
"""

    # Iterative generation with testing
    for iteration in range(1, max_iterations + 1):
        try:
            logger.info(f"Generating template (iteration {iteration}/{max_iterations})...")

            # Call LLM
            messages = [
                {"role": "system", "content": generation_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = llm.invoke(messages)
            template_content = response.content.strip()

            # Remove markdown code blocks if present
            if "```" in template_content:
                lines = template_content.split("\n")
                template_lines = []
                in_code_block = False
                for line in lines:
                    if line.strip().startswith("```"):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block or not template_lines:
                        template_lines.append(line)
                template_content = "\n".join(template_lines)

            # Test template
            test_result = test_template(template_content, output_sample)

            # Generate filename
            # Example: cisco_ios_show_version.textfsm
            command_slug = command.lower().replace(" ", "_")
            filename = f"{platform}_{command_slug}.textfsm"

            # Check if successful
            if test_result["success"] and test_result["coverage"] >= 0.5:
                logger.info(f"✅ Template generated successfully (coverage: {test_result['coverage']})")
                return {
                    "template": template_content,
                    "filename": filename,
                    "test_result": test_result,
                    "iteration": iteration
                }
            else:
                logger.warning(f"❌ Template test failed (iteration {iteration}): {test_result.get('error', 'Low coverage')}")
                # Add error feedback for next iteration
                user_prompt += f"\n\n**Previous Attempt Failed**: {test_result.get('error', 'Low coverage')}. Please fix and try again."

        except Exception as e:
            logger.error(f"Template generation failed (iteration {iteration}): {e}")
            if iteration == max_iterations:
                return {
                    "template": None,
                    "filename": None,
                    "test_result": {"success": False, "error": str(e)},
                    "iteration": iteration
                }

    # All iterations failed
    return {
        "template": None,
        "filename": None,
        "test_result": {"success": False, "error": "Max iterations reached"},
        "iteration": max_iterations
    }
