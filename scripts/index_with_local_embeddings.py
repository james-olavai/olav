#!/usr/bin/env python3
"""
Index PDF documents using LOCAL embeddings (sentence-transformers)

No API calls, no costs, runs entirely on your machine.
Uses BAAI/bge-small-zh-v1.5 model (512-dim embeddings, Chinese-optimized)

Features:
- Automatic model download from HuggingFace (first run only)
- Progress tracking with real-time chunk count
- Batch processing for efficient database writes
- GPU acceleration (if available)

Usage:
    uv run python scripts/index_with_local_embeddings.py
"""

import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.paths import OLAV_DIR, DB_MAIN_PATH
from config.settings import settings
from src.olav.core.llm import LLMFactory
from langchain.text_splitter import RecursiveCharacterTextSplitter
import duckdb


def index_knowledge_base(
    pdf_dir: Optional[Path] = None,
    rebuild: bool = False,
    verbose: bool = True,
) -> dict:
    """Index all PDF files using LOCAL embeddings.
    
    Args:
        pdf_dir: Directory containing PDFs (default: .olav/knowledge/)
        rebuild: If True, delete existing chunks and rebuild
        verbose: Print progress information
    
    Returns:
        Statistics: {files_indexed, chunks_created, elapsed_time, embedding_dim}
    """
    import PyPDF2
    import uuid
    
    start_time = time.time()
    
    # Setup paths
    if pdf_dir is None:
        pdf_dir = OLAV_DIR / "knowledge"
    
    if not pdf_dir.exists():
        logger.error(f"Knowledge directory not found: {pdf_dir}")
        return {"error": f"Directory not found: {pdf_dir}"}
    
    # List PDF files
    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"No PDF files found in {pdf_dir}")
        return {"files_indexed": 0, "chunks_created": 0}
    
    logger.info(f"Found {len(pdf_files)} PDF file(s)")
    
    # Initialize embeddings (LOCAL MODE)
    logger.info("Initializing LOCAL embeddings (sentence-transformers)...")
    logger.info(f"Embedding mode: {settings.embedding_mode}")
    logger.info(f"Embedding model: {settings.embedding_local_model}")
    
    try:
        embeddings = LLMFactory.get_embeddings()
        logger.info("✓ Embeddings initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize embeddings: {e}")
        logger.error("Make sure langchain-huggingface and sentence-transformers are installed:")
        logger.error("  uv add langchain-huggingface sentence-transformers torch")
        raise
    
    # Get embedding dimension by generating a test embedding
    test_embedding = embeddings.embed_query("test")
    embedding_dim = len(test_embedding)
    logger.info(f"Embedding dimension: {embedding_dim}")
    
    # Text splitter (same as before)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )
    
    # Connect to database
    conn = duckdb.connect(str(DB_MAIN_PATH))
    
    # Drop and recreate table if rebuild
    if rebuild:
        logger.info("Dropping existing knowledge_chunks table...")
        conn.execute("DROP TABLE IF EXISTS knowledge_chunks")
    
    # Create table with current embedding dimension
    logger.info(f"Creating knowledge_chunks table (embedding dimension: {embedding_dim})...")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id VARCHAR PRIMARY KEY,
            content TEXT NOT NULL,
            embedding FLOAT[{embedding_dim}],
            source_file VARCHAR NOT NULL,
            file_path VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            metadata JSON
        )
    """)
    
    # Index all PDFs
    files_indexed = 0
    chunks_created = 0
    batch_data = []
    batch_size = 50  # Insert in batches of 50
    
    for pdf_file in pdf_files:
        try:
            logger.info(f"\n📄 Processing: {pdf_file.name}")
            
            # Extract text from PDF
            try:
                with open(pdf_file, "rb") as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    text_content = ""
                    for page_num, page in enumerate(pdf_reader.pages):
                        text_content += f"\n--- Page {page_num + 1} ---\n"
                        text_content += page.extract_text() or "[No text extracted]"
                    
                    logger.info(f"   ✓ Extracted {len(pdf_reader.pages)} pages")
            except Exception as e:
                logger.error(f"   ✗ Failed to extract PDF: {e}")
                continue
            
            # Split into chunks
            chunks = text_splitter.split_text(text_content)
            logger.info(f"   ✓ Split into {len(chunks)} chunks")
            
            # Generate embeddings for this PDF
            logger.info(f"   ⏳ Generating embeddings...")
            start_embed = time.time()
            
            try:
                chunk_embeddings = embeddings.embed_documents(chunks)
                embed_time = time.time() - start_embed
                logger.info(f"   ✓ Generated {len(chunks)} embeddings in {embed_time:.1f}s")
            except Exception as e:
                logger.error(f"   ✗ Failed to generate embeddings: {e}")
                continue
            
            # Prepare batch data
            for i, (chunk, embedding) in enumerate(zip(chunks, chunk_embeddings)):
                batch_data.append((
                    str(uuid.uuid4()),  # unique id
                    chunk,  # content
                    embedding,  # embedding vector
                    pdf_file.name,  # source_file
                    str(pdf_file),  # file_path
                ))
                
                chunks_created += 1
                
                # Insert batch when reach batch_size
                if len(batch_data) >= batch_size:
                    conn.executemany("""
                        INSERT INTO knowledge_chunks 
                        (id, content, embedding, source_file, file_path)
                        VALUES (?, ?, ?, ?, ?)
                    """, batch_data)
                    logger.info(f"   💾 Saved batch: {chunks_created} chunks total")
                    batch_data = []
            
            files_indexed += 1
            logger.info(f"   ✓ Indexed: {len(chunks)} chunks")
            
        except Exception as e:
            logger.error(f"Failed to index {pdf_file.name}: {e}")
            continue
    
    # Insert remaining batch
    if batch_data:
        conn.executemany("""
            INSERT INTO knowledge_chunks 
            (id, content, embedding, source_file, file_path)
            VALUES (?, ?, ?, ?, ?)
        """, batch_data)
        logger.info(f"   💾 Saved final batch: {chunks_created} chunks total")
    
    # Create index for vector search
    try:
        logger.info("Creating vector search index...")
        # Note: DuckDB doesn't have HNSW extension enabled by default, using linear search
        # For better performance with large datasets, consider Pinecone or Milvus
        logger.info("   ℹ Using linear search (DuckDB HNSW not configured)")
    except Exception as e:
        logger.warning(f"Could not create vector index: {e}")
    
    conn.close()
    
    elapsed = time.time() - start_time
    
    result = {
        "files_indexed": files_indexed,
        "chunks_created": chunks_created,
        "embedding_dim": embedding_dim,
        "embedding_model": settings.embedding_local_model,
        "elapsed_time": round(elapsed, 2),
        "total_time_string": f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
    }
    
    logger.info("\n" + "=" * 60)
    logger.info("✓ INDEXING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Files indexed: {result['files_indexed']}")
    logger.info(f"Chunks created: {result['chunks_created']}")
    logger.info(f"Embedding model: {result['embedding_model']} ({result['embedding_dim']}dim)")
    logger.info(f"Elapsed time: {result['total_time_string']}")
    logger.info("=" * 60)
    
    return result


def verify_index() -> dict:
    """Verify the indexed knowledge base."""
    logger.info("\n🔍 Verifying knowledge base...")
    
    conn = duckdb.connect(str(DB_MAIN_PATH), read_only=True)
    
    try:
        # Count chunks
        result = conn.execute("""
            SELECT 
                COUNT(*) as total_chunks,
                COUNT(DISTINCT source_file) as unique_files,
                MIN(created_at) as first_indexed,
                MAX(created_at) as last_indexed
            FROM knowledge_chunks
        """).fetchone()
        
        if result:
            total, files, first, last = result
            logger.info(f"  ✓ Total chunks: {total}")
            logger.info(f"  ✓ Unique files: {files}")
            
            if first:
                logger.info(f"  ✓ First indexed: {first}")
            if last:
                logger.info(f"  ✓ Last indexed: {last}")
            
            # Check embedding dimensions
            sample = conn.execute("""
                SELECT LENGTH(embedding) as dim 
                FROM knowledge_chunks 
                LIMIT 1
            """).fetchone()
            
            if sample:
                logger.info(f"  ✓ Embedding dimension: {sample[0]}")
            
            return {"status": "verified", "total_chunks": total}
        else:
            logger.warning("  ⚠ No chunks found in database")
            return {"status": "empty"}
    
    except Exception as e:
        logger.error(f"  ✗ Verification failed: {e}")
        return {"status": "error", "error": str(e)}
    
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        # Index knowledge base
        result = index_knowledge_base()
        
        # Verify
        if result.get("chunks_created", 0) > 0:
            verify_index()
        
        logger.info("\n✅ Ready to use with search_knowledge tool!")
        logger.info("   Try: olav ask '怎么排查BGP邻接体不通？'")
        
    except KeyboardInterrupt:
        logger.info("\n⚠ Indexing cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n✗ Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
