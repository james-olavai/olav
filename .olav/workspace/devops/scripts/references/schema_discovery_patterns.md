# Schema Discovery Script Patterns

Reference patterns for the **devops agent** when writing schema discovery or
field-classification scripts. The `config/discovery` subagent uses these tools
interactively — this reference is for when you need standalone scripts.

---

## Pattern 1: Field Classification Script

```python
# Classify a set of unknown DB column names against the OLAV standard schema.
# The classify_field tool (semantic vector lookup + optional LLM fallback) is
# already available as a tool call. Use this pattern when you need a batch script.

import duckdb
import json

def classify_fields_batch(db_path: str, table: str) -> dict:
    """Classify all columns of a DuckDB table against OLAV unified schema."""
    con = duckdb.connect(db_path, read_only=True)
    pragma = con.execute(f"PRAGMA table_info({table})").fetchall()
    col_names = [row[1] for row in pragma]  # column index 1 = name
    con.close()

    # For each column, you would call classify_field(field_name=col)
    # In a devops script, log unknowns for human review:
    unknowns = []
    for col in col_names:
        # placeholder — replace with actual classify_field() call
        unknowns.append({"field": col, "status": "needs_classification"})

    return {"table": table, "columns": len(col_names), "unknowns": unknowns}
```

---

## Pattern 2: Unified View Generation

```python
# After field classification, create_unified_view generates a normalized VIEW.
# Use this pattern to script the view creation for a new data source.

import duckdb

MAPPING = {
    # raw_field_name → canonical_field_name
    "intf_name": "interface_name",
    "ipv4_addr": "ip_address",
    "nbr_id": "neighbor_id",
}

def create_view_from_mapping(db_path: str, source_table: str, view_name: str) -> str:
    """Generate a CREATE VIEW statement from a field mapping dict."""
    selects = [f"{raw} AS {canonical}" for raw, canonical in MAPPING.items()]
    sql = f"CREATE OR REPLACE VIEW {view_name} AS SELECT {', '.join(selects)} FROM {source_table};"

    con = duckdb.connect(db_path)
    con.execute(sql)
    con.close()
    return sql
```

---

## Pattern 3: Schema Reference Sync

```python
# Keep SCHEMA_REFERENCE.md in sync with live DB column names.
# Mirrors what sync_schema_reference does interactively.

import duckdb
from pathlib import Path

def sync_schema_reference(db_path: str, ref_path: str = ".olav/workspace/config/references/SCHEMA_REFERENCE.md") -> None:
    """Overwrite schema reference with live table/column names."""
    con = duckdb.connect(db_path, read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    lines = ["# Live Schema Reference\n\n"]
    for (tbl,) in tables:
        try:
            cols = con.execute(f"PRAGMA table_info({tbl})").fetchall()
            lines.append(f"## {tbl}\n\n")
            for _, name, dtype, *_ in cols:
                lines.append(f"- `{name}` ({dtype})\n")
            lines.append("\n")
        except Exception:
            pass
    con.close()
    Path(ref_path).write_text("".join(lines), encoding="utf-8")
```

---

## When to use config/discovery tools vs. scripting

| Need | Use |
|------|-----|
| Classify fields during discovery run | `classify_field` tool directly |
| Generate a unified VIEW on-the-fly | `create_unified_view` tool directly |
| Batch schema migration script | devops agent + this reference |
| CI schema drift detection | devops agent generates standalone `.py` |
