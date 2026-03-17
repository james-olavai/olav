"""Audit-to-Training-Dataset Export Pipeline (Phase 1-4).

Reads from ``audit.duckdb``, applies 3-layer redaction, gate checks,
quality scoring, and exports SFT JSONL, tool trajectory JSONL, and ATIF trace JSONL.

Design doc: ``dev_docs/audit_dataset_export.md``
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from olav.core.audit_recorder import _REDACT_PATTERNS, redact_sensitive
from olav.enterprise.dataset_encryption import (
    DatasetEncryptor,
    atomic_write,
    build_associated_data,
)

# ---------------------------------------------------------------------------
# Optional netutils (network interface canonicalisation)
# ---------------------------------------------------------------------------
try:
    from netutils.interface import canonical_interface_name as _canonical_interface_name
except ImportError:  # pragma: no cover
    _canonical_interface_name = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:/(\d{1,2}))?\b")

# Cisco-style interface names (Gi0/1, TenGigE0/0/0/0, etc.)
_CISCO_IF_RE = re.compile(
    r"\b((?:Gi|Fa|Te|Hu|Eth|Lo|Vl|Po|Tu|Se|TenGigE|GigabitEthernet|FastEthernet"
    r"|TenGigabitEthernet|HundredGigE|Loopback|Vlan|Port-channel|Tunnel|Serial)"
    r"[\d/.:]+)\b"
)

# Juniper-style interface names (ge-0/0/0, xe-0/0/0.100, etc.)
_JUNOS_IF_RE = re.compile(r"\b((?:ge|xe|et|lo|ae|irb|em|fxp)-\d+/\d+/\d+(?:\.\d+)?)\b")

# Arista EOS-style (Ethernet1/1, etc.) — overlaps partly with Cisco
_EOS_IF_RE = re.compile(r"\b(Ethernet\d+(?:/\d+)*)\b")

# Network hostname heuristic: >=2 hyphen-separated segments, starts with letter
_HOSTNAME_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9]*(?:-[a-zA-Z0-9]+){1,})\b")

# ---------------------------------------------------------------------------
# Presidio / scrubadub hook (optional enhancement layer)
# ---------------------------------------------------------------------------
_presidio_hook: Callable[[str], str] | None = None


def register_presidio_hook(fn: Callable[[str], str] | None) -> None:
    global _presidio_hook
    _presidio_hook = fn


def _apply_presidio_hook(text: str) -> str:
    if _presidio_hook is not None:
        return _presidio_hook(text)
    return text


# =========================================================================
# 1. Run Rebuild
# =========================================================================


def rebuild_run_timeline(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
) -> dict[str, Any]:
    """Rebuild a single run's full timeline from the audit tables.

    Returns a dict with keys:
        run_id, metadata, messages, tool_calls, events
    """
    # --- Run metadata ---
    row = conn.execute(
        """
        SELECT run_id, start_time, end_time, status, agent_id,
               session_id, thread_id, user_id, source_channel
        FROM audit_runs
        WHERE run_id = ?
        """,
        [run_id],
    ).fetchone()

    if row is None:
        return {
            "run_id": run_id,
            "metadata": {},
            "messages": [],
            "tool_calls": [],
            "events": [],
        }

    cols_run = [
        "run_id",
        "start_time",
        "end_time",
        "status",
        "agent_id",
        "session_id",
        "thread_id",
        "user_id",
        "source_channel",
    ]
    metadata = dict(zip(cols_run, row, strict=True))

    # --- Messages (ordered by sequence_no) ---
    msg_rows = conn.execute(
        """
        SELECT message_id, run_id, timestamp, sequence_no, role, content, tool_call_id
        FROM audit_messages
        WHERE run_id = ?
        ORDER BY COALESCE(sequence_no, 0) ASC, timestamp ASC
        """,
        [run_id],
    ).fetchall()
    msg_cols = [
        "message_id",
        "run_id",
        "timestamp",
        "sequence_no",
        "role",
        "content",
        "tool_call_id",
    ]
    messages = [dict(zip(msg_cols, r, strict=True)) for r in msg_rows]

    # --- Tool calls ---
    tc_rows = conn.execute(
        """
        SELECT call_id, run_id, timestamp, tool_name, input_args,
               output, status, error, duration_ms
        FROM audit_tool_calls
        WHERE run_id = ?
        ORDER BY timestamp ASC
        """,
        [run_id],
    ).fetchall()
    tc_cols = [
        "call_id",
        "run_id",
        "timestamp",
        "tool_name",
        "input_args",
        "output",
        "status",
        "error",
        "duration_ms",
    ]
    tool_calls = [dict(zip(tc_cols, r, strict=True)) for r in tc_rows]

    # --- Events ---
    ev_rows = conn.execute(
        """
        SELECT event_id, event_type, timestamp, sequence_no, run_id,
               session_id, agent_id, payload, redaction
        FROM audit_events
        WHERE run_id = ?
        ORDER BY COALESCE(sequence_no, 0) ASC, timestamp ASC
        """,
        [run_id],
    ).fetchall()
    ev_cols = [
        "event_id",
        "event_type",
        "timestamp",
        "sequence_no",
        "run_id",
        "session_id",
        "agent_id",
        "payload",
        "redaction",
    ]
    events = [dict(zip(ev_cols, r, strict=True)) for r in ev_rows]

    return {
        "run_id": run_id,
        "metadata": metadata,
        "messages": messages,
        "tool_calls": tool_calls,
        "events": events,
    }


# =========================================================================
# 2. Network Object Anonymiser
# =========================================================================


def _generate_hmac_token(secret_key: bytes, value: str) -> str:
    """HMAC-SHA256 digest (first 8 hex chars) for stable anonymisation."""
    return hmac.new(secret_key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]


def _classify_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Return a short classification tag for an IP address."""
    if isinstance(addr, ipaddress.IPv6Address):
        return "v6"
    # RFC 5737 documentation ranges
    _doc_nets = [
        ipaddress.IPv4Network("192.0.2.0/24"),
        ipaddress.IPv4Network("198.51.100.0/24"),
        ipaddress.IPv4Network("203.0.113.0/24"),
    ]
    for net in _doc_nets:
        if addr in net:
            return "doc_v4"
    if addr.is_private:
        return "priv_v4"
    return "pub_v4"


