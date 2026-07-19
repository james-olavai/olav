"""``batfish_q`` — generic Batfish question runner (dev_docs/73 §2.1).

A single @tool that:

  1. Lazy-initialises a netops snapshot into the Batfish service
     (configs exported via :func:`olav_netops.export.batfish.export_configs`
     are loaded via ``bf.init_snapshot``).
  2. Caches loaded snapshots in a module-level ``_LOADED_SNAPSHOTS`` set
     so repeat queries against the same snapshot pay the init cost only
     once.
  3. Dispatches to ``bf.q.<question>(**args).answer()`` and converts
     the resulting pandas DataFrame to a JSON-friendly ``list[dict]``.
  4. Optionally runs differential queries when ``reference_snapshot``
     is provided.

Returned envelope::

    {
      "status": "ok" | "error",
      "rows":   list[dict] | None,    # row data
      "row_count": int,
      "snapshot_id": "<the snapshot used>",
      "reference_snapshot": "<if differential>" | None,
      "message": "<error detail when status=error>",
    }

Connection settings come from env vars (see ``_get_session``):

  * ``OLAV_BATFISH_HOST``    (default ``localhost``)
  * ``OLAV_BATFISH_HTTP_PORT`` (default ``9996``)
  * ``OLAV_BATFISH_SSL``      (``true`` / ``false``; default ``false``)
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema for Batfish PacketHeaderConstraints
# ---------------------------------------------------------------------------
#
# Phase E root cause (2026-05-14): LLMs naturally pass list values for
# ``dstIps`` / ``srcIps`` because they look like the polymorphic
# ``nodes`` field.  But Batfish's PacketHeaderConstraints expects
# strings — the specifier syntax accepts comma-separated values.  A
# list raises an unhelpful 500.  This model normalises the types
# before the call.

class PacketHeaderConstraintsArgs(BaseModel):
    """Strict schema for the ``headers`` arg of Batfish questions like
    ``reachability`` and ``traceroute``.

    Every field accepts ``str | list[str]`` and the validator coerces
    lists to Batfish's comma-separated specifier syntax.  Unknown
    fields raise a Pydantic ValidationError that ``batfish_q`` surfaces
    as a clean envelope message — far more useful than the Batfish 500.
    """

    model_config = ConfigDict(extra="forbid")

    dstIps: str | None = None
    srcIps: str | None = None
    applications: str | None = None
    ipProtocols: str | None = None
    dscps: str | None = None
    ecns: str | None = None
    srcPorts: str | None = None
    dstPorts: str | None = None
    icmpCodes: str | None = None
    icmpTypes: str | None = None
    packetLengths: str | None = None
    tcpFlags: str | None = None

    @field_validator(
        "dstIps", "srcIps", "applications", "ipProtocols", "dscps", "ecns",
        "srcPorts", "dstPorts", "icmpCodes", "icmpTypes", "packetLengths",
        "tcpFlags",
        mode="before",
    )
    @classmethod
    def _coerce_list_to_specifier(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, list):
            return ",".join(str(item) for item in v)
        return v


def _extract_caused_by_chain(exc: BaseException) -> str:
    """Pull the deepest ``Caused by:`` line out of a Batfish HTTPError.

    pybatfish raises ``requests.HTTPError`` for Batfish 500s; the
    response body usually contains the Java exception chain.  Returning
    the deepest cause gives the LLM the actionable schema error
    instead of a useless ``"HTTPError 500"`` string.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    body = getattr(response, "text", "") or ""
    causes = re.findall(r"Caused by: ([^\n]+)", body)
    if causes:
        # Deepest cause is the last "Caused by:" line.
        return causes[-1].strip()
    # No chain — try a one-line BatfishException summary if present.
    bf_line = re.search(r"(org\.batfish[^\n]+)", body)
    if bf_line:
        return bf_line.group(1).strip()
    return str(exc)


