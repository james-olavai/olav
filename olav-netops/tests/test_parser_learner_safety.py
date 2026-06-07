"""Unit tests for olav_netops.core.parser_learner.ast_safety_check.

R70 inlined the AST safety check from the (deleted) etl_discovery module.
These tests pin the allowlist + banlist so future LLM prompt changes
can't silently broaden the accepted surface.
"""
from __future__ import annotations

import pytest

from olav_netops.core.parser_learner import (
    ast_safety_check,
    _ALLOWED_MODULES,
    _BANNED_NAMES,
)


# ──────────────────────────────────────────────────────────────────────────
# Allowed patterns
# ──────────────────────────────────────────────────────────────────────────

class TestAllowed:
    def test_simple_function(self):
        ok, reason = ast_safety_check("def f(x):\n    return x + 1\n")
        assert ok, reason

    def test_import_re(self):
        ok, reason = ast_safety_check("import re\npat = re.compile(r'foo')\n")
        assert ok, reason

    def test_import_json(self):
        ok, _ = ast_safety_check("import json\nd = json.loads('{}')\n")
        assert ok

    def test_from_typing(self):
        ok, _ = ast_safety_check("from typing import List\n")
        assert ok

    def test_from_dataclasses(self):
        ok, _ = ast_safety_check(
            "from dataclasses import dataclass\n"
            "@dataclass\nclass C:\n    x: int = 0\n"
        )
        assert ok

    def test_from_netutils(self):
        """R68 added netutils for IP / interface normalisation."""
        ok, reason = ast_safety_check(
            "from netutils.interface import canonical_interface_name\n"
        )
        assert ok, reason

    def test_nested_from_submodule(self):
        ok, _ = ast_safety_check("from re import compile, match\n")
        assert ok

    def test_comprehensions_and_lambdas(self):
        ok, _ = ast_safety_check(
            "squares = [x * x for x in range(10)]\n"
            "f = lambda a, b: a + b\n"
        )
        assert ok

    def test_raise_and_try(self):
        ok, _ = ast_safety_check(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('x')\n"
            "    except ValueError:\n"
            "        return None\n"
        )
        assert ok


# ──────────────────────────────────────────────────────────────────────────
# Banned module imports
# ──────────────────────────────────────────────────────────────────────────

class TestBannedImports:
    @pytest.mark.parametrize("module", ["os", "sys", "subprocess", "shutil",
                                        "socket", "urllib", "requests", "httpx",
                                        "pathlib"])
    def test_top_level_import_blocked(self, module):
        ok, reason = ast_safety_check(f"import {module}\n")
        assert not ok
        assert "allowlist" in reason

    def test_os_path_blocked_via_import(self):
        ok, reason = ast_safety_check("import os.path\n")
        assert not ok
        assert "os" in reason

    def test_from_os_import_blocked(self):
        ok, reason = ast_safety_check("from os import getcwd\n")
        assert not ok
        assert "allowlist" in reason

    def test_from_subprocess_blocked(self):
        ok, _ = ast_safety_check("from subprocess import run\n")
        assert not ok


# ──────────────────────────────────────────────────────────────────────────
# Banned names (variables / direct references)
# ──────────────────────────────────────────────────────────────────────────

class TestBannedNames:
    def test_eval_rejected(self):
        ok, reason = ast_safety_check("x = eval('1+1')\n")
        assert not ok
        assert "eval" in reason

    def test_exec_rejected(self):
        ok, reason = ast_safety_check("exec('x = 1')\n")
        assert not ok
        assert "exec" in reason

    def test_compile_rejected(self):
        ok, _ = ast_safety_check("x = compile('1', '<s>', 'eval')\n")
        assert not ok

    def test_open_rejected(self):
        ok, reason = ast_safety_check("f = open('/etc/passwd')\n")
        assert not ok
        assert "open" in reason

    def test_dunder_import_rejected(self):
        ok, reason = ast_safety_check("m = __import__('os')\n")
        assert not ok
        assert "__import__" in reason

    def test_input_rejected(self):
        ok, _ = ast_safety_check("x = input('prompt')\n")
        assert not ok


# ──────────────────────────────────────────────────────────────────────────
# Banned attribute access
# ──────────────────────────────────────────────────────────────────────────

class TestBannedAttributes:
    def test_os_attr_rejected(self):
        ok, reason = ast_safety_check("x = os.getenv('HOME')\n")
        assert not ok
        assert "os" in reason

    def test_subprocess_run_rejected(self):
        ok, reason = ast_safety_check("subprocess.run(['ls'])\n")
        assert not ok
        assert "subprocess" in reason

    def test_nested_attr_on_banned_root(self):
        ok, _ = ast_safety_check("x = os.path.exists('/tmp')\n")
        assert not ok


# ──────────────────────────────────────────────────────────────────────────
# Banned introspection calls
# ──────────────────────────────────────────────────────────────────────────

class TestBannedIntrospection:
    @pytest.mark.parametrize("fn", ["getattr", "setattr", "delattr",
                                    "globals", "locals", "vars"])
    def test_introspection_call_rejected(self, fn):
        src = f"x = {fn}(1)\n" if fn in {"globals", "locals", "vars"} else f"x = {fn}(1, 'a')\n"
        ok, reason = ast_safety_check(src)
        assert not ok
        assert fn in reason


# ──────────────────────────────────────────────────────────────────────────
# Syntax errors / invalid input
# ──────────────────────────────────────────────────────────────────────────

class TestSyntaxErrors:
    def test_syntax_error_rejected(self):
        ok, reason = ast_safety_check("def :\n")
        assert not ok
        assert "SyntaxError" in reason

    def test_empty_string_accepted(self):
        """Empty source parses to empty module — not dangerous."""
        ok, _ = ast_safety_check("")
        assert ok


# ──────────────────────────────────────────────────────────────────────────
# Allow/ban lists are frozen constants (regression guard)
# ──────────────────────────────────────────────────────────────────────────

class TestConstants:
    def test_allowlist_contains_core_modules(self):
        for m in ("json", "re", "typing", "dataclasses"):
            assert m in _ALLOWED_MODULES

    def test_banlist_contains_exec_primitives(self):
        for n in ("exec", "eval", "__import__", "compile", "open"):
            assert n in _BANNED_NAMES

    def test_banlist_contains_io_modules(self):
        for n in ("os", "sys", "subprocess", "shutil", "socket"):
            assert n in _BANNED_NAMES

    def test_no_overlap_between_allow_and_ban(self):
        assert _ALLOWED_MODULES.isdisjoint(_BANNED_NAMES)
