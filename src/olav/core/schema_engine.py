"""Schema Engine — Phase 1 core implementation.

Provides:
    build_semantic_summary(field)       → str
    build_mutation_request(...)         → SchemaMutationRequest
    create_unified_view(command, maps)  → SQL str
    get_domain_collection(domain)       → str
    SchemaEngine                        → classify_field / save_mapping

Design notes (api_discovery.md §3, §4):
    - Strict mode: embedder and LanceDB are required for classification.
  - LanceDB table per domain: ``{domain}_field_mappings`` (olav_platform.md §12.5).
  - Distance conversion: confidence = 1.0 - (distance / 2.0), values in [0, 1].
  - SchemaEngine never writes shared DB directly; all changes go through
    SchemaMutationService.stage_request().
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any, cast

from olav.core.bootstrap_yang import load_bundled_openconfig_reference

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)

YangLeaf = dict[str, str]

# ---------------------------------------------------------------------------
# OpenConfig YANG reference tree — injected into LLM prompts (OC-3)
# ---------------------------------------------------------------------------

OPENCONFIG_YANG_REFERENCE = load_bundled_openconfig_reference()

# ---------------------------------------------------------------------------
# Pure helpers — no dependencies on runtime services
# ---------------------------------------------------------------------------


def build_semantic_summary(field: dict[str, Any]) -> str:
    """Join field metadata into a pipe-delimited semantic summary string.

    Empty / falsy values are excluded so vectors stay dense with signal.

    >>> build_semantic_summary({"name": "ip_address", "description": "IPv4 mgmt"})
    'ip_address | IPv4 mgmt'
    """
    parts: list[str] = [
        str(field.get("name", "") or ""),
        str(field.get("description", "") or ""),
        str(field.get("type", "") or ""),
        str(field.get("example", "")) if field.get("example") is not None else "",
        str(field.get("command", "") or ""),
    ]
    return " | ".join(part for part in parts if part)


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
        List of ``{"raw_key", "openconfig_path", "data_type"}`` dicts.
    """
    view_name = "v_unified_" + command.strip().replace(" ", "_").replace("-", "_")
    cols_parts: list[str] = []
    for m in mappings:
        raw_key = m["raw_key"]
        oc_path = m["openconfig_path"]
        data_type = m.get("data_type", "VARCHAR")
        cols_parts.append(f"  TRY_CAST(parsed_data->>'{raw_key}' AS {data_type}) AS {oc_path}")
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
        ``None`` is invalid for strict classification mode.
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
        self._embedder: Any | None
        if embedder is _SENTINEL:
            from olav.core.embedder import get_embedder

            self._embedder = cast(Any, get_embedder())
        else:
            self._embedder = embedder
        self._lancedb_override = _lancedb_override

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_field(self, field_metadata: dict[str, Any]) -> dict[str, Any]:
        """Classify *field_metadata* and stage the appropriate mutation request.

        Returns a dict with keys: ``status``, ``confidence``,
        and optionally ``openconfig_path``.
        """
        if not self._embedder:
            raise RuntimeError("SchemaEngine requires an embedder in strict mode")

        domain = field_metadata.get("domain", "platform")
        summary = build_semantic_summary(field_metadata)

        try:
            vector = self._embedder.encode(summary, normalize_embeddings=True).tolist()
        except Exception as exc:
            raise RuntimeError(f"Embedding failed: {exc}") from exc

        db = self._get_lancedb()

        try:
            table = db.open_table(get_domain_collection(domain))
            results = table.search(vector).limit(1).to_list()
        except Exception as exc:
            raise RuntimeError(f"LanceDB lookup failed: {exc}") from exc

        if not results:
            self._stage_evolution(field_metadata, vector, domain)
            return {"status": "unclassified", "confidence": 0.0}

        # Distance in [0, 2] (cosine) → confidence in [0, 1]
        distance = results[0].get("_distance", 2.0)
        confidence = 1.0 - (distance / 2.0)

        if confidence > self._TIER0_THRESHOLD:
            openconfig_path = results[0]["openconfig_path"]
            self.save_mapping(field_metadata, openconfig_path, method="vector")
            return {
                "status": "matched",
                "openconfig_path": openconfig_path,
                "confidence": confidence,
            }

        if confidence >= self._TIER1_THRESHOLD:
            openconfig_path = self._llm_confirm(field_metadata, results[0], confidence)
            self.save_mapping(field_metadata, openconfig_path, method="llm_confirm")
            return {
                "status": "llm_confirmed",
                "openconfig_path": openconfig_path,
                "confidence": confidence,
            }

        # Tier 2: below threshold → evolution pool
        self._stage_evolution(field_metadata, vector, domain)
        return {"status": "unclassified", "confidence": confidence}

    def save_mapping(
        self,
        field_metadata: dict[str, Any],
        openconfig_path: str,
        method: str = "vector",
    ) -> None:
        """Stage a ``upsert_mapping`` mutation request."""
        domain = field_metadata.get("domain", "platform")
        req = build_mutation_request(
            domain=domain,
            mutation_type="upsert_mapping",
            target="schema_catalog",
            payload={
                "platform": field_metadata.get("platform")
                or field_metadata.get("vendor")
                or domain,
                "source_name": field_metadata.get("command", ""),
                "fields": [
                    {
                        "name": field_metadata.get("name", ""),
                        "openconfig_path": openconfig_path,
                        "method": method,
                    }
                ],
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
            from olav.core.config import DATABASES_DIR

            lancedb = cast(Any, importlib.import_module("lancedb"))
            return lancedb.connect(str(DATABASES_DIR / "memory.lancedb"))
        except Exception as exc:
            raise RuntimeError(f"LanceDB connection failed: {exc}") from exc

    def _llm_confirm(
        self,
        field_metadata: dict[str, Any],
        top_result: dict[str, Any],
        confidence: float,
    ) -> str:
        """Zero-shot LLM confirmation for borderline matches.

        Returns the confirmed ``openconfig_path``.
        """
        try:
            from olav.core.llm import LLMFactory

            llm = LLMFactory.get_chat_model(agent_id="schema_engine")
            prompt = (
                f"Field name: {field_metadata.get('name')}\n"
                f"Description: {field_metadata.get('description', '')}\n"
                f"Best vector match: {top_result['openconfig_path']} "
                f"(confidence={confidence:.2f})\n\n"
                f"OpenConfig YANG reference:\n{OPENCONFIG_YANG_REFERENCE}\n\n"
                "Respond with ONLY the most appropriate OpenConfig path "
                "from the YANG reference above or the vector match. "
                "If the match is correct, repeat it exactly."
            )
            response = llm.invoke(prompt)
            content = getattr(response, "content", str(response)).strip().split()[0]
            if not content:
                raise RuntimeError("LLM confirm returned empty path")
            return content
        except Exception as exc:
            raise RuntimeError(f"LLM confirm failed: {exc}") from exc

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
            rows = cast(
                list[tuple[str, str, Any, Any]],
                conn.execute(
                    "SELECT raw_key, command, vector_preview, sample_field"
                    " FROM pending_schema_evolutions WHERE status = 'pending'"
                ).fetchall(),
            )
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
            np = cast(Any, importlib.import_module("numpy"))
            OPTICS = cast(Any, importlib.import_module("sklearn.cluster").OPTICS)
        except ImportError as exc:  # pragma: no cover
            return {
                "clusters_found": 0,
                "proposals": [],
                "skipped": f"scikit-learn unavailable: {exc}",
            }

        # Reconstruct vectors from stored 8-dim vector_preview.
        # In a future version the full 384-dim vectors would be stored in a
        # dedicated LanceDB evolution_pool table for higher-quality clustering.
        vectors: list[list[float]] = []
        for row in rows:
            preview = row[2]  # vector_preview column
            preview_values = cast(list[Any] | tuple[Any, ...] | None, preview)
            if (
                preview_values is not None
                and isinstance(preview_values, (list, tuple))
                and len(preview_values) > 0
            ):
                vectors.append([float(value) for value in preview_values])
            else:
                vectors.append([0.0] * 8)

        vectors_array = np.array(vectors, dtype=np.float32)
        # Pad or trim to uniform length (shouldn't happen, defensive)
        if vectors_array.ndim != 2 or vectors_array.shape[1] < 2:
            return {"clusters_found": 0, "proposals": [], "skipped": "Degenerate feature vectors"}

        clustering = OPTICS(min_samples=min_samples, metric="euclidean").fit(vectors_array)
        labels: list[int] = [int(label) for label in cast(Any, clustering.labels_)]

        unique_clusters: set[int] = set(labels) - {-1}
        if not unique_clusters:
            return {
                "clusters_found": 0,
                "proposals": [],
                "skipped": "No dense clusters found — accumulating more data",
            }

        proposals: list[str] = []
        for cluster_id in sorted(unique_clusters):
            member_indices: list[int] = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
            raw_keys: list[str] = [str(rows[i][0]) for i in member_indices]
            sample_fields: list[Any] = [rows[i][3] for i in member_indices]

            proposed_name = self._llm_propose_openconfig_path(raw_keys, sample_fields, domain)
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

    def _llm_propose_openconfig_path(
        self,
        raw_keys: list[str],
        sample_fields: list[Any],
        domain: str,
    ) -> str:
        """Zero-shot LLM call: propose an OpenConfig YANG path for a cluster."""
        try:
            from olav.core.llm import LLMFactory

            llm = LLMFactory.get_chat_model(agent_id="schema_engine")
            examples = ", ".join(str(k) for k in raw_keys[:8])
            prompt = (
                f"Domain: {domain}\n"
                f"These field names were observed across multiple vendors/commands:\n"
                f"  {examples}\n\n"
                f"OpenConfig YANG reference:\n{OPENCONFIG_YANG_REFERENCE}\n\n"
                "Propose ONE concise OpenConfig YANG path from the reference above "
                "that best represents the shared semantic meaning. "
                "Respond with ONLY the openconfig- prefixed path."
            )
            response = llm.invoke(prompt)
            content = getattr(response, "content", str(response)).strip().split()[0]
            return content or raw_keys[0]
        except Exception as exc:
            logger.warning("LLM propose failed: %s", exc)
            return raw_keys[0] if raw_keys else "unknown_field"


# ---------------------------------------------------------------------------
# P2-3: Schema-to-Schema Mapping — DuckDB mapping_rules table
# ---------------------------------------------------------------------------

_MAPPING_RULES_DDL = """
CREATE TABLE IF NOT EXISTS mapping_rules (
    vendor      TEXT NOT NULL,
    command     TEXT NOT NULL,
    src_field   TEXT NOT NULL,
    oc_path     TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    PRIMARY KEY (vendor, command, src_field)
)
"""


def create_mapping_rules_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create (or ensure exists) the ``mapping_rules`` table in *con*."""
    con.execute(_MAPPING_RULES_DDL)


def _tokenise(name: str) -> set[str]:
    import re

    return set(re.split(r"[-_/\s]+", name.lower().strip()))


_FIELD_ALIASES: dict[str, str] = {
    "neighbor_interface": "port-id",
    "neighbor_port_id": "port-id",
    "neighbor_port": "port-id",
    "local_interface": "name",
    "local_port": "name",
    "neighbor_name": "system-name",
    "neighbor": "system-name",
    "neighbor_description": "system-description",
    "neighbor_interface_description": "system-description",
    "chassis_id": "chassis-id",
    "mgmt_address": "management-address",
    "management_ip": "management-address",
    "management_ipv6": "management-address",
    "neighbor_port_description": "port-description",
}

_COMMAND_MODULE_HINTS: list[tuple[str, str]] = [
    ("lldp", "openconfig-lldp"),
    ("cdp", "openconfig-lldp"),
    ("bgp", "openconfig-bgp"),
    ("ospf", "openconfig-network-instance"),
    ("interface", "openconfig-interfaces"),
    # _olav: private namespace — operational data without OC YANG mapping
    ("clock", "_olav:diagnostic"),
    ("logging", "_olav:diagnostic"),
    ("aliases", "_olav:diagnostic"),
    ("hosts", "_olav:diagnostic"),
    ("users", "_olav:system"),
    ("processes", "_olav:system"),
    ("cpu", "_olav:system"),
]

_INTERFACE_EXACT_PATHS: dict[str, str] = {
    "interface": "interfaces/interface/config/name",
    "physicalinterface": "interfaces/interface/config/name",
    "logicalinterface": "interfaces/interface/config/name",
    "description": "interfaces/interface/config/description",
    "mtu": "interfaces/interface/config/mtu",
    "admin_status": "interfaces/interface/state/admin-status",
    "enabled": "interfaces/interface/state/admin-status",
    "oper_status": "interfaces/interface/state/oper-status",
    "link_status": "interfaces/interface/state/oper-status",
    "linkstatus": "interfaces/interface/state/oper-status",
    "protocol_status": "interfaces/interface/state/oper-status",
    "proto": "interfaces/interface/state/oper-status",
    "status": "interfaces/interface/state/oper-status",
    "ip_address": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/state/ip",
    "ipaddress": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/state/ip",
    "ip": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/state/ip",
    "prefix_length": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/state/prefix-length",
}

_BGP_EXACT_PATHS: dict[str, str] = {
    "neighbor": "bgp/neighbors/neighbor/state/neighbor-address",
    "bgp_neighbor": "bgp/neighbors/neighbor/state/neighbor-address",
    "peer": "bgp/neighbors/neighbor/state/neighbor-address",
    "neighbor_ip": "bgp/neighbors/neighbor/state/neighbor-address",
    "peer_ip": "bgp/neighbors/neighbor/state/neighbor-address",
    "peer_as": "bgp/neighbors/neighbor/config/peer-as",
    "neighbor_as": "bgp/neighbors/neighbor/config/peer-as",
    "remote_as": "bgp/neighbors/neighbor/config/peer-as",
    "peerstate": "bgp/neighbors/neighbor/state/session-state",
    "bgp_state": "bgp/neighbors/neighbor/state/session-state",
    "state": "bgp/neighbors/neighbor/state/session-state",
    "state_or_prefixes_received": "bgp/neighbors/neighbor/afi-safis/afi-safi/state/prefixes/received",
    "received": "bgp/neighbors/neighbor/afi-safis/afi-safi/state/prefixes/received",
    "prefixes_received": "bgp/neighbors/neighbor/afi-safis/afi-safi/state/prefixes/received",
    "router_id": "bgp/global/config/router-id",
    "local_as": "bgp/global/config/as",
}


def _path_exists(yang_leaves: list[YangLeaf], candidate: str) -> bool:
    return any(str(leaf["yang_path"]) == candidate for leaf in yang_leaves)


def _command_specific_path(
    field_name: str, command: str, yang_leaves: list[YangLeaf]
) -> str | None:
    normalised = field_name.strip().lower()
    command_lower = command.lower()

    candidates: dict[str, str] | None = None
    if "bgp" in command_lower:
        candidates = _BGP_EXACT_PATHS
    elif "interface" in command_lower and "ospf" not in command_lower:
        candidates = _INTERFACE_EXACT_PATHS

    if candidates is None:
        return None

    path = candidates.get(normalised)
    if path and _path_exists(yang_leaves, path):
        return path
    return None


def _best_yang_match(
    field_name: str,
    yang_leaves: list[YangLeaf],
) -> tuple[str | None, float]:
    """Name-similarity match: return (yang_path, score) or (None, 0)."""
    normalised = field_name.strip().lower()
    alias_leaf = _FIELD_ALIASES.get(normalised)
    if alias_leaf is not None:
        for leaf in yang_leaves:
            if leaf["leaf_name"] == alias_leaf:
                return str(leaf["yang_path"]), 1.0

    field_tokens = _tokenise(field_name)
    best_path: str | None = None
    best_score = 0.0

    _stop = {"show", "ip", "interface", "state", "config", "name", "the", "a"}

    for leaf in yang_leaves:
        leaf_tokens = _tokenise(leaf["leaf_name"])
        sig_field = field_tokens - _stop
        sig_leaf = leaf_tokens - _stop

        if not sig_field:
            sig_field = field_tokens

        if sig_leaf and sig_field == sig_leaf:
            score = 1.0
        elif sig_field & sig_leaf:
            score = 0.5 + 0.1 * (len(sig_field & sig_leaf) / max(len(sig_field), 1))
        else:
            path_tokens = _tokenise(leaf["yang_path"])
            overlap = sig_field & path_tokens
            score = 0.3 if overlap else 0.0

        if score > best_score:
            best_score = score
            best_path = str(leaf["yang_path"])

    return best_path, best_score


def build_mapping_rules(
    con: duckdb.DuckDBPyConnection,
    *,
    llm: Any | None = None,
    min_score: float = 0.3,
) -> dict[str, Any]:
    """Populate ``mapping_rules`` from ``schema_catalog`` × ``yang_leaves``.

    This is the sole legitimate writer to ``mapping_rules`` — deriving it
    from ``schema_catalog`` for legacy compatibility.

    For every (platform, command, field) row in ``schema_catalog``:
      1. Name-similarity match against ``yang_leaves``.
      2. If *llm* is provided and score is ambiguous (0.3–0.7), LLM confirms.
      3. Insert into ``mapping_rules`` with ``confidence`` = match method.

    Only rows scoring >= *min_score* are inserted.

    Parameters
    ----------
    con:
        Open DuckDB connection containing both ``schema_catalog`` and
        ``yang_leaves``.
    llm:
        Optional LangChain chat model for confidence boosting.  Pass ``None``
        (default) to rely on name-similarity only.
    min_score:
        Minimum similarity score to include a mapping.

    Returns
    -------
    dict
        ``{"rules_inserted": int, "vendors_covered": list[str]}``
    """
    import json as _json

    create_mapping_rules_table(con)

    # Load yang_leaves once
    yang_rows = cast(
        list[tuple[str, str, str, str | None, str]],
        con.execute(
            "SELECT yang_path, leaf_name, leaf_type, description, module FROM yang_leaves"
        ).fetchall(),
    )
    yang_leaves: list[YangLeaf] = [
        {
            "yang_path": r[0],
            "leaf_name": r[1],
            "leaf_type": r[2],
            "description": r[3] or "",
            "module": r[4],
        }
        for r in yang_rows
    ]

    if not yang_leaves:
        raise ValueError("build_mapping_rules requires non-empty yang_leaves")

    # Load schema_catalog
    catalog_rows = cast(
        list[tuple[str, str, Any]],
        con.execute("SELECT platform, source_name, fields FROM schema_catalog").fetchall(),
    )

    inserted = 0
    vendors: set[str] = set()
    batch: list[tuple[str, str, str, str, str]] = []

    for platform, command, fields_json in catalog_rows:
        try:
            fields: list[dict[str, Any]] = cast(
                list[dict[str, Any]],
                (_json.loads(fields_json) if isinstance(fields_json, str) else (fields_json or [])),
            )
        except Exception as exc:
            raise ValueError(
                f"Invalid schema_catalog.fields JSON for platform={platform!r}, command={command!r}"
            ) from exc

        cmd_lower = command.lower()
        candidates: list[YangLeaf] = yang_leaves
        for keyword, module in _COMMAND_MODULE_HINTS:
            if keyword in cmd_lower:
                candidates = [yl for yl in yang_leaves if yl["module"] == module]
                break

        for field in fields:
            field_name = field.get("name", "")
            if not field_name:
                continue

            command_specific = _command_specific_path(field_name, command, candidates)
            if command_specific is not None:
                best_path, score = command_specific, 1.0
            else:
                best_path, score = _best_yang_match(field_name, candidates)

            if best_path is None or score < min_score:
                continue

            # Optional LLM confirmation for mid-range scores
            confidence = "name_similarity"
            if llm is not None and 0.3 <= score < 0.7:
                try:
                    prompt = (
                        f"Vendor field: {field_name} (platform={platform}, command={command})\n"
                        f"Best name-similarity match: {best_path} (score={score:.2f})\n\n"
                        f"OpenConfig YANG reference:\n{OPENCONFIG_YANG_REFERENCE}\n\n"
                        "If this mapping is correct, respond with the path unchanged. "
                        "Otherwise respond with a better path from the reference. "
                        "Respond with ONLY the path."
                    )
                    response = llm.invoke(prompt)
                    content = getattr(response, "content", str(response)).strip().split()[0]
                    if content and "/" in content:
                        valid_paths = {yl["yang_path"] for yl in yang_leaves}
                        if content in valid_paths:
                            best_path = content
                    confidence = "llm_confirmed"
                except Exception as exc:
                    raise RuntimeError(f"build_mapping_rules LLM call failed: {exc}") from exc

            batch.append((platform, command, field_name, best_path, confidence))
            vendors.add(platform)

    if batch:
        con.executemany(
            """
            INSERT OR REPLACE INTO mapping_rules
                (vendor, command, src_field, oc_path, confidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            batch,
        )
        inserted = len(batch)

    logger.info(
        "build_mapping_rules: inserted %d rules covering %d vendors",
        inserted,
        len(vendors),
    )
    return {"rules_inserted": inserted, "vendors_covered": sorted(vendors)}
