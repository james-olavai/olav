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


def cmd_import_kb(args) -> int:
    """Load all files from a directory into LanceDB as expert_knowledge rows.

    ADR-0015: replaces ``import-experts`` (YAML schema retired). Accepts any
    file format — PDF, DOCX, Markdown, TXT, HTML, CSV — via LangChain loaders.
    """
    from olav.core.memory.kb_import import import_kb

    kb_dir = Path(getattr(args, "path", None) or "olav_kb")
    if not kb_dir.exists():
        print(f"Error: directory not found: {kb_dir}", file=sys.stderr)
        return 1

    store = _get_store()
    chunk_size = getattr(args, "chunk_size", 500)
    chunk_overlap = getattr(args, "chunk_overlap", 100)
    result = import_kb(kb_dir, store=store, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    imported = result["imported"]
    skipped = result["skipped"]
    errors = result.get("errors", [])
    print(f"Imported {imported} chunk(s) from {kb_dir} ({skipped} skipped, {len(errors)} error(s))")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}", file=sys.stderr)
    return 0 if not errors else 1


def cmd_gc(args) -> int:
    """Delete expired rows and optionally purge all expert_knowledge rows.

    ADR-0015:
      Default: delete rows WHERE expires_at IS NOT NULL AND expires_at < now()
      With --purge-expert: also delete all rows WHERE category = 'expert_knowledge'
    """
    from olav.core.memory import MEMORY_TABLE

    store = _get_store()
    purge_expert = getattr(args, "purge_expert", False)

    deleted_expired = 0
    deleted_expert = 0

    if not store.table_exists(MEMORY_TABLE):
        print("Knowledge store: empty (no memory table)")
        return 0

    try:
        tbl = store.get_table(MEMORY_TABLE)
        # Delete expired reflection rows
        tbl.delete("expires_at IS NOT NULL AND expires_at < now()")
        # Count what's left (approximate — count before delete was tricky with LanceDB)
        deleted_expired = -1  # LanceDB delete doesn't return count; report as done
    except Exception as e:
        print(f"Error during expired row cleanup: {e}", file=sys.stderr)
        return 1

    if purge_expert:
        try:
            tbl.delete("category = 'expert_knowledge'")
            deleted_expert = -1
        except Exception as e:
            print(f"Error during expert_knowledge purge: {e}", file=sys.stderr)
            return 1

    print("GC complete:")
    print("  Expired reflection rows: deleted (WHERE expires_at IS NOT NULL AND expires_at < now())")
    if purge_expert:
        print("  expert_knowledge rows: purged (--purge-expert)")
    return 0


def cmd_list_experts(args) -> int:
    """List ``expert_knowledge`` entries with optional scope/source filters.

    R87 Phase 1.5 audit surface — lets the user (and operators) see
    what's primed, separate shipped from user-injected content, and
    inspect precedence flags.
    """
    import json as _json

    store = _get_store()
    if store is None:
        print("Error: knowledge store unavailable", file=sys.stderr)
        return 1

    rows = store.get_memories(category="expert_knowledge", limit=1000)
    if not rows:
        print("No expert_knowledge entries found.")
        return 0

    source_filter = getattr(args, "source", None)
    scope_filter = getattr(args, "scope", None)

    def _meta(row: dict) -> dict:
        md = row.get("metadata") or {}
        if isinstance(md, str):
            try:
                md = _json.loads(md)
            except Exception:
                md = {}
        return md

    filtered = []
    for r in rows:
        md = _meta(r)
        if source_filter and md.get("source") != source_filter:
            continue
        if scope_filter and r.get("scope") != scope_filter:
            continue
        filtered.append((r, md))

    if not filtered:
        print("No entries match the filters.")
        return 0

    # Header — column widths sized to current data; truncates long topics
    print(f"{'ID':52s}  {'SCOPE':18s}  {'SOURCE':8s}  {'PREC':9s}  TOPIC")
    print(f"{'-' * 52}  {'-' * 18}  {'-' * 8}  {'-' * 9}  {'-' * 32}")
    for r, md in filtered:
        rid = (r.get("id") or "")[:52]
        scope = r.get("scope") or "?"
        source = (md.get("source") or "?")
        prec = (md.get("precedence") or "default")
        topic = md.get("topic") or ""
        print(f"{rid:52s}  {scope:18s}  {source:8s}  {prec:9s}  {topic}")
    print(f"\n{len(filtered)} entr{'y' if len(filtered) == 1 else 'ies'}")
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


# ── 2026-05-15 (dev_docs/79) — enterprise KB lifecycle commands ──────

