"""Knowledge Base Status Tool - Health check and statistics for the KB index.

Reports:
  - DuckDB knowledge_chunks table: total chunks, indexed source files.
  - Knowledge directory: file counts (.md / .pdf) and total size.
  - Embedding configuration: model, dimension, mode.
  - Database file size.

Path defaults are resolved from config.paths so nothing is hardcoded.
Defaults are also documented in SKILL.md under config.knowledge.
"""

import json
import logging
from pathlib import Path

try:
    from langchain_core.tools import tool
except ImportError:
    tool = lambda f: f

from config.paths import KNOWLEDGE_BASE_DIR, MAIN_DB_PATH

logger = logging.getLogger(__name__)


def _human_size(num_bytes: int) -> str:
    """Format bytes as human-readable string (KB / MB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 ** 2:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 ** 2):.1f} MB"


@tool
def get_knowledge_status(
    knowledge_dir: str = "",
    db_path: str = "",
) -> str:
    """Report knowledge base statistics and health.

    Checks three things:
      1. Knowledge directory — how many files exist and their total size.
      2. DuckDB chunks table — how many chunks are indexed and which files
         they came from.
      3. Embedding configuration — model name, vector dimension, and mode.

    Args:
        knowledge_dir: Directory containing source .md/.pdf knowledge files.
                       Default: KNOWLEDGE_BASE_DIR (.olav/knowledge/).
        db_path:       DuckDB file that stores knowledge_chunks.
                       Default: MAIN_DB_PATH (.olav/db/olav.duckdb).

    Returns:
        str: Formatted status report.

    Examples:
        >>> get_knowledge_status()
        >>> get_knowledge_status(knowledge_dir="/custom/docs")
    """
    kdir = Path(knowledge_dir) if knowledge_dir else KNOWLEDGE_BASE_DIR
    db = Path(db_path) if db_path else MAIN_DB_PATH

    lines = ["📊 Knowledge Base Status", "=" * 40]

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

    # --- 2. DuckDB chunks table ---
    lines.append("\n🗄️  DuckDB Index:")
    lines.append(f"   Path: {db}")

    if not db.exists():
        lines.append("   ⚠️  Database file not found — run index_knowledge_files() first.")
    else:
        db_size = db.stat().st_size
        lines.append(f"   DB size: {_human_size(db_size)}")

        try:
            import duckdb  # type: ignore
            conn = duckdb.connect(str(db), read_only=True)

            # Check table exists
            tbl_check = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name='knowledge_chunks'"
            ).fetchone()

            if not tbl_check or tbl_check[0] == 0:
                lines.append("   ⚠️  knowledge_chunks table not found — index not built yet.")
            else:
                total_chunks = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks"
                ).fetchone()[0]
                lines.append(f"   Total chunks: {total_chunks}")

                # Source files breakdown via metadata JSON
                try:
                    meta_rows = conn.execute(
                        "SELECT metadata FROM knowledge_chunks"
                    ).fetchall()
                    source_counts: dict[str, int] = {}
                    for (meta_raw,) in meta_rows:
                        try:
                            meta = (
                                json.loads(meta_raw)
                                if isinstance(meta_raw, str)
                                else (meta_raw or {})
                            )
                            src = meta.get("source_file", "<unknown>")
                            source_counts[src] = source_counts.get(src, 0) + 1
                        except Exception:
                            pass

                    if source_counts:
                        lines.append(
                            f"   Indexed files: {len(source_counts)}"
                        )
                        lines.append("   Chunks per file:")
                        for fname, count in sorted(
                            source_counts.items(), key=lambda x: -x[1]
                        ):
                            lines.append(f"     • {fname}: {count} chunks")
                    else:
                        lines.append("   (No source_file metadata found in chunks)")

                except Exception as meta_err:
                    logger.debug("Could not parse chunk metadata: %s", meta_err)
                    lines.append("   (Could not parse per-file breakdown)")

            conn.close()

        except ImportError:
            lines.append("   ❌ duckdb not installed. Install: pip install duckdb")
        except Exception as e:
            logger.error("DB status query failed: %s", e)
            lines.append(f"   ❌ DB query error: {e}")

    # --- 3. Embedding configuration ---
    lines.append("\n🤖 Embedding Configuration:")
    try:
        from src.olav.core.knowledge.embedding_gateway import EmbeddingGateway
        gw = EmbeddingGateway()
        cfg = gw.get_embedding_config()
        lines.append(f"   Mode:      {cfg.get('embedding_mode', 'unknown')}")
        lines.append(f"   Model:     {cfg.get('embedding_model', 'unknown')}")
        lines.append(f"   Dimension: {cfg.get('embedding_dim', 'unknown')}")
    except ValueError as e:
        lines.append(f"   ⚠️  API key not configured: {e}")
    except Exception as e:
        logger.debug("Could not load embedding config: %s", e)
        lines.append(f"   ⚠️  Could not load config: {e}")

    return "\n".join(lines)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(get_knowledge_status.invoke({}))
