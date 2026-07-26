"""DuckDB-backed OpenAPI / Swagger schema registry for the OLAV platform.

Stores normalized operation and definition tables in a shared DuckDB file so
that skill-side consumers (e.g. clab_client.py) can query the registry via
direct DuckDB access without importing any OLAV Python modules.

Public API (sync):
    load_schema   – fetch & persist a remote schema
    find_path     – exact (api_name, method, path) lookup
    field_names   – property names for a definition
    verify_operations – bulk check of required ops
    is_loaded     – quick existence check
    list_apis     – summary of all registered APIs

CLI:
    python -m olav.core.api_registry load <api_name> <schema_url> [--base-url URL] [--db PATH] [--force]
    python -m olav.core.api_registry list [--db PATH]
    python -m olav.core.api_registry find <api_name> <method> <path> [--db PATH]
    python -m olav.core.api_registry fields <api_name> <def_name> [--db PATH]
    python -m olav.core.api_registry verify <api_name> [--ops "METHOD PATH,..."] [--db PATH]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any

from olav.core.db_write import open_write_connection

import duckdb
import httpx

# ---------------------------------------------------------------------------
# Default DB location
# ---------------------------------------------------------------------------

DEFAULT_DB = Path.home() / ".olav" / "olav_registry.duckdb"

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_DDL = """
CREATE SCHEMA IF NOT EXISTS api_registry;

CREATE TABLE IF NOT EXISTS api_registry.schemas (
    api_name     VARCHAR PRIMARY KEY,
    base_url     VARCHAR NOT NULL,
    schema_url   VARCHAR NOT NULL,
    fetched_at   VARCHAR NOT NULL,
    spec_version VARCHAR,
    raw_doc      JSON
);

CREATE TABLE IF NOT EXISTS api_registry.operations (
    api_name         VARCHAR NOT NULL,
    method           VARCHAR NOT NULL,
    path             VARCHAR NOT NULL,
    summary          VARCHAR,
    tags             VARCHAR[],
    request_body_def VARCHAR,
    response_200_def VARCHAR,
    query_params     JSON,
    PRIMARY KEY (api_name, method, path)
);

CREATE TABLE IF NOT EXISTS api_registry.definitions (
    api_name  VARCHAR NOT NULL,
    def_name  VARCHAR NOT NULL,
    fields    JSON NOT NULL,
    PRIMARY KEY (api_name, def_name)
);
"""


@contextmanager
def _open(db_path: Path, read_only: bool = False):
    """Yield a connection to the api_registry DB.

    Reads connect directly; writes go through the shared write seam
    (open_write_connection) so they serialise with every other DuckDB writer
    (in-process lock + connect-retry in OSS, enterprise flock queue when
    olav-ent is installed — ADR-0018/0019).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            yield con
        finally:
            con.close()
        return
    with open_write_connection(db_path) as con:
        con.executemany("", [])  # noop to ensure connection is live
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                con.execute(stmt)
        # Migrate: add query_params column to existing DBs that predate this column
        try:
            con.execute(
                "ALTER TABLE api_registry.operations ADD COLUMN IF NOT EXISTS query_params JSON"
            )
        except Exception:
            pass  # column already exists or DDL already added it
        yield con


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _ref_short(ref: str) -> str | None:
    """Extract short name from a $ref string.

    '#/definitions/models.ExecRequest' → 'ExecRequest'
    '#/components/schemas/ExecRequest' → 'ExecRequest'
    """
    if not ref:
        return None
    name = ref.rsplit("/", 1)[-1]
    # Strip common prefixes like "models."
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return name or None


def _resolve_ref(schema_obj: dict | None) -> str | None:
    """Return short def name from a schema object that may contain $ref directly
    or under items (for arrays)."""
    if not schema_obj:
        return None
    ref = schema_obj.get("$ref")
    if ref:
        return _ref_short(ref)
    # Array wrapper: {"type": "array", "items": {"$ref": "..."}}
    items = schema_obj.get("items", {})
    if items:
        ref = items.get("$ref")
        if ref:
            return _ref_short(ref)
    return None


