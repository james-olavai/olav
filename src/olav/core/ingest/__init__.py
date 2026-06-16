"""Portable snapshot ingest — accepts pre-collected raw output bundles.

Design: ``dev_docs/76. PORTABLE_SNAPSHOT_INGEST.md``.

Public API surface (P1):
  * ``schema``         — Pydantic models for the bundle contract
  * ``bundle_reader``  — discover layout, iterate (host, command, body)
  * ``validators``     — content sha256 + manifest sanity (no DB touch)
  * ``landing``        — end-to-end driver: bundle → raw_output_store → views
"""
from __future__ import annotations
