"""OC-14: YANG Golden Dict compiler.

Shallow-scans a directory of .yang files, compiles each module with pyang,
and populates the ``yang_leaves`` DuckDB table.  This table is the sole
ground truth for OC-13 (schema-to-schema mapping).

Usage
-----
    from olav.core.bootstrap_yang import bootstrap_yang
    import duckdb

    con = duckdb.connect(".olav/databases/main.duckdb")
    result = bootstrap_yang(yang_dir=".olav/yang_models", con=con)
    print(result)  # {"modules_compiled": N, "leaves_inserted": M, "errors": [...]}

Design reference: dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md §3.2 (OC-14)
"""

from __future__ import annotations

from importlib import resources
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pyang import context, repository

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)

_BUNDLED_REFERENCE_PACKAGE = "olav.data.yang"
_BUNDLED_REFERENCE_NAME = "openconfig_reference.txt"

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS yang_leaves (
    yang_path   TEXT NOT NULL,
    leaf_name   TEXT NOT NULL,
    leaf_type   TEXT NOT NULL,
    description TEXT,
    module      TEXT NOT NULL,
    PRIMARY KEY (yang_path, module)
)
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_yang_leaves_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create (or ensure exists) the ``yang_leaves`` table in *con*."""
    con.execute(_CREATE_TABLE_SQL)


def compile_yang_text(
    yang_text: str,
    *,
    module_name: str,
    con: duckdb.DuckDBPyConnection,
    yang_search_path: str = "",
) -> int:
    """Parse *yang_text* and insert all leaf nodes into ``yang_leaves``.

    Parameters
    ----------
    yang_text:
        Raw YANG module source.
    module_name:
        The YANG module name (used as ``module`` column value and as the
        temporary file reference passed to pyang).
    con:
        Open DuckDB connection with ``yang_leaves`` table already created.
    yang_search_path:
        Directory pyang should search for imported YANG modules.

    Returns
    -------
    int
        Number of leaf rows inserted.

    Raises
    ------
    ValueError
        If pyang emits errors that prevent the module from loading.
    """
    create_yang_leaves_table(con)

    import os
    import tempfile

    search_paths = [yang_search_path] if yang_search_path else []

    # Write to a temp file so pyang can resolve the module reference.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_yang = os.path.join(tmpdir, f"{module_name}.yang")
        with open(tmp_yang, "w", encoding="utf-8") as fh:
            fh.write(yang_text)

        all_paths = [tmpdir] + search_paths
        repo = repository.FileRepository(*all_paths)
        ctx = context.Context(repo)
        module = ctx.add_module(tmp_yang, yang_text)

    if module is None:
        errors = [str(e) for e in ctx.errors if e]
        raise ValueError(f"pyang failed to parse module '{module_name}': {errors}")

    leaves = _extract_leaves(module, module_name)

    if not leaves:
        return 0

    # UPSERT so a re-run is idempotent (PRIMARY KEY = yang_path + module).
    con.executemany(
        """
        INSERT OR REPLACE INTO yang_leaves
            (yang_path, leaf_name, leaf_type, description, module)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (r["yang_path"], r["leaf_name"], r["leaf_type"], r["description"], r["module"])
            for r in leaves
        ],
    )
    return len(leaves)


