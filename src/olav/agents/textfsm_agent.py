"""Template Developer Agent for TextFSM Generation.

This module implements a LangGraph-based agent that automatically
generates TextFSM templates for parsing network command outputs.

Architecture (v0.9.11):
- LangGraph State Machine with 3 nodes
- GenerateNode: Generate initial TextFSM template
- TestNode: Test template against sample outputs
- AnalyzeNode: Analyze failures and iterate

Roadmap: Task 7.1 - Implement Template Developer Graph
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.graph import END, StateGraph

from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================


@dataclass
class TextfsmState:
    """State for the Template Developer agent.

    Attributes:
        raw_output: Raw command output to parse
        command_name: Name of the command (e.g., "show ip bgp summary")
        platform: Device platform (e.g., "cisco_ios")
        sample_outputs: Additional sample outputs for testing
        template: Current TextFSM template
        test_results: Results from testing the template
        parse_results: Results from parsing with template
        iteration: Current iteration number
        max_iterations: Maximum iterations to attempt
        error_message: Error message if failed
        status: Current status
    """

    raw_output: str
    command_name: str
    platform: str
    sample_outputs: list[str] = field(default_factory=list)
    template: str = ""
    test_results: dict[str, Any] = field(default_factory=dict)
    parse_results: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 3
    error_message: str = ""
    status: Literal["start", "generating", "testing", "analyzing", "success", "failed"] = "start"


# =============================================================================
# LLM Initialization
# =============================================================================


def create_llm(model: str | None = None) -> BaseChatModel:
    """Create LLM for template generation.

    Args:
        model: Model name (None = use settings.agent.textfsm_model)

    Returns:
        ChatModel instance from LLMFactory (supports base_url)
    """
    from config.settings import settings

    if model is None:
        model = settings.agent.textfsm_model

    return LLMFactory.get_chat_model(temperature=0)


# =============================================================================
# Node Functions
# =============================================================================


async def generate_node(state: TextfsmState) -> TextfsmState:
    """Generate TextFSM template from raw output.

    Args:
        state: Current agent state

    Returns:
        Updated state
    """
    logger.info(f"Generating TextFSM template for {state.command_name}")

    state.status = "generating"
    state.iteration += 1

    llm = create_llm()

    # Build generation prompt
    prompt = _build_generation_prompt(
        state.raw_output, state.command_name, state.platform, state.parse_results
    )

    try:
        messages = [SystemMessage(content=prompt)]
        response = await llm.ainvoke(messages)

        # Extract template from response
        template = _extract_template(response.content)

        if template:
            state.template = template
            logger.info(f"Template generated (iteration {state.iteration})")
        else:
            state.error_message = "Failed to extract template from LLM response"
            state.status = "failed"  # Mark as failed so test_node won't proceed

    except Exception as e:
        state.error_message = f"Template generation failed: {e}"
        logger.error(state.error_message)
        state.status = "failed"  # Mark as failed so test_node won't proceed

    return state


async def test_node(state: TextfsmState) -> TextfsmState:
    """Test TextFSM template against sample outputs.

    Args:
        state: Current agent state

    Returns:
        Updated state
    """
    # Skip testing if generation failed
    if state.status == "failed" or not state.template:
        logger.info("Skipping test: generation failed or no template")
        return state

    logger.info("Testing TextFSM template")

    state.status = "testing"

    # Prepare test outputs
    test_outputs = [state.raw_output] + state.sample_outputs

    results = {"success": [], "failed": [], "total": len(test_outputs)}

    for i, output in enumerate(test_outputs):
        try:
            parsed = _test_template(state.template, output)
            if parsed:
                results["success"].append(i)
                state.parse_results.extend(parsed)
            else:
                results["failed"].append(i)
        except Exception as e:
            results["failed"].append(i)
            logger.debug(f"Test {i} failed: {e}")

    state.test_results = results

    # Determine success
    if results["total"] > 0:
        success_rate = len(results["success"]) / results["total"]
        if success_rate >= 0.8:  # 80% success rate threshold
            state.status = "success"
            logger.info(f"Template testing passed: {success_rate:.1%} success rate")
        else:
            logger.info(f"Template testing failed: {success_rate:.1%} success rate")
    else:
        logger.info("No test outputs available")

    return state


async def analyze_node(state: TextfsmState) -> TextfsmState:
    """Analyze test failures and provide feedback.

    Args:
        state: Current agent state

    Returns:
        Updated state
    """
    logger.info("Analyzing template failures")

    state.status = "analyzing"

    # Check if we should continue iterating
    if state.iteration >= state.max_iterations:
        state.status = "failed"
        state.error_message = f"Max iterations ({state.max_iterations}) reached"
        return state

    # Build analysis prompt
    llm = create_llm()
    prompt = _build_analysis_prompt(state.template, state.test_results, state.raw_output)

    try:
        messages = [SystemMessage(content=prompt)]
        response = await llm.ainvoke(messages)

        # Store analysis for next generation iteration
        state.error_message = f"Iteration {state.iteration}: {response.content[:200]}"
        logger.info(f"Analysis complete: {response.content[:100]}...")

        # Loop back to generate_node for next iteration
        # (LangGraph will handle this based on edge conditions)

    except Exception as e:
        state.error_message = f"Analysis failed: {e}"
        state.status = "failed"

    return state


# =============================================================================
# Helper Functions
# =============================================================================


def _build_generation_prompt(
    raw_output: str,
    command_name: str,
    platform: str,
    parse_results: list[dict[str, Any]] | None,
) -> str:
    """Build prompt for TextFSM template generation.

    Phase 2: Load base prompt from SKILL.md instead of hardcoding.

    Args:
        raw_output: Raw command output
        command_name: Name of the command
        platform: Device platform
        parse_results: Previous parse results (for refinement)

    Returns:
        Prompt string
    """
    # Phase 2: Load generation prompt from SKILL.md
    try:
        from olav.core.subagent_loader import load_skill_prompt

        base_prompt = load_skill_prompt("textfsm-generator", "generation")
    except Exception as e:
        logger.warning(f"Failed to load generation prompt from SKILL.md: {e}")
        # Fallback to simple prompt if SKILL.md not available
        base_prompt = "You are a TextFSM template expert for network command outputs."

    prompt = f"""{base_prompt}

