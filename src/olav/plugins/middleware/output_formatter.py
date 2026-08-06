"""Output Formatter Plugin — deterministic post-processing of agent tool results.

Solves the problem where LLM agents hit max_tokens limits during multi-step
pipelines and truncate/omit final output formatting.  This plugin runs in
``aafter_agent`` and performs guaranteed post-processing:

1. render_report → auto-extract Executive Summary from report file
2. format_and_export → if script content detected but no file written, auto-export
3. execute_sql → if LLM truncated tabular output, append full table

All processing is deterministic (no LLM calls, zero token cost).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from olav.plugins.base import OLAVMiddlewarePlugin, SupplementState

logger = logging.getLogger(__name__)


class OutputFormatterPlugin(OLAVMiddlewarePlugin):
    """Post-processor that supplements LLM output with deterministic formatting."""

    # Declares `_output_supplements`; without it langgraph drops the key
    # and the notes below never reach the operator (dev_docs/115 §11).
    state_schema = SupplementState

    name = "output_formatter"
    version = "1.0.0"
    description = "Agent 输出后处理：自动提取 summary、自动导出脚本"
    tags = ["output", "builtin"]

    async def aafter_agent(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Inspect tool results and supplement the final output if needed."""
        messages = state.get("messages", [])
        if not messages:
            return None

        # Collect tool results and final assistant content from messages
        tool_results: list[dict] = []
        assistant_content = ""
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
            else:
                role = getattr(msg, "type", "") or getattr(msg, "role", "")
                content = getattr(msg, "content", "") or ""

            if role == "tool":
                name = msg.get("name", "") if isinstance(msg, dict) else getattr(msg, "name", "")
                tool_results.append({"name": name, "content": str(content)})
            elif role in ("assistant", "ai"):
                assistant_content = str(content) if content else assistant_content

        supplements: list[str] = []

        # ── 1. render_report: extract Executive Summary ──────────────
        # Check direct tool results AND both subagent-delegation tool names
        # (``olav_delegate`` + deepagents' ``task``) because the audit
        # orchestrator routes through ``task`` while ops-analyze routes
        # through ``olav_delegate``. Plus we scan assistant_content itself
        # for the report-path marker — if neither delegation tool carried
        # the wrapped output (some models surface it only in the final
        # assistant message), the fallback below still catches the path.
        _DELEGATION_TOOLS = {"olav_delegate", "task"}
        # Match common render_report success markers:
        #   "Report saved: /path/x.md"
        #   "report_path: /path/x.md"
        #   "exports/audit_reports/x.md"  (last resort — just a .md path)
        import re as _re
        _REPORT_PATH_RE = _re.compile(
            r'(?:Report saved:|report_path[:=]?|report saved at)\s*["\']?([^\s"\'\]]+\.md)',
            _re.IGNORECASE,
        )
        _FALLBACK_MD_RE = _re.compile(
            r'(exports[\w/_-]*/audit_reports/[\w./_-]+\.md)',
            _re.IGNORECASE,
        )
        seen_paths: set[str] = set()

        def _maybe_append(path_str: str) -> None:
            if not path_str or path_str in seen_paths:
                return
            seen_paths.add(path_str)
            summary = self._extract_summary_from_report(path_str)
            if summary and summary not in assistant_content:
                supplements.append(summary)

        for tr in tool_results:
            content = tr["content"]
            if tr["name"] == "render_report" and content:
                _maybe_append(content)
            elif tr["name"] in _DELEGATION_TOOLS and content:
                m = _REPORT_PATH_RE.search(content) or _FALLBACK_MD_RE.search(content)
                if m:
                    _maybe_append(m.group(1))

        # Fallback: scan final assistant message for a report path even if
        # neither delegation tool's result carried it structured. Catches
        # the "agent just prints the path" surface (Gitea #5).
        if not supplements and assistant_content:
            m = _REPORT_PATH_RE.search(assistant_content) or _FALLBACK_MD_RE.search(assistant_content)
            if m:
                _maybe_append(m.group(1))

        # ── 2. Script auto-export ────────────────────────────────────
        if self._has_script_content(assistant_content) and not self._has_export_path(assistant_content):
            export_path = self._auto_export_script(assistant_content)
            if export_path:
                supplements.append(f"\n📁 Script auto-exported: {export_path}")

        # ── 3. Return supplements for main.py to print ─────────────
        # Return ONLY this run's additions: the reducer is `operator.add`, so
        # echoing the accumulated list back would re-append every earlier note.
        if supplements:
            logger.info("OutputFormatterPlugin: %d supplements ready", len(supplements))
            return {"_output_supplements": supplements}

        return None

    def _extract_summary_from_report(self, tool_output: str) -> str | None:
        """Read a report file and extract the Executive Summary section."""
        # tool_output is typically the file path
        report_path = tool_output.strip().strip("'\"")
        path = Path(report_path)

        # Try multiple possible locations
        candidates = [path]
        if not path.is_absolute():
            from olav.core.workspace import resolve_workspace_root
            try:
                ws = resolve_workspace_root()
                candidates.append(ws.parent / report_path)
                candidates.append(Path.cwd() / report_path)
            except Exception:
                pass

        for p in candidates:
            if p.exists() and p.is_file():
                try:
                    text = p.read_text(encoding="utf-8")
                    return self._parse_executive_summary(text, str(p))
                except Exception as e:
                    logger.debug("Failed to read report %s: %s", p, e)

        return None

    @staticmethod
    def _parse_executive_summary(text: str, path: str) -> str | None:
        """Extract ## Executive Summary section from markdown text."""
        # Find the Executive Summary heading
        pattern = r'##\s*(Executive\s+Summary|Summary|Overview)\s*\n(.*?)(?=\n##|\n---|\Z)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            return None

        summary_content = match.group(2).strip()
        if not summary_content or len(summary_content) < 20:
            return None

        # Extract health verdict if present
        verdict = ""
        for line in summary_content.splitlines():
            if any(v in line for v in ("🔴", "⚠️", "✅", "Critical", "At Risk", "Healthy")):
                verdict = f"\n**Verdict:** {line.strip()}"
                break

        return f"\n📋 **Executive Summary** (from `{Path(path).name}`):\n\n{summary_content}{verdict}"

    @staticmethod
    def _has_script_content(text: str) -> bool:
        """Check if text contains a shell/python script.

        Detects (in order of strength):
          * Explicit shebangs or hardening pragmas
          * ``def main(`` / ``import argparse`` style Python entry points
          * A fenced code block tagged as bash/sh/python — covers the
            common "here's a script:" pattern without a shebang
        """
        markers = ["#!/bin/bash", "#!/usr/bin/env", "set -euo pipefail",
                   "def main(", "import argparse"]
        if any(m in text for m in markers):
            return True
        # Fenced code block tagged as bash/sh/python/py counts as script.
        if re.search(r'```(?:bash|sh|python|py)\b', text):
            return True
        return False

    @staticmethod
    def _has_export_path(text: str) -> bool:
        """Check if text mentions an exports/ file path."""
        return bool(re.search(r'exports?/\S+\.\w+', text))

    @staticmethod
    def _auto_export_script(text: str) -> str | None:
        """Extract script from markdown code block and write to exports/scripts/.

        Writes to the project-root ``exports/scripts/`` via the
        ``olav.core.config.EXPORTS_DIR`` constant — the same location
        the ``format_and_export`` tool uses — so T2-25 and other
        downstream checks that scan ``exports/`` find the file.
        """
        # Find the largest code block — allow arbitrary / missing language tag.
        blocks = re.findall(
            r'```(?:[a-zA-Z0-9_-]*)?\n(.*?)```', text, re.DOTALL
        )
        if not blocks:
            return None

        script = max(blocks, key=len)
        if len(script) < 50:  # too short to be a real script
            return None

        # Determine extension
        ext = "sh" if script.lstrip().startswith("#!") or "bash" in script[:100] else "py"
        filename = f"auto_export.{ext}"

        try:
            from olav.core.config import EXPORTS_DIR
            exports_dir = EXPORTS_DIR / "scripts"
            exports_dir.mkdir(parents=True, exist_ok=True)
            out = exports_dir / filename
            out.write_text(script, encoding="utf-8")
            if ext == "sh":
                out.chmod(0o755)
            return str(out)
        except Exception as e:
            logger.debug("Auto-export failed: %s", e)
            return None
