from __future__ import annotations

import sys


def test_init_subcommand_registered() -> None:
    old_argv = sys.argv[:]
    sys.argv = ["olav", "init"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "init"
    finally:
        sys.argv = old_argv


def test_workspace_subcommand_registered() -> None:
    old_argv = sys.argv[:]
    sys.argv = ["olav", "workspace", "status"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "workspace"
        assert args.args == ["status"]
    finally:
        sys.argv = old_argv


def test_export_subcommand_registered() -> None:
    old_argv = sys.argv[:]
    sys.argv = ["olav", "export", "claude-plugin", "--agent", "quick", "--output", "dist"]
    try:
        from olav.cli.main import parse_args

        args = parse_args()
        assert args.command == "export"
        assert args.args == ["claude-plugin", "--agent", "quick", "--output", "dist"]
    finally:
        sys.argv = old_argv