def _classify_prefix(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> str:
    """Return a short classification tag for a network prefix."""
    if isinstance(network, ipaddress.IPv6Network):
        return "v6"
    _doc_nets = [
        ipaddress.IPv4Network("192.0.2.0/24"),
        ipaddress.IPv4Network("198.51.100.0/24"),
        ipaddress.IPv4Network("203.0.113.0/24"),
    ]
    for net in _doc_nets:
        if network.subnet_of(net) or network.supernet_of(net) or network.overlaps(net):
            return "doc_v4"
    if network.is_private:
        return "priv_v4"
    return "pub_v4"


def _detect_interface_platform(interface_name: str) -> str:
    """Guess the vendor platform from an interface name."""
    lower = interface_name.lower()
    if _JUNOS_IF_RE.match(interface_name):
        return "junos"
    # Arista uses plain "EthernetN" without Gi/Fa prefix
    if lower.startswith("ethernet") and not lower.startswith("etherchannel"):
        return "eos"
    # Default to cisco for Gi/Fa/Te/etc.
    return "cisco"


class NetworkObjectAnonymizer:
    """Stable, HMAC-based anonymiser for network objects.

    Within a single export, the same raw value always maps to the same
    anonymised token.
    """

    def __init__(self, secret_key: bytes | None = None) -> None:
        self._secret = secret_key or os.urandom(32)
        self._mapping: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    # -- helpers ----------------------------------------------------------

    def _next_counter(self, prefix: str) -> int:
        self._counters.setdefault(prefix, 0)
        self._counters[prefix] += 1
        return self._counters[prefix]

    def _get_or_create(self, raw_value: str, prefix: str) -> str:
        """Return cached token or generate a new stable one."""
        if raw_value in self._mapping:
            return self._mapping[raw_value]
        n = self._next_counter(prefix)
        token = f"{prefix}_{n:03d}"
        self._mapping[raw_value] = token
        return token

    # -- public API -------------------------------------------------------

    def anonymize_ip(self, ip_str: str) -> str:
        """Anonymise a single IP address string."""
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return ip_str
        cls = _classify_ip(addr)
        prefix = f"ip_{cls}"
        return self._get_or_create(ip_str, prefix)

    def anonymize_prefix(self, prefix_str: str) -> str:
        """Anonymise a CIDR prefix string."""
        try:
            net = ipaddress.ip_network(prefix_str, strict=False)
        except ValueError:
            return prefix_str
        cls = _classify_prefix(net)
        tag = f"pfx_{cls}"
        return self._get_or_create(prefix_str, tag)

    def anonymize_interface(self, if_name: str) -> str:
        """Anonymise an interface name."""
        platform = _detect_interface_platform(if_name)
        prefix = f"if_{platform}"
        return self._get_or_create(if_name, prefix)

    def anonymize_hostname(self, hostname: str) -> str:
        """Anonymise a network hostname."""
        return self._get_or_create(hostname, "host")

    def save_mapping(self, path: str | Path) -> None:
        """Persist mapping + counters to JSON for cross-export consistency."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"mapping": self._mapping, "counters": self._counters}
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_mapping(self, path: str | Path) -> None:
        """Restore mapping + counters from a previous export. No-op if missing."""
        p = Path(path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self._mapping.update(data.get("mapping", {}))
            for k, v in data.get("counters", {}).items():
                self._counters[k] = max(self._counters.get(k, 0), v)
        except (json.JSONDecodeError, OSError):
            return

    def anonymize_text(self, text: str) -> str:
        """Find and replace all network objects in free text."""
        if not text:
            return text

        # --- Pass 1: IP addresses and prefixes ---
        def _replace_ip(m: re.Match[str]) -> str:
            ip_part = m.group(1)
            prefix_part = m.group(2)
            try:
                ipaddress.ip_address(ip_part)
            except ValueError:
                return m.group(0)
            if prefix_part is not None:
                return self.anonymize_prefix(f"{ip_part}/{prefix_part}")
            return self.anonymize_ip(ip_part)

        text = _IP_RE.sub(_replace_ip, text)

        # --- Pass 2: interface names ---
        for pattern in (_JUNOS_IF_RE, _CISCO_IF_RE, _EOS_IF_RE):
            text = pattern.sub(lambda m: self.anonymize_interface(m.group(1)), text)

        # --- Pass 3: hostnames ---
        text = _HOSTNAME_RE.sub(lambda m: self.anonymize_hostname(m.group(1)), text)

        return text


# =========================================================================
# 3. Redaction Pipeline
# =========================================================================


def redact_audit_run(
    timeline: dict[str, Any],
    anonymizer: NetworkObjectAnonymizer | None = None,
) -> dict[str, Any]:
    """Apply the 3-layer redaction pipeline to a rebuilt run timeline.

    Layer 1: Credential-level redaction (``redact_sensitive``).
    Layer 2: Network object anonymisation (IPs, prefixes, interfaces, hostnames).
    Layer 3: Config-block marking (Phase 1 stub — detection only).

    Returns a **new** dict (shallow copy of top-level keys) with
    ``redaction_metadata`` added.
    """
    if anonymizer is None:
        anonymizer = NetworkObjectAnonymizer()

    result = dict(timeline)
    fields_redacted: list[str] = []
    network_objects_hashed: list[str] = []
    config_blocks_masked = 0

    def _redact_text(text: str | None) -> str | None:
        if text is None:
            return None
        # Layer 1
        out = redact_sensitive(text)
        if out != text:
            fields_redacted.append("credential")
        # Layer 2
        out2 = anonymizer.anonymize_text(out)
        if out2 != out:
            network_objects_hashed.append("network_object")
        out3 = _apply_presidio_hook(out2)
        return out3

    # --- Messages ---
    new_messages = []
    for msg in timeline.get("messages", []):
        m = dict(msg)
        m["content"] = _redact_text(m.get("content"))
        new_messages.append(m)
    result["messages"] = new_messages

    # --- Tool calls ---
    new_tc = []
    for tc in timeline.get("tool_calls", []):
        t = dict(tc)
        t["input_args"] = _redact_text(t.get("input_args"))
        t["output"] = _redact_text(t.get("output"))
        new_tc.append(t)
    result["tool_calls"] = new_tc

    # --- Events ---
    new_ev = []
    for ev in timeline.get("events", []):
        e = dict(ev)
        e["payload"] = _redact_text(e.get("payload"))
        new_ev.append(e)
    result["events"] = new_ev

    # Layer 3: count config blocks across messages, tool_calls, and events
    _config_kw = re.compile(
        r"(?m)^\s*(?:interface|router|neighbor|ip route|access-list|policy-map|route-map)\b"
    )
    for msg in new_messages:
        content = msg.get("content") or ""
        if _config_kw.search(content):
            config_blocks_masked += 1
    for tc in new_tc:
        for field in ("input_args", "output"):
            text = tc.get(field) or ""
            if _config_kw.search(text):
                config_blocks_masked += 1
    for ev in new_ev:
        payload = ev.get("payload") or ""
        if _config_kw.search(payload):
            config_blocks_masked += 1

    result["redaction_metadata"] = {
        "applied": True,
        "policy_version": "audit-redaction-v1",
        "fields_redacted": list(set(fields_redacted)),
        "network_objects_hashed": list(set(network_objects_hashed)),
        "config_blocks_masked": config_blocks_masked,
    }
    return result


# =========================================================================
# 4. Gate Checks
# =========================================================================


def gate_check(redacted_timeline: dict[str, Any]) -> tuple[bool, list[str]]:
    """Verify that a redacted run timeline is safe for export.

    Returns ``(passed, reasons)`` where *reasons* lists failures.
    """
    reasons: list[str] = []

    # Check 1: redaction applied?
    rmeta = redacted_timeline.get("redaction_metadata")
    if not rmeta or not rmeta.get("applied"):
        reasons.append("redaction_not_applied")

    # Gather all text content to scan
    all_text: list[str] = []
    for msg in redacted_timeline.get("messages", []):
        if msg.get("content"):
            all_text.append(msg["content"])
    for tc in redacted_timeline.get("tool_calls", []):
        for field in ("input_args", "output"):
            if tc.get(field):
                all_text.append(tc[field])
    for ev in redacted_timeline.get("events", []):
        if ev.get("payload"):
            all_text.append(ev["payload"])

    combined = "\n".join(all_text)

    # Check 2: plaintext credentials?
    for pattern in _REDACT_PATTERNS:
        # We look for the pattern but ensure the value part is NOT [REDACTED]
        for m in pattern.finditer(combined):
            full_match = m.group(0)
            if "[REDACTED]" not in full_match:
                reasons.append("plaintext_credential_detected")
                break

    # Check 3: raw IPv4 still present?
    # We look for bare IPs that are NOT already anonymised tokens
    _anon_prefixes = ("ip_", "pfx_", "if_", "host_")
    for m in _IP_RE.finditer(combined):
        ip_str = m.group(1)
        try:
            ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        # Check surrounding context — if preceded by an anon prefix, skip
        start = max(0, m.start() - 10)
        context = combined[start : m.start()]
        if any(context.endswith(p) for p in _anon_prefixes):
            continue
        reasons.append("raw_ip_address_detected")
        break

    passed = len(reasons) == 0
    return passed, reasons


# =========================================================================
# 5. Export Encryption Helper
# =========================================================================


def _encrypt_export_file(
    plaintext_path: Path,
    encryptor: DatasetEncryptor,
    associated_data: bytes,
    remove_plaintext: bool = True,
) -> Path:
    plaintext_bytes = plaintext_path.read_bytes()
    ciphertext = encryptor.encrypt_bytes(plaintext_bytes, associated_data)
    enc_path = plaintext_path.with_suffix(plaintext_path.suffix + ".enc")
    atomic_write(enc_path, ciphertext)
    if remove_plaintext:
        plaintext_path.unlink()
    return enc_path


def _build_encryption_manifest(
    applied: bool,
    key_ref: str | None = None,
) -> dict[str, Any]:
    if applied:
        return {
            "applied": True,
            "mode": "required",
            "provider": "tink",
            "primitive": "aead",
            "key_ref": key_ref,
        }
    return {
        "applied": False,
        "mode": "disabled",
        "provider": None,
        "primitive": None,
        "key_ref": None,
    }


# =========================================================================
# 5b. SFT JSONL Export
# =========================================================================


def audit_to_sft_jsonl(
    conn_or_path: duckdb.DuckDBPyConnection | str | Path | None = None,
    output_dir: str | Path = "exports/audit_datasets/default",
    *,
    hours: int = 24,
    secret_key: bytes | None = None,
    min_rule_score: float = 0.0,
    encrypt: bool | None = None,
    key_ref: str | None = None,
    keyset_dir: Path | None = None,
) -> dict[str, Any]:
    """Export completed audit runs as SFT JSONL training data.

    Parameters
    ----------
    conn_or_path:
        DuckDB connection, path to ``audit.duckdb``, or ``None`` (uses default).
    output_dir:
        Directory to write ``sft.jsonl``, ``manifest.json``, etc.
    hours:
        Look-back window in hours.
    secret_key:
        Optional HMAC key for stable anonymisation across exports.

    Returns
    -------
    dict
        Export statistics.
    """
    # --- Resolve connection ---
    own_conn = False
    if conn_or_path is None:
        from olav.core.config import AUDIT_DB_PATH

        conn = duckdb.connect(str(AUDIT_DB_PATH), read_only=True)
        own_conn = True
        source_db = str(AUDIT_DB_PATH)
    elif isinstance(conn_or_path, str | Path):
        conn = duckdb.connect(str(conn_or_path), read_only=True)
        own_conn = True
        source_db = str(conn_or_path)
    else:
        conn = conn_or_path
        source_db = "in-memory"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    anonymizer = NetworkObjectAnonymizer(secret_key=secret_key)

    try:
        # --- Scan runs in window ---
        run_rows = conn.execute(
            """
            SELECT run_id, status
            FROM audit_runs
            WHERE start_time >= now() - INTERVAL (?) HOUR
            ORDER BY start_time DESC
            """,
            [hours],
        ).fetchall()

        runs_scanned = len(run_rows)
        completed_run_ids = [r[0] for r in run_rows if r[1] == "completed"]
        runs_after_filter = len(completed_run_ids)

        exported_samples: list[dict[str, Any]] = []
        rejected_runs: list[dict[str, Any]] = []

        for run_id in completed_run_ids:
            timeline = rebuild_run_timeline(conn, run_id)
            redacted = redact_audit_run(timeline, anonymizer=anonymizer)
            passed, reasons = gate_check(redacted)

            if not passed:
                rejected_runs.append({"run_id": run_id, "reasons": reasons})
                continue

            # Build SFT sample: only system/user/assistant messages
            sft_messages = []
            for msg in redacted["messages"]:
                role = msg.get("role", "")
                if role in ("system", "user", "assistant"):
                    sft_messages.append(
                        {
                            "role": role,
                            "content": msg.get("content", ""),
                        }
                    )

            if not sft_messages:
                rejected_runs.append({"run_id": run_id, "reasons": ["no_exportable_messages"]})
                continue

            meta = redacted.get("metadata", {})
            sample = {
                "messages": sft_messages,
                "metadata": {
                    "run_id": run_id,
                    "agent_id": meta.get("agent_id"),
                    "source_channel": meta.get("source_channel"),
                    "status": meta.get("status", "completed"),
                    "redaction_policy": "audit-redaction-v1",
                },
            }

            score_result = compute_quality_score(sample)
            gate_passed, gate_reason = quality_gate(score_result, min_rule_score=min_rule_score)
            if not gate_passed:
                rejected_runs.append(
                    {"run_id": run_id, "reasons": [f"quality_gate: {gate_reason}"]}
                )
                continue

            sample["metadata"]["rule_score"] = score_result["rule_score"]
            sample["metadata"]["score_components"] = score_result["score_components"]
            if score_result["llm_score"] is not None:
                sample["metadata"]["llm_score"] = score_result["llm_score"]
                sample["metadata"]["quality_labels"] = score_result["quality_labels"]

            exported_samples.append(sample)

        # --- Write sft.jsonl ---
        sft_path = output_path / "sft.jsonl"
        with sft_path.open("w", encoding="utf-8") as f:
            for sample in exported_samples:
                f.write(json.dumps(sample, ensure_ascii=False, default=str) + "\n")

        encryption_applied = False
        effective_key_ref = key_ref or "dataset-export-key-v1"
        if encrypt:
            encryptor = DatasetEncryptor(keyset_dir=keyset_dir)
            encryptor.load_keyset(effective_key_ref)
            ad = build_associated_data(
                export_id=output_path.name,
                format_name="sft",
                dedup_strategy="none",
                scoring_policy="dataset-score-v1",
            )
            _encrypt_export_file(sft_path, encryptor, ad)
            encryption_applied = True

        # --- Write rejected_runs.json ---
        rejected_path = output_path / "rejected_runs.json"
        with rejected_path.open("w", encoding="utf-8") as f:
            json.dump(rejected_runs, f, indent=2, ensure_ascii=False, default=str)

        # --- Build stats ---
        runs_exported = len(exported_samples)
        runs_rejected = len(rejected_runs)
        avg_messages = (
            sum(len(s["messages"]) for s in exported_samples) / runs_exported
            if runs_exported > 0
            else 0.0
        )

        rule_scores = [s["metadata"]["rule_score"] for s in exported_samples]
        avg_rule = sum(rule_scores) / len(rule_scores) if rule_scores else 0.0

        rejected_reasons: dict[str, int] = {}
        for r in rejected_runs:
            for reason in r.get("reasons", []):
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1

        scoring_policy = {
            "min_rule_score": min_rule_score,
            "llm_scoring": _llm_scorer_fn is not None,
            "weights": dict(_RULE_WEIGHTS),
        }

        stats = {
            "runs_scanned": runs_scanned,
            "runs_after_filter": runs_after_filter,
            "runs_exported": runs_exported,
            "runs_rejected": runs_rejected,
            "samples_exported": runs_exported,
            "samples_scored": runs_after_filter,
            "avg_messages_per_sample": round(avg_messages, 2),
            "avg_rule_score": round(avg_rule, 4),
            "avg_quality_score": round(avg_rule, 4),
            "scoring_policy": scoring_policy,
            "rejected_by_reason": rejected_reasons,
        }

        stats_path = output_path / "stats.json"
        with stats_path.open("w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

        # --- Build manifest ---
        export_id = output_path.name
        now = datetime.now(UTC)
        manifest = {
            "export_id": export_id,
            "source_db": source_db,
            "window": {
                "hours": hours,
                "exported_at": now.isoformat(),
            },
            "redaction_policy": "audit-redaction-v1",
            "encryption": _build_encryption_manifest(encryption_applied, effective_key_ref),
            "formats": ["sft"],
            "runs_scanned": runs_scanned,
            "runs_after_filter": runs_after_filter,
            "runs_exported": runs_exported,
            "runs_rejected": runs_rejected,
            "scoring_policy": scoring_policy,
        }

        manifest_path = output_path / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)

        return stats

    finally:
        if own_conn:
            conn.close()


# =========================================================================
# 8. ATIF / Harbor Trace Export
# =========================================================================


def _build_atif_spans(
    timeline: dict[str, Any],
) -> list[dict[str, Any]]:
    messages = timeline.get("messages", [])
    tool_calls = timeline.get("tool_calls", [])

    spans: list[dict[str, Any]] = []
    tc_queue = list(tool_calls)
    tc_idx = 0

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            spans.append({"name": "user_input", "type": "message", "content": content})
        elif role == "tool":
            if tc_idx < len(tc_queue):
                tc = tc_queue[tc_idx]
                spans.append(
                    {
                        "name": "tool_call",
                        "type": "tool",
                        "tool": tc.get("tool_name", "unknown"),
                        "input": tc.get("input_args") or {},
                    }
                )
                spans.append({"name": "tool_result", "type": "tool_result", "output": content})
                tc_idx += 1
            else:
                spans.append({"name": "tool_result", "type": "tool_result", "output": content})
        elif role == "assistant":
            spans.append({"name": "assistant_output", "type": "message", "content": content})

    # Emit any remaining tool_calls that had no matching tool message
    for tc in tc_queue[tc_idx:]:
        spans.append(
            {
                "name": "tool_call",
                "type": "tool",
                "tool": tc.get("tool_name", "unknown"),
                "input": tc.get("input_args") or {},
            }
        )

    return spans


def audit_to_atif(
    conn_or_path: duckdb.DuckDBPyConnection | str | Path | None = None,
    output_dir: str | Path = "exports/audit_datasets/default",
    *,
    hours: int = 24,
    secret_key: bytes | None = None,
    encrypt: bool | None = None,
    key_ref: str | None = None,
    keyset_dir: Path | None = None,
) -> dict[str, Any]:
    own_conn = False
    if conn_or_path is None:
        from olav.core.config import AUDIT_DB_PATH

        conn = duckdb.connect(str(AUDIT_DB_PATH), read_only=True)
        own_conn = True
        source_db = str(AUDIT_DB_PATH)
    elif isinstance(conn_or_path, str | Path):
        conn = duckdb.connect(str(conn_or_path), read_only=True)
        own_conn = True
        source_db = str(conn_or_path)
    else:
        conn = conn_or_path
        source_db = "in-memory"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    anonymizer = NetworkObjectAnonymizer(secret_key=secret_key)

    try:
        run_rows = conn.execute(
            """
            SELECT run_id, status
            FROM audit_runs
            WHERE start_time >= now() - INTERVAL (?) HOUR
            ORDER BY start_time DESC
            """,
            [hours],
        ).fetchall()

        runs_scanned = len(run_rows)
        completed_run_ids = [r[0] for r in run_rows if r[1] == "completed"]
        runs_after_filter = len(completed_run_ids)

        exported_samples: list[dict[str, Any]] = []
        rejected_runs: list[dict[str, Any]] = []

        for run_id in completed_run_ids:
            timeline = rebuild_run_timeline(conn, run_id)
            redacted = redact_audit_run(timeline, anonymizer=anonymizer)
            passed, reasons = gate_check(redacted)

            if not passed:
                rejected_runs.append({"run_id": run_id, "reasons": reasons})
                continue

            spans = _build_atif_spans(redacted)

            if not spans:
                rejected_runs.append({"run_id": run_id, "reasons": ["empty_spans"]})
                continue

            meta = redacted.get("metadata", {})
            sample = {
                "trace_id": str(uuid.uuid4()),
                "spans": spans,
                "metadata": {
                    "run_id": run_id,
                    "agent_id": meta.get("agent_id"),
                    "task_type": "trace_analysis",
                    "domain_tags": ["trace"],
                    "redaction_policy": "audit-redaction-v1",
                },
            }
            exported_samples.append(sample)

        atif_path = output_path / "atif.jsonl"
        with atif_path.open("w", encoding="utf-8") as f:
            for sample in exported_samples:
                f.write(json.dumps(sample, ensure_ascii=False, default=str) + "\n")

        encryption_applied = False
        effective_key_ref = key_ref or "dataset-export-key-v1"
        if encrypt:
            encryptor = DatasetEncryptor(keyset_dir=keyset_dir)
            encryptor.load_keyset(effective_key_ref)
            ad = build_associated_data(
                export_id=output_path.name,
                format_name="atif",
                dedup_strategy="none",
                scoring_policy="none",
            )
            _encrypt_export_file(atif_path, encryptor, ad)
            encryption_applied = True

        rejected_path = output_path / "rejected_runs.json"
        with rejected_path.open("w", encoding="utf-8") as f:
            json.dump(rejected_runs, f, indent=2, ensure_ascii=False, default=str)

        runs_exported = len(exported_samples)
        runs_rejected = len(rejected_runs)

        stats = {
            "runs_scanned": runs_scanned,
            "runs_after_filter": runs_after_filter,
            "runs_exported": runs_exported,
            "runs_rejected": runs_rejected,
            "samples_exported": runs_exported,
        }

        stats_path = output_path / "stats.json"
        with stats_path.open("w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

        export_id = output_path.name
        now = datetime.now(UTC)
        manifest = {
            "export_id": export_id,
            "source_db": source_db,
            "window": {
                "hours": hours,
                "exported_at": now.isoformat(),
            },
            "redaction_policy": "audit-redaction-v1",
            "encryption": _build_encryption_manifest(encryption_applied, effective_key_ref),
            "formats": ["atif"],
            "runs_scanned": runs_scanned,
            "runs_after_filter": runs_after_filter,
            "runs_exported": runs_exported,
            "runs_rejected": runs_rejected,
        }

        manifest_path = output_path / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)

        return stats

    finally:
        if own_conn:
            conn.close()


# =========================================================================
# 6. Dedup Fingerprint
# =========================================================================


def _compute_dedup_fingerprint(
    instruction: str,
    tool_sequence: list[str],
    final_answer: str,
    task_type: str = "tool_selection",
) -> str:
    """SHA-256 fingerprint for dedup within an export window.

    Normalises inputs (whitespace collapse, lowercase, tool sort) so that
    semantically identical trajectories produce the same digest.
    """
    _ws = re.compile(r"\s+")

    def _norm(text: str) -> str:
        return _ws.sub(" ", text.strip().lower())

    parts = [
        task_type,
        _norm(instruction),
        ",".join(sorted(tool_sequence)),
        _norm(final_answer),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# =========================================================================
# 7. Tool Trajectory Export
# =========================================================================


def _build_trajectory_steps(
    timeline: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Build trajectory step list from a redacted timeline.

    Returns ``(steps, is_valid)`` where *is_valid* is ``False`` when
    tool calls are missing results or the sequence is broken.
    """
    messages = timeline.get("messages", [])
    tool_calls = timeline.get("tool_calls", [])

    steps: list[dict[str, Any]] = []
    is_valid = True

    # Index tool calls by call_id for matching
    tc_by_id: dict[str, dict[str, Any]] = {}
    for tc in tool_calls:
        cid = tc.get("call_id") or tc.get("tool_name", "")
        tc_by_id[cid] = tc

    # Also build a simple list of tool calls in order for sequential matching
    tc_queue = list(tool_calls)
    tc_idx = 0

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            continue  # instruction is extracted separately
        elif role == "tool":
            # This is a tool result — find matching tool call
            if tc_idx < len(tc_queue):
                tc = tc_queue[tc_idx]
                steps.append(
                    {
                        "type": "tool_call",
                        "tool": tc.get("tool_name", "unknown"),
                        "args": tc.get("input_args") or {},
                    }
                )
                steps.append({"type": "tool_result", "content": content})
                tc_idx += 1
            else:
                # tool result without matching call
                steps.append({"type": "tool_result", "content": content})
                is_valid = False
        elif role == "assistant":
            steps.append({"type": "assistant_reasoning", "content": content})

    # Check for unmatched tool calls (call without result)
    if tc_idx < len(tc_queue):
        for tc in tc_queue[tc_idx:]:
            if tc.get("status") != "completed":
                is_valid = False
                break
            steps.append(
                {
                    "type": "tool_call",
                    "tool": tc.get("tool_name", "unknown"),
                    "args": tc.get("input_args") or {},
                }
            )
            is_valid = False

    # Relabel last assistant step as assistant_final
    for i in range(len(steps) - 1, -1, -1):
        if steps[i]["type"] == "assistant_reasoning":
            steps[i] = {"type": "assistant_final", "content": steps[i]["content"]}
            break

    return steps, is_valid


def _has_hitl_reject(timeline: dict[str, Any]) -> bool:
    for ev in timeline.get("events", []):
        payload = ev.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(payload, dict) and payload.get("hitl_decision") == "reject":
            return True
        if ev.get("event_type") == "hitl_reject":
            return True
    return False


def audit_to_tool_trajectory(
    conn_or_path: duckdb.DuckDBPyConnection | str | Path | None = None,
    output_dir: str | Path = "exports/audit_datasets/default",
    *,
    hours: int = 24,
    secret_key: bytes | None = None,
    min_rule_score: float = 0.0,
    encrypt: bool | None = None,
    key_ref: str | None = None,
    keyset_dir: Path | None = None,
) -> dict[str, Any]:
    """Export completed audit runs as tool-use trajectory JSONL.

    Parameters
    ----------
    conn_or_path:
        DuckDB connection, path to ``audit.duckdb``, or ``None`` (uses default).
    output_dir:
        Directory to write ``trajectory.jsonl``, ``manifest.json``, etc.
    hours:
        Look-back window in hours.
    secret_key:
        Optional HMAC key for stable anonymisation across exports.

    Returns
    -------
    dict
        Export statistics.
    """
    own_conn = False
    if conn_or_path is None:
        from olav.core.config import AUDIT_DB_PATH

        conn = duckdb.connect(str(AUDIT_DB_PATH), read_only=True)
        own_conn = True
        source_db = str(AUDIT_DB_PATH)
    elif isinstance(conn_or_path, str | Path):
        conn = duckdb.connect(str(conn_or_path), read_only=True)
        own_conn = True
        source_db = str(conn_or_path)
    else:
        conn = conn_or_path
        source_db = "in-memory"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    anonymizer = NetworkObjectAnonymizer(secret_key=secret_key)

    try:
        run_rows = conn.execute(
            """
            SELECT run_id, status
            FROM audit_runs
            WHERE start_time >= now() - INTERVAL (?) HOUR
            ORDER BY start_time DESC
            """,
            [hours],
        ).fetchall()

        runs_scanned = len(run_rows)
        completed_run_ids = [r[0] for r in run_rows if r[1] == "completed"]
        runs_after_filter = len(completed_run_ids)

        candidates: list[dict[str, Any]] = []
        rejected_runs: list[dict[str, Any]] = []

        for run_id in completed_run_ids:
            timeline = rebuild_run_timeline(conn, run_id)
            redacted = redact_audit_run(timeline, anonymizer=anonymizer)
            passed, reasons = gate_check(redacted)

            if not passed:
                rejected_runs.append({"run_id": run_id, "reasons": reasons})
                continue

            # Check HITL rejection
            if _has_hitl_reject(redacted):
                rejected_runs.append({"run_id": run_id, "reasons": ["hitl_rejected"]})
                continue

            # Extract instruction from first user message
            instruction = ""
            for msg in redacted["messages"]:
                if msg.get("role") == "user":
                    instruction = msg.get("content", "")
                    break

            if not instruction:
                rejected_runs.append({"run_id": run_id, "reasons": ["no_user_instruction"]})
                continue

            # Build trajectory steps
            steps, is_valid = _build_trajectory_steps(redacted)

            if not steps:
                rejected_runs.append({"run_id": run_id, "reasons": ["empty_trajectory"]})
                continue

            # Extract final answer for fingerprint
            final_answer = ""
            for step in reversed(steps):
                if step["type"] == "assistant_final":
                    final_answer = step.get("content", "")
                    break

            # Extract tool sequence for fingerprint
            tool_seq = [s["tool"] for s in steps if s["type"] == "tool_call"]

            fingerprint = _compute_dedup_fingerprint(
                instruction=instruction,
                tool_sequence=tool_seq,
                final_answer=final_answer,
            )

            meta = redacted.get("metadata", {})
            sample = {
                "instruction": instruction,
                "trajectory": steps,
                "metadata": {
                    "run_id": run_id,
                    "agent_id": meta.get("agent_id"),
                    "task_type": "tool_selection",
                    "domain_tags": ["tool_use"],
                    "requires_tool": bool(tool_seq),
                    "redaction_policy": "audit-redaction-v1",
                    "dedup_fingerprint": fingerprint,
                    "dedup_strategy": "exact_v1",
                    "invalid_trajectory": not is_valid,
                },
            }

            if not is_valid:
                rejected_runs.append(
                    {
                        "run_id": run_id,
                        "reasons": ["invalid_trajectory"],
                    }
                )
                continue

            score_result = compute_quality_score(sample)
            gate_passed, gate_reason = quality_gate(score_result, min_rule_score=min_rule_score)
            if not gate_passed:
                rejected_runs.append(
                    {"run_id": run_id, "reasons": [f"quality_gate: {gate_reason}"]}
                )
                continue

            sample["metadata"]["rule_score"] = score_result["rule_score"]
            sample["metadata"]["score_components"] = score_result["score_components"]
            if score_result["llm_score"] is not None:
                sample["metadata"]["llm_score"] = score_result["llm_score"]
                sample["metadata"]["quality_labels"] = score_result["quality_labels"]

            candidates.append(sample)

        # --- Dedup: keep latest per fingerprint ---
        seen_fingerprints: dict[str, int] = {}
        deduped: list[dict[str, Any]] = []
        for sample in candidates:
            fp = sample["metadata"]["dedup_fingerprint"]
            if fp not in seen_fingerprints:
                seen_fingerprints[fp] = len(deduped)
                deduped.append(sample)
            else:
                # Keep the later one (current), replace earlier
                deduped[seen_fingerprints[fp]] = sample

        exported_samples = deduped

        # --- Write trajectory.jsonl ---
        traj_path = output_path / "trajectory.jsonl"
        with traj_path.open("w", encoding="utf-8") as f:
            for sample in exported_samples:
                f.write(json.dumps(sample, ensure_ascii=False, default=str) + "\n")

        encryption_applied = False
        effective_key_ref = key_ref or "dataset-export-key-v1"
        if encrypt:
            encryptor = DatasetEncryptor(keyset_dir=keyset_dir)
            encryptor.load_keyset(effective_key_ref)
            ad = build_associated_data(
                export_id=output_path.name,
                format_name="trajectory",
                dedup_strategy="exact_v1",
                scoring_policy="dataset-score-v1",
            )
            _encrypt_export_file(traj_path, encryptor, ad)
            encryption_applied = True

        # --- Write rejected_runs.json ---
        rejected_path = output_path / "rejected_runs.json"
        with rejected_path.open("w", encoding="utf-8") as f:
            json.dump(rejected_runs, f, indent=2, ensure_ascii=False, default=str)

        # --- Build stats ---
        runs_exported = len(exported_samples)
        runs_rejected = len(rejected_runs)
        runs_deduped = len(candidates) - runs_exported
        avg_steps = (
            sum(len(s["trajectory"]) for s in exported_samples) / runs_exported
            if runs_exported > 0
            else 0.0
        )

        rule_scores = [s["metadata"]["rule_score"] for s in exported_samples]
        avg_rule = sum(rule_scores) / len(rule_scores) if rule_scores else 0.0

        rejected_reasons: dict[str, int] = {}
        for r in rejected_runs:
            for reason in r.get("reasons", []):
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1

        scoring_policy = {
            "min_rule_score": min_rule_score,
            "llm_scoring": _llm_scorer_fn is not None,
            "weights": dict(_RULE_WEIGHTS),
        }

        stats = {
            "runs_scanned": runs_scanned,
            "runs_after_filter": runs_after_filter,
            "runs_exported": runs_exported,
            "runs_rejected": runs_rejected,
            "runs_deduped": runs_deduped,
            "samples_exported": runs_exported,
            "samples_scored": runs_after_filter,
            "avg_steps_per_trajectory": round(avg_steps, 2),
            "avg_rule_score": round(avg_rule, 4),
            "avg_quality_score": round(avg_rule, 4),
            "scoring_policy": scoring_policy,
            "rejected_by_reason": rejected_reasons,
        }

        stats_path = output_path / "stats.json"
        with stats_path.open("w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

        # --- Build manifest ---
        export_id = output_path.name
        now = datetime.now(UTC)
        manifest = {
            "export_id": export_id,
            "source_db": source_db,
            "window": {
                "hours": hours,
                "exported_at": now.isoformat(),
            },
            "redaction_policy": "audit-redaction-v1",
            "encryption": _build_encryption_manifest(encryption_applied, effective_key_ref),
            "formats": ["trajectory"],
            "runs_scanned": runs_scanned,
            "runs_after_filter": runs_after_filter,
            "runs_exported": runs_exported,
            "runs_rejected": runs_rejected,
            "runs_deduped": runs_deduped,
            "scoring_policy": scoring_policy,
        }

        manifest_path = output_path / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)

        return stats

    finally:
        if own_conn:
            conn.close()


# =========================================================================
# 9. Quality Scoring (Phase 4)
# =========================================================================

_TEMPLATE_PATTERNS = re.compile(
    r"(?:i don't have enough information|i cannot|i'm sorry|"
    r"i am unable|no data available|please provide|"
    r"i need more context|unfortunately)",
    re.IGNORECASE,
)

_FAILURE_PATTERNS = re.compile(
    r"(?:error occurred|failed to|could not|exception|traceback|"
    r"no results found|empty result|timed? ?out)",
    re.IGNORECASE,
)

HARD_REJECT_LABELS = frozenset(
    {
        "hallucination",
        "unresolved_failure",
        "low_signal_template",
        "unsafe_sensitive_pattern",
    }
)

_llm_scorer_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def register_llm_scorer(fn: Callable[[dict[str, Any]], dict[str, Any]] | None) -> None:
    global _llm_scorer_fn  # noqa: PLW0603
    _llm_scorer_fn = fn


def _extract_user_text(sample: dict[str, Any]) -> str:
    if "instruction" in sample:
        return sample["instruction"]
    for msg in sample.get("messages", []):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _extract_assistant_text(sample: dict[str, Any]) -> str:
    if "trajectory" in sample:
        for step in reversed(sample["trajectory"]):
            if step.get("type") == "assistant_final":
                return step.get("content", "")
        for step in reversed(sample["trajectory"]):
            if step.get("type") == "assistant_reasoning":
                return step.get("content", "")
        return ""
    for msg in reversed(sample.get("messages", [])):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return ""


def _extract_tool_results(sample: dict[str, Any]) -> list[str]:
    results: list[str] = []
    if "trajectory" in sample:
        for step in sample["trajectory"]:
            if step.get("type") == "tool_result":
                results.append(step.get("content", ""))
    else:
        for msg in sample.get("messages", []):
            if msg.get("role") == "tool":
                results.append(msg.get("content", ""))
    return results


def _score_completeness(user_text: str, assistant_text: str, sample: dict[str, Any]) -> float:
    if not user_text.strip():
        return 0.0
    score = 0.4
    if assistant_text.strip():
        score += 0.4
    has_tool = bool(sample.get("trajectory")) or any(
        m.get("role") == "tool" for m in sample.get("messages", [])
    )
    if has_tool:
        tool_results = _extract_tool_results(sample)
        if tool_results:
            score += 0.2
    else:
        score += 0.2
    return min(score, 1.0)


def _score_query_specificity(user_text: str) -> float:
    text = user_text.strip()
    if not text:
        return 0.0
    word_count = len(text.split())
    if word_count <= 1:
        return 0.1
    if word_count <= 3:
        return 0.3
    has_entity = bool(
        re.search(
            r"[A-Z][a-z]+-?\d|router|switch|device|interface|bgp|ospf|vlan", text, re.IGNORECASE
        )
    )
    has_action = bool(
        re.search(
            r"\b(?:show|list|find|get|check|display|query|count|compare|diff)\b",
            text,
            re.IGNORECASE,
        )
    )
    base = 0.5
    if has_entity:
        base += 0.25
    if has_action:
        base += 0.25
    return min(base, 1.0)


def _score_analysis_value(assistant_text: str) -> float:
    text = assistant_text.strip()
    if not text:
        return 0.0
    if _TEMPLATE_PATTERNS.search(text):
        return 0.2
    if _FAILURE_PATTERNS.search(text):
        return 0.1
    word_count = len(text.split())
    if word_count < 5:
        return 0.3
    base = 0.6
    has_data = bool(re.search(r"\d+", text))
    has_specifics = bool(re.search(r"(?:ip_|pfx_|host_|AS\d|Gi\d|Established|up|down)", text))
    if has_data:
        base += 0.2
    if has_specifics:
        base += 0.2
    return min(base, 1.0)


def _score_tool_consistency(assistant_text: str, tool_results: list[str]) -> float:
    if not tool_results:
        return 1.0
    if not assistant_text.strip():
        return 0.0
    combined_tools = " ".join(tool_results).lower()
    assistant_lower = assistant_text.lower()

    _token_re = re.compile(r"[a-z0-9][a-z0-9/._-]*[a-z0-9]|[a-z0-9]+")
    tool_tokens = set(_token_re.findall(combined_tools))
    assistant_tokens = set(_token_re.findall(assistant_lower))
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "not",
        "it",
        "this",
        "that",
        "with",
    }
    tool_tokens -= stopwords
    assistant_tokens -= stopwords

    if not tool_tokens:
        return 0.5

    overlap = tool_tokens & assistant_tokens
    ratio = len(overlap) / len(tool_tokens)

    numbers_in_tools = set(re.findall(r"\d+", combined_tools))
    numbers_in_answer = set(re.findall(r"\d+", assistant_lower))
    if numbers_in_tools and not (numbers_in_tools & numbers_in_answer):
        ratio *= 0.5

    return min(max(ratio, 0.0), 1.0)


