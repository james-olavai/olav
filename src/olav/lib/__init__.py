"""OLAV v0.10.0 Platform-Agnostic Utilities

This package contains utilities that work across different platforms:
- OLAV CLI (.olav/)
- Claude Code (.claude/)
- Gemini Agent (.gemini/)
"""

from olav.lib.data_gateway import DataGateway, get_gateway

__all__ = ["DataGateway", "get_gateway"]