# ---------------------------------------------------------------------------
# Module-level session + snapshot cache
# ---------------------------------------------------------------------------
_BF_SESSION: Any = None         # cached pybatfish.Session
_LOADED_SNAPSHOTS: set[str] = set()


def _batfish_endpoint() -> tuple[str, int, bool]:
    """Resolve the Batfish endpoint: env var → api.json ``batfish`` block →
    default localhost:9996. Env wins so a shell override always applies; the
    config block is what the admin agent edits to point at a remote Batfish.
    """
    host = os.environ.get("OLAV_BATFISH_HOST")
    port = os.environ.get("OLAV_BATFISH_HTTP_PORT")
    ssl = os.environ.get("OLAV_BATFISH_SSL")
    if host is None or port is None or ssl is None:
        try:
            from olav.core.config import get_config
            # ConfigLoader.section() — the old `getattr(get_config(), "_data", {})`
            # read a nonexistent attr, so the api.json batfish block was dead
            # (env vars were the only working override).
            bf = get_config().section("batfish")
        except Exception:
            bf = {}
        host = host or bf.get("host") or "localhost"
        port = port or str(bf.get("port") or 9996)
        ssl = ssl if ssl is not None else str(bf.get("ssl", "false"))
    return host, int(port), str(ssl).lower() == "true"


def _batfish_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Cheap TCP probe — is a Batfish service actually listening?"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def batfish_setup_hint(host: str, port: int) -> str:
    """Actionable next steps when Batfish is not reachable (software-
    understands-human: name the fix, don't leak a stack trace).

    Container lifecycle is the **services** agent's job (deploy_service /
    docker-compose), so we route there rather than telling the user to run
    docker by hand. Remote-endpoint config is the admin agent's job.
    """
    return (
        f"Batfish is not running / not reachable at {host}:{port}. Config-layer "
        f"validation (subnet conflicts, protocol compatibility, reachability) "
        f"needs a Batfish service. Two ways to get one:\n"
        f"  1) Deploy it locally via the services agent (it owns containers):\n"
        f"     olav --agent services \"deploy the batfish/allinone container, "
        f"expose ports 9996 and 9997\"\n"
        f"  2) Point OLAV at an existing/remote Batfish — ask the admin agent to "
        f"set the `batfish` host in .olav/config/api.json, or export "
        f"OLAV_BATFISH_HOST.\n"
        f"(If pybatfish is missing, install the sim extra: pip install pybatfish.)\n"
        f"Then retry the validation."
    )


def _latest_snapshot_with_configs() -> str | None:
    """Latest snapshot that actually has running-config rows (so Batfish has
    something to load). Honours 'default to latest' while dodging an empty
    snapshot row that carries no device configs."""
    try:
        import duckdb
        from olav.core.config import MAIN_DB_PATH
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            row = conn.execute(
                "SELECT snapshot_id FROM netops.v_snapshots_auto "
                "WHERE snapshot_id IN ("
                "  SELECT DISTINCT snapshot_id FROM netops.raw_output_store "
                "  WHERE command = 'show running-config') "
                "ORDER BY captured_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not resolve latest snapshot: %s", exc)
        return None


def _get_session() -> Any:
    """Get or create the cached pybatfish.Session."""
    global _BF_SESSION
    if _BF_SESSION is None:
        from pybatfish.client.session import Session
        host, port, ssl = _batfish_endpoint()
        _BF_SESSION = Session(host=host, port_v2=port, ssl=ssl)
        logger.info(
            f"batfish_q: created pybatfish.Session(host={host}, port={port}, ssl={ssl})"
        )
    return _BF_SESSION


