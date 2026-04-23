#!/usr/bin/env python3
"""
OLAV UDP Syslog Receiver — Lightweight Python implementation.

Features:
  - Listens on UDP 5514 (configurable), receives RFC 3164 / RFC 5424 syslog messages
  - Parses timestamp / host / severity / facility / message fields
  - Writes to Parquet in batches (every N records OR every N seconds)
  - Path: .olav/databases/logs/YYYY-MM-DD/syslog-HH.parquet

Usage:
  # Via OLAV service manager (recommended)
  olav service logs start

  # Direct invocation (foreground)
  uv run python -m olav.services.syslog_receiver

  # With custom port
  uv run python -m olav.services.syslog_receiver --port 514 --flush-interval 30
"""

import asyncio
import logging
import os
import re
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from olav.core.config import LOG_STORAGE_DIR

    LOG_DIR = Path(LOG_STORAGE_DIR)
except Exception:
    # Fallback: resolve relative to project root
    _here = Path(__file__).resolve()
    _root = next((p for p in _here.parents if (p / "pyproject.toml").exists()), Path.cwd())
    LOG_DIR = _root / ".olav" / "databases" / "logs"

_root_for_pid = next(
    (p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()),
    Path.cwd(),
)
PID_FILE = _root_for_pid / ".olav" / "run" / "syslog_receiver.pid"

UDP_HOST = "0.0.0.0"
UDP_PORT = int(os.environ.get("OLAV_SYSLOG_PORT", 5514))
BATCH_SIZE = int(os.environ.get("OLAV_SYSLOG_BATCH_SIZE", 100))
FLUSH_INTERVAL = int(os.environ.get("OLAV_SYSLOG_FLUSH_INTERVAL", 60))  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("olav.syslog_receiver")

# ── Syslog priority maps ──────────────────────────────────────────────────────
SEVERITY_MAP = {
    0: "EMERGENCY",
    1: "ALERT",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG",
}

FACILITY_MAP = {
    0: "kern",
    1: "user",
    2: "mail",
    3: "daemon",
    4: "auth",
    5: "syslog",
    6: "lpr",
    7: "news",
    8: "uucp",
    9: "cron",
    10: "security",
    11: "ftp",
    12: "ntp",
    13: "audit",
    14: "alert",
    15: "clock",
    16: "local0",
    17: "local1",
    18: "local2",
    19: "local3",
    20: "local4",
    21: "local5",
    22: "local6",
    23: "local7",
}

# RFC 3164: <PRI>TIMESTAMP HOST TAG: MSG
_RE_RFC3164 = re.compile(
    r"^<(\d{1,3})>"
    r"(?:(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+)?"
    r"(?:(\S+)\s+)?"
    r"(.*)$",
    re.DOTALL,
)

# RFC 5424: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID SD MSG
_RE_RFC5424 = re.compile(
    r"^<(\d{1,3})>(\d)\s+"
    r"(\S+)\s+"
    r"(\S+)\s+"
    r"(\S+)\s+"
    r"(\S+)\s+"
    r"(\S+)\s+"
    r"(?:\[.*?\]|-)\s*"
    r"(.*)?$",
    re.DOTALL,
)


def parse_syslog(raw: bytes, source_ip: str) -> dict[str, Any]:
    """Parse a syslog datagram, return a structured dict."""
    try:
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        text = raw.decode("latin-1", errors="replace").strip()

    now_iso = datetime.now(UTC).isoformat()
    base: dict[str, Any] = {
        "timestamp": now_iso,
        "host": source_ip,
        "severity": "INFO",
        "facility": "user",
        "message": text,
        "raw": text,
    }

    m5 = _RE_RFC5424.match(text)
    if m5:
        pri = int(m5.group(1))
        ts_str = m5.group(3)
        hostname = m5.group(4)
        msg = (m5.group(8) or "").strip()
        base.update(
            {
                "timestamp": ts_str if ts_str != "-" else now_iso,
                "host": hostname if hostname != "-" else source_ip,
                "severity": SEVERITY_MAP.get(pri & 0x07, "INFO"),
                "facility": FACILITY_MAP.get(pri >> 3, "user"),
                "message": msg or text,
            }
        )
        return base

    m3 = _RE_RFC3164.match(text)
    if m3:
        pri = int(m3.group(1))
        ts_raw = m3.group(2)
        hostname = m3.group(3)
        msg = m3.group(4) or text

        parsed_ts = now_iso
        if ts_raw:
            try:
                year = datetime.now(UTC).year
                t = datetime.strptime(f"{year} {ts_raw}", "%Y %b %d %H:%M:%S")
                parsed_ts = t.replace(tzinfo=UTC).isoformat()
            except ValueError:
                pass

        base.update(
            {
                "timestamp": parsed_ts,
                "host": hostname or source_ip,
                "severity": SEVERITY_MAP.get(pri & 0x07, "INFO"),
                "facility": FACILITY_MAP.get(pri >> 3, "user"),
                "message": msg.strip(),
            }
        )
        return base

    return base


