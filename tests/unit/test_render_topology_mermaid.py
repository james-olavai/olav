from __future__ import annotations

from olav.data.workspace.core.writer.scripts.render_topology_mermaid import (
    render_topology_mermaid,
)


def _invoke(table_md: str) -> str:
    if hasattr(render_topology_mermaid, "invoke"):
        return render_topology_mermaid.invoke({"adjacencies_table_markdown": table_md})
    return render_topology_mermaid(table_md)


def test_empty_input_returns_omitted_note():
    out = _invoke("")
    assert "empty input" in out
    assert "diagram omitted" in out


def test_unparseable_input_returns_omitted_note():
    out = _invoke("just prose, no markdown table")
    assert "could not parse" in out
    assert "diagram omitted" in out


def test_missing_required_columns_returns_omitted_note():
    bad = "| Foo | Bar |\n|---|---|\n| x | y |\n"
    out = _invoke(bad)
    assert "missing required column" in out
    assert "Source" in out


def test_valid_table_renders_basic_mermaid_graph():
    table = """\
| Source | Local Intf | Dest | Remote Intf | Status |
|---|---|---|---|---|
| R1 | Eth0/0 | R2 | Eth0/1 | up |
"""
    out = _invoke(table)

    assert out.startswith("```mermaid\ngraph LR\n")
    assert 'R1["R1"]' in out
    assert 'R2["R2"]' in out
    assert 'R1 ---|"Eth0/0 ↔ Eth0/1"| R2' in out
    assert out.endswith("```\n")


def test_down_and_unknown_status_render_dashed_edges():
    table = """\
| Source | Local Intf | Dest | Remote Intf | Status |
|---|---|---|---|---|
| R1 | Eth0/0 | R2 | Eth0/1 | down |
| R2 | Eth0/2 | R3 | Eth0/3 | unknown |
| R3 | Eth0/4 | R4 | Eth0/5 | new |
"""
    out = _invoke(table)

    assert 'R1 -.->|"Eth0/0 ↔ Eth0/1"| R2' in out
    assert 'R2 -.->|"Eth0/2 ↔ Eth0/3"| R3' in out
    assert 'R3 ---|"Eth0/4 ↔ Eth0/5"| R4' in out
