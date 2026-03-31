"""Unit tests for bootstrap_yang.py (P2-2 / OC-14).

TDD: these tests define the contract for bootstrap_yang BEFORE the
implementation exists.  Run first → RED, then implement → GREEN.

Tests exercise:
  - create_yang_leaves_table()   : DuckDB schema initialisation
  - compile_yang_text()          : single-module YANG → yang_leaves rows
  - bootstrap_yang()             : directory scan → all .yang files processed

Design reference: dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md §3.2 (OC-14)
"""

from __future__ import annotations

import textwrap

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Shared YANG snippets (pyang must be able to parse these)
# ---------------------------------------------------------------------------

MINIMAL_YANG = textwrap.dedent(
    """\
    module test-oc {
      namespace "http://test.org/yang";
      prefix "test-oc";

      container interfaces {
        list interface {
          key "name";
          leaf name {
            type string;
            description "Interface name";
          }
          leaf enabled {
            type boolean;
            description "Whether the interface is enabled";
          }
          leaf mtu {
            type uint32;
            description "Maximum transmission unit";
          }
        }
      }
    }
    """
)

SECOND_YANG = textwrap.dedent(
    """\
    module test-bgp {
      namespace "http://test.org/bgp";
      prefix "test-bgp";

      container bgp {
        leaf as-number {
          type uint32;
          description "Autonomous system number";
        }
      }
    }
    """
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem_con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


# ---------------------------------------------------------------------------
# Test group 1: create_yang_leaves_table
# ---------------------------------------------------------------------------


def test_create_yang_leaves_table_creates_correct_schema() -> None:
    """yang_leaves table must have the five required columns."""
    from olav.core.bootstrap_yang import create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)

    cols = {c[0] for c in con.execute("DESCRIBE yang_leaves").fetchall()}
    assert "yang_path" in cols, "Missing yang_path column"
    assert "leaf_name" in cols, "Missing leaf_name column"
    assert "leaf_type" in cols, "Missing leaf_type column"
    assert "description" in cols, "Missing description column"
    assert "module" in cols, "Missing module column"
    con.close()


def test_create_yang_leaves_table_is_idempotent() -> None:
    """Calling create_yang_leaves_table twice must not raise."""
    from olav.core.bootstrap_yang import create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    create_yang_leaves_table(con)  # second call — must not throw
    con.close()


# ---------------------------------------------------------------------------
# Test group 2: compile_yang_text
# ---------------------------------------------------------------------------


def test_compile_yang_text_extracts_leaves(tmp_path) -> None:
    """compile_yang_text must insert all leaf nodes from the YANG module."""
    from olav.core.bootstrap_yang import compile_yang_text, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    compile_yang_text(MINIMAL_YANG, module_name="test-oc", con=con, yang_search_path=str(tmp_path))

    rows = con.execute("SELECT leaf_name FROM yang_leaves").fetchall()
    leaf_names = {r[0] for r in rows}

    assert "name" in leaf_names, f"leaf 'name' not found; got {leaf_names}"
    assert "enabled" in leaf_names, f"leaf 'enabled' not found; got {leaf_names}"
    assert "mtu" in leaf_names, f"leaf 'mtu' not found; got {leaf_names}"
    con.close()


def test_compile_yang_text_stores_correct_path(tmp_path) -> None:
    """yang_path must encode the full schema path for each leaf."""
    from olav.core.bootstrap_yang import compile_yang_text, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    compile_yang_text(MINIMAL_YANG, module_name="test-oc", con=con, yang_search_path=str(tmp_path))

    rows = con.execute(
        "SELECT yang_path FROM yang_leaves WHERE leaf_name = 'enabled'"
    ).fetchall()
    assert rows, "No row for leaf 'enabled'"
    path = rows[0][0]
    assert "interface" in path, f"Expected 'interface' in path; got {path!r}"
    assert "enabled" in path, f"Expected 'enabled' at end of path; got {path!r}"
    con.close()


def test_compile_yang_text_stores_leaf_type(tmp_path) -> None:
    """leaf_type column must capture the YANG base type name."""
    from olav.core.bootstrap_yang import compile_yang_text, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    compile_yang_text(MINIMAL_YANG, module_name="test-oc", con=con, yang_search_path=str(tmp_path))

    row = con.execute(
        "SELECT leaf_type FROM yang_leaves WHERE leaf_name = 'enabled'"
    ).fetchone()
    assert row is not None
    assert "boolean" in row[0].lower(), f"Expected type 'boolean'; got {row[0]!r}"

    row2 = con.execute(
        "SELECT leaf_type FROM yang_leaves WHERE leaf_name = 'mtu'"
    ).fetchone()
    assert row2 is not None
    assert "uint32" in row2[0].lower(), f"Expected type 'uint32'; got {row2[0]!r}"
    con.close()


