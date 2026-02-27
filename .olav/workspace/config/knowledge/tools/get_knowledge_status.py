"""Knowledge Base Status Tool - Health check and statistics for the KB index.

Reports:
  - DuckDB knowledge_chunks table: total chunks, indexed source files.
  - Knowledge directory: file counts (.md / .pdf) and total size.
  - Embedding configuration: model, dimension, mode.
  - Database file size.

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
                       Default: .olav/knowledge/ (from paths.json).
        db_path:       DuckDB file that stores knowledge_chunks.
                       Default: .olav/databases/main.duckdb (from paths.json).

    Returns:
        str: Formatted status report.

    Examples:
        >>> get_knowledge_status()
        >>> get_knowledge_status(knowledge_dir="/custom/docs")
    """
    paths_config = get_paths_config()
    kdir = Path(knowledge_dir) if knowledge_dir else (paths_config.project_root / paths_config.knowledge_dir)
    db = Path(db_path) if db_path else (paths_config.project_root / paths_config.main_db)

    lines = ["📊 Knowledge Base Status", "=" * 40]

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

            with duckdb.connect(str(db)) as conn:
                # Check table exists
                tbl_check = conn.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='knowledge_chunks'"
                ).fetchone()
                                if isinstance(meta_raw, str)
                                else (meta_raw or {})
                            )
                            src = meta.get("source_file", "<unknown>")
                            source_counts[src] = source_counts.get(src, 0) + 1
                        except Exception as exc:
                            logger.debug("Failed to parse metadata: %s", exc)

                    if source_counts:
                        lines.append(f"   Indexed files: {len(source_counts)}")
                        lines.append("   Chunks per file:")
                        for fname, count in sorted(source_counts.items(), key=lambda x: -x[1]):
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
