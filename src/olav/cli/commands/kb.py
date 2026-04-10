"""OLAV KB — Unified Knowledge Store CLI Commands.

Provides the `olav kb` command group:

  olav kb                     Show knowledge store status (alias for `status`)
  olav kb export [--dir DIR]  Export vault to Obsidian markdown
  olav kb sync [--dir DIR]    Sync markdown vault ↔ LanceDB
  olav kb import <file>       Import a single file into the knowledge store
  olav kb graph [--output F]  Generate vis.js HTML knowledge graph
  olav kb status              Print knowledge store statistics
  olav kb migrate             Backfill origin/confidence/tags on legacy entries
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _get_store():
    """Return a configured LanceDBStore from environment / config."""
    db_path = os.environ.get("OLAV_MEMORY_DB_PATH")
    if not db_path:
        try:
            from olav.core.config import get_memory_config
            cfg = get_memory_config()
            db_path = str(cfg.db_path)
        except Exception:
            db_path = str(Path.home() / ".olav" / "databases" / "memory.db")

    from olav.core.memory import get_store
    return get_store(db_path=db_path)


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


def cmd_graph(args) -> int:
    """Generate vis.js HTML knowledge graph."""
    store = _get_store()
    output = Path(getattr(args, "output", None) or "_graph.html")
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
    """Backfill origin/confidence/tags for legacy memory entries."""
    store = _get_store()
    from olav.core.memory.migrate import migrate_memory_table
    result = migrate_memory_table(store)
    print(f"Migration complete: updated={result['updated']}, skipped={result['skipped']}, errors={result['errors']}")
    return 0 if result["errors"] == 0 else 1


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

    # graph
    grp = kb_sub.add_parser("graph", help="Generate vis.js HTML knowledge graph")
    grp.add_argument("--output", default="_graph.html", help="Output HTML file")
    grp.add_argument("--open", action="store_true", help="Open in browser after generating")

    # migrate
    kb_sub.add_parser("migrate", help="Backfill origin/confidence/tags for legacy entries")

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
    elif kb_cmd == "graph":
        return cmd_graph(args)
    elif kb_cmd == "migrate":
        return cmd_migrate(args)
    else:
        print(f"Unknown kb subcommand: {kb_cmd}", file=sys.stderr)
        return 1
