"""OLAV KB — Unified Knowledge Store CLI Commands.

Provides the `olav kb` command group:

  olav kb                         Show knowledge store status (alias for `status`)
  olav kb export [--dir DIR]      Export vault to Obsidian markdown
  olav kb sync [--dir DIR]        Sync markdown vault ↔ LanceDB
  olav kb import <file>           Import a single file into the knowledge store
  olav kb graph [--output F]      Generate vis.js HTML knowledge graph
  olav kb status                  Print knowledge store statistics
  olav kb search <query>          Full-text search the knowledge store
  olav kb migrate                 Backfill origin/confidence/tags on legacy entries
  olav kb backfill-tags           Batch LLM tag extraction for untagged entries
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _get_store():
    """Return a configured LanceDBStore, running UKS migration if needed."""
    db_path = os.environ.get("OLAV_MEMORY_DB_PATH")
    from olav.core.memory import get_store
    store = get_store(db_path=db_path) if db_path else get_store()
    store.create_table()  # idempotent — ensures origin/confidence/tags columns exist
    return store


def _default_export_dir() -> Path:
    export_env = os.environ.get("OLAV_KB_EXPORT_DIR")
    if export_env:
        return Path(export_env)
    return Path(".olav") / "knowledge"


def _default_vault_dir() -> Path:
    return _default_export_dir()


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────────────────


def cmd_status(args) -> int:
    """Print knowledge store statistics."""
    store = _get_store()
    from olav.core.memory import MEMORY_TABLE

    if not store.table_exists(MEMORY_TABLE):
        print("Knowledge store: empty (no memory table)")
        print("Total entries: 0")
        return 0

    memories = store.get_memories(limit=100_000)
    total = len(memories)

    origin_counts: dict[str, int] = {}
    conf_sum = 0.0
    for m in memories:
        o = m.get("origin") or "unknown"
        origin_counts[o] = origin_counts.get(o, 0) + 1
        conf_sum += float(m.get("confidence") or 0.5)

    avg_conf = conf_sum / total if total else 0.0

    print("═══════════════════════════════")
    print("  OLAV Knowledge Store Status  ")
    print("═══════════════════════════════")
    print(f"Total entries     : {total}")
    print(f"Avg confidence    : {avg_conf:.2f}")
    print()
    print("By origin:")
    for origin, count in sorted(origin_counts.items()):
        bar = "█" * min(count, 40)
        print(f"  {origin:<12} {count:>6}  {bar}")
    return 0


def cmd_export(args) -> int:
    """Export vault to Obsidian markdown."""
    store = _get_store()
    output_dir = Path(getattr(args, "dir", None) or _default_export_dir())

    from olav.core.memory.knowledge_graph import export_obsidian
    result = export_obsidian(store, output_dir)
    print(f"Exported {result['written']} entries, {result['entities']} entity pages → {output_dir}")
    return 0


def cmd_sync(args) -> int:
    """Sync markdown vault directory ↔ LanceDB."""
    store = _get_store()
    kb_dir = Path(getattr(args, "dir", None) or _default_vault_dir())
    dry_run = getattr(args, "dry_run", False)
    origin = getattr(args, "origin", "user")

    from olav.core.memory.sync import sync_from_files
    result = sync_from_files(store, kb_dir, origin=origin, dry_run=dry_run)

    prefix = "[DRY RUN] " if dry_run else ""
    print(
        f"{prefix}Sync complete — "
        f"inserted={result['inserted']}, updated={result['updated']}, "
        f"deleted={result['deleted']}, skipped={result['skipped']}, "
        f"errors={result['errors']}"
    )
    return 0 if result["errors"] == 0 else 1


def cmd_import(args) -> int:
    """Import a single file into the knowledge store."""
    store = _get_store()
    file_path = Path(args.file)
    origin = getattr(args, "origin", "document")

    from olav.core.memory.sync import kb_import
    result = kb_import(store, file_path, origin=origin)

    if result["status"] == "success":
        print(f"Imported {result['chunks']} chunk(s) from {result['file']}")
        return 0
    else:
        print(f"Error: {result.get('message', 'unknown error')}", file=sys.stderr)
        return 1


def cmd_import_guides(args) -> int:
    """Scan a directory for ``*.guide.yaml`` files and prime each as a
    ``usage_guide`` memory entry.

    Sibling to ``cmd_import``: ``import`` chunks markdown documents into
    many memory rows, ``import-guides`` writes one whole-body row per
    guide (no chunking) keyed by ``guide_<agent>_<intent>``.
    """
    workspace_root = Path(args.dir)
    if not workspace_root.exists():
        print(f"Error: directory not found: {workspace_root}", file=sys.stderr)
        return 1

    from olav.core.memory.guide_kb import prime_guides_from_dir
    store = _get_store()
    result = prime_guides_from_dir(workspace_root, store=store)

    n = result["guide_entries"]
    skipped = result["skipped"]
    print(f"Imported {n} guide(s) from {workspace_root} ({skipped} skipped)")
    if skipped == -1:
        return 1
    return 0


def cmd_import_formats(args) -> int:
    """Scan a directory for ``*.format.yaml`` files and prime each as a
    ``format_guide`` memory entry.

    R85 sibling to ``cmd_import_guides``: format guides describe how
    the agent should call ``format_and_export`` for a given output
    shape (mermaid diagram, query result CSV, audit report, ...).
    """
    workspace_root = Path(args.dir)
    if not workspace_root.exists():
        print(f"Error: directory not found: {workspace_root}", file=sys.stderr)
        return 1

    from olav.core.memory.format_kb import prime_formats_from_dir
    store = _get_store()
    result = prime_formats_from_dir(workspace_root, store=store)

    n = result["format_entries"]
    skipped = result["skipped"]
    print(f"Imported {n} format(s) from {workspace_root} ({skipped} skipped)")
    if skipped == -1:
        return 1
    return 0


def cmd_graph(args) -> int:
    """Generate vis.js HTML knowledge graph."""
    store = _get_store()
    output = Path(getattr(args, "output", None) or str(_default_vault_dir() / "_graph.html"))
    open_browser = getattr(args, "open", False)

    from olav.core.memory.knowledge_graph import materialize_graph, export_visjs, cluster_knowledge

    graph_data = materialize_graph(store)
    if not graph_data["nodes"]:
        print("Knowledge store is empty — generating empty graph.")

    communities = cluster_knowledge(graph_data)
    export_visjs(graph_data, output, communities=communities)
    print(f"Graph written → {output} ({len(graph_data['nodes'])} nodes, {len(graph_data['edges'])} edges)")

    if open_browser:
        import webbrowser
        webbrowser.open(output.resolve().as_uri())

    return 0


def cmd_migrate(args) -> int:
    """Backfill origin/confidence/tags for legacy memory entries.

    LEGACY-KEEP: ``olav kb migrate`` upgrades v0.10 memory rows (kb_chunks /
    kb_query_cache tables) to the unified v0.11+ schema. Remove this command
    only once COMPATIBILITY_CUTOFF reaches v0.11.0+ and no supported
    deployment can still be on the old schema.
    """
    store = _get_store()
    drop_legacy = getattr(args, "drop_legacy", False)
    from olav.core.memory.migrate import migrate_memory_table
    result = migrate_memory_table(store)
    print(f"Migration complete: updated={result['updated']}, skipped={result['skipped']}, errors={result['errors']}")

    if drop_legacy:
        import lancedb  # type: ignore[import]
        db = lancedb.connect(store._db_path)
        dropped = []
        for tbl in ("kb_chunks", "kb_query_cache"):
            if tbl in db.table_names():
                db.drop_table(tbl)
                dropped.append(tbl)
        if dropped:
            print(f"Dropped legacy tables: {', '.join(dropped)}")
        else:
            print("No legacy tables found (kb_chunks / kb_query_cache).")

    return 0 if result["errors"] == 0 else 1


def cmd_search(args) -> int:
    """Search the unified knowledge store."""
    store = _get_store()
    query = args.query
    limit = getattr(args, "limit", 5)

    results = store.search_by_text(query, limit=limit)
    if not results:
        print("No results found.")
        return 0

    for i, mem in enumerate(results, 1):
        mem_id = mem.get("id", "?")
        origin = mem.get("origin") or "?"
        confidence = float(mem.get("confidence") or 0.5)
        text = (mem.get("text") or "").replace("\n", " ")
        snippet = text[:120] + "…" if len(text) > 120 else text
        print(f"[{i}] {mem_id}  origin={origin}  conf={confidence:.2f}")
        print(f"     {snippet}")
        print()
    return 0


def cmd_backfill_tags(args) -> int:
    """Batch LLM tag extraction for entries with empty tags."""
    store = _get_store()
    batch_size = getattr(args, "batch_size", 50)
    dry_run = getattr(args, "dry_run", False)

    from olav.core.memory import MEMORY_TABLE
    # Use to_pandas() for a fast full-table scan (avoids vector search hang)
    try:
        tbl = store.get_table(MEMORY_TABLE)
        df = tbl.to_pandas()
        memories = df.to_dict("records")
    except Exception as e:
        print(f"Failed to read knowledge store: {e}", file=sys.stderr)
        return 1

    empty = [m for m in memories if not m.get("tags") or str(m.get("tags")) in ("[]", "null", "")]
    print(f"Found {len(empty)} entries with empty tags.")

    if not empty:
        return 0

    # Try to get LLM from platform config (api_key + base_url)
    llm = None
    try:
        from langchain_openai import ChatOpenAI  # type: ignore[import]
        from olav.core.config import get_llm_config
        cfg = get_llm_config()
        api_key = cfg.api_key or os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            kwargs: dict = {"model": "gpt-4o-mini", "temperature": 0, "api_key": api_key}
            base_url = cfg.base_url or os.environ.get("OPENAI_BASE_URL", "")
            if base_url:
                kwargs["base_url"] = base_url
            llm = ChatOpenAI(**kwargs)
    except Exception:
        pass

    if llm is None:
        print("LLM not available (set OPENAI_API_KEY or configure api_key in .olav/config/api.json).")
        print("Use --dry-run to preview which entries need tagging.")
        if not dry_run:
            return 1

    if dry_run:
        for m in empty[:10]:
            print(f"  {m.get('id')}: {str(m.get('text') or '')[:80]}")
        if len(empty) > 10:
            print(f"  ... and {len(empty) - 10} more")
        return 0

    from langchain_core.messages import HumanMessage  # type: ignore[import]

    BATCH_PROMPT = (
        "Extract 1-5 concise keyword tags from each text. "
        "Return a JSON array of arrays: [[\"tag1\",\"tag2\"], [\"tag3\"], ...]\n\n"
        "Texts:\n{texts}"
    )

    def _chunked(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    updated = errors = 0

    for batch_num, batch in enumerate(_chunked(empty, batch_size), 1):
        texts_block = "\n---\n".join(f"{i+1}. {str(m.get('text') or '')[:300]}" for i, m in enumerate(batch))
        try:
            resp = llm.invoke([HumanMessage(content=BATCH_PROMPT.format(texts=texts_block))])
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            tags_list = json.loads(raw)
            if not isinstance(tags_list, list):
                raise ValueError("Expected list")
        except Exception as e:
            print(f"  Batch {batch_num} LLM error: {e}", file=sys.stderr)
            errors += len(batch)
            continue

        # Write this batch immediately — group by tag JSON to reduce update calls
        from collections import defaultdict
        tags_to_ids: dict[str, list[str]] = defaultdict(list)
        for mem, tags in zip(batch, tags_list):
            if isinstance(tags, list):
                mid = str(mem.get("id", ""))
                if mid:
                    tags_to_ids[json.dumps(tags)].append(mid)

        for tags_json, ids in tags_to_ids.items():
            id_list = ", ".join(f"'{rid}'" for rid in ids)
            try:
                tbl.update(where=f"id IN ({id_list})", values={"tags": tags_json})
                updated += len(ids)
                # Print generated tags so callers can verify domain relevance
                print(f"  tags: {tags_json}")
            except Exception as e:
                print(f"  Batch {batch_num} tag update error: {e}", file=sys.stderr)
                errors += len(ids)

        print(f"  Batch {batch_num}: tagged {len(tags_to_ids)} groups ({sum(len(v) for v in tags_to_ids.values())} entries)")

    print(f"Backfill complete: updated={updated}, errors={errors}")
    return 0 if errors == 0 else 1


# ─────────────────────────────────────────────────────────────────────────────
# Parser builder
# ─────────────────────────────────────────────────────────────────────────────


def build_kb_parser(parent_subparsers) -> argparse.ArgumentParser:
    """Register `kb` subcommand on a parent argparse subparsers object."""
    kb_parser = parent_subparsers.add_parser(
        "kb",
        help="Unified Knowledge Store management (export/sync/import/graph/status)",
    )
    kb_sub = kb_parser.add_subparsers(dest="kb_command", help="KB subcommand")

    # status
    kb_sub.add_parser("status", help="Show knowledge store statistics")

    # export
    exp = kb_sub.add_parser("export", help="Export vault to Obsidian markdown")
    exp.add_argument("--dir", default=None, help="Output directory (default: .olav/knowledge/)")

    # sync
    syn = kb_sub.add_parser("sync", help="Sync markdown vault ↔ LanceDB")
    syn.add_argument("--dir", default=None, help="Vault directory (default: .olav/knowledge/)")
    syn.add_argument("--origin", default="user", help="Origin tag for synced entries")
    syn.add_argument("--dry-run", action="store_true", dest="dry_run", help="Preview changes without writing")

    # import
    imp = kb_sub.add_parser("import", help="Import a single file into the knowledge store")
    imp.add_argument("file", help="File path to import")
    imp.add_argument("--origin", default="document", help="Origin tag (default: document)")
    imp.add_argument("--chunk-size", type=int, default=1500, dest="chunk_size")

    # import-guides — prime *.guide.yaml under a workspace as usage_guide rows
    imp_g = kb_sub.add_parser(
        "import-guides",
        help="Scan a directory for *.guide.yaml and prime them as "
             "usage_guide memory rows (1 file = 1 row, idempotent)",
    )
    imp_g.add_argument(
        "dir",
        nargs="?",
        default=".olav/workspace",
        help="Workspace root (default: .olav/workspace)",
    )

    # import-formats — prime *.format.yaml under a workspace as format_guide rows (R85)
    imp_f = kb_sub.add_parser(
        "import-formats",
        help="Scan a directory for *.format.yaml and prime them as "
             "format_guide memory rows (R85 inline-save)",
    )
    imp_f.add_argument(
        "dir",
        nargs="?",
        default=".olav/workspace",
        help="Workspace root (default: .olav/workspace)",
    )

    # graph
    grp = kb_sub.add_parser("graph", help="Generate vis.js HTML knowledge graph")
    grp.add_argument("--output", default=None, help="Output HTML file (default: .olav/knowledge/_graph.html)")
    grp.add_argument("--open", action="store_true", help="Open in browser after generating")

    # migrate
    mig = kb_sub.add_parser("migrate", help="Backfill origin/confidence/tags for legacy entries")
    mig.add_argument("--drop-legacy", action="store_true", dest="drop_legacy",
                     help="Drop kb_chunks and kb_query_cache tables after migration")

    # search
    srch = kb_sub.add_parser("search", help="Full-text search the unified knowledge store")
    srch.add_argument("query", help="Search query text")
    srch.add_argument("--limit", type=int, default=5, help="Maximum results (default: 5)")

    # backfill-tags
    bft = kb_sub.add_parser("backfill-tags", help="Batch LLM tag extraction for untagged entries")
    bft.add_argument("--batch-size", type=int, default=50, dest="batch_size")
    bft.add_argument("--dry-run", action="store_true", dest="dry_run", help="Preview only")

    return kb_parser


def handle_kb_command(args) -> int:
    """Dispatch kb subcommand from parsed args."""
    kb_cmd = getattr(args, "kb_command", None)

    if kb_cmd == "status" or kb_cmd is None:
        return cmd_status(args)
    elif kb_cmd == "export":
        return cmd_export(args)
    elif kb_cmd == "sync":
        return cmd_sync(args)
    elif kb_cmd == "import":
        return cmd_import(args)
    elif kb_cmd == "import-guides":
        return cmd_import_guides(args)
    elif kb_cmd == "import-formats":
        return cmd_import_formats(args)
    elif kb_cmd == "graph":
        return cmd_graph(args)
    elif kb_cmd == "migrate":
        return cmd_migrate(args)
    elif kb_cmd == "search":
        return cmd_search(args)
    elif kb_cmd == "backfill-tags":
        return cmd_backfill_tags(args)
    else:
        print(f"Unknown kb subcommand: {kb_cmd}", file=sys.stderr)
        return 1
