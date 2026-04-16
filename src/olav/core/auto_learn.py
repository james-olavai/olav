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


# ── Completeness estimation ───────────────────────────────────────────────

def _estimate_data_rows(raw_output: str, command: str) -> int:
    """Estimate how many data rows the raw output contains.

    Heuristic: count lines that look like data (start with IP, hostname, or
    interface name) vs headers/separators/blank lines.

    Returns 0 if estimation is unreliable (better to accept any parse result).
    """
    import re

    lines = raw_output.strip().split("\n")
    if len(lines) < 3:
        return 0

    # For tabular output: skip header lines (first 1-3 lines), count data lines
    # A data line typically starts with a non-space character and contains
    # at least 2 whitespace-separated fields
    data_lines = 0
    header_seen = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip obvious headers/separators
        if stripped.startswith("---") or stripped.startswith("==="):
            continue
        if any(kw in stripped.lower() for kw in [
            "threading", "groups:", "table ", "peer ", "local interface",
            "device id", "capability", "platform:",
        ]):
            header_seen = True
            continue

        # After header, lines starting with IP/hostname/interface are data
        if header_seen:
            # Matches: IP address, hostname (letters+digits), interface name
            if re.match(r'^[0-9a-zA-Z]', stripped) and len(stripped.split()) >= 2:
                data_lines += 1

    return data_lines


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


# ── LLM template generation (ReAct pattern) ──────────────────────────────

def _get_reference_templates(platform: str, max_examples: int = 3) -> str:
    """Load existing ntc-templates for the same platform as few-shot examples."""
    try:
        import ntc_templates
        templates_dir = Path(ntc_templates.__file__).parent / "templates"
        candidates = sorted(templates_dir.glob(f"{platform}_*.textfsm"))
        if not candidates:
            return ""

        examples = []
        for t in candidates[:max_examples]:
            content = t.read_text(encoding="utf-8")
            examples.append(f"# --- {t.name} ---\n{content}")
        return "\n\n".join(examples)
    except Exception:
        return ""


def _get_existing_template(platform: str, command: str) -> str | None:
    """Load the existing ntc-template for this exact command (the one that failed)."""
    try:
        import ntc_templates
        templates_dir = Path(ntc_templates.__file__).parent / "templates"
        cmd_key = command.strip().lower().replace(" ", "_")
        path = templates_dir / f"{platform}_{cmd_key}.textfsm"
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return None


def _extract_parse_error(template_text: str, raw_output: str) -> str:
    """Try parsing and capture the specific error message."""
    try:
        import io
        import textfsm
        fsm = textfsm.TextFSM(io.StringIO(template_text))
        fsm.ParseText(raw_output)
        return "No error (but returned 0 rows)"
    except Exception as exc:
        return str(exc)[:300]


