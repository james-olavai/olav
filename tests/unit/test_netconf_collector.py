"""Tests for NETCONF collector service (OC-11).

These tests mock ncclient and xmltodict. No real device or NETCONF server is
contacted during unit validation.
"""

from unittest.mock import MagicMock, patch


class TestNetconfCollectorImports:
    def test_import_collector_class(self):
        from olav.services.netconf_collector import NetconfCollector

        assert NetconfCollector is not None

    def test_import_defaults(self):
        from olav.services.netconf_collector import (
            NETCONF_DEFAULT_PORT,
            OPENCONFIG_NETCONF_FILTERS,
        )

        assert NETCONF_DEFAULT_PORT == 830
        assert "interfaces" in OPENCONFIG_NETCONF_FILTERS


class TestNetconfCollectorInit:
    def test_init_with_defaults(self):
        from olav.services.netconf_collector import NetconfCollector

        collector = NetconfCollector(
            host="10.0.0.1",
            username="admin",
            password="admin",
        )

        assert collector.host == "10.0.0.1"
        assert collector.port == 830
        assert collector.hostkey_verify is False


class TestNetconfCollectorOperations:
    def _make_collector(self):
        from olav.services.netconf_collector import NetconfCollector

        return NetconfCollector(
            host="10.0.0.1",
            username="admin",
            password="admin",
        )

    @patch("olav.services.netconf_collector.manager")
    def test_get_capabilities(self, mock_manager):
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            "urn:ietf:params:netconf:base:1.0",
            "http://openconfig.net/yang/interfaces?module=openconfig-interfaces",
        ]
        mock_manager.connect.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_manager.connect.return_value.__exit__ = MagicMock(return_value=False)

        collector = self._make_collector()
        capabilities = collector.get_capabilities()

        assert len(capabilities) == 2
        assert any("openconfig-interfaces" in item for item in capabilities)

    @patch("olav.services.netconf_collector.xmltodict")
    @patch("olav.services.netconf_collector.manager")
    def test_collect_interfaces(self, mock_manager, mock_xmltodict):
        mock_session = MagicMock()
        mock_reply = MagicMock()
        mock_reply.xml = "<data><interfaces/></data>"
        mock_session.get_config.return_value = mock_reply
        mock_manager.connect.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_manager.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_xmltodict.parse.return_value = {"data": {"interfaces": None}}

        collector = self._make_collector()
        result = collector.collect("interfaces")

        assert result == {"data": {"interfaces": None}}
        mock_session.get_config.assert_called_once()

    @patch("olav.services.netconf_collector.xmltodict")
    @patch("olav.services.netconf_collector.manager")
    def test_collect_all_uses_capabilities(self, mock_manager, mock_xmltodict):
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            "http://openconfig.net/yang/interfaces?module=openconfig-interfaces",
            "http://openconfig.net/yang/lldp?module=openconfig-lldp",
        ]
        mock_reply = MagicMock()
        mock_reply.xml = "<data/>"
        mock_session.get_config.return_value = mock_reply
        mock_manager.connect.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_manager.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_xmltodict.parse.return_value = {"data": {}}

        collector = self._make_collector()
        result = collector.collect_all()

        assert set(result) == {"interfaces", "lldp"}
        assert mock_session.get_config.call_count == 2

    @patch("olav.services.netconf_collector.manager")
    def test_collect_handles_connection_error(self, mock_manager):
        mock_manager.connect.side_effect = ConnectionError("unreachable")

        collector = self._make_collector()
        result = collector.collect("interfaces")

        assert result is None

    @patch("olav.services.netconf_collector.xmltodict")
    def test_parse_xml_handles_invalid_payload(self, mock_xmltodict):
        mock_xmltodict.parse.side_effect = ValueError("bad xml")

        collector = self._make_collector()
        result = collector._parse_xml("<broken")

        assert result is None


