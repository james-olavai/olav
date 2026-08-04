"""Ownership manifest gate.

CLAUDE.md presents `scripts/scan_ownership.py` as a governance command that
"should be 0 ERROR", but until 2026-08-04 **nothing ran it** — not a test, not
either forge's workflow. It was a manual command, which is the same failure
shape as a CI step carrying `continue-on-error`: a check that cannot fail is not
a check. This file makes every governance run exercise it.

It also covers the vocabulary validation added the same day. The manifest
declares `owners`, `classes` and `statuses` at the top, but nothing verified
that rules used only those values, so three ad-hoc values had entered silently:
`owner: olav-post`, `class: content` and `class: audit`. The last one mattered
beyond tidiness — it re-introduced the audit-agent / audit-trail ambiguity that
dev_docs/31 had to untangle, and its own sibling rules already used
`class: netops`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "scan_ownership.py"


def _load_scan_module():
    spec = importlib.util.spec_from_file_location("scan_ownership", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[spec.name]
        raise
    return mod


def test_ownership_scan_passes():
    """0 ERROR and no vocabulary problems, from the real entry point."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--summary"],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    assert proc.returncode == 0, (
        "scan_ownership.py failed — every repo path must match a rule, and every "
        "rule must use the manifest's declared vocabulary:\n"
        + proc.stdout[-3000:] + proc.stderr[-2000:]
    )
    assert "SCHEMA" not in proc.stdout, proc.stdout[-2000:]


def test_vocabulary_validation_rejects_an_undeclared_value():
    """Prove the validator fires — a gate nobody has seen fail is not known to work."""
    mod = _load_scan_module()
    manifest = {"owners": ["olav"], "classes": ["platform"], "statuses": ["authoritative"]}
    bad = [
        {"pattern": "x/**", "owner": "nope", "class": "platform", "status": "authoritative"},
        {"pattern": "y/**", "owner": "olav", "class": "invented", "status": "authoritative"},
        {"pattern": "z/**", "owner": "olav", "class": "platform", "status": "authoritative",
         "git": "maybe"},
    ]
    problems = mod.validate_rule_vocabulary(manifest, bad)
    assert len(problems) == 3, problems
    joined = "\n".join(problems)
    assert "owner='nope'" in joined
    assert "class='invented'" in joined
    assert "git='maybe'" in joined


def test_a_clean_ruleset_reports_nothing():
    mod = _load_scan_module()
    manifest = {"owners": ["olav"], "classes": ["platform"], "statuses": ["authoritative"]}
    ok = [{"pattern": "x/**", "owner": "olav", "class": "platform",
           "status": "authoritative", "git": "track"}]
    assert mod.validate_rule_vocabulary(manifest, ok) == []