def _normalize_swagger2(doc: dict, api_name: str) -> tuple[list[dict], list[dict]]:
    """Return (ops_rows, def_rows) from a Swagger 2.0 document."""
    ops_rows: list[dict] = []
    def_rows: list[dict] = []

    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for path, methods_obj in doc.get("paths", {}).items():
        for method, op_obj in methods_obj.items():
            if method.lower() not in http_methods:
                continue
            if not isinstance(op_obj, dict):
                continue

            summary = op_obj.get("summary") or op_obj.get("operationId")
            tags = op_obj.get("tags") or []

            # request_body_def – from parameters where in=body
            req_body_def: str | None = None
            query_params: list[dict] = []
            for param in op_obj.get("parameters", []):
                if param.get("in") == "body":
                    schema_obj = param.get("schema", {})
                    req_body_def = _resolve_ref(schema_obj)
                elif param.get("in") == "query":
                    query_params.append({
                        "name": param.get("name", ""),
                        "type": param.get("type") or param.get("schema", {}).get("type", "string"),
                        "description": param.get("description", ""),
                        "required": param.get("required", False),
                    })

            # response_200_def
            resp_200 = (
                op_obj.get("responses", {}).get("200", {})
                or op_obj.get("responses", {}).get("201", {})
            )
            resp_schema = resp_200.get("schema") if isinstance(resp_200, dict) else None
            resp_200_def = _resolve_ref(resp_schema) if resp_schema else None

            ops_rows.append({
                "api_name": api_name,
                "method": method.upper(),
                "path": path,
                "summary": summary,
                "tags": tags,
                "request_body_def": req_body_def,
                "response_200_def": resp_200_def,
                "query_params": query_params,
            })

    # Definitions
    for def_name, def_body in doc.get("definitions", {}).items():
        short_name = _ref_short(f"#/definitions/{def_name}")
        props = def_body.get("properties", {})
        fields: dict[str, str] = {}
        for prop_name, prop_body in props.items():
            if not isinstance(prop_body, dict):
                fields[prop_name] = "unknown"
                continue
            if "$ref" in prop_body:
                fields[prop_name] = _ref_short(prop_body["$ref"]) or "ref"
            elif prop_body.get("type") == "array":
                item_ref = _resolve_ref(prop_body)
                fields[prop_name] = f"array[{item_ref}]" if item_ref else "array"
            else:
                fields[prop_name] = prop_body.get("type", "unknown")

        def_rows.append({
            "api_name": api_name,
            "def_name": short_name,
            "fields": fields,
        })

    return ops_rows, def_rows


def _normalize_openapi3(doc: dict, api_name: str) -> tuple[list[dict], list[dict]]:
    """Return (ops_rows, def_rows) from an OpenAPI 3.0 document."""
    ops_rows: list[dict] = []
    def_rows: list[dict] = []

    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for path, methods_obj in doc.get("paths", {}).items():
        for method, op_obj in methods_obj.items():
            if method.lower() not in http_methods:
                continue
            if not isinstance(op_obj, dict):
                continue

            summary = op_obj.get("summary") or op_obj.get("operationId")
            tags = op_obj.get("tags") or []

            # request_body_def
            req_body_def: str | None = None
            req_body = op_obj.get("requestBody", {})
            if req_body:
                content = req_body.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                req_body_def = _resolve_ref(json_schema)

            # query_params – OpenAPI 3.x uses parameters list with in=query
            query_params: list[dict] = []
            for param in op_obj.get("parameters", []):
                if param.get("in") == "query":
                    schema_obj = param.get("schema", {})
                    query_params.append({
                        "name": param.get("name", ""),
                        "type": schema_obj.get("type", "string") if schema_obj else "string",
                        "description": param.get("description", ""),
                        "required": param.get("required", False),
                    })

            # response_200_def
            resp_200 = (
                op_obj.get("responses", {}).get("200", {})
                or op_obj.get("responses", {}).get("201", {})
            )
            resp_200_def: str | None = None
            if isinstance(resp_200, dict):
                content = resp_200.get("content", {})
                resp_schema = content.get("application/json", {}).get("schema", {})
                resp_200_def = _resolve_ref(resp_schema) if resp_schema else None

            ops_rows.append({
                "api_name": api_name,
                "method": method.upper(),
                "path": path,
                "summary": summary,
                "tags": tags,
                "request_body_def": req_body_def,
                "response_200_def": resp_200_def,
                "query_params": query_params,
            })

    # Definitions from components/schemas
    for def_name, def_body in doc.get("components", {}).get("schemas", {}).items():
        short_name = _ref_short(f"#/components/schemas/{def_name}")
        props = def_body.get("properties", {})
        fields: dict[str, str] = {}
        for prop_name, prop_body in props.items():
            if not isinstance(prop_body, dict):
                fields[prop_name] = "unknown"
                continue
            if "$ref" in prop_body:
                fields[prop_name] = _ref_short(prop_body["$ref"]) or "ref"
            elif prop_body.get("type") == "array":
                item_ref = _resolve_ref(prop_body)
                fields[prop_name] = f"array[{item_ref}]" if item_ref else "array"
            else:
                fields[prop_name] = prop_body.get("type", "unknown")

        def_rows.append({
            "api_name": api_name,
            "def_name": short_name,
            "fields": fields,
        })

    return ops_rows, def_rows