def bootstrap_yang(
    yang_dir: str,
    con: duckdb.DuckDBPyConnection,
) -> dict:
    """Scan *yang_dir* for .yang files and compile them all into *con*.

    Parameters
    ----------
    yang_dir:
        Directory containing .yang files (non-recursive).
    con:
        Open DuckDB connection.

    Returns
    -------
    dict
        ``{"modules_compiled": int, "leaves_inserted": int, "errors": list[str]}``
    """
    create_yang_leaves_table(con)

    yang_files = sorted(Path(yang_dir).glob("*.yang"))
    modules_compiled = 0
    leaves_total = 0
    errors: list[str] = []

    for yang_file in yang_files:
        module_name = yang_file.stem
        try:
            yang_text = yang_file.read_text(encoding="utf-8")
            n = compile_yang_text(
                yang_text,
                module_name=module_name,
                con=con,
                yang_search_path=yang_dir,
            )
            modules_compiled += 1
            leaves_total += n
            logger.debug("bootstrap_yang: compiled %s → %d leaves", module_name, n)
        except Exception as exc:
            msg = f"{yang_file.name}: {exc}"
            errors.append(msg)
            logger.warning("bootstrap_yang: SKIP %s", msg)

    logger.info(
        "bootstrap_yang: %d modules, %d leaves, %d errors",
        modules_compiled,
        leaves_total,
        len(errors),
    )
    return {
        "modules_compiled": modules_compiled,
        "leaves_inserted": leaves_total,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_path(stmt) -> str:
    """Return the full schema path for a statement node."""
    parts: list[str] = []
    s = stmt
    while s is not None and s.keyword not in ("module", "submodule"):
        if hasattr(s, "arg") and s.arg:
            parts.append(s.arg)
        s = getattr(s, "parent", None)
    return "/" + "/".join(reversed(parts))


def _extract_leaves(module_stmt, module_name: str) -> list[dict]:
    """Recursively walk *module_stmt* and return a list of leaf dicts."""
    results: list[dict] = []

    def _walk(stmt) -> None:
        if stmt.keyword == "leaf":
            type_stmt = stmt.search_one("type")
            desc_stmt = stmt.search_one("description")
            results.append(
                {
                    "yang_path": _build_path(stmt),
                    "leaf_name": stmt.arg,
                    "leaf_type": type_stmt.arg if type_stmt else "unknown",
                    "description": desc_stmt.arg if desc_stmt else "",
                    "module": module_name,
                }
            )
        for child in stmt.substmts:
            _walk(child)

    _walk(module_stmt)
    return results


# ---------------------------------------------------------------------------
# Reference-seeding (OC-14 fast-path: no YANG files needed)
# ---------------------------------------------------------------------------


def bootstrap_yang_from_reference(
    reference_text: str,
    con: duckdb.DuckDBPyConnection,
) -> dict:
    """Seed ``yang_leaves`` from a markdown-style OpenConfig YANG reference.

    Parses lines of the form::

        openconfig-interfaces:interfaces/interface/config/name

    Comment lines (starting with ``#``), blank lines, and lines without
    a ``:`` separator are silently ignored.

    Parameters
    ----------
    reference_text:
        Multi-line string with ``<module>:<path>`` entries.
    con:
        Open DuckDB connection; ``yang_leaves`` table is created if absent.

    Returns
    -------
    dict
        ``{"leaves_inserted": int}``
    """
    create_yang_leaves_table(con)

    rows: list[tuple] = []
    for raw_line in reference_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        module, yang_path = line.split(":", 1)
        module = module.strip()
        yang_path = yang_path.strip()
        if not module or not yang_path:
            continue
        leaf_name = yang_path.rstrip("/").rsplit("/", 1)[-1]
        rows.append((yang_path, leaf_name, "string", "", module))

    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO yang_leaves
                (yang_path, leaf_name, leaf_type, description, module)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

    logger.info("bootstrap_yang_from_reference: inserted %d leaves", len(rows))
    return {"leaves_inserted": len(rows)}


def load_bundled_openconfig_reference() -> str:
    """Return the bundled OpenConfig reference text shipped with the package."""
    ref_path = resources.files(_BUNDLED_REFERENCE_PACKAGE).joinpath(_BUNDLED_REFERENCE_NAME)
    return ref_path.read_text(encoding="utf-8")


def bootstrap_bundled_openconfig_reference(con: duckdb.DuckDBPyConnection) -> dict:
    """Seed ``yang_leaves`` from the bundled OpenConfig reference asset."""
    return bootstrap_yang_from_reference(load_bundled_openconfig_reference(), con)


def ensure_bundled_openconfig_reference(con: duckdb.DuckDBPyConnection) -> dict:
    """Populate ``yang_leaves`` from bundled data only when the table is empty."""
    create_yang_leaves_table(con)
    existing = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]
    if existing:
        return {"status": "already_populated", "existing_rows": existing}

    result = bootstrap_bundled_openconfig_reference(con)
    result["status"] = "bootstrapped"
    return result
