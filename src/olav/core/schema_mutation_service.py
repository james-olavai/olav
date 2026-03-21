"""Schema mutation staging service.

This service is the platform-owned control-plane entry point for schema changes.
It does not write shared DuckDB or LanceDB state directly. Instead, it validates
requests and stages them to a JSONL file for later review and application.

Lifecycle::

    service.stage_request(req)          # agents call this; writes .pending.jsonl
    service.list_pending()              # operator reviews staged requests
    service.approve_request(req_id)     # operator approves; moves to .approved.jsonl
    service.apply_approved(conn)        # platform applies to DuckDB; clears .approved.jsonl

Supported mutation_type values:
    upsert_mapping     — upsert field metadata into schema_catalog.fields
    append_evolution   — INSERT into pending_schema_evolutions
    replace_view       — CREATE OR REPLACE VIEW <target> AS <payload.sql>
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

if TYPE_CHECKING:
    import duckdb as _duckdb_type

from olav.core.config import DATABASES_DIR


@dataclass(frozen=True)
class SchemaMutationRequest:
    """Single schema mutation request staged by the control plane."""

    domain: str
    mutation_type: str
    target: str
    payload: Mapping[str, Any]
    requested_by: str = "system"
    request_id: str = field(default_factory=lambda: str(uuid4()))
    requested_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the request."""
        return asdict(self)