def test_compile_yang_text_stores_description(tmp_path) -> None:
    """description column must be populated when YANG has a description."""
    from olav.core.bootstrap_yang import compile_yang_text, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    compile_yang_text(MINIMAL_YANG, module_name="test-oc", con=con, yang_search_path=str(tmp_path))

    row = con.execute(
        "SELECT description FROM yang_leaves WHERE leaf_name = 'name'"
    ).fetchone()
    assert row is not None
    assert row[0] and len(row[0]) > 0, "description should not be empty"
    con.close()


def test_compile_yang_text_stores_module_name(tmp_path) -> None:
    """module column must record the module name for every leaf."""
    from olav.core.bootstrap_yang import compile_yang_text, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    compile_yang_text(MINIMAL_YANG, module_name="test-oc", con=con, yang_search_path=str(tmp_path))

    rows = con.execute("SELECT DISTINCT module FROM yang_leaves").fetchall()
    modules = {r[0] for r in rows}
    assert "test-oc" in modules, f"Module name not stored; got {modules}"
    con.close()


def test_compile_invalid_yang_raises_value_error(tmp_path) -> None:
    """compile_yang_text must raise ValueError for unparseable YANG."""
    from olav.core.bootstrap_yang import compile_yang_text, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)

    with pytest.raises((ValueError, Exception)):  # pyang parse error
        compile_yang_text(
            "this is not valid YANG text",
            module_name="broken",
            con=con,
            yang_search_path=str(tmp_path),
        )
    con.close()


# ---------------------------------------------------------------------------
# Test group 3: bootstrap_yang (directory scan)
# ---------------------------------------------------------------------------


def test_bootstrap_yang_from_directory(tmp_path) -> None:
    """bootstrap_yang must process all .yang files in a directory."""
    from olav.core.bootstrap_yang import bootstrap_yang

    (tmp_path / "test-oc.yang").write_text(MINIMAL_YANG, encoding="utf-8")
    (tmp_path / "test-bgp.yang").write_text(SECOND_YANG, encoding="utf-8")

    con = _mem_con()
    result = bootstrap_yang(yang_dir=str(tmp_path), con=con)

    assert result["modules_compiled"] == 2, f"Expected 2 modules; got {result}"
    count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]
    assert count >= 4, f"Expected >= 4 leaves total; got {count}"
    con.close()


def test_bootstrap_yang_returns_stats(tmp_path) -> None:
    """bootstrap_yang must return a stats dict with required keys."""
    from olav.core.bootstrap_yang import bootstrap_yang

    (tmp_path / "test-oc.yang").write_text(MINIMAL_YANG, encoding="utf-8")

    con = _mem_con()
    result = bootstrap_yang(yang_dir=str(tmp_path), con=con)

    assert "modules_compiled" in result
    assert "leaves_inserted" in result
    assert result["modules_compiled"] >= 1
    assert result["leaves_inserted"] >= 3
    con.close()


def test_bootstrap_yang_empty_directory(tmp_path) -> None:
    """bootstrap_yang on an empty directory must return zeros, not raise."""
    from olav.core.bootstrap_yang import bootstrap_yang

    con = _mem_con()
    result = bootstrap_yang(yang_dir=str(tmp_path), con=con)

    assert result["modules_compiled"] == 0
    assert result["leaves_inserted"] == 0
    con.close()


def test_bootstrap_yang_does_not_process_non_yang_files(tmp_path) -> None:
    """bootstrap_yang must ignore non-.yang files in the directory."""
    from olav.core.bootstrap_yang import bootstrap_yang

    (tmp_path / "README.md").write_text("# docs", encoding="utf-8")
    (tmp_path / "test-oc.yang").write_text(MINIMAL_YANG, encoding="utf-8")

    con = _mem_con()
    result = bootstrap_yang(yang_dir=str(tmp_path), con=con)

    assert result["modules_compiled"] == 1, "Should only compile .yang files"
    con.close()


def test_bootstrap_yang_deduplicates_on_rerun(tmp_path) -> None:
    """Running bootstrap_yang twice must not duplicate rows (REPLACE semantics)."""
    from olav.core.bootstrap_yang import bootstrap_yang

    (tmp_path / "test-oc.yang").write_text(MINIMAL_YANG, encoding="utf-8")

    con = _mem_con()
    bootstrap_yang(yang_dir=str(tmp_path), con=con)
    first_count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]

    bootstrap_yang(yang_dir=str(tmp_path), con=con)
    second_count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]

    assert first_count == second_count, (
        f"Rows duplicated on re-run: {first_count} → {second_count}"
    )
    con.close()


