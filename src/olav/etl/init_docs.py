"""Initialize olav-docs index for document RAG.

This script creates the OpenSearch index used for storing document embeddings
from PDF/Markdown/Text files indexed by the document_indexer module.

Index: olav-docs
Purpose: Document RAG (Vendor documentation vector search)
Fields:
    - content: Document text chunk
    - embedding: 1536-dim vector (OpenAI text-embedding-3-small)
    - metadata: Document metadata (vendor, type, path, etc.)
"""

import logging

from opensearchpy import OpenSearch

from olav.core.memory import create_opensearch_client
from config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INDEX_NAME = "olav-docs"


def main() -> None:
    """Create olav-docs index for document RAG.

    Index Schema optimized for kNN semantic search:
        - content (text): Document chunk text
        - embedding (knn_vector): 1536-dim embedding vector
        - metadata.file_path (keyword): Source file path
        - metadata.vendor (keyword): Vendor name (cisco, juniper, arista)
        - metadata.document_type (keyword): Document type (manual, rfc, etc.)
        - metadata.chunk_index (integer): Chunk position in document
        - metadata.total_chunks (integer): Total chunks in document
        - metadata.page_number (integer): Page number if applicable
        - created_at (date): Indexing timestamp
    """
    logger.info("Initializing olav-docs index...")

    client = create_opensearch_client()

    # Check if index exists
    if client.indices.exists(index=INDEX_NAME):
        logger.info(f"Index {INDEX_NAME} already exists, skipping creation...")
        # Count documents
        count = client.count(index=INDEX_NAME)["count"]
        logger.info(f"  Current document count: {count}")
        return

    # Create index with kNN settings
    mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "index.knn": True,  # Enable kNN for vector search
        },
        "mappings": {
            "properties": {
                "content": {
                    "type": "text",
                    "analyzer": "standard",
                },
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 1536,  # OpenAI text-embedding-3-small
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": 128,
                            "m": 16,
                        },
                    },
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "keyword"},
                        "file_name": {"type": "keyword"},
                        "vendor": {"type": "keyword"},
                        "document_type": {"type": "keyword"},
                        "chunk_index": {"type": "integer"},
                        "total_chunks": {"type": "integer"},
                        "page_number": {"type": "integer"},
                        "file_size": {"type": "long"},
                        "file_extension": {"type": "keyword"},
                    },
                },
                "created_at": {"type": "date"},
            },
        },
    }

    client.indices.create(index=INDEX_NAME, body=mapping)
    logger.info(f"✓ Created index: {INDEX_NAME}")
    logger.info("  - Embedding dimension: 1536 (OpenAI text-embedding-3-small)")
    logger.info("  - kNN engine: nmslib (HNSW)")
    logger.info("  - Space type: cosinesimil")
    logger.info("")
    logger.info("To index documents, use:")
    logger.info("  uv run python -m olav.tools.indexing_tool <file_or_directory>")
    logger.info("Or via CLI:")
    logger.info("  > index_document file_path=data/documents/cisco/guide.pdf")


if __name__ == "__main__":
    main()
