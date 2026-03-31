"""Tests for Pydantic validation + LLM self-heal loop (OC-5).

TDD cycle: validate mapped data against OC Pydantic models,
auto-feed ValidationError to LLM for correction on failure.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError


class TestValidateAndHealImport:
    def test_import(self):
        from olav.core.schema_validation import validate_and_heal

        assert callable(validate_and_heal)


class TestValidateAndHealSuccess:
    def test_valid_interface_passes(self):
        from olav.core.schema_validation import validate_and_heal

        data = {
            "name": "eth0",
            "state": {
                "name": "eth0",
                "oper-status": "UP",
                "admin-status": "UP",
                "mtu": 1500,
            },
        }
        result = validate_and_heal(data, "interface")
        assert result["valid"] is True
        assert result["data"]["name"] == "eth0"
        assert result["healed"] is False

    def test_valid_bgp_neighbor_passes(self):
        from olav.core.schema_validation import validate_and_heal

        data = {
            "neighbor-address": "10.0.0.1",
            "state": {
                "neighbor-address": "10.0.0.1",
                "peer-as": 65001,
                "session-state": "ESTABLISHED",
            },
        }
        result = validate_and_heal(data, "bgp_neighbor")
        assert result["valid"] is True

    def test_valid_lldp_interface_passes(self):
        from olav.core.schema_validation import validate_and_heal

        data = {
            "name": "eth0",
            "neighbors": [{"state": {"system-name": "switch1", "port-id": "Gi0/1"}}],
        }
        result = validate_and_heal(data, "lldp_interface")
        assert result["valid"] is True


class TestValidateAndHealFailure:
    def test_missing_required_field_triggers_heal(self):
        from olav.core.schema_validation import validate_and_heal

        data = {"state": {"oper-status": "UP"}}
        result = validate_and_heal(data, "interface", max_retries=0)
        assert result["valid"] is False
        assert "errors" in result

    def test_wrong_type_triggers_heal(self):
        from olav.core.schema_validation import validate_and_heal

        data = {
            "name": "eth0",
            "state": {"name": "eth0", "mtu": "not_a_number"},
        }
        result = validate_and_heal(data, "interface", max_retries=0)
        assert result["valid"] is False


class TestSelfHealLoop:
    @patch("olav.core.llm.LLMFactory")
    def test_heal_retries_with_llm(self, mock_factory):
        from olav.core.schema_validation import validate_and_heal

        fixed_data = {
            "name": "eth0",
            "state": {"name": "eth0", "oper-status": "UP"},
        }
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=json.dumps(fixed_data))
        mock_factory.get_chat_model.return_value = mock_llm

        bad_data = {"state": {"oper-status": "UP"}}
        result = validate_and_heal(bad_data, "interface", max_retries=2)

        assert result["valid"] is True
        assert result["healed"] is True
        mock_llm.invoke.assert_called_once()

    @patch("olav.core.llm.LLMFactory")
    def test_heal_exhausts_retries(self, mock_factory):
        from olav.core.schema_validation import validate_and_heal

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"bad": "data"}')
        mock_factory.get_chat_model.return_value = mock_llm

        bad_data = {"state": {"oper-status": "UP"}}
        result = validate_and_heal(bad_data, "interface", max_retries=2)

        assert result["valid"] is False
        assert mock_llm.invoke.call_count == 2

    @patch("olav.core.llm.LLMFactory")
    def test_heal_prompt_contains_validation_error(self, mock_factory):
        from olav.core.schema_validation import validate_and_heal

        fixed_data = {
            "name": "eth0",
            "state": {"name": "eth0"},
        }
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=json.dumps(fixed_data))
        mock_factory.get_chat_model.return_value = mock_llm

        bad_data = {"state": {"name": "eth0"}}
        validate_and_heal(bad_data, "interface", max_retries=1)

        prompt_text = mock_llm.invoke.call_args[0][0]
        assert "validation" in prompt_text.lower() or "error" in prompt_text.lower()


class TestModelRegistry:
    def test_get_model_for_known_domains(self):
        from olav.core.schema_validation import DOMAIN_MODELS

        assert "interface" in DOMAIN_MODELS
        assert "bgp_neighbor" in DOMAIN_MODELS
        assert "lldp_interface" in DOMAIN_MODELS
        assert "ospf_area" in DOMAIN_MODELS
        assert "component" in DOMAIN_MODELS

    def test_unknown_domain_raises(self):
        from olav.core.schema_validation import validate_and_heal

        with pytest.raises(KeyError):
            validate_and_heal({"foo": "bar"}, "nonexistent_domain")


# ---------------------------------------------------------------------------
# OC-15: Dynamic YANG validation via yangson
# ---------------------------------------------------------------------------

_MINIMAL_YANG = """\
module test-net {
  namespace "http://example.com/test-net";
  prefix tn;
  container interfaces {
    list interface {
      key "name";
      leaf name  { type string; }
      leaf mtu   { type uint16; }
      leaf enabled { type boolean; }
    }
  }
}
"""

_MINIMAL_YANG_LIB = {
    "ietf-yang-library:modules-state": {
        "module-set-id": "0",
        "module": [
            {
                "name": "test-net",
                "revision": "",
                "namespace": "http://example.com/test-net",
                "conformance-type": "implement",
            }
        ],
    }
}


class TestValidateWithYangson:
    """validate_with_yangson() — OC-15 dynamic YANG validation layer."""

    def test_import(self):
        from olav.core.schema_validation import validate_with_yangson

        assert callable(validate_with_yangson)

    def test_valid_data_returns_valid_true(self):
        from olav.core.schema_validation import validate_with_yangson

        data = {
            "test-net:interfaces": {
                "interface": [{"name": "Gi0/0", "mtu": 1500, "enabled": True}]
            }
        }
        result = validate_with_yangson(data, _MINIMAL_YANG, _MINIMAL_YANG_LIB)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_invalid_type_returns_valid_false(self):
        from olav.core.schema_validation import validate_with_yangson

        data = {
            "test-net:interfaces": {
                "interface": [{"name": "Gi0/0", "mtu": "NOT_AN_INT", "enabled": True}]
            }
        }
        result = validate_with_yangson(data, _MINIMAL_YANG, _MINIMAL_YANG_LIB)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_missing_key_leaf_returns_valid_false(self):
        """List entry without its key leaf must fail YANG validation."""
        from olav.core.schema_validation import validate_with_yangson

        data = {
            "test-net:interfaces": {
                "interface": [{"mtu": 1500}]  # 'name' (key) is missing
            }
        }
        result = validate_with_yangson(data, _MINIMAL_YANG, _MINIMAL_YANG_LIB)
        assert result["valid"] is False

    def test_empty_data_returns_valid_true(self):
        """An empty root dict is structurally valid (no mandatory top-level leaves)."""
        from olav.core.schema_validation import validate_with_yangson

        result = validate_with_yangson({}, _MINIMAL_YANG, _MINIMAL_YANG_LIB)
        assert result["valid"] is True

    def test_invalid_yang_text_returns_valid_false_with_error(self):
        """Malformed YANG text must produce a graceful error, not a crash."""
        from olav.core.schema_validation import validate_with_yangson

        result = validate_with_yangson(
            {"test-net:interfaces": {}},
            "THIS IS NOT YANG",
            _MINIMAL_YANG_LIB,
        )
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_returns_dict_with_required_keys(self):
        from olav.core.schema_validation import validate_with_yangson

        result = validate_with_yangson({}, _MINIMAL_YANG, _MINIMAL_YANG_LIB)
        assert "valid" in result
        assert "errors" in result
        assert isinstance(result["errors"], list)
