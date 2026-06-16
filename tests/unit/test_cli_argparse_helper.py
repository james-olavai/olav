"""
tests/unit/test_cli_argparse_helper.py
──────────────────────────────────────
Unit coverage for src/olav/cli/commands/_argparse.py.

``parse_subcommand_args`` is the shared helper that replaces the
repeated ``import shlex; shlex.split(args.strip() or '')`` pattern in
~10 CLI command modules (audit in dev_docs/50 §12.1 Phase 3 cleanup).
Centralising it:

  - lets every subcommand handle ``None`` / empty / whitespace-only
    input uniformly (currently duplicated in each file)
  - gives one obvious place to tune quoting behaviour (the ``posix=``
    flag matters on Windows; inconsistent defaults in different files
    would cause subtle bugs)
  - becomes the shared test surface for ``--`` separator handling

This test is written FIRST (TDD red phase); implementation follows.
"""

from __future__ import annotations

import pytest


# ── 1. Module/symbol importable ─────────────────────────────────────────────


def test_module_importable() -> None:
    from olav.cli.commands import _argparse

    assert callable(_argparse.parse_subcommand_args)


# ── 2. None / empty / whitespace safety ─────────────────────────────────────


def test_none_returns_empty_list() -> None:
    """argparse's REMAINDER gives ``None`` when the user provides no
    trailing args.  The helper must not crash."""
    from olav.cli.commands._argparse import parse_subcommand_args

    assert parse_subcommand_args(None) == []


def test_empty_string_returns_empty_list() -> None:
    from olav.cli.commands._argparse import parse_subcommand_args

    assert parse_subcommand_args("") == []


def test_whitespace_only_returns_empty_list() -> None:
    from olav.cli.commands._argparse import parse_subcommand_args

    assert parse_subcommand_args("   \t  \n") == []


# ── 3. Shell-split preserves quoted spans ───────────────────────────────────


def test_quoted_arg_with_spaces_stays_one_token() -> None:
    """Skill names / workspace paths can contain spaces when
    quoted on the command line."""
    from olav.cli.commands._argparse import parse_subcommand_args

    parts = parse_subcommand_args("install '/path/with spaces/pkg'")
    assert parts == ["install", "/path/with spaces/pkg"]


def test_double_quoted_arg() -> None:
    from olav.cli.commands._argparse import parse_subcommand_args

    parts = parse_subcommand_args('install "/abs/path with spaces"')
    assert parts == ["install", "/abs/path with spaces"]


def test_flags_passed_through() -> None:
    from olav.cli.commands._argparse import parse_subcommand_args

    parts = parse_subcommand_args(
        "install /path/pkg --merge-into target --force"
    )
    assert parts == [
        "install",
        "/path/pkg",
        "--merge-into",
        "target",
        "--force",
    ]


# ── 4. Accepts list input transparently ────────────────────────────────────


def test_accepts_list_input_unchanged() -> None:
    """argparse occasionally delivers pre-split list (when nargs='*'
    rather than REMAINDER).  The helper should accept either form."""
    from olav.cli.commands._argparse import parse_subcommand_args

    # A list passed in comes back filtered of empties but otherwise intact.
    parts = parse_subcommand_args(["install", "", "  ", "/path"])
    assert parts == ["install", "/path"]


def test_accepts_tuple_input() -> None:
    from olav.cli.commands._argparse import parse_subcommand_args

    parts = parse_subcommand_args(("install", "/path"))
    assert parts == ["install", "/path"]


# ── 5. Malformed quoting degrades gracefully ────────────────────────────────


def test_unmatched_quote_raises_valueerror() -> None:
    """shlex raises ValueError on unmatched quotes.  The helper
    re-raises so the caller can surface a clean error message
    instead of crashing inside shell-split internals."""
    from olav.cli.commands._argparse import parse_subcommand_args

    with pytest.raises(ValueError, match=r"(?i)(quotation|quote)"):
        parse_subcommand_args("install 'unterminated")