Command: {command_name}
Platform: {platform}

Raw Output:
```
{raw_output[:2000]}
```
"""

    if parse_results:
        prompt += f"""

Previous Parse Results (for refinement):
{str(parse_results[:5])}

Improve the template based on what worked and what didn't.
"""

    return prompt


def _extract_template(content: str | list[Any]) -> str | None:
    """Extract TextFSM template from LLM response.

    Args:
        content: LLM response content (str or list)

    Returns:
        Extracted template or None
    """
    # Handle list content from LangChain
    if isinstance(content, list):
        # Extract string content from list
        content_str = ""
        for item in content:
            if isinstance(item, str):
                content_str += item
            elif isinstance(item, dict):
                # Handle dict items (e.g., {"type": "text", "text": "..."})
                if "text" in item:
                    content_str += item["text"]
        content = content_str
    elif not isinstance(content, str):
        return None
    # Remove markdown code blocks
    if "```" in content:
        # Extract content between triple backticks
        parts = content.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:  # Odd indices are code blocks
                # Remove language identifier if present
                lines = part.split("\n")
                if lines[0].lower() in ["textfsm", "template"]:
                    lines = lines[1:]
                template = "\n".join(lines).strip()
                if template:
                    return template

    # If no code blocks, try to extract the whole response
    content = content.strip()
    if "Value" in content and "Start" in content:
        return content

    return None


def _test_template(template: str, output: str) -> list[dict[str, Any]] | None:
    """Test TextFSM template against output.

    Args:
        template: TextFSM template
        output: Raw command output

    Returns:
        Parsed results or None if failed
    """
    import textfsm

    try:
        fsm = textfsm.TextFSM(template)
        return fsm.ParseText(output)
    except Exception:
        return None


def _build_analysis_prompt(template: str, test_results: dict[str, Any], raw_output: str) -> str:
    """Build prompt for failure analysis.

    Phase 2: Load analysis prompt from SKILL.md instead of hardcoding.

    Args:
        template: Current template
        test_results: Test results
        raw_output: Raw output

    Returns:
        Analysis prompt
    """
    # Phase 2: Load analysis prompt from SKILL.md
    try:
        from olav.core.subagent_loader import load_skill_prompt

        base_prompt = load_skill_prompt("textfsm-generator", "analysis")
    except Exception as e:
        logger.warning(f"Failed to load analysis prompt from SKILL.md: {e}")
        # Fallback to simple prompt if SKILL.md not available
        base_prompt = "Analyze why the TextFSM template failed and provide specific improvements."

    success_count = len(test_results.get("success", []))
    total_count = test_results.get("total", 1)

    prompt = f"""{base_prompt}

