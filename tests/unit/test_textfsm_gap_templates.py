from pathlib import Path

import pytest
import textfsm


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "exports" / "snapshots" / "2026-03-19_2001" / "raw" / "R2"
ROUTING_RAW_DIR = PROJECT_ROOT / "exports" / "snapshots" / "2026-03-19_2026" / "raw" / "R2"
TEMPLATE_DIR = PROJECT_ROOT / ".olav" / "templates"


@pytest.mark.parametrize(
    ("template_name", "raw_name", "minimum_rows"),
    [
        ("cisco_ios_show_platform.textfsm", "show_platform.txt", 2),
        ("cisco_ios_show_processes_memory_sorted.textfsm", "show_processes_memory_sorted.txt", 10),
        ("cisco_ios_show_redundancy.textfsm", "show_redundancy.txt", 1),
        ("cisco_ios_show_users.textfsm", "show_users.txt", 1),
    ],
)
def test_gap_templates_parse_snapshot_raw_outputs(template_name: str, raw_name: str, minimum_rows: int) -> None:
    template_path = TEMPLATE_DIR / template_name
    raw_path = RAW_DIR / raw_name

    with template_path.open(encoding="utf-8") as template_handle:
        parser = textfsm.TextFSM(template_handle)

    rows = parser.ParseText(raw_path.read_text(encoding="utf-8"))

    assert len(rows) >= minimum_rows, f"expected at least {minimum_rows} rows from {raw_name}"


def test_capability_feature_routing_template_parses_r2_snapshot() -> None:
    template_path = TEMPLATE_DIR / "cisco_ios_show_capability_feature_routing.textfsm"
    raw_path = ROUTING_RAW_DIR / "show_capability_feature_routing.txt"

    with template_path.open(encoding="utf-8") as template_handle:
        parser = textfsm.TextFSM(template_handle)

    rows = parser.ParseText(raw_path.read_text(encoding="utf-8"))

    assert len(rows) >= 50