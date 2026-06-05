"""olav_kb/ → LanceDB expert_knowledge importer (ADR-0015).

Loads all files from a directory into LanceDB as ``expert_knowledge`` rows
using LangChain's DirectoryLoader with format-specific sub-loaders.

Replaces ``expert_kb.py`` (YAML schema retired per ADR-0015 D6).

Usage::

    from olav.core.memory.kb_import import import_kb
    result = import_kb(Path("olav_kb/"), store=store)
    # → {"imported": 12, "skipped": 0, "errors": []}

Accepted formats:
    .txt     → TextLoader
    .md      → UnstructuredMarkdownLoader (falls back to TextLoader)
    .pdf     → PyPDFLoader (optional; skip if pypdf not installed)
    .docx    → Docx2txtLoader (optional; skip if docx2txt not installed)
    .html    → UnstructuredHTMLLoader (optional; skip if unstructured not installed)
    .csv     → CSVLoader

All chunks are written to LanceDB as:
    category = "expert_knowledge"
    origin   = "import"
    scope    = "global"
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loader map: extension → (loader_class_or_importpath, extra_kwargs)
# ---------------------------------------------------------------------------

# Hard-coded imports are guarded individually in _load_documents() so that
# missing optional dependencies only skip those file types rather than
# breaking the whole import.
_LOADER_MAP: dict[str, tuple[str, dict]] = {
    ".txt": ("langchain_community.document_loaders.TextLoader", {}),
    ".md": ("langchain_community.document_loaders.UnstructuredMarkdownLoader", {}),
    ".pdf": ("langchain_community.document_loaders.PyPDFLoader", {}),
    ".docx": ("langchain_community.document_loaders.Docx2txtLoader", {}),
    ".html": ("langchain_community.document_loaders.UnstructuredHTMLLoader", {}),
    ".htm": ("langchain_community.document_loaders.UnstructuredHTMLLoader", {}),
    ".csv": ("langchain_community.document_loaders.CSVLoader", {}),
}

_MD_FALLBACK = "langchain_community.document_loaders.TextLoader"


def _import_loader(dotted_path: str):
    """Import a loader class from a dotted module path."""
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ImportError(f"Cannot parse loader path: {dotted_path!r}")
    module_path, class_name = parts
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _load_documents(file_path: Path) -> list[Any]:
    """Load a single file using the appropriate LangChain loader.

    Returns a list of ``Document`` objects, or empty list on failure.
    """
    suffix = file_path.suffix.lower()
    loader_spec = _LOADER_MAP.get(suffix)

    if loader_spec is None:
        logger.debug("kb_import: no loader registered for %s — skipping", suffix)
        return []

    loader_path, kwargs = loader_spec

    # Attempt primary loader
    try:
        LoaderClass = _import_loader(loader_path)
        loader = LoaderClass(str(file_path), **kwargs)
        return loader.load()
    except ImportError as exc:
        if suffix == ".md":
            # Fallback for Markdown when unstructured is not installed
            try:
                FallbackClass = _import_loader(_MD_FALLBACK)
                loader = FallbackClass(str(file_path))
                return loader.load()
            except Exception as fb_exc:
                logger.warning("kb_import: .md fallback TextLoader failed for %s: %s", file_path, fb_exc)
                return []
        logger.warning(
            "kb_import: optional dependency missing for %s (%s) — skipping file %s",
            suffix,
            exc,
            file_path,
        )
        return []
    except Exception as exc:
        logger.warning("kb_import: failed to load %s: %s", file_path, exc)
        return []


def _split_documents(docs: list[Any], chunk_size: int, chunk_overlap: int) -> list[Any]:
    """Split documents using RecursiveCharacterTextSplitter."""
    if not docs:
        return []
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return splitter.split_documents(docs)
    except ImportError:
        logger.warning("kb_import: langchain_text_splitters not installed — returning unsplit docs")
        return docs
    except Exception as exc:
        logger.warning("kb_import: text splitting failed: %s", exc)
        return docs


def _embed(text: str) -> list[float] | None:
    """Embed text; returns None on failure."""
    try:
        from olav.core.embedder import embed_text

        return embed_text(text)
    except Exception as exc:
        logger.debug("kb_import: embed failed: %s", exc)
        return None


def import_kb(
    kb_dir: Path,
    store: Any | None = None,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> dict:
    """Load all files from ``kb_dir`` into LanceDB as ``expert_knowledge`` rows.

    Args:
        kb_dir:        Directory to scan recursively (e.g. ``olav_kb/``).
        store:         LanceDBStore instance. If None, loads the singleton.
        chunk_size:    Token target per chunk (default 500).
        chunk_overlap: Token overlap between adjacent chunks (default 100).

    Returns:
        ``{"imported": N, "skipped": N, "errors": [str, ...]}``
    """
    from olav.core.memory import MEMORY_TABLE, MemoryCategory

    if store is None:
        try:
            from olav.core.memory import get_store

            store = get_store()
        except Exception as exc:
            logger.warning("kb_import: store unavailable: %s", exc)
            return {"imported": 0, "skipped": 0, "errors": [str(exc)]}

    kb_dir = Path(kb_dir)
    if not kb_dir.exists():
        return {"imported": 0, "skipped": 0, "errors": [f"Directory not found: {kb_dir}"]}

    if not store.table_exists(MEMORY_TABLE):
        store.create_table(MEMORY_TABLE)

    imported = 0
    skipped = 0
    errors: list[str] = []

    # Walk all files recursively; skip hidden files and .gitkeep
    all_files = [
        f
        for f in sorted(kb_dir.rglob("*"))
        if f.is_file() and not f.name.startswith(".") and f.name != ".gitkeep"
    ]

    if not all_files:
        logger.info("kb_import: no files found in %s", kb_dir)
        return {"imported": 0, "skipped": 0, "errors": []}

    for file_path in all_files:
        docs = _load_documents(file_path)
        if not docs:
            skipped += 1
            continue

        chunks = _split_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            skipped += 1
            continue

        for chunk in chunks:
            text = chunk.page_content.strip()
            if not text:
                skipped += 1
                continue

            vec = _embed(text)
            if vec is None:
                vec = [0.0] * store.embedding_dim

            chunk_id = f"kb-{uuid.uuid4().hex[:12]}"
            source_rel = str(file_path.relative_to(kb_dir)) if kb_dir in file_path.parents or file_path.parent == kb_dir else str(file_path)
            metadata = {
                "source_file": source_rel,
                "kb_dir": str(kb_dir),
                "chunk_size": chunk_size,
            }
            # Carry through any LangChain metadata
            if chunk.metadata:
                for k, v in chunk.metadata.items():
                    if k not in metadata:
                        metadata[k] = str(v)

            try:
                result = store.add_memory(
                    id=chunk_id,
                    text=text,
                    vector=vec,
                    category=MemoryCategory.EXPERT_KNOWLEDGE,
                    origin="import",
                    scope="global",
                    metadata=metadata,
                    confidence=1.0,
                    tags="[]",
                    table_name=MEMORY_TABLE,
                )
                if result.get("status") in ("success", "ok"):
                    imported += 1
                elif result.get("status") == "blocked":
                    skipped += 1
                    logger.debug("kb_import: blocked chunk from %s: %s", file_path, result)
                else:
                    errors.append(f"{file_path}: {result.get('reason', result)}")
            except Exception as exc:
                errors.append(f"{file_path}: {exc}")
                logger.warning("kb_import: write failed for chunk from %s: %s", file_path, exc)

    logger.info(
        "kb_import: imported=%d, skipped=%d, errors=%d from %s",
        imported, skipped, len(errors), kb_dir,
    )
    return {"imported": imported, "skipped": skipped, "errors": errors}