def _do_export_and_init(snapshot_id: str) -> str:
    """Export netops snapshot configs to Batfish-compatible layout +
    bf.init_snapshot.  Returns the on-disk configs directory path.

    Wrapped as its own function so tests can mock the heavy work.
    """
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    from olav_netops.export.batfish import export_configs

    conn = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    try:
        result = export_configs(conn, snapshot_id=snapshot_id)
    finally:
        conn.close()

    # The exporter writes ``configs/`` inside ``<out_base>``; Batfish
    # wants the parent dir that *contains* ``configs/``.
    out_base = Path(result["output_dir"])
    if not (out_base / "configs").is_dir():
        raise RuntimeError(
            f"batfish_q: export_configs for {snapshot_id} produced no "
            f"configs/ subdir at {out_base}"
        )

    bf = _get_session()
    bf.init_snapshot(str(out_base), name=snapshot_id, overwrite=True)
    logger.info(
        f"batfish_q: initialised Batfish snapshot {snapshot_id!r} "
        f"({result.get('config_count', 0)} configs from {out_base})"
    )
    return str(out_base)


def _init_snapshot_if_needed(snapshot_id: str) -> None:
    """Cache-aware snapshot init.  No-op if already loaded."""
    if snapshot_id in _LOADED_SNAPSHOTS:
        return
    _do_export_and_init(snapshot_id)
    _LOADED_SNAPSHOTS.add(snapshot_id)


# ---------------------------------------------------------------------------
# The @tool
# ---------------------------------------------------------------------------

