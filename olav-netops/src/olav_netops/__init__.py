"""olav-netops — OLAV Network Operations domain package.

Provides:
- Network-specific DuckDB table declarations (BaseIngestTable subclasses)
- ``olav-netops`` CLI binary (init, snapshot, etc.)
- NETOPS-ONLY config extensions (NORNIR_CONFIG_PATH, TextFSM paths, etc.)

Installation::

    pip install olav-netops
    olav-netops init   # injects netops workspace + bootstraps TextFSM templates
"""

__version__ = "0.11.0"
