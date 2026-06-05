"""Governance tests for ADR-0015 memory architecture.

Ensures:
  1. No agent code (outside kb_import.py and tests/) writes category='expert_knowledge'
  2. trace_learner writes REFLECTION, not EXPERT_KNOWLEDGE
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

# Root of the src/olav package
SRC_ROOT = Path(__file__).parent.parent.parent / "src" / "olav"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_python_files(
    root: Path,
    *,
    exclude_names: set[str] | None = None,
) -> list[Path]:
    """Return all .py files under root, optionally excluding specific filenames."""
    exclude_names = exclude_names or set()
    return [
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and p.name not in exclude_names
    ]


# ---------------------------------------------------------------------------
# test_no_agent_code_writes_expert_knowledge
# ---------------------------------------------------------------------------



# Patterns that indicate an actual *write* of expert_knowledge (not reads, deletes, or doc strings).
# We look for add_memory / store.add_memory calls with category='expert_knowledge'.
_EXPERT_KNOWLEDGE_WRITE_PATTERNS = [
    # add_memory(... category=MemoryCategory.EXPERT_KNOWLEDGE ...)
    re.compile(r"add_memory\s*\([^)]*category\s*=\s*MemoryCategory\.EXPERT_KNOWLEDGE"),
    # add_memory(... category="expert_knowledge" ...)
    re.compile(r"""add_memory\s*\([^)]*category\s*=\s*['"]expert_knowledge['"]"""),
    # Direct assignment: category=MemoryCategory.EXPERT_KNOWLEDGE (write context)
    # Narrow: only match when the preceding context looks like a function call arg
    re.compile(r"""store_event\s*\([^)]*category\s*=\s*['"]expert_knowledge['"]"""),
    # olav_store_memory with expert_knowledge (the public @tool)
    re.compile(r"""olav_store_memory\s*\([^)]*category\s*=\s*['"]expert_knowledge['"]"""),
]

_ALLOWED_EXPERT_KNOWLEDGE_WRITERS = {
    "kb_import.py",      # ADR-0015 sanctioned importer
}


def test_no_agent_code_writes_expert_knowledge():
    """No src/olav/*.py file (outside kb_import.py) may call add_memory with expert_knowledge.

    ADR-0015 D1: expert_knowledge is user-curated-only; agent code must write
    ``reflection`` instead.  The only allowed writer is ``kb_import.py``.

    Note: reading, deleting, or filtering by 'expert_knowledge' is permitted.
    Only actual writes (add_memory/olav_store_memory calls) are prohibited.
    """
    violations: list[str] = []

    # Collect all Python files under src/olav, excluding allowed writers
    files = _collect_python_files(SRC_ROOT, exclude_names=_ALLOWED_EXPERT_KNOWLEDGE_WRITERS)

    for py_file in sorted(files):
        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for pattern in _EXPERT_KNOWLEDGE_WRITE_PATTERNS:
            for match in pattern.finditer(source):
                line_no = source[: match.start()].count("\n") + 1
                rel_path = py_file.relative_to(SRC_ROOT)
                violations.append(f"{rel_path}:{line_no}: {match.group()!r}")

    assert not violations, (
        "ADR-0015 violation: the following files write category='expert_knowledge' "
        "outside of the allowed kb_import.py module.\n"
        "Agent code must write category='reflection' instead.\n"
        "Only olav kb import-kb (via kb_import.py) may write expert_knowledge.\n\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# test_reflection_ttl_written
# ---------------------------------------------------------------------------


def test_reflection_ttl_written():
    """ADR-0015: trace_learner must write REFLECTION category, not EXPERT_KNOWLEDGE."""
    import importlib as _importlib
    tl_mod = _importlib.import_module("olav.core.curator.trace_learner")
    from olav.core.memory import MemoryCategory

    # 1. trace_learner module must expose _write_constraints_to_memory
    assert hasattr(tl_mod, "_write_constraints_to_memory"), (
        "trace_learner._write_constraints_to_memory not found"
    )

    # 2. Read the source file and check it uses REFLECTION
    src = Path(tl_mod.__file__).read_text(encoding="utf-8")

    assert re.search(r"MemoryCategory\.REFLECTION", src), (
        "trace_learner._write_constraints_to_memory must use MemoryCategory.REFLECTION "
        "(ADR-0015); still using EXPERT_KNOWLEDGE"
    )
    assert not re.search(r"MemoryCategory\.EXPERT_KNOWLEDGE", src), (
        "trace_learner._write_constraints_to_memory must NOT use EXPERT_KNOWLEDGE "
        "(ADR-0015); change to REFLECTION"
    )

    # 3. MemoryCategory must have REFLECTION
    assert hasattr(MemoryCategory, "REFLECTION"), "MemoryCategory.REFLECTION must exist (ADR-0015)"
    assert MemoryCategory.REFLECTION == "reflection"


# ---------------------------------------------------------------------------
# test_expert_kb_deleted
# ---------------------------------------------------------------------------


def test_expert_kb_deleted():
    """ADR-0015 D6: src/olav/core/memory/expert_kb.py must be deleted."""
    expert_kb_path = SRC_ROOT / "core" / "memory" / "expert_kb.py"
    assert not expert_kb_path.exists(), (
        f"ADR-0015: expert_kb.py must be deleted, but still exists at {expert_kb_path}"
    )


# ---------------------------------------------------------------------------
# test_kb_import_module_exists
# ---------------------------------------------------------------------------


def test_kb_import_module_exists():
    """ADR-0015: src/olav/core/memory/kb_import.py must exist with import_kb function."""
    kb_import_path = SRC_ROOT / "core" / "memory" / "kb_import.py"
    assert kb_import_path.exists(), (
        f"ADR-0015: kb_import.py must exist at {kb_import_path}"
    )

    try:
        from olav.core.memory.kb_import import import_kb
    except ImportError as exc:
        pytest.fail(f"Cannot import import_kb from kb_import: {exc}")

    assert callable(import_kb), "import_kb must be callable"
