"""Schema Engine — Phase 1 core implementation.

Provides:
    build_semantic_summary(field)       → str
    build_mutation_request(...)         → SchemaMutationRequest
    create_unified_view(command, maps)  → SQL str
    get_domain_collection(domain)       → str
    SchemaEngine                        → classify_field / save_mapping

Design notes (api_discovery.md §3, §4):
  - Embedder is optional: gracefully degrades to "unclassified" when absent.
  - LanceDB table per domain: ``{domain}_field_mappings`` (olav_platform.md §12.5).
  - Distance conversion: confidence = 1.0 - (distance / 2.0), values in [0, 1].
  - SchemaEngine never writes shared DB directly; all changes go through
    SchemaMutationService.stage_request().
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pure helpers — no dependencies on runtime services
# ---------------------------------------------------------------------------


def build_semantic_summary(field: dict[str, Any]) -> str:
    """Join field metadata into a pipe-delimited semantic summary string.

    Empty / falsy values are excluded so vectors stay dense with signal.

    >>> build_semantic_summary({"name": "ip_address", "description": "IPv4 mgmt"})
    'ip_address | IPv4 mgmt'
    """
    parts = [
        field.get("name", ""),
        field.get("description", ""),
        field.get("type", ""),
        str(field.get("example", "")) if field.get("example") is not None else "",
        field.get("command", ""),
    ]
    return " | ".join(p for p in parts if p)

def get_domain_collection(domain: str) -> str:
    """Derive the LanceDB collection name for a given domain.

    Convention (olav_platform.md \u00a712.5):
        ``{domain}_field_mappings``

    Examples
    --------
    >>> get_domain_collection("netops")
    'netops_field_mappings'
    >>> get_domain_collection("itsm")
    'itsm_field_mappings'

    Platform code should always call this helper instead of hardcoding
    collection names so that the naming convention is enforced uniformly.
    """
    return f"{domain}_field_mappings"


def create_unified_view(command: str, mappings: list[dict[str, Any]]) -> str:
    """Generate a ``CREATE OR REPLACE VIEW`` SQL statement.

    The view name is derived from *command* with spaces and hyphens
    replaced by underscores, prefixed ``v_unified_``.

    Parameters
    ----------
    command:
        CLI command string, e.g. ``"show interfaces"``.
    mappings:
        List of ``{"raw_key", "standard_name", "data_type"}`` dicts.
    """
    view_name = "v_unified_" + command.strip().replace(" ", "_").replace("-", "_")
    cols_parts: list[str] = []
    for m in mappings:
        raw_key = m["raw_key"]
        std_name = m["standard_name"]
        data_type = m.get("data_type", "VARCHAR")
        cols_parts.append(
            f"  TRY_CAST(parsed_data->>'{raw_key}' AS {data_type}) AS {std_name}"
        )
    cols_sql = (",\n".join(cols_parts) + ",\n") if cols_parts else ""
    return (
        f"CREATE OR REPLACE VIEW {view_name} AS\n"
        f"SELECT\n"
        f"  device_name,\n"
        f"  snapshot_id,\n"
        f"{cols_sql}"
        f"  parsed_data AS raw_attributes\n"
        f"FROM parsed_outputs\n"
        f"WHERE command = '{command}'"
    )


def build_mutation_request(
    domain: str,
    mutation_type: str,
    target: str,
    payload: dict[str, Any],
    requested_by: str = "schema_engine",
):
    """Convenience factory for ``SchemaMutationRequest``."""
    from olav.core.schema_mutation_service import SchemaMutationRequest

    return SchemaMutationRequest(
        domain=domain,
        mutation_type=mutation_type,
        target=target,
        payload=payload,
        requested_by=requested_by,
    )


# ---------------------------------------------------------------------------
# SchemaEngine — stateful classifier that delegates writes to the service
# ---------------------------------------------------------------------------


_SENTINEL = object()


class SchemaEngine:
    """Vector-first field classifier backed by LanceDB + SchemaMutationService.

    Parameters
    ----------
    mutation_service:
        A ``SchemaMutationService`` instance (or compatible mock) that will
        receive ``stage_request()`` calls.
    embedder:
        A ``SentenceTransformer``-compatible object with an ``encode()`` method.
        Pass ``None`` to disable vector classification (graceful degradation).
    _lancedb_override:
        Inject a pre-connected LanceDB database object instead of opening one
        from ``DATABASES_DIR``.  Intended for testing only.
    """

    # Confidence thresholds (api_discovery.md §3.2)
    _TIER0_THRESHOLD = 0.85
    _TIER1_THRESHOLD = 0.60

    def __init__(
        self,
        mutation_service: Any,
        embedder: Any = _SENTINEL,
        _lancedb_override: Any = None,
    ) -> None:
        self._svc = mutation_service
        # Allow caller to pass ``None`` explicitly (disabled embedder)
        if embedder is _SENTINEL:
            from olav.core.embedder import get_embedder
            self._embedder = get_embedder()
        else:
            self._embedder = embedder
        self._lancedb_override = _lancedb_override

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_field(self, field_metadata: dict[str, Any]) -> dict[str, Any]:
        """Classify *field_metadata* and stage the appropriate mutation request.

        Returns a dict with keys: ``status``, ``confidence``,
        and optionally ``standard_name``.
        """
        if not self._embedder:
            return {"status": "unclassified", "confidence": 0.0}

        domain = field_metadata.get("domain", "platform")
        summary = build_semantic_summary(field_metadata)

        try:
            vector = self._embedder.encode(
                summary, normalize_embeddings=True
            ).tolist()
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)
            return {"status": "unclassified", "confidence": 0.0}

        db = self._get_lancedb()
        if db is None:
            return {"status": "unclassified", "confidence": 0.0}

        try:
            table = db.open_table(get_domain_collection(domain))
            results = table.search(vector).limit(1).to_list()
        except Exception as exc:
            logger.warning("LanceDB lookup failed: %s", exc)
            return {"status": "unclassified", "confidence": 0.0}

        if not results:
            self._stage_evolution(field_metadata, vector, domain)
            return {"status": "unclassified", "confidence": 0.0}

        # Distance in [0, 2] (cosine) → confidence in [0, 1]
        distance = results[0].get("_distance", 2.0)
        confidence = 1.0 - (distance / 2.0)

        if confidence > self._TIER0_THRESHOLD:
            standard_name = results[0]["standard_name"]
            self.save_mapping(field_metadata, standard_name, method="vector")
            return {
                "status": "matched",
                "standard_name": standard_name,
                "confidence": confidence,
            }

        if confidence >= self._TIER1_THRESHOLD:
            standard_name = self._llm_confirm(field_metadata, results[0], confidence)
            self.save_mapping(field_metadata, standard_name, method="llm_confirm")
            return {
                "status": "llm_confirmed",
                "standard_name": standard_name,
                "confidence": confidence,
            }

        # Tier 2: below threshold → evolution pool
        self._stage_evolution(field_metadata, vector, domain)
        return {"status": "unclassified", "confidence": confidence}

    def save_mapping(
        self,
        field_metadata: dict[str, Any],
        standard_name: str,
        method: str = "vector",
    ) -> None:
        """Stage a ``upsert_mapping`` mutation request."""
        domain = field_metadata.get("domain", "platform")
        req = build_mutation_request(
            domain=domain,
            mutation_type="upsert_mapping",
            target="schema_mappings",
            payload={
                "raw_key": field_metadata.get("name", ""),
                "standard_name": standard_name,
                "vendor": field_metadata.get("vendor", ""),
                "command": field_metadata.get("command", ""),
                "method": method,
            },
        )
        self._svc.stage_request(req)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_lancedb(self) -> Any:
        if self._lancedb_override is not None:
            return self._lancedb_override
        try:
            import lancedb

            from olav.core.config import DATABASES_DIR
            return lancedb.connect(str(DATABASES_DIR / "memory.lancedb"))
        except Exception as exc:
            logger.warning("LanceDB connection failed: %s", exc)
            return None

    def _llm_confirm(
        self,
        field_metadata: dict[str, Any],
        top_result: dict[str, Any],
        confidence: float,
    ) -> str:
        """Zero-shot LLM confirmation for borderline matches.

        Returns the confirmed ``standard_name`` (or the vector hit as fallback).
        """
        try:
            from olav.core.llm import LLMFactory
            llm = LLMFactory.get_chat_model(agent_id="schema_engine")
            prompt = (
                f"Field name: {field_metadata.get('name')}\n"
                f"Description: {field_metadata.get('description', '')}\n"
                f"Best vector match: {top_result['standard_name']} "
                f"(confidence={confidence:.2f})\n\n"
                "Respond with ONLY the most appropriate standard field name "
                "from the vector match or a closely related name. "
                "If the match is correct, repeat it exactly."
            )
            response = llm.invoke(prompt)
            content = getattr(response, "content", str(response)).strip().split()[0]
            return content or top_result["standard_name"]
        except Exception as exc:
            logger.warning("LLM confirm failed: %s", exc)
            return top_result["standard_name"]

    def _stage_evolution(
        self,
        field_metadata: dict[str, Any],
        vector: list[float],
        domain: str,
    ) -> None:
        """Stage an ``append_evolution`` mutation request for unclassified fields."""
        req = build_mutation_request(
            domain=domain,
            mutation_type="append_evolution",
            target="pending_schema_evolutions",
            payload={
                "raw_key": field_metadata.get("name", ""),
                "command": field_metadata.get("command", ""),
                "vector_preview": vector[:8],  # store first 8 dims for debug
                "sample_field": field_metadata,
            },
        )
        self._svc.stage_request(req)


    # ------------------------------------------------------------------
    # Evolution trigger — Phase 5 (api_discovery.md §3.5)
    # ------------------------------------------------------------------

    def evolve_trigger(
        self,
        conn: Any,
        domain: str = "platform",
        min_samples: int = 3,
    ) -> dict[str, Any]:
        """Cluster unclassified evolution-pool vectors and propose new standard fields.

        Uses ``sklearn.cluster.OPTICS`` (scikit-learn, already a project dependency).
        High-confidence clusters are submitted to LLM for naming, then staged as
        ``propose_standard`` mutation requests pending human approval via
        ``olav config evolve --list / --approve <id>``.

        Parameters
        ----------
        conn:
            A live DuckDB connection that has a ``pending_schema_evolutions`` table.
        domain:
            Domain namespace to scope the cluster proposals.
        min_samples:
            OPTICS ``min_samples`` — minimum cluster density threshold.

        Returns
        -------
        dict with keys:
            ``clusters_found``  — number of dense clusters detected
            ``proposals``       — list of proposed standard field names staged for review
            ``skipped``         — reason string if evolution was skipped, else ``None``
        """
        try:
            rows = conn.execute(
                "SELECT raw_key, command, vector_preview, sample_field"
                " FROM pending_schema_evolutions WHERE status = 'pending'"
            ).fetchall()
        except Exception as exc:
            return {"clusters_found": 0, "proposals": [], "skipped": f"DB read failed: {exc}"}

        if len(rows) < min_samples:
            return {
                "clusters_found": 0,
                "proposals": [],
                "skipped": (
                    f"Not enough unclassified fields ({len(rows)} < min_samples={min_samples})"
                ),
            }

        try:
            import numpy as np
            from sklearn.cluster import OPTICS
        except ImportError as exc:  # pragma: no cover
            return {"clusters_found": 0, "proposals": [], "skipped": f"scikit-learn unavailable: {exc}"}

        # Reconstruct vectors from stored 8-dim vector_preview.
        # In a future version the full 384-dim vectors would be stored in a
        # dedicated LanceDB evolution_pool table for higher-quality clustering.
        vectors = []
        for row in rows:
            preview = row[2]  # vector_preview column
            if isinstance(preview, list | tuple) and len(preview) > 0:
                vectors.append(list(map(float, preview)))
            else:
                vectors.append([0.0] * 8)

        vectors_array = np.array(vectors, dtype=np.float32)
        # Pad or trim to uniform length (shouldn't happen, defensive)
        if vectors_array.ndim != 2 or vectors_array.shape[1] < 2:
            return {"clusters_found": 0, "proposals": [], "skipped": "Degenerate feature vectors"}

        clustering = OPTICS(min_samples=min_samples, metric="euclidean").fit(vectors_array)
        labels = clustering.labels_  # -1 = noise

        unique_clusters = set(labels) - {-1}
        if not unique_clusters:
            return {
                "clusters_found": 0,
                "proposals": [],
                "skipped": "No dense clusters found — accumulating more data",
            }

        proposals: list[str] = []
        for cluster_id in sorted(unique_clusters):
            member_indices = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
            raw_keys = [rows[i][0] for i in member_indices]
            sample_fields = [rows[i][3] for i in member_indices]

            proposed_name = self._llm_propose_standard_name(raw_keys, sample_fields, domain)
            proposals.append(proposed_name)

            req = build_mutation_request(
                domain=domain,
                mutation_type="propose_standard",
                target="pending_schema_evolutions",
                payload={
                    "proposed_name": proposed_name,
                    "cluster_id": int(cluster_id),
                    "member_count": len(member_indices),
                    "sample_raw_keys": raw_keys[:5],
                },
                requested_by="evolve_trigger",
            )
            self._svc.stage_request(req)

        return {
            "clusters_found": len(unique_clusters),
            "proposals": proposals,
            "skipped": None,
        }

    def _llm_propose_standard_name(
        self,
        raw_keys: list[str],
        sample_fields: list[Any],
        domain: str,
    ) -> str:
        """Zero-shot LLM call: propose a standard snake_case field name for a cluster."""
        try:
            from olav.core.llm import LLMFactory
            llm = LLMFactory.get_chat_model(agent_id="schema_engine")
            examples = ", ".join(str(k) for k in raw_keys[:8])
            prompt = (
                f"Domain: {domain}\n"
                f"These field names were observed across multiple vendors/commands:\n"
                f"  {examples}\n\n"
                "Propose ONE concise snake_case standard field name that best represents "
                "the shared semantic meaning. Respond with ONLY the field name."
            )
            response = llm.invoke(prompt)
            content = getattr(response, "content", str(response)).strip().split()[0]
            return content or raw_keys[0]
        except Exception as exc:
            logger.warning("LLM propose failed: %s", exc)
            return raw_keys[0] if raw_keys else "unknown_field"
