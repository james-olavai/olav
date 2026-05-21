"""ARCH-11 Phase 2 — citation linter for rendered audit reports.

Phase 1 (previous round) decorated findings with ``_source`` dicts and
made ``render_report`` emit an ``## Evidence`` block carrying
``[src: …]`` tags. Phase 2 verifies that every non-empty Job section in
the final markdown actually carries at least one citation, so a silent
drop at the LLM rendering step doesn't go unnoticed.

The linter runs as a pure post-render pass: it reads the produced
markdown file, segments it by ``## <section-name>`` headings, and for
every section that the JSON envelope declared non-empty asserts a
``[src: …]`` match. Violations are returned structured so the caller can
log / fail CI / append to the report.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# Sections that are inherently derived / editorial — the LLM synthesises
# them from other sections' findings and they don't need their own cites.
_SKIP_SECTIONS = {
    "Executive Summary",
    "Playbook",
    "Evidence",
    "Citation Audit",
}

_CITE_RE = re.compile(r"\[src:[^\]]+\]")
_SECTION_RE = re.compile(r"^##\s+([^\n]+?)\s*$", re.MULTILINE)


@dataclass
class CitationViolation:
    section: str
    line: int
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {"section": self.section, "line": self.line, "note": self.note}


def _split_sections(markdown: str) -> list[tuple[str, int, str]]:
    """Return ``[(heading, start_line, body), …]`` split on ``##`` headings.

    The first chunk (everything before the first ``##``) is returned
    under a sentinel heading of ``""`` and the linter ignores it.
    """
    matches = list(_SECTION_RE.finditer(markdown))
    if not matches:
        return [("", 1, markdown)]

    sections: list[tuple[str, int, str]] = []
    lines = markdown.splitlines()
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line) + 1)

    def _char_to_line(char_pos: int) -> int:
        # Linear scan is fine — section headings are few.
        for i, offset in enumerate(line_offsets):
            if offset > char_pos:
                return i  # 1-based
        return len(lines)

    preamble = markdown[: matches[0].start()]
    if preamble.strip():
        sections.append(("", 1, preamble))

    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        start_char = match.end()
        end_char = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        body = markdown[start_char:end_char]
        start_line = _char_to_line(match.start())
        sections.append((heading, start_line, body))
    return sections


def lint_citations(
    markdown: str,
    *,
    non_empty_sections: set[str] | None = None,
) -> list[CitationViolation]:
    """Return the list of sections that should have a ``[src: …]`` tag but don't.

    Args:
        markdown: The full rendered report text.
        non_empty_sections: Optional allowlist of section names the caller
            knows produced non-zero findings. When ``None``, every ``##``
            section outside ``_SKIP_SECTIONS`` is checked. When provided,
            placeholder sections (``count==0``) are automatically
            excused.
    """
    violations: list[CitationViolation] = []
    for heading, line, body in _split_sections(markdown):
        if not heading or heading in _SKIP_SECTIONS:
            continue
        if non_empty_sections is not None and heading not in non_empty_sections:
            continue
        if _CITE_RE.search(body):
            continue
        violations.append(
            CitationViolation(
                section=heading,
                line=line,
                note="section is non-empty but has no [src: …] citation",
            )
        )
    return violations


def lint_report_file(
    report_path: str | Path,
    *,
    non_empty_sections: set[str] | None = None,
) -> list[CitationViolation]:
    """Read a rendered report and return violations (convenience wrapper)."""
    text = Path(report_path).read_text(encoding="utf-8")
    return lint_citations(text, non_empty_sections=non_empty_sections)


def format_audit_block(violations: list[CitationViolation]) -> str:
    """Render a human-readable ``## Citation Audit`` section.

    Appended to the report tail by ``render_report`` so operators see the
    violations alongside the findings without digging through logs.
    """
    if not violations:
        return "## Citation Audit\n\n_All non-empty sections carry at least one `[src: …]` tag._\n\n---\n"
    lines = [
        "## Citation Audit",
        "",
        f"⚠️ {len(violations)} section(s) are missing citations:",
        "",
    ]
    for v in violations:
        lines.append(f"- **{v.section}** (line {v.line}): {v.note}")
    lines.append("")
    lines.append("---")
    return "\n".join(lines) + "\n"
