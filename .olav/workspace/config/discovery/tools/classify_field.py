"""classify_field — thin LangChain tool wrapper around SchemaEngine.

Delegates entirely to ``olav.core.schema_engine.SchemaEngine.classify_field()``.
No direct DuckDB or LanceDB access here (api_discovery.md D4 principle).
"""

from __future__ import annotations


def classify_field(
    name: str,
    domain: str = "netops",
    description: str = "",
    data_type: str = "",
    example: str = "",
    command: str = "",
) -> dict:
    """Classify a field using vector similarity + optional LLM confirmation.

    Parameters
    ----------
    name:        Raw field name, e.g. ``"IP_ADDRESS"``.
    domain:      Domain namespace for the LanceDB table, e.g. ``"netops"``.
    description: Human-readable description of the field.
    data_type:   Expected DuckDB type, e.g. ``"VARCHAR"``.
    example:     Example value, e.g. ``"192.168.1.1"``.
    command:     Source CLI command, e.g. ``"show interfaces"``.

    Returns
    -------
    dict with keys:
        status        — ``"matched"`` | ``"llm_confirmed"`` | ``"unclassified"``
        confidence    — float [0, 1]
        standard_name — present when status != "unclassified"
    """
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService
    from olav.core.config import DATABASES_DIR
    from pathlib import Path

    staging_dir = Path(DATABASES_DIR) / "staging"
    svc = SchemaMutationService(staging_dir=staging_dir)
    engine = SchemaEngine(mutation_service=svc)

    field_metadata = {
        "name": name,
        "domain": domain,
        "description": description,
        "type": data_type,
        "example": example,
        "command": command,
    }
    return engine.classify_field(field_metadata)
