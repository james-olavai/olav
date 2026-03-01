#!/usr/bin/env python3
"""
Tool 6: Generate Template (LLM-powered, ReAct + Reflection)

Generates TextFSM template using LLM with NTC references.
Template quality is validated via an LLM reflection step that compares
the raw output against the parsed result — no hardcoded heuristics.
"""

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def test_template(template_content: str, output_sample: str) -> dict[str, Any]:
    """Run TextFSM template and return parsed records as a readable table.

    Only responsible for syntax validity and execution — coverage judgement
    is delegated to the LLM reflection step (_reflect_on_coverage).
    """
    try:
        import io

        import textfsm

        fsm = textfsm.TextFSM(io.StringIO(template_content))
        parsed = fsm.ParseText(output_sample)
        headers = fsm.header

        # Format as readable text table for LLM reflection
        if parsed:
            col_widths = [max(len(h), max(len(str(row[i])) for row in parsed))
                          for i, h in enumerate(headers)]
            header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
            sep = "  ".join("-" * w for w in col_widths)
            data_rows = [
                "  ".join(str(v).ljust(w) for v, w in zip(row, col_widths))
                for row in parsed
            ]
            parsed_table = "\n".join([header_row, sep] + data_rows)
        else:
            parsed_table = "(no records parsed)"

        return {
            "success": True,
            "parsed_records": len(parsed),
            "headers": headers,
            "parsed_table": parsed_table,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "parsed_records": 0,
            "headers": [],
            "parsed_table": "",
            "error": str(e),
        }


def _reflect_on_coverage(
    llm: Any, template_content: str, raw_output: str, parsed_table: str
) -> dict[str, Any]:
    """LLM reflection step: compare raw output vs parsed result.

    The LLM acts as a domain expert, reading both the raw CLI output and
    the parsed table to determine whether any data rows were silently dropped.

    Returns:
        {
            "verdict": "PASS" | "FAIL",
            "missed_rows": [...],   # raw lines the LLM identified as missing
            "reason": "...",        # brief explanation
        }
    """
    import json
    import re

    prompt = f"""You are a TextFSM expert validating a template.

TASK: Compare the RAW CLI OUTPUT with the PARSED RESULT below.
Identify any data rows present in the raw output that were NOT captured in the parsed result.

=== RAW CLI OUTPUT ===
{raw_output}

=== PARSED RESULT ({len(parsed_table.splitlines()) - 2 if parsed_table != '(no records parsed)' else 0} records) ===
{parsed_table}

=== CURRENT TEMPLATE ===
```
{template_content}
```

INSTRUCTIONS:
- A "data row" is any non-blank line in the raw output that represents a device/interface/route/peer entry.
- Header lines (column titles, separator lines with dashes/equals) are NOT data rows.
- Continuation/indented lines are part of the previous data row (already covered if the parent was captured).
- If every data row in the raw output appears in the parsed result → verdict PASS.
- If any data row is missing → verdict FAIL, list the exact missing raw lines.

Respond with ONLY valid JSON (no markdown):
{{"verdict": "PASS" or "FAIL", "missed_rows": ["exact raw line 1", ...], "reason": "one sentence"}}"""

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        text = response.content.strip()
        # Strip markdown fences if present
        text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
        result = json.loads(text)
        return {
            "verdict": result.get("verdict", "FAIL"),
            "missed_rows": result.get("missed_rows", []),
            "reason": result.get("reason", ""),
        }
    except Exception as e:
        logger.warning(f"Reflection LLM call failed: {e}")
        # Fail-safe: treat as unknown, don't block generation
        return {"verdict": "PASS", "missed_rows": [], "reason": f"reflection unavailable: {e}"}


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
        settings,  # Load settings
    )

    # Load generation prompt (absolute path via config.paths — CWD-independent)
    # Path should be: .olav/workspace/config/learner/reference/textfsm_generation.md
    prompt_path = SKILL_BASE_PATH / "config" / "learner" / "reference" / "textfsm_generation.md"
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

**Full Sample Output to Parse**:
```
{output_sample}
```

Requirements:
1. Extract ALL approved fields
2. Use regex patterns similar to NTC examples
3. Template must capture ALL data rows — **zero missed data lines**
4. Handle vendor-specific notation (e.g. Juniper `-->` next-hop markers)
5. Follow TextFSM best practices
6. Return ONLY the template code (no explanations)

Return the template code directly.
"""

    # ReAct loop: Act (generate) → Observe (parse) → Reflect (LLM compare) → repeat
    for iteration in range(1, max_iterations + 1):
        try:
            logger.info(f"[ACT] Generating template (iteration {iteration}/{max_iterations})...")

            # --- ACT: Generate template ------------------------------------------
            messages = [
                {"role": "system", "content": generation_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = llm.invoke(messages)
            template_content = response.content.strip()

            # Strip markdown fences if present
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

            # Generate filename
            command_slug = command.lower().replace(" ", "_")
            filename = f"{platform}_{command_slug}.textfsm"

            # --- OBSERVE: Run TextFSM, get parsed table --------------------------
            test_result = test_template(template_content, output_sample)

            if not test_result["success"]:
                logger.warning(f"[OBSERVE] Syntax error on iteration {iteration}: {test_result['error']}")
                user_prompt += (
                    f"\n\n**Iteration {iteration} — Syntax Error**: {test_result['error']}\n"
                    "Fix the TextFSM syntax and regenerate."
                )
                continue

            logger.info(f"[OBSERVE] Parsed {test_result['parsed_records']} records.")

            # --- REFLECT: LLM compares raw output vs parsed table ----------------
            reflection = _reflect_on_coverage(
                llm, template_content, output_sample, test_result["parsed_table"]
            )
            logger.info(
                f"[REFLECT] verdict={reflection['verdict']}  "
                f"missed={len(reflection['missed_rows'])}  reason={reflection['reason']}"
            )

            if reflection["verdict"] == "PASS":
                logger.info(
                    f"✅ Template accepted (iteration {iteration}, "
                    f"records={test_result['parsed_records']}, reflection=PASS)"
                )
                return {
                    "template": template_content,
                    "filename": filename,
                    "test_result": {**test_result, "reflection": reflection},
                    "iteration": iteration,
                }

            # FAIL: feed reflection back as next-iteration context
            missed_report = (
                "\n\n**MISSED DATA ROWS** (identified by reflection):\n"
                + "\n".join(f"  {ln}" for ln in reflection["missed_rows"][:20])
                + f"\n\nReason: {reflection['reason']}"
                + "\n\nYou MUST add TextFSM rules that capture every missed row above."
            )
            logger.warning(
                f"❌ Iteration {iteration} rejected: {reflection['reason']} "
                f"({len(reflection['missed_rows'])} missed rows)"
            )
            user_prompt += (
                f"\n\n**Iteration {iteration} — Reflection FAILED**:{missed_report}\n"
                "Regenerate the template fixing all missed rows."
            )

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
