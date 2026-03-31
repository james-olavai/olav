"""Test that 'olav log' sub-commands are wired in the argparse definition."""
from __future__ import annotations

import sys
import types


def _get_parser():
    """Import and return the argparse parser without executing CLI."""
    # parse_args() calls sys.exit on -h; just call the inner builder
    import importlib

    spec = importlib.util.find_spec("olav.cli.main")
    assert spec is not None

    # We need just parse_args — simulate sys.argv so the pre-parser takes the
    # "log" branch without falling into interactive / query mode.
    old_argv = sys.argv[:]
    sys.argv = ["olav", "log"]
    try:
        from olav.cli.main import parse_args

        return parse_args
    finally:
        sys.argv = old_argv


def test_log_subcommand_registered():
    """'olav log' must be a recognised subcommand (no SystemExit)."""
    import sys

    old_argv = sys.argv[:]
    sys.argv = ["olav", "log"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "log"
    except SystemExit as exc:
        raise AssertionError(
            f"'olav log' caused SystemExit({exc.code}); subcommand not registered"
        ) from exc
    finally:
        sys.argv = old_argv


def test_log_show_subcommand():
    """'olav log show <run_id>' must parse correctly."""
    import sys

    old_argv = sys.argv[:]
    sys.argv = ["olav", "log", "show", "abc-123"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "log"
        assert getattr(args, "log_command", None) == "show"
        assert args.run_id == "abc-123"
    except SystemExit as exc:
        raise AssertionError(
            f"'olav log show' caused SystemExit({exc.code})"
        ) from exc
    finally:
        sys.argv = old_argv


def test_log_errors_subcommand():
    """'olav log errors' must parse correctly."""
    import sys

    old_argv = sys.argv[:]
    sys.argv = ["olav", "log", "errors"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "log"
        assert getattr(args, "log_command", None) == "errors"
    except SystemExit as exc:
        raise AssertionError(
            f"'olav log errors' caused SystemExit({exc.code})"
        ) from exc
    finally:
        sys.argv = old_argv
