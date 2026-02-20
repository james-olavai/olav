"""Index Knowledge Files Tool - Build/update the KB vector index.

Scans a knowledge directory for Markdown and PDF files, splits them into
semantic chunks, embeds with the configured embedding model, and stores
the vectors in DuckDB for later similarity search.

Three indexing modes:
  - Full (default): Index all files (may add duplicates if already indexed).
  - Incremental:    Skip files whose source_file is already in knowledge_chunks.
  - Force rebuild:  Drop the entire table and rebuild from scratch.

Path arguments default to config.paths values so nothing is hardcoded.
Defaults are also documented in SKILL.md under config.knowledge.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

try:
    from langchain_core.tools import tool
    from langchain_core.documents import Document
    from langchain_community.vectorstores import DuckDB
except ImportError:
    DuckDB = None
    Document = None
    tool = lambda f: f

from config.paths import KNOWLEDGE_BASE_DIR, MAIN_DB_PATH
from src.olav.core.knowledge.text_processor import TextProcessor
from src.olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


def _read_markdown(file_path: Path) -> str:
    """Read markdown file content."""
    return file_path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(file_path: Path) -> str:
    """Extract text from PDF using pdfplumber (optional dependency)."""
    try:
        import pdfplumber  # type: ignore
        pages = []
        with pdfplumber.open(str(file_path)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                pages.append(f"=== PAGE {i} ===\n{text}")
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("pdfplumber not installed — skipping PDF: %s", file_path.name)
        return ""
    except Exception as e:
        logger.warning("Failed to read PDF %s: %s", file_path.name, e)
        return ""


def _file_hash(file_path: Path) -> str:
    """Compute MD5 hex digest of file contents (fast small-file check)."""
    md5 = hashlib.md5()
    md5.update(file_path.read_bytes())
    return md5.hexdigest()


def _get_indexed_source_files(conn) -> set[str]:
    """Return set of source_file values already in knowledge_chunks."""
    try:
        conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name='knowledge_chunks'")
        if not conn.fetchone():
            return set()
        rows = conn.execute("SELECT DISTINCT metadata FROM knowledge_chunks").fetchall()
        sources = set()
        for (meta_raw,) in rows:
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                src = meta.get("source_file", "")
                if src:
                    sources.add(src)
            except Exception:
                pass
        return sources
    except Exception:
        return set()


@tool
def index_knowledge_files(
    knowledge_dir: str = "",
    db_path: str = "",
    force_reindex: bool = False,
    incremental: bool = False,
    chunk_size: int = 1024,
    chunk_overlap: int = 128,
) -> str:
    """Index knowledge files (Markdown/PDF) into the vector search database.

    Scans `knowledge_dir` recursively, chunks each file, embeds the chunks,
    and stores them in the `knowledge_chunks` table in DuckDB.

    Three modes (mutually exclusive, force_reindex takes priority):
      - force_reindex=True  →  Drop whole table and rebuild from scratch.
      - incremental=True    →  Add only files not yet present in the index.
      - default             →  Index all files (may duplicate if already run).

    Path defaults are resolved from config.paths so no value needs to be
    hardcoded; override only when targeting a non-standard directory or DB.

    Args:
        knowledge_dir: Directory to scan for .md / .pdf files.
                       Default: KNOWLEDGE_BASE_DIR (.olav/knowledge/).
        db_path:       DuckDB file to write vectors into.
                       Default: MAIN_DB_PATH (.olav/db/olav.duckdb).
        force_reindex: Drop existing knowledge_chunks table and rebuild.
        incremental:   Only process files not yet indexed (by source_file name).
        chunk_size:    Characters per chunk (default: 1024).
        chunk_overlap: Overlap between adjacent chunks (default: 128).

    Returns:
        str: Indexing summary with file counts and chunk totals.

    Examples:
        >>> index_knowledge_files()                          # full index
        >>> index_knowledge_files(incremental=True)          # add new files only
        >>> index_knowledge_files(force_reindex=True)        # full rebuild
        >>> index_knowledge_files(knowledge_dir="/tmp/docs") # custom directory
    """
    if DuckDB is None or Document is None:
        return (
            "❌ Missing dependency: langchain-community. "
            "Install: pip install langchain-community"
        )

    # --- Resolve paths ---
    kdir = Path(knowledge_dir) if knowledge_dir else KNOWLEDGE_BASE_DIR
    db = Path(db_path) if db_path else MAIN_DB_PATH

    if not kdir.exists():
        return f"❌ Knowledge directory not found: {kdir}"

    # --- Collect files ---
    md_files = sorted(kdir.glob("**/*.md"))
    pdf_files = sorted(kdir.glob("**/*.pdf"))
    all_files = md_files + pdf_files

    if not all_files:
        return f"⚠️  No .md or .pdf files found in {kdir}"

    # --- Init tools ---
    try:
        embeddings = LLMFactory.get_embeddings()
    except ValueError as e:
        return f"❌ Embedding init failed — check LLM_API_KEY: {e}"

    processor = TextProcessor(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    # --- Open DB ---
    try:
        import duckdb  # type: ignore
    except ImportError:
        return "❌ duckdb not installed. Install: pip install duckdb"

    conn = duckdb.connect(str(db))

    # --- Handle force_reindex ---
    if force_reindex:
        try:
            conn.execute("DROP TABLE IF EXISTS knowledge_chunks")
            logger.info("knowledge_chunks table dropped for full rebuild.")
        except Exception as e:
            logger.warning("Could not drop knowledge_chunks: %s", e)

    # --- Incremental: resolve already-indexed files ---
    already_indexed: set[str] = set()
    if incremental and not force_reindex:
        already_indexed = _get_indexed_source_files(conn)
        logger.info("Incremental mode: %d files already indexed.", len(already_indexed))

    # --- Build documents ---
    docs: list = []
    stats = {
        "files_processed": 0,
        "files_skipped": 0,
        "files_failed": 0,
        "total_chunks": 0,
    }

    for file_path in all_files:
        fname = file_path.name

        if incremental and fname in already_indexed:
            stats["files_skipped"] += 1
            continue

        try:
            if file_path.suffix.lower() == ".pdf":
                raw_text = _read_pdf(file_path)
            else:
                raw_text = _read_markdown(file_path)

            if not raw_text.strip():
                logger.warning("Empty content in %s — skipping.", fname)
                stats["files_failed"] += 1
                continue

            chunks = processor.split_into_chunks(raw_text)
            total = len(chunks)

            for idx, chunk in enumerate(chunks, 1):
                meta = processor.build_chunk_metadata(
                    chunk_content=chunk,
                    chunk_index=idx,
                    total_chunks=total,
                    source_file=fname,
                    extra_metadata={"file_hash": _file_hash(file_path)},
                )
                docs.append(Document(page_content=chunk, metadata=meta))

            stats["files_processed"] += 1
            stats["total_chunks"] += total
            logger.debug("Indexed %s: %d chunks", fname, total)

        except Exception as e:
            logger.error("Failed to process %s: %s", fname, e)
            stats["files_failed"] += 1

    if not docs:
        return (
            "⚠️  No new documents to index.\n"
            f"  Skipped (already indexed): {stats['files_skipped']}\n"
            f"  Failed: {stats['files_failed']}"
        )

    # --- Write to DuckDB via LangChain ---
    try:
        DuckDB.from_documents(
            documents=docs,
            embedding=embeddings,
            connection=conn,
            table_name="knowledge_chunks",
        )
    except Exception as e:
        logger.error("Vector write failed: %s", e)
        return f"❌ Failed to write vectors to DB: {e}"

    # --- Summary ---
    mode = "REBUILD" if force_reindex else ("INCREMENTAL" if incremental else "FULL")
    lines = [
        f"✅ Knowledge Base Indexing Complete ({mode} mode)",
        f"  Files indexed:  {stats['files_processed']}",
        f"  Chunks written: {stats['total_chunks']}",
        f"  Files skipped:  {stats['files_skipped']}",
        f"  Files failed:   {stats['files_failed']}",
        f"  Directory:      {kdir}",
        f"  Database:       {db}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    force = "--force" in sys.argv
    incr = "--incremental" in sys.argv
    print(index_knowledge_files.invoke({
        "force_reindex": force,
        "incremental": incr,
    }))
