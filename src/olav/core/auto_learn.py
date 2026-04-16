"""Auto-learn TextFSM templates when ntc-templates fails.

Pipeline integration point: called by netops_init Stage 3.5 after SSH collection.
When TextFSM parsing fails for a command with valid output, this module:
1. Checks for false positives (error messages, empty output, backup commands)
2. Checks for existing custom templates
3. Generates a new template via LLM (if available)
4. Validates the template by parsing the raw output
5. Saves successful templates to workspace for future use
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── False positive detection ──────────────────────────────────────────────

BACKUP_COMMANDS = frozenset({
    "show running-config", "show startup-config", "show configuration",
    "show running-config | display set", "show configuration | display set",
})

ERROR_PATTERNS = [
    "% invalid", "% unknown", "syntax error", "not found",
    "command not recognized", "% incomplete", "permission denied",
    "access denied", "% authorization", "% ambiguous",
]


def should_learn(command: str, raw_output: str) -> bool:
    """Determine if a parse failure should trigger template learning.

    Returns False for: empty output, error messages, backup commands, timeouts.
    Returns True only when raw_output looks like valid structured CLI output.
    """
    text = raw_output.strip()

    # Empty or too short
    if len(text) < 30:
        return False

    # Backup commands — store raw, don't parse
    if command.lower().strip() in BACKUP_COMMANDS:
        return False

    # Device error messages (check first 3 lines)
    first_lines = "\n".join(text.split("\n")[:3]).lower()
    if any(p in first_lines for p in ERROR_PATTERNS):
        return False

    # Timeout
    lower = text.lower()
    if "timeout" in lower or "timed out" in lower:
        return False

    return True


# ── Custom template management ────────────────────────────────────────────

def _template_path(base_dir: Path, platform: str, command: str) -> Path:
    """Build path: base_dir/platform/command.textfsm"""
    safe_cmd = command.strip().lower().replace(" ", "_").replace("/", "_")[:60]
    return base_dir / platform / f"{safe_cmd}.textfsm"


def save_custom_template(
    base_dir: Path, platform: str, command: str, template: str
) -> Path:
    """Save a TextFSM template to the custom templates directory."""
    path = _template_path(base_dir, platform, command)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template, encoding="utf-8")
    logger.info("auto_learn: saved custom template %s", path)
    return path


def load_custom_template(
    base_dir: Path, platform: str, command: str
) -> str | None:
    """Load a custom TextFSM template if it exists."""
    path = _template_path(base_dir, platform, command)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def parse_with_custom_template(
    base_dir: Path, platform: str, command: str, raw_output: str
) -> list[dict] | None:
    """Parse raw output using a custom TextFSM template."""
    template_text = load_custom_template(base_dir, platform, command)
    if template_text is None:
        return None
    return _parse_with_template_text(template_text, raw_output)


def _parse_with_template_text(template_text: str, raw_output: str) -> list[dict] | None:
    """Parse raw_output with a TextFSM template string."""
    try:
        import io
        import textfsm
        fsm = textfsm.TextFSM(io.StringIO(template_text))
        rows = fsm.ParseText(raw_output)
        if not rows:
            return None
        headers = fsm.header
        return [dict(zip(headers, row)) for row in rows]
    except Exception as exc:
        logger.debug("auto_learn: template parse failed: %s", exc)
        return None


# ── LLM template generation ──────────────────────────────────────────────

def generate_textfsm_template(
    platform: str, command: str, raw_output: str
) -> str | None:
    """Generate a TextFSM template from raw CLI output using LLM.

    Returns template string or None if LLM is unavailable.
    """
    try:
        from olav.core.llm import LLMFactory
        llm = LLMFactory.get_chat_model()
    except Exception:
        logger.debug("auto_learn: LLM unavailable, skipping template generation")
        return None

    prompt = f"""Generate a TextFSM template to parse this {platform} CLI output.

Command: {command}

Raw output:
```
{raw_output[:2000]}
```

Rules:
1. Use Value directives for each column/field
2. Use regex patterns that match the exact output format
3. Include a Start state with Record transitions
4. Return ONLY the TextFSM template text, no explanation

TextFSM template:"""

    try:
        response = llm.invoke(prompt)
        template = response.content.strip()
        # Clean markdown code blocks if present
        if template.startswith("```"):
            lines = template.split("\n")
            template = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            )
        if "Value" in template and "Start" in template:
            return template.strip()
        return None
    except Exception as exc:
        logger.debug("auto_learn: LLM generation failed: %s", exc)
        return None


# ── Stage 3.5 integration ────────────────────────────────────────────────

def auto_learn_failed_parses(
    parse_failures: list[dict],
    custom_template_dir: Path,
    max_retries: int = 5,
) -> list[dict]:
    """Auto-learn TextFSM templates for commands that failed parsing.

    Called by netops_init between SSH collection (Stage 3) and Topology ETL (Stage 4).

    Args:
        parse_failures: List of {device, platform, command, raw_output} dicts
        custom_template_dir: Where to save learned templates
        max_retries: Max LLM attempts per command

    Returns:
        List of newly parsed results: {device, command, parsed_data}
    """
    newly_parsed = []

    # Deduplicate by (platform, command) — learn once per command, not per device
    seen_commands: dict[tuple[str, str], str] = {}  # (platform, command) → raw_output
    for item in parse_failures:
        key = (item["platform"], item["command"])
        if key not in seen_commands:
            seen_commands[key] = item["raw_output"]

    for (platform, command), raw_output in seen_commands.items():
        # 1. False positive check
        if not should_learn(command, raw_output):
            logger.info("auto_learn: skip %s/%s (false positive or backup)", platform, command)
            continue

        # 2. Check existing custom template
        result = parse_with_custom_template(custom_template_dir, platform, command, raw_output)
        if result:
            logger.info("auto_learn: %s/%s parsed with existing custom template", platform, command)
            # Apply to all devices with this command
            for item in parse_failures:
                if item["platform"] == platform and item["command"] == command:
                    newly_parsed.append({
                        "device": item["device"],
                        "command": command,
                        "parsed_data": result,
                        "source": "custom_template",
                    })
            continue

        # 3. LLM learn (max retries)
        learned = False
        for attempt in range(max_retries):
            template = generate_textfsm_template(platform, command, raw_output)
            if template is None:
                logger.info("auto_learn: LLM unavailable, stopping learn for %s/%s", platform, command)
                break  # LLM not available, no point retrying

            result = _parse_with_template_text(template, raw_output)
            if result and len(result) > 0:
                save_custom_template(custom_template_dir, platform, command, template)
                logger.info(
                    "auto_learn: ✓ learned %s/%s in %d attempt(s) (%d rows)",
                    platform, command, attempt + 1, len(result),
                )
                for item in parse_failures:
                    if item["platform"] == platform and item["command"] == command:
                        newly_parsed.append({
                            "device": item["device"],
                            "command": command,
                            "parsed_data": result,
                            "source": f"learned_attempt_{attempt + 1}",
                        })
                learned = True
                break

        if not learned:
            logger.warning("auto_learn: ✗ failed to learn %s/%s after %d attempts", platform, command, max_retries)

    return newly_parsed
