"""Tools exposed to the ingest sub-agent.

Both are thin ``@tool`` wrappers around ``olav.core.ingest.*`` library
functions — no business logic here.  The library lives in the platform
package so non-agent consumers (CLI, tests, future olav-collector) can
re-use it without depending on a workspace.
"""
from __future__ import annotations
