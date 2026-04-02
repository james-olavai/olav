"""Index Knowledge Files Tool - Build/update the KB vector index in LanceDB.

Scans a knowledge directory for Markdown and PDF files, splits them into
semantic chunks, embeds with the configured embedding model, and stores
the vectors in LanceDB KB table for later similarity search.

Three indexing modes:
  - Full (default): Index all files (may add duplicates if already indexed).
  - Incremental:    Skip files whose source_file is already in KB.
  - Force rebuild:  Delete all KB chunks and rebuild from scratch.

Path arguments default to config.paths values so nothing is hardcoded.
Defaults are also documented in SKILL.md under config.knowledge.
"""
import logging
from pathlib import Path

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(f):
        return f

from olav.core.config import get_paths_config
from olav.core.knowledge import KB_TABLE, get_knowledge_base
from olav.core.memory import get_store

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
    except Exception as e:
        logger.warning(f"Could not extract PDF {file_path}: {e}. Skipping.")
        return ""


@tool
def index_knowledge_files(
    knowledge_dir: str = "",
    force_reindex: bool = False,
    incremental: bool = False,
    chunk_size: int = 1024,
    chunk_overlap: int = 128,
) -> str:
    """Index knowledge files (Markdown/PDF) into the LanceDB vector KB.

    Scans `knowledge_dir` recursively, chunks each file, embeds the chunks,
    and stores them in the LanceDB `kb_chunks` table.

    Three modes (mutually exclusive, force_reindex takes priority):
      - force_reindex=True  ->  Delete all KB chunks and rebuild from scratch.
      - incremental=True    ->  Add only files not yet present in the KB.
      - default             ->  Index all files (may duplicate if already run).

    Args:
        knowledge_dir: Directory to scan for .md / .pdf files.
                       Default: .olav/knowledge/ (from paths.json).
        force_reindex: Delete all KB chunks and rebuild from scratch.
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
    # --- Resolve paths ---
    paths_config = get_paths_config()
    kdir = Path(knowledge_dir) if knowledge_dir else (paths_config.project_root / paths_config.knowledge_dir)

    if not kdir.exists():
        return f"❌ Knowledge directory not found: {kdir}"

    # --- Collect files ---
    md_files = sorted(kdir.glob("**/*.md"))
    pdf_files = sorted(kdir.glob("**/*.pdf"))
    all_files = md_files + pdf_files

    if not all_files:
        return f"⚠️  No .md or .pdf files found in {kdir}"

    # --- Init KB engine ---
    try:
        store = get_store()
        kb = get_knowledge_base(store)
    except Exception as e:
        return f"❌ Failed to initialize KB engine: {e}"

    # --- Get already-indexed sources (for incremental mode) ---
    indexed_sources = set()
    if incremental or force_reindex:
        try:
            indexed_sources = set(kb.get_indexed_sources())
            if force_reindex:
                logger.info(f"Force reindex: deleting {len(indexed_sources)} existing sources...")
                for src in indexed_sources:
                    try:
                        kb.delete_source(src)
                    except Exception as e:
                        logger.warning(f"Could not delete source {src}: {e}")
                indexed_sources.clear()
        except Exception as e:
            logger.warning(f"Could not get indexed sources: {e}")

    # --- Index files ---
    total_indexed = 0
    skipped = 0
    failed = 0
    results = []

    for file_path in all_files:
        rel_path = str(file_path.relative_to(kdir))

        # Skip if already indexed (incremental mode)
        if incremental and rel_path in indexed_sources:
            skipped += 1
            continue

        # Read file
        try:
            if file_path.suffix.lower() == ".md":
                content = _read_markdown(file_path)
            elif file_path.suffix.lower() == ".pdf":
                content = _read_pdf(file_path)
                if not content:
                    failed += 1
                    continue
            else:
                continue

            if not content.strip():
                failed += 1
                results.append(f"  ⚠️  {rel_path}: empty content")
                continue

            # Index into KB
            try:
                kb.index_document(
                    file_path=rel_path,
                    text_content=content,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                total_indexed += 1
                results.append(f"  ✓ {rel_path}")
            except Exception as e:
                failed += 1
                results.append(f"  ❌ {rel_path}: {e}")

        except Exception as e:
            failed += 1
            logger.warning(f"Error processing {rel_path}: {e}")
            results.append(f"  ❌ {rel_path}: {e}")

    # --- Summary ---
    mode = "REBUILD" if force_reindex else ("INCREMENTAL" if incremental else "FULL")
    summary = f"""
✅ Knowledge Base Indexing Complete ({mode} mode)

📊 Statistics:
  • Files indexed:  {total_indexed}
  • Files skipped:  {skipped}
  • Files failed:   {failed}
  • Total files:    {len(all_files)}

📁 Source directory: {kdir}
🗂️  Target: LanceDB kb_chunks table

📝 Details:
"""
    if results:
        summary += "\n".join(results)
    else:
        summary += "  (No changes)"

    return summary