@tool
def batfish_q(
    snapshot_id: str | None = None,
    question: str = "",
    q_args: dict | None = None,
    reference_snapshot: str | None = None,
) -> dict[str, Any]:
    """Run a Batfish question against a netops snapshot.

    Args:
        snapshot_id: netops snapshot identifier (e.g.
            ``snap_20260514_101701_156d60``).  Will be auto-loaded
            into Batfish on first use; cached thereafter.
        question: Batfish question name (e.g. ``bgpSessionStatus``,
            ``reachability``, ``routes``, ``differentialReachability``).
            See ``sim/guides/batfish_question_catalog.guide.yaml`` for
            the supported set + arg schemas.
        q_args: optional kwargs forwarded to ``bf.q.<question>(**q_args)``.
            Typical keys: ``nodes`` (regex), ``network`` (prefix),
            ``headers`` (HeaderConstraints).  (Parameter is named
            ``q_args`` rather than ``args`` because langchain @tool
            reserves the ``args`` kwarg for internal use.)
        reference_snapshot: optional baseline for differential
            queries (e.g. ``differentialReachability``).  When set,
            ``bf.set_reference_snapshot(<ref>)`` is called before
            ``bf.set_snapshot(<snapshot_id>)`` and the question runs
            in differential mode.

    Returns:
        Envelope ``{status, rows, row_count, snapshot_id,
        reference_snapshot, message}``.  ``status`` is ``"ok"`` on
        success or ``"error"`` with ``message`` populated.

    Example::

        batfish_q(
            snapshot_id="snap_20260514_101701_156d60",
            question="bgpSessionStatus",
            q_args={"nodes": "R1|R3"},
        )
        → {"status": "ok", "rows": [{"Node": "R1", ...}], "row_count": 1, ...}
    """
    args = dict(q_args) if q_args else {}

    # Default the snapshot to the latest one that actually has configs (so the
    # caller can just say "validate this" without hunting for a snapshot id;
    # 'latest' alone can be an empty snapshot row that carries no device data).
    if not snapshot_id:
        snapshot_id = _latest_snapshot_with_configs()
        if not snapshot_id:
            return {
                "status": "error",
                "message": (
                    "no ingested snapshot with device configs found — import or "
                    "collect a snapshot first (e.g. `olav --agent netops \"import …\"`)."
                ),
                "snapshot_id": None, "reference_snapshot": reference_snapshot,
                "rows": None, "row_count": 0,
            }

    # Fail fast + actionable when Batfish itself isn't running, instead of
    # leaking a pybatfish connection stack trace (software-understands-human).
    _host, _port, _ = _batfish_endpoint()
    if not _batfish_reachable(_host, _port):
        return {
            "status": "error",
            "message": batfish_setup_hint(_host, _port),
            "batfish_reachable": False,
            "snapshot_id": snapshot_id, "reference_snapshot": reference_snapshot,
            "rows": None, "row_count": 0,
        }

    # Phase E: validate + coerce headers via Pydantic so list-typed
    # dstIps/srcIps don't slip through and hit Batfish as 500.
    if isinstance(args.get("headers"), dict):
        try:
            normalised = PacketHeaderConstraintsArgs(**args["headers"])
        except Exception as exc:
            return {
                "status": "error",
                "message": f"invalid headers field(s): {exc}",
                "snapshot_id": snapshot_id,
                "reference_snapshot": reference_snapshot,
                "rows": None,
                "row_count": 0,
            }
        args["headers"] = normalised.model_dump(exclude_none=True)

    try:
        _init_snapshot_if_needed(snapshot_id)
        if reference_snapshot:
            _init_snapshot_if_needed(reference_snapshot)
    except Exception as exc:
        logger.warning(f"batfish_q: snapshot init failed for {snapshot_id}: {exc}")
        return {
            "status": "error",
            "message": f"snapshot init failed: {exc}",
            "snapshot_id": snapshot_id,
            "reference_snapshot": reference_snapshot,
            "rows": None,
            "row_count": 0,
        }

    bf = _get_session()
    try:
        if reference_snapshot:
            bf.set_reference_snapshot(reference_snapshot)
        bf.set_snapshot(snapshot_id)
    except Exception as exc:
        return {
            "status": "error",
            "message": f"set_snapshot failed: {exc}",
            "snapshot_id": snapshot_id,
            "reference_snapshot": reference_snapshot,
            "rows": None,
            "row_count": 0,
        }

    # Look up the question on bf.q
    question_fn = getattr(bf.q, question, None)
    if question_fn is None:
        return {
            "status": "error",
            "message": (
                f"unknown Batfish question {question!r}; see "
                f"sim/guides/batfish_question_catalog for valid names"
            ),
            "snapshot_id": snapshot_id,
            "reference_snapshot": reference_snapshot,
            "rows": None,
            "row_count": 0,
        }

    try:
        answer = question_fn(**args).answer()
        df = answer.frame()
        rows = df.to_dict("records") if df is not None else []
        # Batfish normalises hostnames to short (domain-stripped) form, so a
        # caller filtering nodes by FQDN ("alpha-border-4500x.net.demo.internal")
        # silently gets 0 rows even though the device is in the snapshot.
        # Coercion-layer fix (V2 §M3): on an empty result with dotted node
        # names, retry ONCE with the domains stripped. Regex specifiers pass
        # through untouched (no dots stripped inside /…/ forms).
        _nodes = args.get("nodes")
        if (not rows) and isinstance(_nodes, str) and "." in _nodes \
                and not _nodes.startswith("/"):
            _short = "|".join(
                part.split(".", 1)[0] for part in _nodes.split("|")
            )
            if _short != _nodes:
                retry_args = {**args, "nodes": _short}
                df2 = question_fn(**retry_args).answer().frame()
                rows = df2.to_dict("records") if df2 is not None else []
                if rows:
                    logger.info(
                        "batfish_q: nodes FQDN %r matched nothing; short form "
                        "%r matched %d row(s)", _nodes, _short, len(rows),
                    )
    except Exception as exc:
        # Phase E: dig the Caused-by chain out of HTTPError bodies so
        # the LLM sees the real schema error, not "HTTPError 500".
        cause = _extract_caused_by_chain(exc)
        return {
            "status": "error",
            "message": f"question {question!r} failed: {cause}",
            "snapshot_id": snapshot_id,
            "reference_snapshot": reference_snapshot,
            "rows": None,
            "row_count": 0,
        }

    return {
        "status": "ok",
        "rows": rows,
        "row_count": len(rows),
        "snapshot_id": snapshot_id,
        "reference_snapshot": reference_snapshot,
        "message": "",
    }
