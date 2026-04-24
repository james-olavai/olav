"""OLAV Daemon — persistent agent process for fast query responses.

Eliminates 3–5s startup overhead per `uv run olav` invocation.
The daemon initializes OLAVAgent once and handles queries via Unix socket.

Usage:
    olav daemon start    # Start daemon in background
    olav daemon stop     # Stop daemon gracefully
    olav daemon status   # Show running/stopped + stats
    olav daemon restart  # Stop then start

Protocol (newline-delimited JSON):
    Request:  {"query": "...", "thread_id": "optional-uuid"}
    Response: {"status": "success"|"error", "response": "...", "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def _runtime_dir() -> Path:
    """Resolve ``.olav/run/`` against the *current* workspace root.

    Pre-rc4 these were module-level ``Path("....")`` constants —
    relative paths interpreted against whatever cwd the daemon
    happened to inherit.  When the parent process's cwd diverged
    from the workspace root (issue #12), the daemon's PID file
    landed in a different workspace than the CLI was looking in,
    so ``stop_daemon`` and ``get_daemon_status`` could never see it.
    """
    from olav.cli.commands.services._paths import find_workspace_root
    return find_workspace_root() / ".olav" / "run"


def _socket_path() -> Path:
    return _runtime_dir() / "daemon.sock"


def _pid_file() -> Path:
    return _runtime_dir() / "daemon.pid"


def _stats_file() -> Path:
    return _runtime_dir() / "daemon.stats.json"


# ============================================================================
# Daemon Server
# ============================================================================


class DaemonServer:
    """Unix socket server that wraps OLAVAgent for persistent, fast queries."""

    def __init__(self) -> None:
        """Initialize daemon server state."""
        self._agent: object | None = None
        self._start_time: float = time.time()
        self._query_count: int = 0
        self._socket_path: Path = _socket_path()
        self._server: asyncio.AbstractServer | None = None

    async def _ensure_agent(self) -> object:
        """Lazily initialise OLAVAgent (called once on first query)."""
        if self._agent is None:
            from olav.agents.agent import create_olav_agent

            logger.info("Daemon: initializing OLAVAgent…")
            self._agent = create_olav_agent(enable_checkpointer=False)
            logger.info("Daemon: OLAVAgent ready.")
        return self._agent

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection (one query per connection)."""
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not raw:
                return
            request = json.loads(raw.decode())
            query: str = request.get("query", "")
            thread_id: str | None = request.get("thread_id")

            if not query:
                response = {"status": "error", "message": "Empty query"}
            else:
                agent = await self._ensure_agent()
                result = await agent.invoke(query, thread_id=thread_id)  # type: ignore[union-attr]
                self._query_count += 1
                self._write_stats()
                response = {
                    "status": result.get("status", "success"),
                    "response": result.get("response", ""),
                    "message": result.get("message", ""),
                }

        except TimeoutError:
            response = {"status": "error", "message": "Request read timeout"}
        except Exception as e:
            logger.exception("Daemon: error handling query")
            response = {"status": "error", "message": str(e)}

        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    def _write_stats(self) -> None:
        """Write stats to disk for `olav daemon status`."""
        try:
            _stats_file().write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "start_time": self._start_time,
                        "query_count": self._query_count,
                        "uptime_seconds": int(time.time() - self._start_time),
                    }
                )
            )
        except Exception:
            pass

    async def _run_time_decay_loop(
        self, stop_event: asyncio.Event, interval_hours: float = 24.0
    ) -> None:
        """Run apply_time_decay() every interval_hours until stop_event is set."""
        interval_secs = interval_hours * 3600
        # Wait one full interval before first run so startup is not delayed
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_secs)
            return  # stop_event fired before first decay run
        except asyncio.TimeoutError:
            pass

        while not stop_event.is_set():
            try:
                from olav.core.memory import get_store
                from olav.core.memory.middleware import apply_time_decay

                store = get_store()
                apply_time_decay(store)
                logger.info("Daemon: time-decay applied.")
            except Exception as e:
                logger.warning("Daemon: time-decay failed (non-fatal): %s", e)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_secs)
                return
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        """Start the Unix socket server and block until SIGTERM/SIGINT."""
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale socket
        if self._socket_path.exists():
            self._socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self._socket_path),
        )

        # Write PID file
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _pid_file().write_text(str(os.getpid()))
        self._write_stats()

        logger.info("Daemon started: socket=%s pid=%d", self._socket_path, os.getpid())

        # Pre-warm agent immediately so first query is instant
        await self._ensure_agent()
        self._write_stats()

        # Block until shutdown signal
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _shutdown(signum: int, frame: object) -> None:
            loop.call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        # Start background time-decay task (runs every 24h, non-fatal)
        decay_task = asyncio.create_task(self._run_time_decay_loop(stop_event))

        async with self._server:
            await stop_event.wait()

        decay_task.cancel()
        try:
            await decay_task
        except asyncio.CancelledError:
            pass

        # Cleanup
        if self._socket_path.exists():
            self._socket_path.unlink()
        if _pid_file().exists():
            _pid_file().unlink()
        if _stats_file().exists():
            _stats_file().unlink()
        logger.info("Daemon stopped.")


