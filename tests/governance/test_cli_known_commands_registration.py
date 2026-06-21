"""Regression pin: every subparser registered on the root CLI must also
appear in the ``known_commands`` set used by the NL-query fast-path.

Background (T1 update, post-Round-60):

``src/olav/cli/main.py`` has a pre-parser at line ~98 that decides
whether the first positional is a subcommand (`olav catalog show`) or
a natural-language query (`olav "list all devices"`). The decision is
made by checking membership in ``known_commands``. Any subparser
missing from that set falls through to the NL-query path, which then
fires the auth gate — so even ``olav <subcommand> --help`` prints
``Not authenticated``.

This pin enumerates the ``build_*_parser`` registrations in
``main.py`` and requires every one to be in ``known_commands``. Caught
a real bug during the Tier-1 update where R25 (catalog), R45 (explain),
and R47 (diff) had been added to the subparser wiring but not to
``known_commands``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAIN_PY = REPO / "src" / "olav" / "cli" / "main.py"


def _extract_known_commands(src: str) -> set[str]:
    tree = ast.parse(src)
    for node in tree.body:
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_KNOWN_COMMANDS":
                value = node.value
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "_KNOWN_COMMANDS" for t in node.targets):
                value = node.value
        if value is None:
            continue
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset":
            if value.args:
                value = value.args[0]
        if isinstance(value, ast.Set):
            out = {
                elt.value for elt in value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
            if out:
                return out
    assert False, "_KNOWN_COMMANDS frozenset literal not found in cli/main.py"


def _extract_subparser_registrations(src: str) -> set[str]:
    """Commands registered directly via ``subparsers.add_parser("name", ...)``."""
    return set(re.findall(r'subparsers\.add_parser\(\s*"([^"]+)"', src))


def _extract_plugin_parser_modules(src: str) -> set[str]:
    """Commands registered via ``build_<name>_parser(subparsers)`` helpers.

    Each helper in ``src/olav/cli/commands/<name>.py`` adds a single
    subparser — by convention its name equals the module name (except
    where an override is visible in the module itself).
    """
    return set(re.findall(r"build_([a-z_]+)_parser\(subparsers\)", src))


def test_known_commands_superset_covers_all_subparsers():
    src = MAIN_PY.read_text(encoding="utf-8")
    known = _extract_known_commands(src)
    direct = _extract_subparser_registrations(src)
    missing = direct - known - {"log", "admin"}  # admin is in known already
    assert not missing, (
        f"Subparser registered but missing from known_commands: {sorted(missing)}\n"
        f"These would fall through to the NL-query fast-path and fire auth "
        f"even on ``--help``."
    )


def test_known_commands_covers_plugin_parsers():
    src = MAIN_PY.read_text(encoding="utf-8")
    known = _extract_known_commands(src)
    # Each build_X_parser(subparsers) registers a subcommand named X. Python
    # helper names can't contain hyphens, so build_trace_review_parser registers
    # the hyphenated command "trace-review"; accept either form in known.
    plugin = _extract_plugin_parser_modules(src)
    missing = {m for m in plugin if m not in known and m.replace("_", "-") not in known}
    assert not missing, (
        f"Plugin-style subparser(s) missing from known_commands: "
        f"{sorted(missing)}.\nAdd them to the set in cli/main.py so "
        f"``olav <name> --help`` doesn't misroute to NL-query."
    )


def test_round60_cli_shortcuts_specifically_covered():
    """Pin the three that prompted this test: catalog (R25), explain
    (R45), diff (R47)."""
    src = MAIN_PY.read_text(encoding="utf-8")
    known = _extract_known_commands(src)
    for cmd in ("catalog", "explain", "diff"):
        assert cmd in known, (
            f"{cmd!r} missing from known_commands — regression on the "
            f"Tier-1-discovered fix during Round 60."
        )


def test_known_commands_all_present_as_subparsers():
    """Reverse direction: every entry in known_commands should point at
    a real subparser. Stale entries (removed subcommand left in the
    set) are harmless but indicate drift."""
    src = MAIN_PY.read_text(encoding="utf-8")
    known = _extract_known_commands(src)
    direct = _extract_subparser_registrations(src)
    plugin = _extract_plugin_parser_modules(src)
    registered = direct | plugin
    # build_X_parser helper names use underscores (Python identifiers) but the
    # command they register may be hyphenated (e.g. build_trace_review_parser →
    # "trace-review"); count both forms as registered.
    registered |= {r.replace("_", "-") for r in registered}
    # A handful of entries in known_commands are intentionally not
    # subparsers — they're legacy command names kept for parsing
    # detection only. Allow-list them explicitly.
    allowed_without_subparser: set[str] = {"help", "reset"}
    orphans = known - registered - allowed_without_subparser
    assert not orphans, (
        f"known_commands lists entries with no matching subparser: "
        f"{sorted(orphans)}. Either register the subparser or remove "
        f"from the set (or add to allowed_without_subparser with reason)."
    )
