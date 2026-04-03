from pathlib import Path

import pytest


@pytest.mark.xfail(
    reason="S13: v0.13 tracking restructured; olav-netops not referenced in tracking.md",
    strict=True,
)
def test_tracking_uses_current_cli_module_paths() -> None:
    tracking_text = Path("dev_docs/01. tracking.md").read_text(encoding="utf-8")

    assert "olav-netops" in tracking_text
    assert "src/olav/cli/admin_cmd.py" not in tracking_text
    assert "src/olav/cli/commands/onboard.py" not in tracking_text


@pytest.mark.xfail(
    reason="S14: v0.13 tracking restructured; api_discovery.md not referenced in tracking.md",
    strict=True,
)
def test_tracking_matches_latest_schema_mutation_design() -> None:
    tracking_text = Path("dev_docs/01. tracking.md").read_text(encoding="utf-8")

    assert "api_discovery.md" in tracking_text
    assert "direct DB writer" not in tracking_text


def test_tracking_design_doc_index_paths_exist() -> None:
    tracked_paths = [
        "dev_docs/olav_aaa.md",
        "dev_docs/ent_features.md",
        "dev_docs/log_rector.md",
        "dev_docs/agent_traces.md",
        "dev_docs/plugin_rector.md",
        "dev_docs/olav_platform.md",
        "dev_docs/api_discovery.md",
        "docs/archive/olav/05_AGENTIC_FEATURES.md",
    ]

    for tracked_path in tracked_paths:
        assert Path(tracked_path).exists(), tracked_path


@pytest.mark.xfail(
    reason="S15: v0.13 tracking §4 is 'Current Reality Snapshot', not 'ContainerLab E2E Sprint'",
    strict=True,
)
def test_tracking_section_four_covers_containerlab_sprint() -> None:
    tracking_text = Path("dev_docs/01. tracking.md").read_text(encoding="utf-8")

    assert "## 4. ContainerLab E2E Sprint" in tracking_text
    assert "CLAB-1" in tracking_text
    assert "CLAB-2" in tracking_text
    assert "CLAB-3" in tracking_text
    assert "DATA-1" in tracking_text
    assert "DATA-2" in tracking_text