def start_daemon() -> None:
    """Entry point: start the daemon server (called from subprocess)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = DaemonServer()
    asyncio.run(server.run())


# ============================================================================
# Client helpers (called from cli_app.py)
# ============================================================================


async def query_daemon(
    query: str,
    thread_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, str] | None:
    """Send a query to the running daemon. Returns response dict or None if daemon not available.

    Args:
        query: Natural language query string.
        thread_id: Optional session thread ID for conversation continuity.
        timeout: Maximum seconds to wait for response.

    Returns:
        Response dict with 'status' and 'response' keys, or None if daemon is unavailable.
    """
    socket_path = str(_socket_path())
    if not Path(socket_path).exists():
        return None

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path),
            timeout=2.0,  # fast: daemon should respond in <100ms
        )
        request = json.dumps({"query": query, "thread_id": thread_id}) + "\n"
        writer.write(request.encode())
        await writer.drain()

        raw = await asyncio.wait_for(reader.readline(), timeout=timeout)
        writer.close()
        await writer.wait_closed()

        return json.loads(raw.decode())
    except Exception:
        return None


def get_daemon_status() -> dict[str, object]:
    """Return daemon status dict for `olav daemon status`.

    Returns:
        Dict with 'running', 'pid', 'uptime_seconds', 'query_count' fields.
    """
    if not _pid_file().exists():
        return {"running": False}

    try:
        pid = int(_pid_file().read_text().strip())
        # Check process is alive
        os.kill(pid, 0)
    except (ValueError, ProcessLookupError, PermissionError):
        return {"running": False}

    stats: dict[str, object] = {"running": True, "pid": pid}
    if _stats_file().exists():
        try:
            stats.update(json.loads(_stats_file().read_text()))
        except Exception:
            pass
    return stats


def spawn_daemon() -> int:
    """Fork a daemon process in the background.

    Returns:
        PID of spawned daemon process.
    """
    import subprocess

    from olav.cli.commands.services._paths import find_workspace_root

    # Pin the daemon's cwd so its socket / PID file land in the workspace
    # the user actually invoked olav from, not whatever cwd the CLI
    # process happened to inherit.  See gitea #12.
    proc = subprocess.Popen(
        [sys.executable, "-m", "olav.cli.daemon"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(find_workspace_root()),
    )
    return proc.pid


def stop_daemon() -> bool:
    """Send SIGTERM to daemon.

    Returns:
        True if daemon was running and signal sent, False if not running.
    """
    if not _pid_file().exists():
        return False
    try:
        pid = int(_pid_file().read_text().strip())
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


# Allow running as: python -m olav.cli.daemon
if __name__ == "__main__":
    start_daemon()
