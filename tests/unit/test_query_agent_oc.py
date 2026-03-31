"""Tests for Query Agent OpenConfig SQL update (OC-8).

TDD cycle: SCHEMA_REFERENCE.md must document OpenConfig JSON path query
patterns, and the schema catalog context must surface openconfig_path info.
"""

import pytest


class TestSchemaReferenceOpenConfig:
    """Verify SCHEMA_REFERENCE.md contains OpenConfig query guidance."""

    def test_reference_contains_openconfig_section(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "openconfig" in content.lower(), "SCHEMA_REFERENCE.md must mention OpenConfig"

    def test_reference_contains_json_path_examples(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "openconfig-interfaces" in content, (
            "Must include openconfig-interfaces path examples"
        )

    @pytest.mark.xfail(
        reason="Phase 2 quarantine: OC examples deleted from SCHEMA_REFERENCE per doc 08 cut line"
    )
    def test_reference_contains_oper_status_example(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "oper-status" in content, (
            "Must include oper-status as a concrete OpenConfig query example"
        )

    @pytest.mark.xfail(
        reason="Phase 2 quarantine: OC examples deleted from SCHEMA_REFERENCE per doc 08 cut line"
    )
    def test_reference_contains_bgp_neighbor_path(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "neighbor-address" in content, (
            "Must include BGP neighbor-address OpenConfig path example"
        )

    @pytest.mark.xfail(
        reason="Phase 2 quarantine: OC examples deleted from SCHEMA_REFERENCE per doc 08 cut line"
    )
    def test_reference_contains_lldp_path(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "system-name" in content, "Must include LLDP system-name OpenConfig path example"


class TestSchemaReferenceOpenConfigViews:
    """Verify SCHEMA_REFERENCE.md documents OpenConfig-aware view patterns."""

    def test_reference_documents_oc_parsed_outputs_pattern(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "json_extract" in content.lower() or "->>" in content, (
            "Must document JSON extraction pattern for OpenConfig parsed_data"
        )

    def test_reference_documents_domain_mapping(self):
        from pathlib import Path

        ref_path = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md")
        content = ref_path.read_text()
        assert "openconfig-bgp" in content, "Must include openconfig-bgp domain reference"


class TestSchemaReferenceSnapshotGuidance:
    """Verify SCHEMA_REFERENCE.md does not teach wrong cross-table snapshots."""

    def test_reference_does_not_use_parsed_outputs_snapshot_for_views(self):
        from pathlib import Path

        content = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md").read_text()
        bad_v_interfaces = "FROM v_interfaces\nWHERE device_name = 'SW1'\n  AND (admin_status != 'up' OR line_status != 'up')\n  AND snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs);"
        bad_v_bgp = "FROM v_bgp_neighbors\nWHERE state = 'Established'\n  AND snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs);"
        bad_topology = "FROM topology_links\nWHERE snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs);"
        assert bad_v_interfaces not in content
        assert bad_v_bgp not in content
        assert bad_topology not in content

    def test_reference_prefers_same_view_snapshot_examples(self):
        from pathlib import Path

        content = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md").read_text()
        assert "MAX(snapshot_id) FROM v_interfaces" in content
        assert "MAX(snapshot_id) FROM v_bgp_neighbors" in content
        assert "MAX(snapshot_id) FROM v_topo_links_clean" in content


class TestSchemaReferenceObjectKinds:
    """Verify SCHEMA_REFERENCE.md object kinds match the live main-schema catalog."""

    def test_reference_marks_live_main_schema_objects_correctly(self):
        from pathlib import Path

        content = Path(".olav/workspace/quick/references/SCHEMA_REFERENCE.md").read_text()
        assert "| **`devices`** | VIEW |" in content
        assert "| **`interfaces`** | TABLE |" in content
        assert "| **`v_interfaces`** | VIEW |" in content
        assert "| **`bgp_neighbors`** | TABLE |" in content
        assert "| **`v_bgp_neighbors`** | VIEW |" in content
        assert "| **`v_ospf_neighbors`** | VIEW |" in content
        assert "| **`v_routes_auto`** | VIEW |" in content
        assert "| **`topology_links`** | VIEW |" in content
        assert "| **`v_topo_links_clean`** | VIEW |" in content
        assert "| **`parsed_outputs`** | VIEW |" in content
        assert "| **`yang_leaves`** | TABLE |" in content
        assert "| **`mapping_rules`** | COMPAT TABLE |" in content
