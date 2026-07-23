"""Enterprise units must never reach the public monorepo mirror.

olav-ent / olav-presales / olav-post are proprietary or local-only. gitea (the
internal forge) keeps the full source, but the public GitHub monorepo mirror
(scripts/publish_github_mirrors.py) MUST strip them. These gates fail loudly if
someone removes the exclusion or re-licenses presales back to the BSL baseline
(dev_docs/106 — presales is the enterprise tier bundled with olav-ent).
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENTERPRISE_UNITS = ("olav-ent/", "olav-presales/", "olav-post/")


def test_public_mirror_strips_enterprise_units():
    src = (_ROOT / "scripts" / "publish_github_mirrors.py").read_text(encoding="utf-8")
    assert "_ENTERPRISE_UNIT_PATHS" in src
    for unit in _ENTERPRISE_UNITS:
        assert f'"{unit}"' in src, f"{unit} missing from _ENTERPRISE_UNIT_PATHS"
    # the exclusion must be wired into the filter-repo paths AND verified
    assert "_HISTORICAL_CRED_PATHS + _ENTERPRISE_UNIT_PATHS" in src
    assert "enterprise-unit files still in mirror history" in src


def test_presales_is_proprietary_not_bsl():
    txt = (_ROOT / "olav-presales" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = {text = "Proprietary"}' in txt
    assert 'license = {text = "BSL' not in txt, "presales must be Proprietary, not BSL"


def test_manifest_marks_presales_enterprise():
    txt = (_ROOT / "ownership_manifest.yaml").read_text(encoding="utf-8")
    assert "class: presales" not in txt, "presales must be class: enterprise, not the baseline class"
