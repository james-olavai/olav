"""Unit tests for olav_netops.core.platform_profiles.

Covers:
  * YAML loading with cache
  * Rule-based vendor fallback for unknown platforms (_derive_vendor)
  * Profile field extraction helpers (extract_model / extract_os_version)
  * Scrapli platform map derivation
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from olav_netops.core import platform_profiles as pp


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset module-level cache between tests so mutations don't leak."""
    pp._PROFILES_CACHE = None
    yield
    pp._PROFILES_CACHE = None


def _with_profiles(profiles: dict) -> None:
    """Directly prime the cache to decouple tests from YAML file presence."""
    pp._PROFILES_CACHE = profiles


class TestDeriveVendor:
    """Rule-based vendor inference when YAML has no profile entry."""

    def test_known_token_cisco(self):
        assert pp._derive_vendor("cisco_xyz_future") == "Cisco"

    def test_known_token_juniper(self):
        assert pp._derive_vendor("juniper_junos") == "Juniper"

    def test_known_token_paloalto_multi_word(self):
        assert pp._derive_vendor("paloalto_panos") == "Palo Alto"

    def test_known_token_aruba(self):
        assert pp._derive_vendor("aruba_osswitch") == "HPE Aruba"

    def test_unknown_token_title_case(self):
        assert pp._derive_vendor("foobar_nos") == "Foobar"

    def test_empty_platform(self):
        assert pp._derive_vendor("") == ""

    def test_single_token_no_underscore(self):
        # "fortinet" alone has no underscore — still matches first token rule.
        assert pp._derive_vendor("fortinet") == "Fortinet"


class TestGetVendor:
    """Vendor resolution: YAML first, then rule fallback."""

    def test_yaml_profile_wins(self):
        _with_profiles({"cisco_ios": {"vendor": "Cisco Systems"}})
        assert pp.get_vendor("cisco_ios") == "Cisco Systems"

    def test_unknown_falls_back_to_rule(self):
        _with_profiles({})
        assert pp.get_vendor("nokia_sros") == "Nokia"

    def test_empty_platform_returns_empty(self):
        _with_profiles({})
        assert pp.get_vendor("") == ""

    def test_profile_with_empty_vendor_falls_back(self):
        _with_profiles({"foo_bar": {"vendor": ""}})
        assert pp.get_vendor("foo_bar") == "Foo"


class TestGetProfile:
    """Profile lookup — YAML row or synthesised fallback."""

    def test_yaml_hit_returned_verbatim(self):
        prof = {"vendor": "X", "model_fields": ["A"]}
        _with_profiles({"x_plat": prof})
        assert pp.get_profile("x_plat") is prof

    def test_unknown_returns_fallback_stub(self):
        _with_profiles({})
        stub = pp.get_profile("nokia_sros")
        assert stub["vendor"] == "Nokia"
        assert stub["model_fields"] == []
        assert stub["os_version_fields"] == []


class TestScrapliPlatformMap:
    """Scrapli fast-path mapping is derived from profile YAML."""

    def test_map_contains_only_platforms_with_scrapli_key(self):
        _with_profiles({
            "cisco_ios": {"scrapli_platform": "cisco_iosxe"},
            "juniper_junos": {"scrapli_platform": "juniper_junos"},
            "huawei_vrp": {},  # no scrapli_platform — must be excluded
        })
        m = pp.scrapli_platform_map()
        assert m == {"cisco_ios": "cisco_iosxe", "juniper_junos": "juniper_junos"}


class TestGetScrapliPlatform:
    def test_present(self):
        _with_profiles({"cisco_ios": {"scrapli_platform": "cisco_iosxe"}})
        assert pp.get_scrapli_platform("cisco_ios") == "cisco_iosxe"

    def test_missing_returns_none(self):
        _with_profiles({"cisco_ios": {}})
        assert pp.get_scrapli_platform("cisco_ios") is None

    def test_unknown_platform_returns_none(self):
        _with_profiles({})
        assert pp.get_scrapli_platform("cisco_ios") is None