class TestResolveOcDomains:
    """resolve_oc_domains() merges multi-subtree xmltodict results into a
    flat {domain: oc_content} dict — the NETCONF Master Resolver (P2-5)."""

    def test_import(self):
        from olav.services.netconf_collector import resolve_oc_domains

        assert callable(resolve_oc_domains)

    def test_strips_data_wrapper(self):
        """xmltodict wraps NETCONF reply in a 'data' key — must be unwrapped."""
        from olav.services.netconf_collector import resolve_oc_domains

        raw = {
            "interfaces": {"data": {"interfaces": {"interface": [{"name": "Gi0/0"}]}}},
        }
        result = resolve_oc_domains(raw)
        assert "interfaces" in result
        assert result["interfaces"] == {"openconfig-interfaces": {"interfaces": {"interface": [{"name": "Gi0/0"}]}}}

    def test_strips_rpc_reply_and_data_wrapper(self):
        """ncclient sometimes nests inside rpc-reply → data → domain."""
        from olav.services.netconf_collector import resolve_oc_domains

        raw = {
            "interfaces": {
                "rpc-reply": {
                    "@message-id": "1",
                    "data": {"interfaces": {"interface": []}},
                }
            },
        }
        result = resolve_oc_domains(raw)
        assert result["interfaces"] == {"openconfig-interfaces": {"interfaces": {"interface": []}}}

    def test_filters_out_none_domains(self):
        """Domains that failed collection (None) must be excluded from output."""
        from olav.services.netconf_collector import resolve_oc_domains

        raw = {
            "interfaces": {"data": {"interfaces": {"interface": []}}},
            "bgp": None,
            "lldp": None,
        }
        result = resolve_oc_domains(raw)
        assert "bgp" not in result
        assert "lldp" not in result
        assert "interfaces" in result

    def test_multiple_domains_merged(self):
        """All non-None domains must appear in the output dict."""
        from olav.services.netconf_collector import resolve_oc_domains

        raw = {
            "interfaces": {"data": {"interfaces": {"interface": []}}},
            "bgp": {"data": {"bgp": {"global": {}}}},
        }
        result = resolve_oc_domains(raw)
        assert set(result.keys()) == {"interfaces", "bgp"}
        assert result["bgp"] == {"openconfig-bgp": {"bgp": {"global": {}}}}

    def test_empty_input_returns_empty(self):
        from olav.services.netconf_collector import resolve_oc_domains

        assert resolve_oc_domains({}) == {}

    def test_all_none_returns_empty(self):
        from olav.services.netconf_collector import resolve_oc_domains

        assert resolve_oc_domains({"interfaces": None, "bgp": None}) == {}

    def test_domain_with_no_recognisable_wrapper_kept_as_is(self):
        """If no 'data' or 'rpc-reply' wrapper is found, content is kept as-is."""
        from olav.services.netconf_collector import resolve_oc_domains

        raw = {"interfaces": {"interface": [{"name": "lo0"}]}}
        result = resolve_oc_domains(raw)
        assert result["interfaces"] == {"openconfig-interfaces": {"interfaces": {"interface": [{"name": "lo0"}]}}}

    def test_empty_data_returns_empty_wrapped_domain(self):
        from olav.services.netconf_collector import resolve_oc_domains

        raw = {"platform": {"rpc-reply": {"data": None}}}
        result = resolve_oc_domains(raw)
        assert result["platform"] == {"openconfig-platform": {"components": {}}}

    @patch("olav.services.netconf_collector.xmltodict")
    @patch("olav.services.netconf_collector.manager")
    def test_collect_falls_back_to_get_when_running_config_is_empty(self, mock_manager, mock_xmltodict):
        mock_session = MagicMock()
        running_reply = MagicMock()
        running_reply.xml = "<rpc-reply><data/></rpc-reply>"
        state_reply = MagicMock()
        state_reply.xml = "<rpc-reply><data><bgp/></data></rpc-reply>"
        mock_session.get_config.return_value = running_reply
        mock_session.get.return_value = state_reply
        mock_manager.connect.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_manager.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_xmltodict.parse.side_effect = [
            {"rpc-reply": {"data": None}},
            {"rpc-reply": {"data": {"bgp": {"global": {}}}}},
        ]

        from olav.services.netconf_collector import NetconfCollector

        collector = NetconfCollector(host="10.0.0.1", username="admin", password="admin")
        result = collector.collect("bgp")

        assert result == {"rpc-reply": {"data": {"bgp": {"global": {}}}}}
        mock_session.get_config.assert_called_once()
        mock_session.get.assert_called_once()
