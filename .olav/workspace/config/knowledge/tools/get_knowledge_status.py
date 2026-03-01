"""Knowledge Base Status Tool - Health check and statistics for the KB index.

Reports:
  - LanceDB kb_chunks table: total chunks, indexed source files.
  - Knowledge directory: file counts (.md / .pdf) and total size.
  - Embedding configuration: model, dimension.
  - LanceDB file size.

Path defaults are resolved from config.paths so nothing is hardcoded.
Defaults are also documented in SKILL.md under config.knowledge.
"""
from pathlib import Path
import logging

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(f):
        return f

from olav.core.config import get_paths_config
from olav.core.knowledge import get_knowledge_base, KB_TABLE
from olav.core.memory import get_store

logger = logging.getLogger(__name__)


def _human_size(num_bytes: int) -> str:
    """Format bytes as human-readable string (KB / MB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024**2:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024**2):.1f} MB"


@tool
def get_knowledge_status(
    knowledge_dir: str = "",
) -> str:
    """Report knowledge base statistics and health.

    Checks three things:
      1. Knowledge directory — how many files exist and their total size.
      2. LanceDB kb_chunks table — how many chunks are indexed and which files
         they came from.
      3. Embedding configuration — model name, vector dimension.

    Args:
        knowledge_dir: Directory containing source .md/.pdf knowledge files.
                       Default: .olav/knowledge/ (from paths.json).

    Returns:
        str: Formatted status report.

    Examples:
        >>> get_knowledge_status()
        >>> get_knowledge_status(knowledge_dir="/custom/docs")
    """
    paths_config = get_paths_config()
    kdir = Path(knowledge_dir) if knowledge_dir else (paths_config.project_root / paths_config.knowledge_dir)

    lines = ["📊 Knowledge Base Status", "=" * 50]

    # --- 1. Knowledge directory ---
    lines.append("\n📁 Knowledge Directory:")
    lines.append(f"   Path: {kdir}")

    if not kdir.exists():
        lines.append("   ⚠️  Directory does not exist.")
    else:
        md_files = list(kdir.glob("**/*.md"))
        pdf_files = list(kdir.glob("**/*.pdf"))
        all_files = md_files + pdf_files
        total_size = sum(f.stat().st_size for f in all_files if f.is_file())
        lines.append(f"   Markdown files: {len(md_files)}")
        lines.append(f"   PDF files:      {len(pdf_files)}")
        lines.append(f"   Total size:     {_human_size(total_size)}")

    # --- 2. LanceDB KB index ---
    lines.append("\n🗄️  LanceDB Index:")
    
    try:
        store = get_store()
        kb = get_knowledge_base(store)
        
        if not store.table_exists(KB_TABLE):
            lines.append(f"   Status: ❌ KB table '{KB_TABLE}' not found")
            lines.append("   Indexed files: 0")
            lines.append("   Total chunks: 0")
        else:
            # Get database info
            db_path = store.db_path  # LanceDB full path
            if isinstance(db_path, str):
                db_path_obj = Path(db_path)
                if db_path_obj.exists():
                    db_size = db_path_obj.stat().st_size
                    lines.append(f"   Path: {db_path}")
                    lines.append(f"   Size: {_human_size(db_size)}")
            
            # Get indexed sources
            try:
                sources = kb.get_indexed_sources()
                lines.append(f"   Indexed files: {len(sources)}")
                
                # Count total chunks in KB
                try:
                    tbl = store.get_table(KB_TABLE)
                    total_chunks = tbl.count_rows()
                    lines.append(f"   Total chunks: {total_chunks}")
                except Exception as e:
                    logger.debug(f"Could not count chunks: {e}")
                    lines.append("   Total chunks: unknown")
                
                if sources:
                    lines.append("   Files indexed:")
                    for src in sorted(sources):
                        lines.append(f"     • {src}")
            except Exception as e:
                logger.debug(f"Could not get indexed sources: {e}")
                lines.append(f"   ⚠️  Could not read KB metadata: {e}")
                
    except Exception as e:
        logger.error(f"KB status query failed: {e}")
        lines.append(f"   ❌ Error: {e}")

    # --- 3. Embedding configuration ---
    lines.append("\n🤖 Embedding Configuration:")
    try:
        from olav.core.llm import LLMFactory

        # Try to get embedding info
        try:
            embeddings = LLMFactory.get_embeddings()
            test_vector = embeddings.embed_query("test")
            dim = len(test_vector)
            
            # Model name (heuristic based on embeddings obj)
            model_name = getattr(embeddings, 'model', 'BAAI/bge-small')
            
            lines.append(f"   Model:     {model_name}")
            lines.append(f"   Dimension: {dim}")
        except Exception as e:
            logger.debug(f"Could not load embedding config: {e}")
            lines.append(f"   ⚠️  Could not initialize: {e}")
            
    except Exception as e:
        logger.debug(f"Could not load embedding support: {e}")
        lines.append(f"   ⚠️  Embedding not configured: {e}")

    return "\n".join(lines)
