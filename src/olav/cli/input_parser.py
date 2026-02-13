"""Input Parser - Parse user input.

Handles file references and shell commands.
"""

import re
import subprocess
from pathlib import Path


def expand_file_references(text: str, base_dir: Path | None = None) -> str:
    """Expand @file references to file content.

    Args:
        text: Input text potentially containing @file.txt
        base_dir: Base directory for resolving relative paths

    Returns:
        Text with file references expanded
    """
    pattern = r"@([\w./\\-]+)"

    def replace_ref(match: re.Match[str]) -> str:  # noqa: ANN001
        filepath = match.group(1)
        path = Path(filepath)

        if base_dir is not None and not path.is_absolute():
            path = base_dir / path

        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
                suffix = path.suffix[1:] if path.suffix else "text"
                return f"\n```{suffix}\n{content}\n```\n"
            except Exception:
                return match.group(0)
        return match.group(0)

    return re.sub(pattern, replace_ref, text)


def parse_input(text: str) -> tuple[str, bool, str | None]:
    """Parse user input into components.

    Args:
        text: Raw user input

    Returns:
        Tuple of (processed_text, is_shell_command, shell_command)
    """
    text = text.strip()

    # Check for shell command (!command)
    if text.startswith("!"):
        shell_cmd = text[1:].strip()
        return text, True, shell_cmd

    # Expand file references
    text = expand_file_references(text)

    return text, False, None
