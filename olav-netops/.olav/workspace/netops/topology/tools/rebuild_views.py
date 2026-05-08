"""rebuild_views — thin wrapper around view_builder.

ARCH-29: callable from agent (interactive refresh) or pipeline
(netops_init Stage 3.7, take_snapshot post-hook). Pure SQL, zero LLM.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
def rebuild_views(concept: str | None = None) -> dict[str, Any]:
    """Rebuild topology SQL views from the current ``view_recipes`` table.

    Args:
        concept: Optional filter — rebuild only the view for this concept
            (``bgp_neighbors``, ``ospf_neighbors``, ``topology_l2``, or
            a user-added custom concept). ``None`` rebuilds all.

    Returns:
        ``{view_name: row_count, ...}``. Pure SQL, no LLM calls.
    """
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    from olav_netops.core.view_builder import build_all_views, build_one_view

    con = duckdb.connect(str(MAIN_DB_PATH))
    try:
        if concept is None:
            counts = build_all_views(con)
        else:
            counts = build_one_view(con, concept)
        return {"status": "ok", "views": counts}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        con.close()