def generate_textfsm_template(
    platform: str, command: str, raw_output: str,
    previous_template: str | None = None,
    previous_error: str | None = None,
) -> str | None:
    """Generate a TextFSM template using ReAct pattern.

    First call: provides reference templates from same platform as few-shot examples.
    Retry calls: provides previous template + error for iterative fix.

    Returns template string or None if LLM is unavailable.
    """
    try:
        from olav.core.llm import LLMFactory
        llm = LLMFactory.get_chat_model()
    except Exception:
        logger.debug("auto_learn: LLM unavailable, skipping template generation")
        return None

    # Build prompt
    if previous_template and previous_error:
        # ReAct RETRY: fix the previous template based on error
        prompt = f"""Fix this TextFSM template that fails to parse {platform} "{command}" output.

## Previous template (FAILED):
```
{previous_template}
```

## Parse error:
{previous_error}

## Raw output to parse:
```
{raw_output[:2000]}
```

## Fix instructions:
- The error shows which line caused the failure
- "State Error" usually means a line doesn't match any rule — add a catch-all or skip rule
- "^\s+. -> Error" is too strict — replace with "^\s+." (no Error action) to skip unknown lines
- Ensure every possible line format has a matching rule or is safely skipped

Return ONLY the fixed TextFSM template, no explanation."""
    else:
        # First attempt: provide reference templates as examples
        existing = _get_existing_template(platform, command)
        references = _get_reference_templates(platform)

        prompt = f"""Generate a TextFSM template to parse this {platform} "{command}" output.

## Raw output:
```
{raw_output[:2000]}
```"""

        if existing:
            prompt += f"""

## Existing template (from ntc-templates, but it FAILS on this output):
```
{existing}
```
Fix the existing template to handle this output format. Common issues:
- "^\s+. -> Error" is too strict for outputs with unexpected indented lines
- Table header/stats lines between records need skip rules"""

        if references:
            prompt += f"""

## Reference: other {platform} templates (for syntax style):
{references[:3000]}"""

        prompt += """

## Rules:
1. Use Value directives with regex for each field
2. Handle multi-line records if needed (e.g. Junos inet.0 stats after peer lines)
3. NEVER use "-> Error" for lines that might vary — use plain match or skip
4. Return ONLY the TextFSM template text, no explanation"""

    try:
        response = llm.invoke(prompt)
        template = response.content.strip()
        # Clean markdown code blocks
        if "```" in template:
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

    Uses ReAct pattern: generate → validate → feed error back → regenerate.
    Each retry is informed by the previous failure, not blind retry.

    Args:
        parse_failures: List of {device, platform, command, raw_output} dicts
        custom_template_dir: Where to save learned templates
        max_retries: Max LLM attempts per command

    Returns:
        List of newly parsed results: {device, command, parsed_data}
    """
    newly_parsed = []

    # Deduplicate by (platform, command) — learn once per command, not per device
    seen_commands: dict[tuple[str, str], str] = {}
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
            for item in parse_failures:
                if item["platform"] == platform and item["command"] == command:
                    newly_parsed.append({
                        "device": item["device"],
                        "command": command,
                        "parsed_data": result,
                        "source": "custom_template",
                    })
            continue

        # 3. ReAct learn loop
        learned = False
        prev_template = None
        prev_error = None

        for attempt in range(max_retries):
            template = generate_textfsm_template(
                platform, command, raw_output,
                previous_template=prev_template,
                previous_error=prev_error,
            )
            if template is None:
                logger.info("auto_learn: LLM unavailable, stopping learn for %s/%s", platform, command)
                break

            result = _parse_with_template_text(template, raw_output)
            if result and len(result) > 0:
                # ── Reflection: validate completeness ──
                expected = _estimate_data_rows(raw_output, command)
                parsed_count = len(result)

                if expected > 0 and parsed_count < expected * 0.7:
                    # Parsed less than 70% of expected rows — template is incomplete
                    prev_template = template
                    prev_error = (
                        f"Template parsed only {parsed_count} rows but raw output "
                        f"has ~{expected} data lines. Missing rows — the Record "
                        f"transition likely fires too late or misses some entries. "
                        f"Ensure every data line produces a Record."
                    )
                    logger.debug(
                        "auto_learn: attempt %d incomplete for %s/%s: %d/%d rows",
                        attempt + 1, platform, command, parsed_count, expected,
                    )
                    continue  # retry with reflection feedback

                save_custom_template(custom_template_dir, platform, command, template)
                logger.info(
                    "auto_learn: ✓ learned %s/%s in %d attempt(s) (%d rows, expected ~%d)",
                    platform, command, attempt + 1, parsed_count, expected,
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
            else:
                # ReAct: capture error for next iteration
                prev_template = template
                prev_error = _extract_parse_error(template, raw_output)
                logger.debug(
                    "auto_learn: attempt %d failed for %s/%s: %s",
                    attempt + 1, platform, command, prev_error[:100],
                )

        if not learned:
            logger.warning("auto_learn: ✗ failed to learn %s/%s after %d attempts", platform, command, max_retries)

    return newly_parsed