_RULE_WEIGHTS = {
    "completeness": 0.25,
    "tool_consistency": 0.25,
    "query_specificity": 0.25,
    "analysis_value": 0.25,
}


def compute_rule_score(sample: dict[str, Any]) -> dict[str, Any]:
    user_text = _extract_user_text(sample)
    assistant_text = _extract_assistant_text(sample)
    tool_results = _extract_tool_results(sample)

    components = {
        "completeness": float(_score_completeness(user_text, assistant_text, sample)),
        "tool_consistency": float(_score_tool_consistency(assistant_text, tool_results)),
        "query_specificity": float(_score_query_specificity(user_text)),
        "analysis_value": float(_score_analysis_value(assistant_text)),
    }

    rule_score = sum(components[k] * _RULE_WEIGHTS[k] for k in components)
    return {
        "score_components": components,
        "rule_score": float(round(rule_score, 4)),
    }


def compute_quality_score(
    sample: dict[str, Any],
    *,
    rule_weight: float = 0.6,
    llm_weight: float = 0.4,
) -> dict[str, Any]:
    rule_result = compute_rule_score(sample)
    rule_score = rule_result["rule_score"]
    components = rule_result["score_components"]

    llm_score: float | None = None
    llm_reason: str | None = None
    quality_labels: list[str] = []
    hard_reject = False

    if _llm_scorer_fn is not None:
        try:
            llm_result = _llm_scorer_fn(sample)
            llm_score = llm_result.get("llm_score")
            llm_reason = llm_result.get("llm_reason")
            quality_labels = llm_result.get("quality_labels", [])
        except Exception:
            llm_score = None
            llm_reason = None
            quality_labels = []

    if any(label in HARD_REJECT_LABELS for label in quality_labels):
        hard_reject = True

    if llm_score is not None:
        quality_score = rule_weight * rule_score + llm_weight * llm_score
    else:
        quality_score = rule_score

    return {
        "rule_score": rule_score,
        "score_components": components,
        "llm_score": llm_score,
        "llm_reason": llm_reason,
        "quality_labels": quality_labels,
        "hard_reject": hard_reject,
        "quality_score": float(round(quality_score, 4)),
    }


def quality_gate(
    score_result: dict[str, Any],
    *,
    min_rule_score: float = 0.3,
    min_quality_score: float | None = None,
) -> tuple[bool, str | None]:
    if score_result.get("hard_reject"):
        return False, "hard_reject"

    if score_result["rule_score"] < min_rule_score:
        return False, f"rule_score {score_result['rule_score']:.2f} < {min_rule_score}"

    if min_quality_score is not None and score_result.get("llm_score") is not None:
        if score_result["quality_score"] < min_quality_score:
            return False, f"quality_score {score_result['quality_score']:.2f} < {min_quality_score}"

    return True, None
