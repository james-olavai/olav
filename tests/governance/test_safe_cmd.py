"""NETOPS-05: CLI-supplied command names can't escape raw_dir via path traversal.

``netops_init._collect_cmd`` derives a file path from the user-supplied
command string. The whitelist regex introduced for NETOPS-05 must drop any
character that could let ``--commands "../../etc/passwd"`` write outside
the intended ``raw_dir``.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from tests.governance._paths import NETOPS_INIT_DIR

REPO = Path(__file__).resolve().parents[2]
RUN_PY = NETOPS_INIT_DIR / "run.py"


def _safe_cmd(cmd: str) -> str:
    """Re-implement the sanitisation rule that production code uses."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", cmd)[:60]


def test_run_py_uses_whitelist_regex():
    src = RUN_PY.read_text(encoding="utf-8")
    assert 'safe_cmd = re.sub(r"[^a-zA-Z0-9_-]"' in src, (
        "run.py no longer uses the whitelist regex — NETOPS-05 regression. "
        "Do NOT revert to str.replace-based sanitisation: that lets "
        "'--commands ..' write outside raw_dir."
    )


def test_safe_cmd_strips_path_traversal():
    assert ".." not in _safe_cmd("..")
    assert "/" not in _safe_cmd("../etc/passwd")
    assert "\\" not in _safe_cmd("..\\windows\\system32")
    assert "\x00" not in _safe_cmd("cmd\x00injection")


def test_safe_cmd_preserves_normal_commands():
    assert _safe_cmd("show version") == "show_version"
    assert _safe_cmd("show ip interface brief") == "show_ip_interface_brief"


def test_safe_cmd_capped_at_60_chars():
    assert len(_safe_cmd("a" * 200)) == 60
