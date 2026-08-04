"""Every shipped ``*.example`` config template must actually parse.

``.olav/config/api.json.example`` shipped with an unescaped ``"`` inside the
``_batfish_doc`` string, so the file had been invalid JSON in git. Nothing
caught it: no test had ever opened a template. The templates are the one
thing a new user is told to copy — ``cp api.json.example api.json`` handed
them a config the loader cannot read.

These are static asset files with no import side effects, so the check is a
plain parse. It is deliberately driven off ``git ls-files`` rather than a
hardcoded list: a template that is added later and never parsed is exactly
the failure this guards against.
"""
from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from ._paths import REPO


def _tracked_examples() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "*.example"],
        capture_output=True, text=True, check=True,
    ).stdout
    return sorted(ln for ln in out.splitlines() if ln)


_EXAMPLES = _tracked_examples()


def test_examples_are_discovered():
    """Guard the guard — an empty glob would make every case below vacuous."""
    assert _EXAMPLES, "no tracked *.example templates found; has the glob broken?"


@pytest.mark.parametrize("rel", _EXAMPLES)
def test_example_template_parses(rel: str):
    path = REPO / rel
    text = path.read_text(encoding="utf-8")

    # Strip the doubled suffix: foo.json.example -> .json
    suffix = path.with_suffix("").suffix.lower()

    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{rel} is not valid JSON: {exc}")
    elif suffix in (".yaml", ".yml"):
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            pytest.fail(f"{rel} is not valid YAML: {exc}")
    else:
        pytest.fail(
            f"{rel} has unrecognised template type {suffix!r} — add a parser "
            f"for it here, or the template ships unvalidated"
        )
