"""An exported filename must not carry a date the model made up.

Twice on the demo VM, a change plan drafted 2026-08-06 was written as
`redundant_ebgp_uplink_alpha_20250522.md` and `redundant_bgp_alpha_20231027.md`.
The content was right both times — correct peer AS, rollback, verification — and
only the name lied. That is the worst place for it, because the filename is what
an operator sorts, greps and cites by, and nothing in the file contradicts it.

A date is a fact the process knows and the model does not, so the process
corrects it. The correction is deliberately narrow, and the narrowness is the
design:

* only a date-shaped token that is **not** today's is replaced;
* the separator style the model chose is preserved, because the same run also
  produced `core_topology_2026-08-06.drawio` with the date *correct* — renaming
  that into another convention would be a regression dressed as a fix;
* a filename with no date is left alone. Stamping every export would be
  intrusive, and query CSVs already carry their own timestamp.

The first attempt at this fix landed in the wrong place. `generate_change_plan`
also lets the model name the file, so it was patched there — but the VM run
showed the plan is written through `format_and_export`, which the model reached
instead. Verifying at the real entry point is what caught it; the unit tests had
passed.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_TOOL = (
    Path(__file__).resolve().parents[1].parent
    / "src/olav/data/workspace/core/tools/format_and_export.py"
)


@pytest.fixture(scope="module")
def fae():
    spec = importlib.util.spec_from_file_location("fae_under_test", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot load format_and_export: {exc}")
    return mod


@pytest.fixture
def now():
    return datetime.now()


class TestAWrongDateIsCorrected:
    def test_the_observed_failure(self, fae, now):
        out = fae._correct_wrong_date("redundant_ebgp_uplink_alpha_20250522")
        assert out == f"redundant_ebgp_uplink_alpha_{now:%Y%m%d}"
        assert "20250522" not in out

    def test_the_earlier_observed_failure(self, fae, now):
        out = fae._correct_wrong_date("redundant_bgp_alpha_20231027")
        assert out == f"redundant_bgp_alpha_{now:%Y%m%d}"

    def test_the_separator_style_survives(self, fae, now):
        """Only the digits move; the model's formatting choice is kept."""
        assert fae._correct_wrong_date("plan_2023-10-27") == f"plan_{now:%Y-%m-%d}"
        assert fae._correct_wrong_date("plan_2023_10_27") == f"plan_{now:%Y_%m_%d}"


class TestWhatMustNotBeTouched:
    def test_a_correct_date_is_left_exactly_as_written(self, fae, now):
        """`core_topology_2026-08-06.drawio` came out of the same run with the
        date right. Rewriting it would break an established convention."""
        name = f"core_topology_{now:%Y-%m-%d}"
        assert fae._correct_wrong_date(name) == name

    def test_a_filename_with_no_date_gains_none(self, fae):
        for name in ("interface_health_report", "bgp_summary", "export"):
            assert fae._correct_wrong_date(name) == name

    def test_a_model_number_is_not_read_as_a_date(self, fae):
        """Stripping too eagerly would mangle the part of the name that carries
        the meaning."""
        for name in ("WS-C4500X_upgrade", "N9K-C93180_fabric", "ISR4331_plan"):
            assert fae._correct_wrong_date(name) == name

    def test_an_already_correct_timestamp_is_untouched(self, fae, now):
        name = f"query_{now:%Y%m%d}_180416"
        assert fae._correct_wrong_date(name) == name

    def test_only_the_first_date_token_is_considered(self, fae, now):
        """Two dates in one name is ambiguous; rewriting both could turn a
        range like `report_20230101_20231231` into nonsense."""
        out = fae._correct_wrong_date("report_20230101_20231231")
        assert out.count(f"{now:%Y%m%d}") == 1


class TestWiring:
    def test_the_tool_applies_the_correction(self):
        src = _TOOL.read_text(encoding="utf-8")
        assert "_correct_wrong_date(filename)" in src, (
            "the helper is inert unless format_and_export runs the filename "
            "through it"
        )

    def test_the_correction_runs_before_the_path_safety_check(self):
        """Order matters: rewriting after the `..`/absolute-path rejection would
        let a correction reintroduce something the check had refused."""
        src = _TOOL.read_text(encoding="utf-8")
        assert src.index("_correct_wrong_date(filename)") < src.index(
            'if ".." in filename or filename.startswith("/")'
        )