# ── Parquet writer ────────────────────────────────────────────────────────────


def _parquet_path() -> Path:
    # UTC-partitioned so operators browsing log archives get consistent dirs
    # regardless of the host's local offset.
    now = datetime.now(UTC)
    day_dir = LOG_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"syslog-{now.strftime('%H')}.parquet"


def _write_parquet(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        schema = pa.schema(
            [
                pa.field("timestamp", pa.string()),
                pa.field("host", pa.string()),
                pa.field("severity", pa.string()),
                pa.field("facility", pa.string()),
                pa.field("message", pa.string()),
                pa.field("raw", pa.string()),
            ]
        )

        new_table = pa.Table.from_pylist(records, schema=schema)
        parquet_path = _parquet_path()

        if parquet_path.exists():
            existing = pq.read_table(str(parquet_path))
            combined = pa.concat_tables([existing, new_table])
        else:
            combined = new_table

        pq.write_table(combined, str(parquet_path), compression="snappy")
        logger.info(
            "Flushed %d records → %s (total rows=%d)",
            len(records),
            parquet_path.name,
            combined.num_rows,
        )
    except Exception as e:
        logger.error("Parquet write failed: %s", e, exc_info=True)


# ── AsyncIO UDP protocol ──────────────────────────────────────────────────────


class SyslogUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, buffer: list, stats: dict) -> None:
        self._buffer = buffer
        self._stats = stats

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        parsed = parse_syslog(data, addr[0])
        self._buffer.append(parsed)
        self._stats["received"] += 1


# ── Main receiver loop ────────────────────────────────────────────────────────


async def run_receiver(
    host: str = UDP_HOST,
    port: int = UDP_PORT,
    batch_size: int = BATCH_SIZE,
    flush_interval: int = FLUSH_INTERVAL,
) -> None:
    """Run the UDP syslog receiver. Can be called directly or via asyncio.run()."""
    loop = asyncio.get_running_loop()
    buffer: list[dict] = []
    stats = {"received": 0, "flushed": 0}

    import socket as _socket

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    transport, _ = await loop.create_datagram_endpoint(
        lambda: SyslogUDPProtocol(buffer, stats),
        sock=sock,
    )
    logger.info("OLAV Syslog Receiver listening on UDP %s:%d", host, port)
    logger.info("Log storage: %s", LOG_DIR)
    logger.info("Batch size: %d  Flush interval: %ds", batch_size, flush_interval)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    last_flush = time.monotonic()

    try:
        while True:
            await asyncio.sleep(1)
            elapsed = time.monotonic() - last_flush
            if (len(buffer) >= batch_size or elapsed >= flush_interval) and buffer:
                batch = buffer[:]
                buffer.clear()
                _write_parquet(batch)
                stats["flushed"] += len(batch)
                last_flush = time.monotonic()
    except asyncio.CancelledError:
        if buffer:
            logger.info("Final flush: %d records", len(buffer))
            _write_parquet(buffer)
    finally:
        transport.close()
        if PID_FILE.exists():
            PID_FILE.unlink()
        logger.info("Stopped. Total received=%d flushed=%d", stats["received"], stats["flushed"])


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="OLAV UDP Syslog Receiver")
    parser.add_argument("--host", default=UDP_HOST)
    parser.add_argument("--port", type=int, default=UDP_PORT)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--flush-interval", type=int, default=FLUSH_INTERVAL)
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(
        run_receiver(args.host, args.port, args.batch_size, args.flush_interval)
    )
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)

    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
