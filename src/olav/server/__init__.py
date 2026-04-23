"""Server-mode glue for OLAV — LangGraph graph factory, config helpers.

This package exists so ``langgraph dev`` / ``langgraph up`` / LangSmith
Studio / (starting v0.20.2) deepagents-cli's server-subprocess mode
can build an OLAV-flavoured compiled graph from outside OLAV's
in-process TUI path.

Phase 5 (v0.20.0) introduces :mod:`olav.server.graph_factory` as the
first and only module.  Later phases add a tool loader and an
entry-point driven agent registry under the same package.
"""
