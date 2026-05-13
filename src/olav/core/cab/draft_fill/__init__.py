"""Draft staged-ReAct fill — section-by-section template-driven draft compose.

Mirrors the audit `render_report` reduce pattern: LLM fills ONE
section at a time with a focused prompt + just the context that
section needs; lint runs after each; final whole-draft lint before
disk write.

Designed to let a 30B model do what a one-shot grammar-constrained
submit_draft can't: produce facts-complete, field-precise drafts.

Entry: ``run_staged_fill(user_prompt, llm_callable, devices_inspector,
                          topology_inspector, ...) → DraftChangePlan``
"""
from __future__ import annotations

from .lint import lint_draft, LintError
from .staged_fill import run_staged_fill, FillJournal
from .inspectors import inspect_devices, inspect_topology
from .llm_wrap import make_llm_callable

__all__ = [
    "lint_draft", "LintError",
    "run_staged_fill", "FillJournal",
    "inspect_devices", "inspect_topology",
    "make_llm_callable",
]