def _detect_version(doc: dict) -> str:
    """Return 'swagger:2.0' or 'openapi:3.x.y'."""
    if "swagger" in doc:
        return f"swagger:{doc['swagger']}"
    if "openapi" in doc:
        return f"openapi:{doc['openapi']}"
    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_schema(
    api_name: str,
    schema_url: str,
    base_url: str,
    db_path: Path = DEFAULT_DB,
    force: bool = False,
) -> int:
    """Fetch schema_url, normalise, store in db_path. Returns operations count.

    Skips fetch if already loaded, unless force=True.
    Supports Swagger 2.0 and OpenAPI 3.0.
    """
    db_path = Path(db_path)

    # Fast check if already loaded
    if not force and is_loaded(api_name, db_path):
        with _open(db_path, read_only=True) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM api_registry.operations WHERE api_name=?",
                [api_name],
            ).fetchone()
        return row[0] if row else 0

    # Fetch schema — JSON first, YAML fallback
    try:
        from olav.core.config import get_services_config
        _api_registry_timeout = get_services_config().api_registry_timeout
    except Exception:
        _api_registry_timeout = 30.0
    with httpx.Client(timeout=_api_registry_timeout) as client:
        resp = client.get(schema_url)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "yaml" in ct or "yml" in ct:
            import yaml as _yaml
            doc: dict[str, Any] = _yaml.safe_load(resp.text)
        else:
            try:
                doc = resp.json()
            except Exception:
                import yaml as _yaml
                doc = _yaml.safe_load(resp.text)

    spec_version = _detect_version(doc)

    if spec_version.startswith("swagger:"):
        ops_rows, def_rows = _normalize_swagger2(doc, api_name)
    elif spec_version.startswith("openapi:"):
        ops_rows, def_rows = _normalize_openapi3(doc, api_name)
    else:
        # Fallback: try swagger2 path
        ops_rows, def_rows = _normalize_swagger2(doc, api_name)

    fetched_at = datetime.now(tz=timezone.utc).isoformat()
    raw_doc_json = json.dumps(doc)

    with _open(db_path) as con:
        # Upsert schema row
        con.execute(
            """
            INSERT INTO api_registry.schemas
                (api_name, base_url, schema_url, fetched_at, spec_version, raw_doc)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (api_name) DO UPDATE SET
                base_url=excluded.base_url,
                schema_url=excluded.schema_url,
                fetched_at=excluded.fetched_at,
                spec_version=excluded.spec_version,
                raw_doc=excluded.raw_doc
            """,
            [api_name, base_url, schema_url, fetched_at, spec_version, raw_doc_json],
        )

        # Delete existing rows for this api_name before re-inserting
        con.execute("DELETE FROM api_registry.operations WHERE api_name=?", [api_name])
        con.execute("DELETE FROM api_registry.definitions WHERE api_name=?", [api_name])

        # Insert operations
        for row in ops_rows:
            con.execute(
                """
                INSERT INTO api_registry.operations
                    (api_name, method, path, summary, tags, request_body_def, response_200_def, query_params)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["api_name"],
                    row["method"],
                    row["path"],
                    row["summary"],
                    row["tags"],
                    row["request_body_def"],
                    row["response_200_def"],
                    json.dumps(row.get("query_params") or []),
                ],
            )

        # Insert definitions
        for row in def_rows:
            con.execute(
                """
                INSERT INTO api_registry.definitions (api_name, def_name, fields)
                VALUES (?, ?, ?)
                """,
                [row["api_name"], row["def_name"], json.dumps(row["fields"])],
            )

    return len(ops_rows)


def find_path(
    api_name: str,
    method: str,
    path: str,
    db_path: Path = DEFAULT_DB,
) -> str:
    """Return path from registry for exact (api_name, method, path) match.

    Raises KeyError if not found.
    """
    db_path = Path(db_path)
    with _open(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT path FROM api_registry.operations WHERE api_name=? AND method=? AND path=?",
            [api_name, method.upper(), path],
        ).fetchone()
    if not row:
        raise KeyError(f"Operation not found in registry: {method.upper()} {path} for api '{api_name}'")
    return row[0]


def field_names(
    api_name: str,
    def_name: str,
    db_path: Path = DEFAULT_DB,
) -> set[str]:
    """Return field names for a definition.

    e.g. field_names("clab", "ExecRequest") -> {"command"}
    Returns empty set if definition not found.
    """
    db_path = Path(db_path)
    with _open(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT fields FROM api_registry.definitions WHERE api_name=? AND def_name=?",
            [api_name, def_name],
        ).fetchone()
    if not row:
        return set()
    return set(json.loads(row[0]).keys())


def verify_operations(
    api_name: str,
    ops: dict[str, tuple[str, str]],
    db_path: Path = DEFAULT_DB,
) -> None:
    """Raise KeyError listing all missing (method, path) pairs."""
    db_path = Path(db_path)
    missing: list[str] = []
    with _open(db_path, read_only=True) as con:
        for name, (method, path) in ops.items():
            row = con.execute(
                "SELECT 1 FROM api_registry.operations WHERE api_name=? AND method=? AND path=?",
                [api_name, method.upper(), path],
            ).fetchone()
            if not row:
                missing.append(f"{name}: {method.upper()} {path}")
    if missing:
        raise KeyError(f"Operations missing from registry for '{api_name}': {missing}")


def get_query_params(
    api_name: str,
    tag: str | None = None,
    db_path: Path = DEFAULT_DB,
) -> dict[str, list[dict]]:
    """Return per-operation query params from the registry.

    Returns a dict keyed by "METHOD /path" with a list of query param dicts:
        {"name": "status", "type": "string", "description": "...", "required": False}

    Optionally filtered by tag.
    """
    db_path = Path(db_path)
    tag_clause = "AND list_contains(tags, ?)" if tag else ""
    params = [api_name]
    if tag:
        params.append(tag)

    with _open(db_path, read_only=True) as con:
        rows = con.execute(
            f"""
            SELECT method, path, query_params
            FROM api_registry.operations
            WHERE api_name = ? {tag_clause}
            ORDER BY path, method
            """,
            params,
        ).fetchall()

    result: dict[str, list[dict]] = {}
    for method, path, qp_json in rows:
        qp = json.loads(qp_json) if isinstance(qp_json, str) else (qp_json or [])
        result[f"{method} {path}"] = qp
    return result


def is_loaded(api_name: str, db_path: Path = DEFAULT_DB) -> bool:
    """Return True if api_name has operations in the registry."""
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    try:
        with _open(db_path, read_only=True) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM api_registry.operations WHERE api_name=?",
                [api_name],
            ).fetchone()
        return (row[0] if row else 0) > 0
    except Exception:
        return False


def list_apis(db_path: Path = DEFAULT_DB) -> list[dict]:
    """Return list of {api_name, base_url, fetched_at, op_count} dicts."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    try:
        with _open(db_path, read_only=True) as con:
            rows = con.execute(
                """
                SELECT s.api_name, s.base_url, s.fetched_at,
                       COUNT(o.path) AS op_count
                FROM api_registry.schemas s
                LEFT JOIN api_registry.operations o USING (api_name)
                GROUP BY s.api_name, s.base_url, s.fetched_at
                ORDER BY s.api_name
                """
            ).fetchall()
        return [
            {
                "api_name": r[0],
                "base_url": r[1],
                "fetched_at": r[2],
                "op_count": r[3],
            }
            for r in rows
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli_load(args: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="api_registry load")
    p.add_argument("api_name")
    p.add_argument("schema_url")
    p.add_argument("--base-url", default="")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--force", action="store_true")
    ns = p.parse_args(args)

    base_url = ns.base_url or ns.schema_url.rsplit("/swagger", 1)[0]
    count = load_schema(
        api_name=ns.api_name,
        schema_url=ns.schema_url,
        base_url=base_url,
        db_path=Path(ns.db),
        force=ns.force,
    )
    print(f"Loaded {count} operations for '{ns.api_name}' into {ns.db}")
    return 0


def _cli_list(args: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="api_registry list")
    p.add_argument("--db", default=str(DEFAULT_DB))
    ns = p.parse_args(args)

    apis = list_apis(db_path=Path(ns.db))
    if not apis:
        print("No APIs registered.")
        return 0
    for api in apis:
        print(
            f"{api['api_name']:20s}  ops={api['op_count']:3d}  "
            f"base={api['base_url']}  fetched={api['fetched_at']}"
        )
    return 0


def _cli_find(args: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="api_registry find")
    p.add_argument("api_name")
    p.add_argument("method")
    p.add_argument("path")
    p.add_argument("--db", default=str(DEFAULT_DB))
    ns = p.parse_args(args)

    try:
        result = find_path(ns.api_name, ns.method, ns.path, db_path=Path(ns.db))
        print(result)
        return 0
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1


def _cli_fields(args: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="api_registry fields")
    p.add_argument("api_name")
    p.add_argument("def_name")
    p.add_argument("--db", default=str(DEFAULT_DB))
    ns = p.parse_args(args)

    names = field_names(ns.api_name, ns.def_name, db_path=Path(ns.db))
    if not names:
        print(f"Definition '{ns.def_name}' not found for api '{ns.api_name}'", file=sys.stderr)
        return 1
    print(sorted(names))
    return 0


def _cli_verify(args: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="api_registry verify")
    p.add_argument("api_name")
    p.add_argument(
        "--ops",
        default="",
        help='Comma-separated "METHOD PATH" pairs, e.g. "GET /api/v1/labs,POST /login"',
    )
    p.add_argument("--db", default=str(DEFAULT_DB))
    ns = p.parse_args(args)

    ops: dict[str, tuple[str, str]] = {}
    if ns.ops:
        for i, pair in enumerate(ns.ops.split(",")):
            parts = pair.strip().split(None, 1)
            if len(parts) == 2:
                ops[f"op_{i}"] = (parts[0], parts[1])

    try:
        verify_operations(ns.api_name, ops, db_path=Path(ns.db))
        print(f"All operations verified for '{ns.api_name}'")
        return 0
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(
            "Usage: python -m olav.core.api_registry "
            "<load|list|find|fields|verify> [args...]"
        )
        return 1

    sub = argv[0]
    rest = argv[1:]

    if sub == "load":
        return _cli_load(rest)
    elif sub == "list":
        return _cli_list(rest)
    elif sub == "find":
        return _cli_find(rest)
    elif sub == "fields":
        return _cli_fields(rest)
    elif sub == "verify":
        return _cli_verify(rest)
    else:
        print(f"Unknown subcommand: {sub}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