# ---------------------------------------------------------------------------
# Test group 4: bootstrap_yang_from_reference (OC-14 reference seeding)
# ---------------------------------------------------------------------------

MINIMAL_REFERENCE = """\
## openconfig-interfaces
openconfig-interfaces:interfaces/interface/config/name
openconfig-interfaces:interfaces/interface/config/enabled
openconfig-interfaces:interfaces/interface/state/admin-status
openconfig-interfaces:interfaces/interface/state/oper-status

## openconfig-bgp
openconfig-bgp:bgp/neighbors/neighbor/state/session-state
openconfig-bgp:bgp/neighbors/neighbor/state/peer-as
"""


def test_bootstrap_from_reference_inserts_rows() -> None:
    """bootstrap_yang_from_reference must insert one row per path line."""
    from olav.core.bootstrap_yang import bootstrap_yang_from_reference, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    result = bootstrap_yang_from_reference(MINIMAL_REFERENCE, con)

    count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]
    assert count == 6, f"Expected 6 paths inserted; got {count}"
    assert result["leaves_inserted"] == 6
    con.close()


def test_bootstrap_from_reference_parses_module_and_path() -> None:
    """Module and yang_path must be correctly split on first ':'."""
    from olav.core.bootstrap_yang import bootstrap_yang_from_reference, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    bootstrap_yang_from_reference(MINIMAL_REFERENCE, con)

    row = con.execute(
        "SELECT module, yang_path, leaf_name FROM yang_leaves "
        "WHERE yang_path = 'interfaces/interface/config/name'"
    ).fetchone()
    assert row is not None, "Row for interfaces/interface/config/name not found"
    assert row[0] == "openconfig-interfaces", f"Wrong module: {row[0]}"
    assert row[1] == "interfaces/interface/config/name", f"Wrong yang_path: {row[1]}"
    assert row[2] == "name", f"Wrong leaf_name: {row[2]}"
    con.close()


def test_bootstrap_from_reference_ignores_comments_and_blanks() -> None:
    """Comment lines (##) and blank lines must not produce rows."""
    from olav.core.bootstrap_yang import bootstrap_yang_from_reference, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    bootstrap_yang_from_reference(MINIMAL_REFERENCE, con)

    # Verify no rows with yang_path starting with "#"
    bad_rows = con.execute(
        "SELECT yang_path FROM yang_leaves WHERE yang_path LIKE '#%'"
    ).fetchall()
    assert len(bad_rows) == 0, f"Comment lines should not be inserted: {bad_rows}"
    con.close()


def test_bootstrap_from_reference_is_idempotent() -> None:
    """Running twice must not duplicate rows."""
    from olav.core.bootstrap_yang import bootstrap_yang_from_reference, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    bootstrap_yang_from_reference(MINIMAL_REFERENCE, con)
    first_count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]

    bootstrap_yang_from_reference(MINIMAL_REFERENCE, con)
    second_count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]

    assert first_count == second_count, (
        f"Rows duplicated on re-run: {first_count} → {second_count}"
    )
    con.close()


def test_bootstrap_from_reference_multi_module() -> None:
    """Paths from different modules must each record their own module name."""
    from olav.core.bootstrap_yang import bootstrap_yang_from_reference, create_yang_leaves_table

    con = _mem_con()
    create_yang_leaves_table(con)
    bootstrap_yang_from_reference(MINIMAL_REFERENCE, con)

    modules = {r[0] for r in con.execute("SELECT DISTINCT module FROM yang_leaves").fetchall()}
    assert "openconfig-interfaces" in modules
    assert "openconfig-bgp" in modules
    con.close()


def test_load_bundled_openconfig_reference_returns_bundled_asset() -> None:
    """The packaged OpenConfig reference asset must be readable at runtime."""
    from olav.core.bootstrap_yang import load_bundled_openconfig_reference

    reference = load_bundled_openconfig_reference()

    assert "openconfig-interfaces:interfaces/interface/config/name" in reference
    assert "openconfig-bgp:bgp/neighbors/neighbor/state/peer-as" in reference


def test_ensure_bundled_openconfig_reference_bootstraps_once() -> None:
    """ensure_bundled_openconfig_reference must seed only when yang_leaves is empty."""
    from olav.core.bootstrap_yang import ensure_bundled_openconfig_reference

    con = _mem_con()

    first = ensure_bundled_openconfig_reference(con)
    count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]
    second = ensure_bundled_openconfig_reference(con)

    assert first["status"] == "bootstrapped"
    assert count > 0
    assert second["status"] == "already_populated"
    assert second["existing_rows"] == count
    con.close()

