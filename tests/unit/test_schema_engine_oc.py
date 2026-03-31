"""Tests for Schema Engine OpenConfig mapping enhancements (OC-3).

TDD RED phase: verifies that the schema engine's LLM prompt and mapping
pipeline are enhanced with OpenConfig YANG path references.
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# YANG reference injection
# ---------------------------------------------------------------------------


class TestYangReferenceTree:
    """OC-3 adds a YANG reference tree constant used in LLM prompts."""

    def test_yang_reference_exists(self):
        from olav.core.schema_engine import OPENCONFIG_YANG_REFERENCE

        assert isinstance(OPENCONFIG_YANG_REFERENCE, str)
        assert len(OPENCONFIG_YANG_REFERENCE) > 100  # non-trivial content

    def test_yang_reference_contains_key_paths(self):
        from olav.core.schema_engine import OPENCONFIG_YANG_REFERENCE

        # Must include all 5 domains
        assert "openconfig-interfaces" in OPENCONFIG_YANG_REFERENCE
        assert "openconfig-bgp" in OPENCONFIG_YANG_REFERENCE
        assert "openconfig-lldp" in OPENCONFIG_YANG_REFERENCE
        assert (
            "openconfig-ospfv2" in OPENCONFIG_YANG_REFERENCE
            or "ospf" in OPENCONFIG_YANG_REFERENCE.lower()
        )
        assert "openconfig-platform" in OPENCONFIG_YANG_REFERENCE

    def test_yang_reference_contains_leaf_paths(self):
        from olav.core.schema_engine import OPENCONFIG_YANG_REFERENCE

        # Should contain key operational state paths
        assert "oper-status" in OPENCONFIG_YANG_REFERENCE
        assert "admin-status" in OPENCONFIG_YANG_REFERENCE
        assert (
            "neighbor-address" in OPENCONFIG_YANG_REFERENCE
            or "neighbor" in OPENCONFIG_YANG_REFERENCE
        )


# ---------------------------------------------------------------------------
# LLM prompt enhancement
# ---------------------------------------------------------------------------


class TestLlmPromptYangInjection:
    """_llm_confirm and _llm_propose_openconfig_path must include YANG context."""

    def _make_engine(self):
        """Create SchemaEngine with mocked dependencies."""
        from olav.core.schema_engine import SchemaEngine

        mock_svc = MagicMock()
        return SchemaEngine(
            mutation_service=mock_svc,
            embedder=None,  # disabled embedder
        )

    @patch("olav.core.llm.LLMFactory")
    def test_llm_confirm_includes_yang_reference(self, mock_factory):
        """_llm_confirm must inject YANG reference tree into prompt."""
        from olav.core.schema_engine import SchemaEngine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="openconfig-interfaces:interfaces/interface/state/mtu"
        )
        mock_factory.get_chat_model.return_value = mock_llm

        engine = self._make_engine()
        field = {"name": "Mtu", "description": "Maximum Transfer Unit"}
        top_result = {"openconfig_path": "openconfig-interfaces:interfaces/interface/state/mtu"}

        result = engine._llm_confirm(field, top_result, 0.72)

        # Verify LLM was called
        mock_llm.invoke.assert_called_once()
        prompt_text = mock_llm.invoke.call_args[0][0]

        # Prompt must contain OpenConfig reference context
        assert "OpenConfig" in prompt_text or "openconfig" in prompt_text
        assert (
            "YANG" in prompt_text or "yang" in prompt_text.lower() or "openconfig-" in prompt_text
        )

    @patch("olav.core.llm.LLMFactory")
    def test_llm_propose_includes_yang_reference(self, mock_factory):
        """_llm_propose_openconfig_path must inject YANG reference tree."""
        from olav.core.schema_engine import SchemaEngine

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="openconfig-interfaces:interfaces/interface/state/oper-status"
        )
        mock_factory.get_chat_model.return_value = mock_llm

        engine = self._make_engine()
        raw_keys = ["oper_status", "Status", "IntfStatus"]
        sample_fields = [
            {"name": "oper_status", "description": "interface operational status"},
        ]

        result = engine._llm_propose_openconfig_path(raw_keys, sample_fields, "netops")

        mock_llm.invoke.assert_called_once()
        prompt_text = mock_llm.invoke.call_args[0][0]

        # Prompt must contain YANG reference
        assert "openconfig-" in prompt_text.lower() or "YANG" in prompt_text

    @patch("olav.core.llm.LLMFactory")
    def test_llm_propose_returns_valid_openconfig_path(self, mock_factory):
        """_llm_propose_openconfig_path returns the LLM response content."""
        from olav.core.schema_engine import SchemaEngine

        mock_llm = MagicMock()
        expected_path = "openconfig-bgp:bgp/neighbors/neighbor/state/session-state"
        mock_llm.invoke.return_value = MagicMock(content=expected_path)
        mock_factory.get_chat_model.return_value = mock_llm

        engine = self._make_engine()
        result = engine._llm_propose_openconfig_path(
            ["bgp_state", "session_status", "peer_state"],
            [{"name": "bgp_state"}],
            "netops",
        )
        assert result == expected_path


# ---------------------------------------------------------------------------
# classify_field with OpenConfig integration
# ---------------------------------------------------------------------------


class TestClassifyFieldOpenConfig:
    """classify_field must work end-to-end with OpenConfig paths."""

    def test_classify_raises_without_embedder(self):
        """When embedder is None, classify raises RuntimeError (strict mode)."""
        from olav.core.schema_engine import SchemaEngine

        mock_svc = MagicMock()
        engine = SchemaEngine(mutation_service=mock_svc, embedder=None)

        with pytest.raises(RuntimeError, match="requires an embedder"):
            engine.classify_field({"name": "hostname", "domain": "netops"})

    def test_matched_result_contains_openconfig_path(self):
        """When vector match is strong, result must include openconfig_path."""
        from olav.core.schema_engine import SchemaEngine

        mock_svc = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=MagicMock(return_value=[0.1] * 384))

        # Mock LanceDB
        mock_table = MagicMock()
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {
                "openconfig_path": "openconfig-interfaces:interfaces/interface/state/name",
                "_distance": 0.1,  # very close = high confidence
            }
        ]
        mock_db = MagicMock()
        mock_db.open_table.return_value = mock_table

        engine = SchemaEngine(
            mutation_service=mock_svc,
            embedder=mock_embedder,
            _lancedb_override=mock_db,
        )

        result = engine.classify_field({"name": "hostname", "domain": "netops"})
        assert result["status"] == "matched"
        assert "openconfig_path" in result
        assert result["openconfig_path"].startswith("openconfig-")


# ---------------------------------------------------------------------------
# create_unified_view with OpenConfig paths
# ---------------------------------------------------------------------------


class TestCreateUnifiedViewOpenConfig:
    def test_view_uses_openconfig_paths(self):
        from olav.core.schema_engine import create_unified_view

        sql = create_unified_view(
            "show interfaces",
            [
                {"raw_key": "Mtu", "openconfig_path": "oc_intf_mtu", "data_type": "INTEGER"},
                {
                    "raw_key": "Status",
                    "openconfig_path": "oc_intf_oper_status",
                    "data_type": "VARCHAR",
                },
            ],
        )
        assert "oc_intf_mtu" in sql
        assert "oc_intf_oper_status" in sql
        assert "v_unified_show_interfaces" in sql
