"""SaveAssertionMiddleware — close the "claimed save without tool call" hole.

R83.4 Chapter 4 verification revealed that small models (grok-4.1-fast)
sometimes write "Saved to /exports/network_topology.mmd" in the final
reply **without** ever calling ``format_and_export`` or
``olav_delegate('writer', ...)``.  The user sees the claim, opens the
path, file isn't there — broken demo.

This middleware closes the loop with deterministic post-processing:

1. **Detect**: scan the final assistant message for save-claim phrases
   (``saved to``, ``/exports/...``, ``保存到``, etc.).
2. **Verify**: walk the agent's full message history for a
   ``format_and_export`` tool call OR an ``olav_delegate('writer')``
   delegation; if found, trust the agent.
3. **Recover**: if no save evidence, attempt to extract the artifact
   (currently Mermaid block) from the assistant content and save it
   directly via ``format_and_export``.  Append a one-line note to the
   final message citing the actually-saved path.

Pattern modelled on :class:`OutputFormatterPlugin`'s script auto-export
(`_has_script_content` + `_auto_export_script`).  Same hook
(``aafter_agent``), same recovery philosophy: never block, always
rescue.

Why a new middleware instead of extending OutputFormatterPlugin
================================================================

OutputFormatterPlugin's mandate is **supplement** the model's output
(extract Executive Summary, append script path).  This middleware's
mandate is **assert** — detect a claim and either confirm or replace
it.  Different semantics, deserves a separate surface.  Both run in
``aafter_agent`` and are independent.

Generic enough to extend
========================

The ``_ASSERTION_RULES`` table makes it trivial to add new
"claim pattern → required tool / auto-recovery" rows for future
hallucination-class bugs (e.g. "Created PR #N" without a gh CLI call,
"Deployed service X" without a ``deploy_service`` call).  Today only
the Mermaid case has a recovery; others can be added as
detection-only (warn but don't auto-fix).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from olav.plugins.base import OLAVMiddlewarePlugin

logger = logging.getLogger(__name__)


# ── Claim-detection phrases (case-insensitive) ─────────────────────
# Trigger inspection when ANY of these appear in the final assistant
# content; absence = no save claim, nothing to verify.
_SAVE_CLAIM_RE = re.compile(
    r"""(
        saved?\ to\b           |  # "saved to /path", "save to /path"
        saved?\ as\b           |  # "saved as /path"
        wrote\ to\b            |  # "wrote to /path"
        exported\ to\b         |  # "exported to /path"
        export\ saved\b        |  # "export saved at /path"
        report\ saved\b        |  # "report saved: /path"
        保存到                  |  # 保存到 …
        已保存                  |  # 已保存
        已导出                     # 已导出
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# ── Path extraction — look for /exports/.../<file>.<ext> mentions ───
_PATH_RE = re.compile(
    r"""(?:^|[\s'"`(])           # word boundary (whitespace or punct)
        (/?[\w./_-]*?exports/[\w./_-]+?\.[a-z0-9]{1,5})  # /exports/foo/bar.ext
        (?=[\s'"`)<]|$)          # trailing boundary
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ── Tool calls that count as "actually saved" ───────────────────────
# Add new save-tools here as agents grow (each tool's existence is
# evidence the model intended a real write).
_SAVE_TOOLS = {
    "format_and_export",   # core/writer
    "render_report",       # audit/auditor — emits .md to exports/audit_reports/
    "save_lab_config",     # ops/lab — writes .clab.yaml configs
    "save_profile",        # audit/auditor — writes profile YAML
}
# Subagent names that internally save (their own tool calls are not
# visible at the orchestrator level, but their delegation IS)
_SAVE_DELEGATIONS = {
    "writer",        # core/writer (format_and_export)
    "audit-auditor", # audit subagent (render_report)
    "ops-lab",       # lab subagent (save_lab_config)
}

# ── Mermaid extraction — block tagged ```mermaid``` or graph-syntax ─
_MERMAID_BLOCK_RE = re.compile(
    r"```mermaid\n(.+?)\n```",
    re.DOTALL,
)
_MERMAID_BARE_RE = re.compile(
    r"^(graph\s+(?:TD|LR|BT|RL)|flowchart\s+(?:TD|LR|BT|RL)|"
    r"sequenceDiagram|stateDiagram|classDiagram|erDiagram)",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_like_save_claim(content: str) -> bool:
    """True iff the assistant content contains a save-claim phrase.

    Cheap pre-filter: avoids the expensive history walk on the 99% of
    responses that aren't claiming a save.
    """
    if not content:
        return False
    return bool(_SAVE_CLAIM_RE.search(content))


def _save_evidence_in_history(messages: list) -> bool:
    """Walk message history looking for actual save evidence.

    Counts as evidence:
    * any ``ToolMessage`` for the ``format_and_export`` tool;
    * any ``AIMessage`` whose ``tool_calls`` include
      ``format_and_export``;
    * any ``olav_delegate(subagent_name='writer', ...)`` invocation
      (writer's internal save is invisible here, but the delegation
      itself is the contract).
    """
    for msg in messages:
        # ToolMessage path — successful save returns a result
        name = (
            msg.get("name") if isinstance(msg, dict)
            else getattr(msg, "name", None)
        )
        if name in _SAVE_TOOLS:
            return True

        # AIMessage path — check tool_calls list
        tcs = (
            msg.get("tool_calls") if isinstance(msg, dict)
            else getattr(msg, "tool_calls", None)
        ) or []
        for tc in tcs:
            tc_name = tc.get("name") if isinstance(tc, dict) else None
            if tc_name in _SAVE_TOOLS:
                return True
            if tc_name == "olav_delegate":
                args = tc.get("args") or {}
                if args.get("subagent_name") in _SAVE_DELEGATIONS:
                    return True
    return False


def _path_exists_on_disk(content: str) -> bool:
    """If the assistant claims a specific path, check whether it exists.

    Stronger than tool-call inspection — even if a tool was called,
    the file might not have landed (the ``format_and_export`` tool
    early-returns on bad input).  Conversely some agents write files
    via ``run_shell`` or similar without going through our save
    tools — checking the disk handles those too.
    """
    for m in _PATH_RE.finditer(content):
        path_str = m.group(1)
        # Normalise: strip leading / so relative paths under cwd resolve
        # (format_and_export returns relative paths like ``exports/x.mmd``).
        candidates = []
        if path_str.startswith("/"):
            candidates.append(Path(path_str))
            # Also try as relative under cwd in case of leading slash typo
            candidates.append(Path.cwd() / path_str.lstrip("/"))
        else:
            candidates.append(Path.cwd() / path_str)
            candidates.append(Path(path_str))
        for p in candidates:
            try:
                if p.is_file():
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _extract_mermaid(content: str) -> str | None:
    """Return the inner Mermaid graph if a renderable block is present.

    Prefers fenced ``​```mermaid`` blocks; falls back to bare
    ``graph TD\n…`` syntax appearing anywhere in the message.  Returns
    ``None`` when no Mermaid is found.
    """
    m = _MERMAID_BLOCK_RE.search(content)
    if m:
        return m.group(1).strip()
    # Bare syntax fallback — find the start, take to end-of-block
    # heuristic (next ``\n\n`` or end-of-string).
    m = _MERMAID_BARE_RE.search(content)
    if not m:
        return None
    start = m.start()
    rest = content[start:]
    # Cut at first double-newline followed by non-graph text — graph
    # bodies typically don't have blank lines mid-definition.
    parts = rest.split("\n\n", 1)
    return parts[0].strip() if parts else rest.strip()


# Markdown "report-shaped" detection — content must look like a real
# report (multiple headings, bullets, or a table) before we treat it
# as recoverable.  A one-line reply is NOT a report.
_MARKDOWN_REPORT_INDICATORS = (
    re.compile(r"^#{1,3}\s+\S", re.MULTILINE),     # heading
    re.compile(r"^\s*[-*]\s+\S", re.MULTILINE),    # bullet
    re.compile(r"^\|.+\|.+\|", re.MULTILINE),      # table row
)


def _is_report_shaped_markdown(content: str) -> bool:
    """True iff the assistant content has at least 2 distinct markdown
    structural elements AND is long enough to be a report.

    Cuts noise: short replies "Saved to /exports/foo.md" alone don't
    qualify; a real report has headings + bullets/table content.
    """
    if not content or len(content) < 200:
        return False
    hits = sum(
        1 for pat in _MARKDOWN_REPORT_INDICATORS if pat.search(content)
    )
    return hits >= 2


# Path-extension detection for the warning path — when content claims
# a save with a recognised extension but no recoverable artifact in
# chat, tell the user exactly what type wasn't recovered.
_PATH_KIND_RE = re.compile(
    r"\.(?P<ext>mmd|md|csv|json|yaml|yml|sh|py|tsv|html|svg)\b",
    re.IGNORECASE,
)

# Extensions handled by sibling middleware — skip our warning path so
# users don't see two messages about the same missing file.
# ``OutputFormatterPlugin._auto_export_script`` writes ``.sh`` / ``.py``
# scripts to ``exports/scripts/`` directly when content has script
# markers; our warning would be redundant and contradictory.
_DEFERRED_TO_OUTPUT_FORMATTER = {"sh", "py"}


def _claimed_extension(content: str) -> str | None:
    """First file extension mentioned in a save-claim path."""
    m = _PATH_KIND_RE.search(content)
    return m.group("ext").lower() if m else None


def _write_recovery(out_dir_name: str, ext: str, payload: str) -> str | None:
    """Common write path for recovery handlers — returns absolute path."""
    try:
        from olav.core.config import EXPORTS_DIR
        out_dir = EXPORTS_DIR / out_dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out_dir / f"recovered_{stamp}.{ext}"
        out.write_text(payload, encoding="utf-8")
        return str(out)
    except Exception as e:  # noqa: BLE001
        logger.debug("save_assertion: recovery write %s failed: %s", ext, e)
        return None


def _attempt_recovery(content: str) -> tuple[str, str] | None:
    """Deterministically save what the agent claimed it saved.

    Dispatch table — order = priority.  Each handler returns either
    ``(path, kind)`` on success or ``None`` to fall through to the
    next.  Currently handles:

    * **Mermaid** (``.mmd``) — fenced ``​```mermaid`` block or bare
      ``graph TD/LR/...`` syntax → ``exports/diagrams/``.
    * **Markdown report** (``.md``) — assistant content with multiple
      headings/bullets/tables (≥200 chars) → ``exports/reports/``.
      Saves the entire chat content; downstream tooling can split.

    Recovery is conservative — when the agent claims save of a
    binary or structured-data type (``.csv`` / ``.json`` / ``.clab.yaml``)
    we deliberately do NOT attempt extraction from prose: the parsing
    is fragile and partial recovery is worse than no recovery (a
    partial config could break a lab).  Caller appends warning instead.
    """
    # Handler 1: Mermaid (highest priority — explicit syntax)
    mermaid = _extract_mermaid(content)
    if mermaid:
        path = _write_recovery("diagrams", "mmd", mermaid)
        if path:
            return (path, "mermaid")

    # Handler 2: Markdown report (catch hallucinated audit / sim / drift saves)
    if _is_report_shaped_markdown(content):
        path = _write_recovery("reports", "md", content.strip())
        if path:
            return (path, "markdown report")

    return None


class SaveAssertionMiddleware(OLAVMiddlewarePlugin):
    """Verify save-claims have actual tool evidence; recover if not.

    Runs in ``aafter_agent`` (once per agent run, after the final
    assistant message lands).  Cheap pre-filter (regex on final
    content) means the no-claim case is sub-millisecond.
    """

    name = "save_assertion"
    version = "1.0.0"
    description = "断言保存声明真实发生；缺失时自动救援导出 (R83.4 Chapter 4)"
    tags = ["assertion", "builtin"]

    async def aafter_agent(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None

        # Find the last assistant text message
        assistant_content = ""
        for msg in reversed(messages):
            role = (
                msg.get("role") if isinstance(msg, dict)
                else getattr(msg, "type", None) or getattr(msg, "role", None)
            )
            content = (
                msg.get("content") if isinstance(msg, dict)
                else getattr(msg, "content", None)
            )
            if role in ("assistant", "ai") and content:
                assistant_content = (
                    content if isinstance(content, str)
                    else "\n".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict)
                    )
                )
                break

        # Cheap pre-filter — most replies don't claim a save
        if not _looks_like_save_claim(assistant_content):
            return None

        # Save claimed — verify with two checks (either passes)
        if _save_evidence_in_history(messages):
            return None  # tool was called, trust the agent
        if _path_exists_on_disk(assistant_content):
            return None  # file is there regardless of how it got there

        # Hallucinated claim — try to recover
        recovery = _attempt_recovery(assistant_content)
        if recovery is None:
            ext = _claimed_extension(assistant_content)
            # ``.sh`` / ``.py`` are handled by OutputFormatterPlugin's
            # ``_auto_export_script`` — skip our warning to avoid the
            # confusing "two complaints about the same file" UX.
            # OutputFormatterPlugin runs first (alphabetical
            # ``output_formatter.py`` < ``save_assertion.py``) and
            # writes a script when it detects code blocks.
            if ext in _DEFERRED_TO_OUTPUT_FORMATTER:
                logger.debug(
                    "save_assertion: deferring .%s to OutputFormatterPlugin",
                    ext,
                )
                return None
            ext_hint = (
                f"a `.{ext}` file" if ext else "a file"
            )
            recoverable_kinds_hint = (
                "Recovery only handles `.mmd` (Mermaid) and `.md` "
                "(report-shaped Markdown).  Structured types like "
                "`.csv` / `.json` / `.yaml` are not recoverable from "
                "prose — re-run with explicit `format_and_export(...)`."
            )
            logger.warning(
                "save_assertion: claim detected (%s) with no tool "
                "evidence and no recoverable artifact",
                ext_hint,
            )
            note = (
                f"\n\n⚠️  **Save assertion warning**: response claims "
                f"saving {ext_hint}, but no `format_and_export` /  "
                f"`olav_delegate('writer', ...)` tool call was found "
                f"in this run, and the cited path is not on disk.\n\n"
                f"{recoverable_kinds_hint}"
            )
            supplements = state.get("_output_supplements") or []
            supplements.append(note)
            state["_output_supplements"] = supplements
            return state

        recovered_path, kind = recovery
        logger.info(
            "save_assertion: %s claim hallucinated — auto-recovered to %s",
            kind, recovered_path,
        )
        note = f"\n\n📁 Auto-recovered {kind} → `{recovered_path}` (model claimed save but didn't call the save tool)"
        supplements = state.get("_output_supplements") or []
        supplements.append(note)
        state["_output_supplements"] = supplements
        return state