class SchemaMutationService:
    """Stage schema mutation requests for later approval and application."""

    def __init__(
        self,
        staging_dir: str | Path | None = None,
        staging_file_name: str = "schema_mutations.pending.jsonl",
    ) -> None:
        self.staging_dir = Path(staging_dir or DATABASES_DIR)
        self.staging_file_name = staging_file_name
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def staging_file(self) -> Path:
        """Return the JSONL file used for pending mutation requests."""
        return self.staging_dir / self.staging_file_name

    def stage_request(self, request: SchemaMutationRequest) -> dict[str, Any]:
        """Validate and append one mutation request to the staging file."""
        self._validate_request(request)
        self._append_request(request)
        return {
            "status": "staged",
            "requests_staged": 1,
            "staging_file": str(self.staging_file),
        }

    def stage_requests(self, requests: Iterable[SchemaMutationRequest]) -> dict[str, Any]:
        """Validate and append multiple mutation requests to the staging file."""
        staged = 0
        for request in requests:
            self._validate_request(request)
            self._append_request(request)
            staged += 1

        return {
            "status": "staged",
            "requests_staged": staged,
            "staging_file": str(self.staging_file),
        }

    def _append_request(self, request: SchemaMutationRequest) -> None:
        with self.staging_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _validate_request(self, request: SchemaMutationRequest) -> None:
        if not request.domain.strip():
            raise ValueError("domain must not be empty")
        if not request.mutation_type.strip():
            raise ValueError("mutation_type must not be empty")
        if not request.target.strip():
            raise ValueError("target must not be empty")
        if not request.payload:
            raise ValueError("payload must not be empty")

    # ------------------------------------------------------------------
    # Review flow
    # ------------------------------------------------------------------

    def list_pending(self) -> list[dict[str, Any]]:
        """Return all requests currently in the pending staging file."""
        if not self.staging_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.staging_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = cast(dict[str, Any], json.loads(line))
            record.setdefault("status", "pending")
            rows.append(record)
        return rows

    def approve_request(self, request_id: str) -> dict[str, Any]:
        """Move a pending request to the approved file.

        Removes the request from the pending file and appends it to
        ``schema_mutations.approved.jsonl``.

        Raises:
            KeyError: if *request_id* is not found in the pending file.
        """
        pending = self.list_pending()
        match = next((r for r in pending if r["request_id"] == request_id), None)
        if match is None:
            raise KeyError(f"No pending request with id={request_id!r}")

        # Rewrite pending file without the approved request
        remaining = [r for r in pending if r["request_id"] != request_id]
        self._write_lines(self.staging_file, remaining)

        # Append to approved file
        match["status"] = "approved"
        approved_file = self.staging_dir / "schema_mutations.approved.jsonl"
        with approved_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(match, ensure_ascii=False, sort_keys=True) + "\n")

        return {"status": "approved", "request_id": request_id}

    # ------------------------------------------------------------------
    # Apply flow
    # ------------------------------------------------------------------

    def apply_approved(self, conn: _duckdb_type.DuckDBPyConnection) -> dict[str, Any]:
        """Apply all approved mutations to *conn* and clear the approved file.

        Each request is applied atomically.  On completion the approved JSONL
        is truncated so the same request cannot be double-applied.

        Returns:
            {"applied": <int>, "errors": [<str>, ...]}
        """
        approved_file = self.staging_dir / "schema_mutations.approved.jsonl"
        if not approved_file.exists():
            return {"applied": 0, "errors": []}

        records = [
            json.loads(line)
            for line in approved_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        applied = 0
        errors: list[str] = []
        for record in records:
            try:
                self._apply_one(conn, record)
                applied += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{record.get('request_id', '?')}: {exc}")

        # Truncate approved file after processing
        approved_file.write_text("", encoding="utf-8")

        return {"applied": applied, "errors": errors}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_one(self, conn: _duckdb_type.DuckDBPyConnection, record: dict[str, Any]) -> None:
        mutation_type = record["mutation_type"]
        payload = record["payload"]
        domain = record.get("domain", "")

        if mutation_type == "upsert_mapping":
            self._apply_schema_catalog_upsert(conn, payload, domain)
        elif mutation_type == "append_evolution":
            evolution_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO pending_schema_evolutions
                    (evolution_id, cluster_id, proposal, domain)
                VALUES (?, ?, ?, ?)
                """,
                [evolution_id, payload.get("cluster_id"), payload.get("proposal"), domain],
            )
        elif mutation_type == "replace_view":
            view_name = record["target"]
            sql = payload["sql"]
            conn.execute(f"CREATE OR REPLACE VIEW {view_name} AS {sql}")  # noqa: S608
        elif mutation_type == "propose_standard":
            evolution_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO pending_schema_evolutions
                    (evolution_id, cluster_id, proposal, domain, status)
                VALUES (?, ?, ?, ?, 'pending_approval')
                """,
                [
                    evolution_id,
                    payload.get("cluster_id"),
                    payload.get("proposed_name"),
                    domain,
                ],
            )
        else:
            raise ValueError(f"Unknown mutation_type: {mutation_type!r}")

    def _apply_schema_catalog_upsert(
        self,
        conn: _duckdb_type.DuckDBPyConnection,
        payload: Mapping[str, Any],
        domain: str,
    ) -> None:
        columns = self._schema_catalog_columns(conn)
        required = {"platform", "source_name", "fields"}
        missing = required - columns
        if missing:
            raise ValueError(
                f"schema_catalog missing required columns for upsert_mapping: {sorted(missing)}"
            )

        platform = str(payload.get("platform") or payload.get("vendor") or domain).strip()
        source_name = str(payload.get("source_name") or payload.get("command") or "").strip()
        if not platform:
            raise ValueError("upsert_mapping requires a non-empty platform")
        if not source_name:
            raise ValueError("upsert_mapping requires a non-empty source_name")

        field_updates = self._extract_catalog_field_updates(payload)
        row_exists, existing_fields = self._load_schema_catalog_row(
            conn,
            columns,
            platform,
            source_name,
        )
        merged_fields = self._merge_catalog_fields(existing_fields, field_updates)
        fields_json = json.dumps(merged_fields, ensure_ascii=False, sort_keys=True)

        if row_exists:
            assignments = ["fields = ?"]
            params: list[Any] = [fields_json]
            if "updated_at" in columns:
                assignments.append("updated_at = ?")
                params.append(self._catalog_timestamp())
            params.extend([platform, source_name])
            conn.execute(
                f"UPDATE schema_catalog SET {', '.join(assignments)} "
                "WHERE platform = ? AND source_name = ?",
                params,
            )
            return

        insert_values: dict[str, Any] = {
            "platform": platform,
            "source_name": source_name,
            "fields": fields_json,
        }
        if "source_type" in columns:
            insert_values["source_type"] = str(payload.get("source_type") or "textfsm")
        if "description" in columns:
            insert_values["description"] = str(payload.get("description") or "")
        if "updated_at" in columns:
            insert_values["updated_at"] = self._catalog_timestamp()

        insert_order = [
            column
            for column in (
                "source_type",
                "source_name",
                "platform",
                "fields",
                "description",
                "updated_at",
            )
            if column in columns and column in insert_values
        ]
        placeholders = ", ".join("?" for _ in insert_order)
        conn.execute(
            f"INSERT INTO schema_catalog ({', '.join(insert_order)}) VALUES ({placeholders})",
            [insert_values[column] for column in insert_order],
        )

    @staticmethod
    def _schema_catalog_columns(conn: _duckdb_type.DuckDBPyConnection) -> set[str]:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = 'schema_catalog'"
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _load_schema_catalog_row(
        self,
        conn: _duckdb_type.DuckDBPyConnection,
        columns: set[str],
        platform: str,
        source_name: str,
    ) -> tuple[bool, list[Any]]:
        order_by = " ORDER BY updated_at DESC NULLS LAST" if "updated_at" in columns else ""
        row = conn.execute(
            "SELECT fields FROM schema_catalog WHERE platform = ? AND source_name = ?"
            f"{order_by} LIMIT 1",
            [platform, source_name],
        ).fetchone()
        if row is None:
            return False, []

        raw_fields = row[0]
        if raw_fields in (None, ""):
            return True, []

        parsed_fields = json.loads(raw_fields) if isinstance(raw_fields, str) else raw_fields
        if not isinstance(parsed_fields, list):
            raise ValueError(
                f"schema_catalog.fields must be a list for platform={platform!r}, "
                f"source_name={source_name!r}"
            )
        return True, cast(list[Any], parsed_fields)

    @staticmethod
    def _extract_catalog_field_updates(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw_fields = payload.get("fields")
        candidate_fields: list[dict[str, Any]] = []
        if isinstance(raw_fields, list):
            for field in cast(list[Any], raw_fields):
                if isinstance(field, dict):
                    candidate_fields.append(cast(dict[str, Any], field))

        if not candidate_fields:
            candidate_fields = [dict(payload)]

        updates: list[dict[str, Any]] = []
        for field in candidate_fields:
            update = dict(field)
            name = str(
                update.get("name")
                or update.get("src_field")
                or update.get("raw_key")
                or payload.get("src_field")
                or payload.get("raw_key")
                or ""
            ).strip()
            openconfig_path = str(
                update.get("openconfig_path")
                or update.get("oc_path")
                or update.get("canonical_path")
                or payload.get("openconfig_path")
                or payload.get("oc_path")
                or payload.get("canonical_path")
                or ""
            ).strip()
            if not name or not openconfig_path:
                continue

            if "method" not in update and payload.get("method"):
                update["method"] = payload["method"]
            update["name"] = name
            update["openconfig_path"] = openconfig_path
            update["oc_path"] = openconfig_path
            updates.append(update)

        if not updates:
            raise ValueError("upsert_mapping requires at least one field name and openconfig_path")
        return updates

    @staticmethod
    def _merge_catalog_fields(
        existing_fields: list[Any],
        field_updates: list[dict[str, Any]],
    ) -> list[Any]:
        merged_fields: list[Any] = []
        for item in existing_fields:
            if isinstance(item, dict):
                merged_fields.append(dict(cast(dict[str, Any], item)))
            else:
                merged_fields.append(item)

        for update in field_updates:
            target_name = update["name"]
            match_index: int | None = None
            for index, field in enumerate(merged_fields):
                if isinstance(field, dict):
                    field_dict = cast(dict[str, Any], field)
                    if str(field_dict.get("name", "")) == target_name:
                        match_index = index
                        break

            if match_index is None:
                merged_fields.append(dict(update))
                continue

            existing = merged_fields[match_index]
            if not isinstance(existing, dict):
                merged_fields[match_index] = dict(update)
                continue

            merged_entry = dict(cast(dict[str, Any], existing))
            merged_entry.update(update)
            merged_entry["name"] = target_name
            merged_entry["openconfig_path"] = update["openconfig_path"]
            merged_entry["oc_path"] = update["openconfig_path"]
            merged_fields[match_index] = merged_entry

        return merged_fields

    @staticmethod
    def _catalog_timestamp() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _write_lines(path: Path, records: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
