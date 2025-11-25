"""OLAV LangServe API Server.

This module provides the FastAPI + LangServe server for remote orchestrator access.
"""

from .app import create_app

__all__ = ["create_app"]
