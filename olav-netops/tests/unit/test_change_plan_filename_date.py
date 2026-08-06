"""The date in a change-plan filename comes from Python, not from the model.

Observed on the demo VM: a plan drafted 2026-08-06 was written as
`redundant_bgp_alpha_20231027.md`. The content was right — correct peer AS,
rollback, verification — and only the name lied, which is the worst place for it
to happen, because the filename is what an operator sorts, greps and cites by.

The model used to supply the whole basename. A date is a fact the process knows
and the model does not, so the process supplies it. Anything date-shaped the
model tacked on is stripped first, so a well-behaved model does not end up with
two dates in one name.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".olav/workspace/netops/analyzer/scripts/generate_change_plan.py"
)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("gcp_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - needs olav importable
        pytest.skip(f"cannot load {_SCRIPT.name}: {exc}")
    return module


@pytest.fixture
def today() -> str:
    return datetime.now().strftime("%Y%m%d")


class TestTodaysDateIsStamped:
    def test_a_name_without_a_date_gets_one(self, mod, today):
        assert mod._dated_stem("redundant_bgp_alpha") == f"redundant_bgp_alpha_{today}"

    def test_the_models_invented_date_is_replaced(self, mod, today):
        """The exact observed failure."""
        out = mod._dated_stem("redundant_bgp_alpha_20231027")
        assert out == f"redundant_bgp_alpha_{today}"
        assert "20231027" not in out

    @pytest.mark.parametrize(
        "supplied",
        ["plan_20231027", "plan_2023-10-27", "plan_2023_10_27", "plan_202310", "plan-20231027"],
    )
    def test_date_shapes_are_all_stripped(self, mod, today, supplied):
        """A model writes dates several ways; none should survive into the name
        alongside the real one."""
        out = mod._dated_stem(supplied)
        assert out == f"plan_{today}", out
        assert out.count(today) == 1

    def test_a_hyphenated_model_name_is_not_mistaken_for_a_date(self, mod, today):
        """`WS-C4500X` and `N9K` must survive — stripping too eagerly would
        mangle the part of the name that carries the meaning."""
        out = mod._dated_stem("WS-C4500X_BFS_staged_upgrade_plan")
        assert out == f"WS-C4500X_BFS_staged_upgrade_plan_{today}"

    def test_an_empty_name_still_produces_a_usable_file(self, mod, today):
        assert mod._dated_stem("") == f"change_plan_{today}"
        assert mod._dated_stem("   ") == f"change_plan_{today}"

    def test_surrounding_whitespace_and_separators_are_trimmed(self, mod, today):
        assert mod._dated_stem("  spaced_  ") == f"spaced_{today}"


def test_the_writer_uses_the_helper():
    """Wiring: the helper is inert unless the output path goes through it."""
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "_dated_stem(output_filename)" in src, (
        "generate_change_plan still writes the model's basename verbatim"
    )
    assert 'out_dir / f"{output_filename}.md"' not in src, (
        "the un-dated path construction is back"
    )