def _find_guide(
    workspace_root: Path,
    intent: str,
    agent_hint: str | None = None,
) -> tuple[Path, dict]:
    """Locate ``<intent>.guide.yaml`` under ``workspace_root``.

    If ``agent_hint`` is given, only that agent's guides directory is
    searched.  Otherwise the search spans the whole workspace and the
    caller gets an error if more than one agent owns the same intent.
    """
    import yaml
    candidates = []
    for path in workspace_root.rglob(f"{intent}.guide.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if data.get("intent") != intent:
            continue
        if agent_hint and data.get("agent") != agent_hint:
            continue
        candidates.append((path, data))
    if not candidates:
        scope = f"agent={agent_hint!r}" if agent_hint else "any agent"
        raise FileNotFoundError(
            f"No guide '{intent}' found under {workspace_root} ({scope})"
        )
    if len(candidates) > 1:
        agents = sorted({d.get("agent", "?") for _, d in candidates})
        raise ValueError(
            f"Multiple guides named '{intent}' found "
            f"(agents: {agents}). Disambiguate with --agent <name>."
        )
    return candidates[0]


def _write_audit_row(
    workspace_root: Path,
    *,
    action: str,
    intent: str,
    agent: str,
    reason: str | None = None,
    body_sha256: str = "",
    source_tier: str | None = None,
) -> Path:
    """Append one ``kb_audit/<ts>_<verb>_<intent>.yaml`` row."""
    import os
    import yaml
    from datetime import datetime, timezone

    audit_dir = workspace_root / "kb_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).astimezone()
    fname = f"{now.strftime('%Y-%m-%dT%H-%M-%S')}_{action}_{intent}.yaml"
    target = audit_dir / fname
    row = {
        "action": action,
        "intent": intent,
        "agent": agent,
        "actor": os.environ.get("USER", "unknown"),
        "timestamp": now.isoformat(timespec="seconds"),
        "body_sha256": body_sha256,
    }
    if reason is not None:
        row["reason"] = reason
    if source_tier is not None:
        row["source_tier"] = source_tier
    target.write_text(
        yaml.safe_dump(row, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return target


def cmd_remove(args) -> int:
    """`olav kb remove <intent>` — tombstone + LanceDB delete + audit row."""
    import hashlib
    import os

    workspace_root = Path(args.workspace).resolve()
    if not workspace_root.exists():
        print(f"workspace root not found: {workspace_root}", file=sys.stderr)
        return 1

    # Reason gate
    reason = args.reason
    if not reason and not os.environ.get("OLAV_KB_REMOVE_ALLOW_NO_REASON"):
        print(
            "error: --reason is required (override with "
            "OLAV_KB_REMOVE_ALLOW_NO_REASON=1 for batch scripts)",
            file=sys.stderr,
        )
        return 2

    try:
        guide_path, data = _find_guide(workspace_root, args.intent, args.agent)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    agent = data.get("agent", args.agent or "?")
    source_tier = data.get("source_tier", "user")
    body = str(data.get("body", ""))
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
    memory_id = f"guide_{agent}_{args.intent}"

    # 1. Tombstone (unless --keep-yaml)
    if not args.keep_yaml:
        tomb = guide_path.with_suffix(guide_path.suffix + ".removed")
        guide_path.rename(tomb)
        tombstone_note = f"tombstoned → {tomb.name}"
    else:
        tombstone_note = "yaml kept (--keep-yaml); reprime will resurrect"

    # 2. LanceDB delete
    try:
        store = _get_store()
        store.delete_memory(id=memory_id)
        lance_note = f"LanceDB row {memory_id} deleted"
    except Exception as exc:
        lance_note = f"LanceDB delete failed: {exc}"

    # 3. Audit row
    audit_path = _write_audit_row(
        workspace_root,
        action="remove",
        intent=args.intent,
        agent=agent,
        reason=reason or "",
        body_sha256=body_sha,
        source_tier=source_tier,
    )

    print(f"✓ removed {args.intent} (agent={agent}, tier={source_tier})")
    print(f"  • {tombstone_note}")
    print(f"  • {lance_note}")
    print(f"  • audit: {audit_path.relative_to(workspace_root)}")
    if reason:
        print(f"  • reason: {reason}")
    return 0


def cmd_show(args) -> int:
    """`olav kb show <intent>` — print the guide YAML."""
    workspace_root = Path(args.workspace).resolve()
    try:
        guide_path, _ = _find_guide(workspace_root, args.intent, args.agent)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(guide_path.read_text(encoding="utf-8"))
    return 0


def cmd_list_guides(args) -> int:
    """`olav kb list-guides` — table of active guides + tiers."""
    import yaml
    workspace_root = Path(args.workspace).resolve()
    if not workspace_root.exists():
        print(f"workspace root not found: {workspace_root}", file=sys.stderr)
        return 1

    rows = []
    for path in sorted(workspace_root.rglob("*.guide.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        intent = data.get("intent", "?")
        agent = data.get("agent", "?")
        tier = data.get("source_tier") or "user (legacy)"
        if args.tier and not str(tier).startswith(args.tier):
            continue
        if args.agent and agent != args.agent:
            continue
        rows.append((agent, intent, tier, path.relative_to(workspace_root)))

    if not rows:
        print("No guides found." if not args.tier and not args.agent
              else f"No guides match filter (tier={args.tier}, agent={args.agent}).")
        return 0

    w_agent = max(len("AGENT"), max(len(r[0]) for r in rows))
    w_intent = max(len("INTENT"), max(len(r[1]) for r in rows))
    w_tier = max(len("TIER"), max(len(str(r[2])) for r in rows))
    print(f"{'AGENT':<{w_agent}}  {'INTENT':<{w_intent}}  {'TIER':<{w_tier}}  PATH")
    print("-" * (w_agent + w_intent + w_tier + 12))
    for agent, intent, tier, p in rows:
        print(f"{agent:<{w_agent}}  {intent:<{w_intent}}  {tier:<{w_tier}}  {p}")
    return 0


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

    # import-kb — load any-format files into expert_knowledge (ADR-0015)
    imp_kb = kb_sub.add_parser(
        "import-kb",
        help="Load all files from olav_kb/ (or a given path) into LanceDB as "
             "expert_knowledge rows. Accepts PDF, DOCX, Markdown, TXT, HTML, CSV. "
             "(ADR-0015 replacement for import-experts)",
    )
    imp_kb.add_argument(
        "path",
        nargs="?",
        default="olav_kb",
        help="Directory to import (default: ./olav_kb/)",
    )
    imp_kb.add_argument("--chunk-size", type=int, default=500, dest="chunk_size",
                        help="Chunk size in tokens (default: 500)")
    imp_kb.add_argument("--chunk-overlap", type=int, default=100, dest="chunk_overlap",
                        help="Chunk overlap in tokens (default: 100)")

    # gc — delete expired rows (ADR-0015)
    gc_p = kb_sub.add_parser(
        "gc",
        help="Delete expired reflection rows (expires_at < now()). "
             "Use --purge-expert to also delete all expert_knowledge rows. (ADR-0015)",
    )
    gc_p.add_argument(
        "--purge-expert",
        action="store_true",
        dest="purge_expert",
        help="Also delete all rows WHERE category = 'expert_knowledge'",
    )

    # list-experts — audit + filter expert_knowledge entries (R87 Phase 1.5)
    list_e = kb_sub.add_parser(
        "list-experts",
        help="List expert_knowledge entries (R87 Phase 1.5) with optional "
             "--source / --scope filters",
    )
    list_e.add_argument(
        "--source",
        choices=["shipped", "user"],
        help="Show only entries from this source (default: all)",
    )
    list_e.add_argument(
        "--scope",
        help="Show only entries with this scope (e.g. ops-lab, shared:ops, org)",
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

    # 2026-05-15 (dev_docs/79): enterprise lifecycle commands ──────────
    rm = kb_sub.add_parser(
        "remove",
        help="Remove a usage_guide by intent — writes tombstone YAML + "
             "kb_audit row + deletes LanceDB row.  Requires --reason.",
    )
    rm.add_argument("intent", help="Guide intent (e.g. netbox_sync_defaults)")
    rm.add_argument("--agent", default=None,
                    help="Disambiguate if multiple agents declare the same intent")
    rm.add_argument("--reason", default=None, required=False,
                    help="Free-form reason for the removal (required unless "
                         "OLAV_KB_REMOVE_ALLOW_NO_REASON=1)")
    rm.add_argument("--keep-yaml", action="store_true", dest="keep_yaml",
                    help="Don't rename source YAML to .removed; only evict "
                         "LanceDB row (use when re-priming after edit)")
    rm.add_argument("--workspace", default=".olav/workspace",
                    help="Workspace root (default: .olav/workspace)")

    sh = kb_sub.add_parser(
        "show",
        help="Print the YAML source of a usage_guide (for promotion / inspection)",
    )
    sh.add_argument("intent", help="Guide intent to show")
    sh.add_argument("--agent", default=None, help="Disambiguate by agent")
    sh.add_argument("--workspace", default=".olav/workspace",
                    help="Workspace root (default: .olav/workspace)")

    lg = kb_sub.add_parser(
        "list-guides",
        help="Table of active usage_guide entries with source_tier",
    )
    lg.add_argument("--tier", default=None,
                    choices=["vendor", "platform", "team", "user"],
                    help="Filter by source_tier")
    lg.add_argument("--agent", default=None, help="Filter by agent")
    lg.add_argument("--workspace", default=".olav/workspace",
                    help="Workspace root (default: .olav/workspace)")

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
    elif kb_cmd == "import-kb":
        return cmd_import_kb(args)
    elif kb_cmd == "gc":
        return cmd_gc(args)
    elif kb_cmd == "list-experts":
        return cmd_list_experts(args)
    elif kb_cmd == "graph":
        return cmd_graph(args)
    elif kb_cmd == "migrate":
        return cmd_migrate(args)
    elif kb_cmd == "search":
        return cmd_search(args)
    elif kb_cmd == "backfill-tags":
        return cmd_backfill_tags(args)
    elif kb_cmd == "remove":
        return cmd_remove(args)
    elif kb_cmd == "show":
        return cmd_show(args)
    elif kb_cmd == "list-guides":
        return cmd_list_guides(args)
    else:
        print(f"Unknown kb subcommand: {kb_cmd}", file=sys.stderr)
        return 1