Current Template:
```
{template}
```

Test Results: {success_count}/{total_count} passed
"""

    return prompt


# =============================================================================
# Graph Creation
# =============================================================================


def create_textfsm_agent_graph() -> StateGraph:
    """Create the Template Developer agent graph.

    Returns:
        LangGraph StateGraph
    """
    workflow = StateGraph(TextfsmState)

    # Add nodes
    workflow.add_node("generate", generate_node)
    workflow.add_node("test", test_node)
    workflow.add_node("analyze", analyze_node)

    # Add edges
    workflow.set_entry_point("generate")

    # generate -> test
    workflow.add_edge("generate", "test")

    # test -> analyze (if failed)
    # test -> END (if success)
    def should_continue(state: TextfsmState) -> str:
        """Determine next step after testing."""
        if state.status == "success":
            return "end"
        elif state.iteration >= state.max_iterations:
            return "end"
        else:
            return "analyze"

    workflow.add_conditional_edges(
        "test",
        should_continue,
        {
            "analyze": "analyze",
            "end": END,
        },
    )

    # analyze -> generate (loop back)
    workflow.add_edge("analyze", "generate")

    return workflow


# =============================================================================
# Main API
# =============================================================================


async def generate_template(
    raw_output: str,
    command_name: str,
    platform: str = "cisco_ios",
    sample_outputs: list[str] | None = None,
    max_iterations: int = 3,
) -> dict[str, Any]:
    """Generate TextFSM template for command output.

    Args:
        raw_output: Sample raw command output
        command_name: Name of the command
        platform: Device platform
        sample_outputs: Additional sample outputs
        max_iterations: Maximum generation iterations

    Returns:
        Dictionary with:
            - template: Generated TextFSM template
            - status: "success" or "failed"
            - parse_results: Parsed data from successful tests
            - test_results: Test statistics
            - iterations: Number of iterations attempted
    """
    logger.info(f"Generating template for {command_name} on {platform}")

    # Initialize state
    state = TextfsmState(
        raw_output=raw_output,
        command_name=command_name,
        platform=platform,
        sample_outputs=sample_outputs or [],
        max_iterations=max_iterations,
    )

    # Create and run graph
    graph = create_textfsm_agent_graph()
    app = graph.compile()

    try:
        final_state = await app.ainvoke(state)

        return {
            "template": final_state.get("template", ""),
            "status": final_state.get("status", "failed"),
            "parse_results": final_state.get("parse_results", []),
            "test_results": final_state.get("test_results", {}),
            "iterations": final_state.get("iteration", 0),
            "error": final_state.get("error_message", ""),
        }

    except Exception as e:
        logger.error(f"Template generation failed: {e}")
        return {
            "template": "",
            "status": "failed",
            "parse_results": [],
            "test_results": {},
            "iterations": 0,
            "error": str(e),
        }


# =============================================================================
# CLI Integration
# =============================================================================


def create_textfsm_agent(model: str | None = None) -> Callable[[str, str, str], Awaitable[str]]:
    """Create a simple wrapper for backward compatibility.

    Args:
        model: LLM model name (None = use settings.agent.textfsm_model)

    Returns:
        Callable agent
    """
    from config.settings import settings

    if model is None:
        model = settings.agent.textfsm_model

    async def agent(raw_output: str, command: str, platform: str) -> str:
        """Generate template from command output."""
        result = await generate_template(raw_output, command, platform)

        if result["status"] == "success":
            return f"✅ Template generated successfully:\n\n{result['template']}"
        else:
            return f"❌ Template generation failed: {result.get('error', 'Unknown error')}"

    return agent


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import asyncio

    async def test() -> None:
        # Sample BGP output
        bgp_output = """
BGP router identifier 10.0.0.1, local AS number 65001
BGP table version is 15, main routing table version 15
10 network entries, 10 paths, 0 redundant paths
5 BGP paths, 0 available paths

        Neighbor        V          AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
        10.0.0.2         4   65001   12345   12346       15    0    0 01:23:45 123456
        10.0.0.3         4   65002    6789    6790       15    0    0 00:45:30 45678
"""

        result = await generate_template(
            raw_output=bgp_output,
            command_name="show ip bgp summary",
            platform="cisco_ios",
        )

        print(f"Status: {result['status']}")
        print(f"Iterations: {result['iterations']}")
        print(f"\nTemplate:\n{result['template']}")

    asyncio.run(test())
