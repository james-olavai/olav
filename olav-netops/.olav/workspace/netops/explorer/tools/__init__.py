"""Tools exposed to the explorer sub-agent.

Three thin ``@tool`` wrappers around ``olav.core.explorer.scratchpad`` —
no business logic here.  The library is in the platform package so
non-agent consumers (CLI, tests) can re-use it.
"""
from __future__ import annotations
