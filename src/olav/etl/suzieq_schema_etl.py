"""ETL pipeline for SuzieQ Avro schema indexing."""

import json
import logging
from pathlib import Path

from opensearchpy import OpenSearch

from olav.core.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """Parse SuzieQ Avro schemas and index to OpenSearch.

    Process:
        1. Read .avsc files from suzieq/config/schema/
        2. Extract table, fields, and metadata
        3. Index to suzieq-schema for Schema-Aware tool discovery
    """
    logger.info("Initializing SuzieQ schema index...")

    client = OpenSearch(
        hosts=[settings.opensearch_url],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
    )

    # Create index
    index_name = "suzieq-schema"
    if client.indices.exists(index=index_name):
        logger.info(f"Index {index_name} already exists, skipping...")
        return

    mapping = {
        "mappings": {
            "properties": {
                "table": {"type": "keyword"},
                "fields": {"type": "keyword"},
                "description": {"type": "text"},
                "methods": {"type": "keyword"},
            },
        },
    }

    client.indices.create(index=index_name, body=mapping)
    logger.info(f"✓ Created index: {index_name}")

    # TODO: Parse actual SuzieQ Avro schemas from archive/suzieq/suzieq/config/schema/
    # For now, create sample entries
    sample_schemas = [
        {
            "table": "bgp",
            "fields": [
                "namespace",
                "hostname",
                "vrf",
                "peer",
                "asn",
                "state",
                "peerAsn",
                "afi",
            ],
            "description": "BGP protocol information including peer state and configuration",
            "methods": ["get", "summarize", "unique", "aver"],
        },
        {
            "table": "interfaces",
            "fields": [
                "namespace",
                "hostname",
                "ifname",
                "state",
                "adminState",
                "mtu",
                "speed",
                "type",
            ],
            "description": "Interface information including operational and admin state",
            "methods": ["get", "summarize", "unique", "aver"],
        },
        {
            "table": "routes",
            "fields": [
                "namespace",
                "hostname",
                "vrf",
                "prefix",
                "nexthopIp",
                "protocol",
                "metric",
            ],
            "description": "Routing table entries with next-hop and protocol information",
            "methods": ["get", "summarize", "unique", "aver"],
        },
    ]

    for schema in sample_schemas:
        client.index(index=index_name, body=schema)

    logger.info(f"✓ Indexed {len(sample_schemas)} SuzieQ table schemas")
    logger.info("  TODO: Implement full Avro schema parser")


if __name__ == "__main__":
    main()