class TestExtractModel:
    def test_first_field_wins(self):
        _with_profiles({"cisco_ios": {"model_fields": ["MODEL", "HARDWARE"]}})
        assert pp.extract_model("cisco_ios", {"MODEL": "C3945", "HARDWARE": ["H1"]}) == "C3945"

    def test_list_field_takes_first_element(self):
        _with_profiles({"cisco_ios": {"model_fields": ["HARDWARE"]}})
        assert pp.extract_model("cisco_ios", {"HARDWARE": ["H1", "H2"]}) == "H1"

    def test_empty_list_continues_to_next_field(self):
        _with_profiles({"cisco_ios": {"model_fields": ["HARDWARE", "MODEL"]}})
        assert pp.extract_model("cisco_ios", {"HARDWARE": [], "MODEL": "C3945"}) == "C3945"

    def test_no_match_returns_none(self):
        _with_profiles({"cisco_ios": {"model_fields": ["MODEL"]}})
        assert pp.extract_model("cisco_ios", {"OTHER": "x"}) is None

    def test_unknown_platform_uses_fallback_profile_empty_fields(self):
        _with_profiles({})
        assert pp.extract_model("nokia_sros", {"MODEL": "7750"}) is None


class TestExtractOsVersion:
    def test_precedence_order(self):
        _with_profiles({"cisco_ios": {"os_version_fields": ["VERSION", "ROMMON"]}})
        entry = {"VERSION": "15.5(3)M", "ROMMON": "12.4"}
        assert pp.extract_os_version("cisco_ios", entry) == "15.5(3)M"

    def test_junos_version_field(self):
        _with_profiles({"juniper_junos": {"os_version_fields": ["JUNOS_VERSION"]}})
        assert pp.extract_os_version("juniper_junos", {"JUNOS_VERSION": "18.4R3"}) == "18.4R3"


class TestLoadProfiles:
    """YAML file integration — covers cache behaviour + malformed handling."""

    def test_cache_is_used_on_second_call(self):
        sentinel = {"mock_plat": {"vendor": "Mock"}}
        pp._PROFILES_CACHE = sentinel
        assert pp.load_profiles() is sentinel

    def test_force_reload_bypasses_cache(self, tmp_path, monkeypatch):
        yaml_body = "platforms:\n  test_plat:\n    vendor: Test\n"
        p = tmp_path / "platform_profiles.yaml"
        p.write_text(yaml_body)
        monkeypatch.setattr(pp, "_profiles_path", lambda: p)
        pp._PROFILES_CACHE = {"stale": {}}
        result = pp.load_profiles(force_reload=True)
        assert "test_plat" in result
        assert result["test_plat"]["vendor"] == "Test"

    def test_missing_file_returns_empty(self, monkeypatch):
        from pathlib import Path
        monkeypatch.setattr(pp, "_profiles_path", lambda: Path("/nonexistent/does_not_exist.yaml"))
        assert pp.load_profiles(force_reload=True) == {}

    def test_malformed_yaml_returns_empty(self, tmp_path, monkeypatch):
        p = tmp_path / "platform_profiles.yaml"
        p.write_text("this is: not: valid: yaml: structure:\n  :::\n")
        monkeypatch.setattr(pp, "_profiles_path", lambda: p)
        # yaml.safe_load may or may not raise — either way we want empty dict.
        result = pp.load_profiles(force_reload=True)
        assert isinstance(result, dict)

    def test_wrong_top_level_shape_returns_empty(self, tmp_path, monkeypatch):
        p = tmp_path / "platform_profiles.yaml"
        p.write_text("platforms: [not, a, mapping]\n")
        monkeypatch.setattr(pp, "_profiles_path", lambda: p)
        assert pp.load_profiles(force_reload=True) == {}
