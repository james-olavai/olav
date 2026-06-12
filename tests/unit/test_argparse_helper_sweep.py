"""
tests/unit/test_argparse_helper_sweep.py
────────────────────────────────────────
Enforcement test for P7 cycle 4 — the ``shlex.split(args.strip()) if
args.strip() else []`` pattern has been removed from all CLI
subcommand modules in favour of the shared
:func:`olav.cli.commands._argparse.parse_subcommand_args` helper.

This is a **drift guard**: each ``olav.cli.commands.*`` module that
receives argparse REMAINDER args must import ``parse_subcommand_args``
instead of rolling its own shell-split.  Catches regressions where
someone adds a new subcommand module and forgets the helper.

Exemptions:

* ``_argparse.py`` — defines the helper itself
* ``shell_runner.py`` — uses a different input shape (no args.strip()
  guard because the callers never pass None)
* ``base.py``, ``__init__.py`` — no argument parsing
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_COMMANDS_DIR = Path(__file__).resolve().parents[2] / "src" / "olav" / "cli" / "commands"

_RAW_SHLEX_PATTERN = re.compile(r"shlex\.split\(\s*args(?:\.strip\(\))?", re.MULTILINE)
"""Matches the old pattern: shlex.split(args, shlex.split(args.strip(),
shlex.split(args.strip()) …"""

_EXEMPT_FILES: set[str] = {
    "_argparse.py",
    "shell_runner.py",
    "base.py",
    "__init__.py",
}


def _command_source_files() -> list[Path]:
    """Return every .py file under src/olav/cli/commands/ (excluding
    exempted utility modules)."""
    files = []
    for p in sorted(_COMMANDS_DIR.glob("*.py")):
        if p.name in _EXEMPT_FILES:
            continue
        files.append(p)
    return files


# ── 1. Helper is in the commands package ──────────────────────────────────


def test_helper_module_exists() -> None:
    helper = _COMMANDS_DIR / "_argparse.py"
    assert helper.is_file()


# ── 2. No non-exempt module uses raw shlex.split(args …) ─────────────────


@pytest.mark.parametrize("src_file", _command_source_files(), ids=lambda p: p.name)
def test_command_file_does_not_use_raw_shlex(src_file: Path) -> None:
    """Each command module must go through parse_subcommand_args
    instead of hand-rolling ``shlex.split(args.strip()) if … else []``."""
    source = src_file.read_text(encoding="utf-8")
    matches = _RAW_SHLEX_PATTERN.findall(source)
    assert not matches, (
        f"{src_file.name} still uses raw shlex.split pattern; "
        f"swap for parse_subcommand_args (found: {matches})"
    )


# ── 3. At least one import site for the helper exists ────────────────────


def test_helper_imported_somewhere() -> None:
    """Sanity check — the helper must be consumed by at least one
    command module, otherwise the refactor didn't actually land."""
    import_pattern = re.compile(
        r"from olav\.cli\.commands\._argparse import .*parse_subcommand_args",
    )
    for src_file in _command_source_files():
        if import_pattern.search(src_file.read_text(encoding="utf-8")):
            return
    pytest.fail("parse_subcommand_args not imported anywhere — refactor not applied")
