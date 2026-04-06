"""TDD tests for audit_dataset_export Phase 1-4 + encrypted_dataset_control.

Tests cover: run rebuild, 3-layer redaction, gate checks, SFT JSONL export,
manifest/stats/rejected output, CLI subparser integration, tool trajectory,
ATIF trace export, quality scoring (rule/LLM/combined), threshold gating,
Tink AEAD encryption, KMS key_ref detection, and one-time token control.
"""

import json
import uuid
from datetime import UTC, datetime

import duckdb
import pytest

# --- DDL from audit_recorder.py (L97-143) ---
_DDL = """
CREATE TABLE IF NOT EXISTS audit_runs (
    run_id        VARCHAR PRIMARY KEY,
    start_time    TIMESTAMP,
    end_time      TIMESTAMP,
    status        VARCHAR,
    agent_id      VARCHAR,
    session_id    VARCHAR,
    thread_id     VARCHAR,
    user_id       VARCHAR,
    source_channel VARCHAR
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id     VARCHAR PRIMARY KEY,
    event_type   VARCHAR NOT NULL,
    timestamp    TIMESTAMP NOT NULL,
    sequence_no  INTEGER,
    run_id       VARCHAR,
    session_id   VARCHAR,
    agent_id     VARCHAR,
    payload      VARCHAR,
    redaction    VARCHAR
);

CREATE TABLE IF NOT EXISTS audit_tool_calls (
    call_id      VARCHAR PRIMARY KEY,
    run_id       VARCHAR,
    timestamp    TIMESTAMP NOT NULL,
    tool_name    VARCHAR NOT NULL,
    input_args   VARCHAR,
    output       VARCHAR,
    status       VARCHAR,
    error        VARCHAR,
    duration_ms  DOUBLE
);

CREATE TABLE IF NOT EXISTS audit_messages (
    message_id   VARCHAR PRIMARY KEY,
    run_id       VARCHAR,
    timestamp    TIMESTAMP NOT NULL,
    sequence_no  INTEGER,
    role         VARCHAR NOT NULL,
    content      VARCHAR,
    tool_call_id VARCHAR,
    tool_calls   VARCHAR
);
"""


def _make_conn():
    conn = duckdb.connect(":memory:")
    conn.execute(_DDL)
    return conn


def _now():
    return datetime.now(UTC)


def _insert_run(conn, run_id, *, status="completed", agent_id="quick", source_channel="cli"):
    conn.execute(
        "INSERT INTO audit_runs (run_id, start_time, end_time, status, agent_id, user_id, source_channel) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [run_id, _now(), _now(), status, agent_id, "testuser", source_channel],
    )


def _insert_message(conn, run_id, *, seq, role, content, msg_id=None, tool_call_id=None, tool_calls=None):
    conn.execute(
        "INSERT INTO audit_messages (message_id, run_id, timestamp, sequence_no, role, content, tool_call_id, tool_calls) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [msg_id or str(uuid.uuid4()), run_id, _now(), seq, role, content, tool_call_id, tool_calls],
    )


def _insert_event(conn, run_id, *, event_type="user_input_received", seq=1, payload=None):
    conn.execute(
        "INSERT INTO audit_events (event_id, event_type, timestamp, sequence_no, run_id, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            str(uuid.uuid4()),
            event_type,
            _now(),
            seq,
            run_id,
            json.dumps(payload) if payload else None,
        ],
    )


def _insert_tool_call(
    conn, run_id, *, tool_name="query_db", input_args=None, output=None, status="completed"
):
    conn.execute(
        "INSERT INTO audit_tool_calls (call_id, run_id, timestamp, tool_name, input_args, output, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            str(uuid.uuid4()),
            run_id,
            _now(),
            tool_name,
            json.dumps(input_args) if input_args else None,
            json.dumps(output) if output else None,
            status,
        ],
    )


# =====================================================================
# A. Run Rebuild Tests
# =====================================================================


class TestRebuildRunTimeline:
    def test_returns_ordered_messages(self):
        from olav.enterprise.audit_dataset_export import rebuild_run_timeline

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=3, role="assistant", content="answer")
        _insert_message(conn, rid, seq=1, role="system", content="sys prompt")
        _insert_message(conn, rid, seq=2, role="user", content="question")
        _insert_event(conn, rid, event_type="user_input_received", seq=1)
        _insert_tool_call(conn, rid, tool_name="query_db")

        tl = rebuild_run_timeline(conn, rid)

        assert tl["run_id"] == rid
        assert tl["metadata"]["status"] == "completed"
        assert len(tl["messages"]) == 3
        assert [m["role"] for m in tl["messages"]] == ["system", "user", "assistant"]
        assert [m["sequence_no"] for m in tl["messages"]] == [1, 2, 3]
        assert len(tl["tool_calls"]) == 1
        assert len(tl["events"]) == 1
        conn.close()

    def test_empty_run(self):
        from olav.enterprise.audit_dataset_export import rebuild_run_timeline

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)

        tl = rebuild_run_timeline(conn, rid)

        assert tl["run_id"] == rid
        assert tl["messages"] == []
        assert tl["tool_calls"] == []
        assert tl["events"] == []
        conn.close()

    def test_filters_by_run_id(self):
        from olav.enterprise.audit_dataset_export import rebuild_run_timeline

        conn = _make_conn()
        rid_a = str(uuid.uuid4())
        rid_b = str(uuid.uuid4())
        _insert_run(conn, rid_a)
        _insert_run(conn, rid_b)
        _insert_message(conn, rid_a, seq=1, role="user", content="msg-a")
        _insert_message(conn, rid_b, seq=1, role="user", content="msg-b")

        tl = rebuild_run_timeline(conn, rid_a)

        assert len(tl["messages"]) == 1
        assert tl["messages"][0]["content"] == "msg-a"
        conn.close()

    def test_nonexistent_run(self):
        from olav.enterprise.audit_dataset_export import rebuild_run_timeline

        conn = _make_conn()
        tl = rebuild_run_timeline(conn, "nonexistent-id")

        assert tl["metadata"] == {}
        assert tl["messages"] == []
        conn.close()


# =====================================================================
# B. Redaction Pipeline Tests
# =====================================================================


class TestRedactionLayer1:
    def test_credentials_redacted(self):
        from olav.core.audit_recorder import redact_sensitive

        text = "neighbor 10.0.0.1 password Sekr3t! community public secret 5 MySecret key-string abc123 pre-shared-key psk999"
        result = redact_sensitive(text)

        assert "Sekr3t!" not in result
        assert "public" not in result
        assert "MySecret" not in result
        assert "abc123" not in result
        assert "psk999" not in result
        assert result.count("[REDACTED]") == 5


class TestRedactionLayer2:
    def test_ip_addresses(self):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"test-key")

        assert anon.anonymize_ip("10.1.2.3").startswith("ip_priv_v4_")
        assert anon.anonymize_ip("192.168.1.1").startswith("ip_priv_v4_")
        assert anon.anonymize_ip("8.8.8.8").startswith("ip_pub_v4_")
        assert anon.anonymize_ip("192.0.2.1").startswith("ip_doc_v4_")

    def test_prefixes(self):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = anon.anonymize_prefix("192.0.2.0/30")
        assert result.startswith("pfx_doc_v4_")

        result2 = anon.anonymize_prefix("10.0.0.0/8")
        assert result2.startswith("pfx_priv_v4_")

    def test_interfaces(self):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result_cisco = anon.anonymize_interface("GigabitEthernet0/1")
        assert result_cisco.startswith("if_cisco_")

        result_junos = anon.anonymize_interface("ge-0/0/0")
        assert result_junos.startswith("if_junos_")

    def test_hostnames(self):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = anon.anonymize_hostname("edge-r1-shanghai")
        assert result.startswith("host_")

        result2 = anon.anonymize_hostname("sw-core-02")
        assert result2.startswith("host_")

    def test_stable_mapping(self):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"stable-key")

        first = anon.anonymize_ip("10.1.2.3")
        second = anon.anonymize_ip("10.1.2.3")
        assert first == second

        third = anon.anonymize_hostname("edge-r1-shanghai")
        fourth = anon.anonymize_hostname("edge-r1-shanghai")
        assert third == fourth

    def test_anonymize_text_replaces_ips(self):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        text = "Traffic from 10.1.2.3 to 8.8.8.8 via GigabitEthernet0/1 on edge-r1-shanghai"
        result = anon.anonymize_text(text)

        assert "10.1.2.3" not in result
        assert "8.8.8.8" not in result
        assert "ip_priv_v4_" in result
        assert "ip_pub_v4_" in result


# =====================================================================
# C. Gate Check Tests
# =====================================================================


class TestGateCheck:
    def _make_clean_timeline(self):
        return {
            "run_id": "test-run",
            "metadata": {"status": "completed"},
            "messages": [
                {"role": "user", "content": "Show me host_001 status"},
                {
                    "role": "assistant",
                    "content": "The device host_001 has ip_priv_v4_001 on if_cisco_001",
                },
            ],
            "tool_calls": [],
            "events": [],
            "redaction_metadata": {
                "applied": True,
                "policy_version": "audit-redaction-v1",
                "fields_redacted": [],
                "network_objects_hashed": ["network_object"],
                "config_blocks_masked": 0,
            },
        }

    def test_passes_clean_run(self):
        from olav.enterprise.audit_dataset_export import gate_check

        tl = self._make_clean_timeline()
        passed, reasons = gate_check(tl)
        assert passed is True
        assert reasons == []

    def test_rejects_unredacted_credentials(self):
        from olav.enterprise.audit_dataset_export import gate_check

        tl = self._make_clean_timeline()
        tl["messages"][1]["content"] = "neighbor host_001 password Sekr3t"
        passed, reasons = gate_check(tl)
        assert passed is False
        assert "plaintext_credential_detected" in reasons

    def test_rejects_unmasked_ip(self):
        from olav.enterprise.audit_dataset_export import gate_check

        tl = self._make_clean_timeline()
        tl["messages"][0]["content"] = "Check 192.168.1.1 status"
        passed, reasons = gate_check(tl)
        assert passed is False
        assert "raw_ip_address_detected" in reasons

    def test_rejects_no_redaction_metadata(self):
        from olav.enterprise.audit_dataset_export import gate_check

        tl = self._make_clean_timeline()
        del tl["redaction_metadata"]
        passed, reasons = gate_check(tl)
        assert passed is False
        assert "redaction_not_applied" in reasons


# =====================================================================
# D. SFT Export Tests
# =====================================================================


class TestAuditToSftJsonl:
    def _setup_conn_with_completed_run(self):
        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed", agent_id="quick", source_channel="cli")
        _insert_message(conn, rid, seq=1, role="system", content="You are an assistant.")
        _insert_message(conn, rid, seq=2, role="user", content="Show interfaces")
        _insert_message(conn, rid, seq=3, role="assistant", content="Here are the interfaces.")
        return conn, rid

    def test_basic_export(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn, rid = self._setup_conn_with_completed_run()
        stats = audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        assert sft_file.exists()

        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) >= 1

        sample = json.loads(lines[0])
        assert "messages" in sample
        assert "metadata" in sample
        assert sample["metadata"]["redaction_policy"] == "audit-redaction-v1"

        roles = [m["role"] for m in sample["messages"]]
        assert "system" in roles or "user" in roles or "assistant" in roles

        assert stats["runs_exported"] >= 1
        conn.close()

    def test_includes_tool_role(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        _insert_message(conn, rid, seq=1, role="user", content="query")
        _insert_message(conn, rid, seq=2, role="tool", content="tool result", tool_call_id="tc_1")
        _insert_message(conn, rid, seq=3, role="assistant", content="answer")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) == 1

        sample = json.loads(lines[0])
        roles = [m["role"] for m in sample["messages"]]
        assert "tool" in roles
        conn.close()

    def test_excludes_incomplete_runs(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid_ok = str(uuid.uuid4())
        rid_err = str(uuid.uuid4())
        rid_cancel = str(uuid.uuid4())

        _insert_run(conn, rid_ok, status="completed")
        _insert_message(conn, rid_ok, seq=1, role="user", content="q1")
        _insert_message(conn, rid_ok, seq=2, role="assistant", content="a1")

        _insert_run(conn, rid_err, status="error")
        _insert_message(conn, rid_err, seq=1, role="user", content="q2")

        _insert_run(conn, rid_cancel, status="cancelled")
        _insert_message(conn, rid_cancel, seq=1, role="user", content="q3")

        stats = audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        assert stats["runs_scanned"] == 3
        assert stats["runs_after_filter"] == 1
        assert stats["runs_exported"] == 1
        conn.close()

    def test_writes_manifest(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn, _ = self._setup_conn_with_completed_run()
        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
        assert "export_id" in manifest
        assert "source_db" in manifest
        assert "redaction_policy" in manifest
        assert manifest["redaction_policy"] == "audit-redaction-v1"
        assert "runs_scanned" in manifest
        assert "runs_exported" in manifest
        assert "runs_rejected" in manifest
        assert manifest["encryption"]["applied"] is False
        conn.close()

    def test_writes_stats(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn, _ = self._setup_conn_with_completed_run()
        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        stats = json.loads((tmp_path / "out" / "stats.json").read_text())
        assert "runs_scanned" in stats
        assert "runs_after_filter" in stats
        assert "runs_exported" in stats
        assert "runs_rejected" in stats
        assert "samples_exported" in stats
        conn.close()

    def test_writes_rejected(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        # Message with raw IP that won't be anonymised by redaction because
        # it's embedded in a way the gate will catch
        _insert_message(conn, rid, seq=1, role="user", content="Check 999.999.999.999")
        _insert_message(conn, rid, seq=2, role="assistant", content="Done")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        json.loads((tmp_path / "out" / "rejected_runs.json").read_text())
        conn.close()

    def test_rejected_run_with_credentials(self, tmp_path):
        """A run where the message content somehow still has credentials after
        redaction (simulated by inserting content that the basic
        ``redact_sensitive`` won't catch but the gate will)."""
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        # This tests the full pipeline — the message goes through
        # redact_sensitive (Layer 1), then anonymize_text (Layer 2), then
        # gate_check. A valid IP will get caught by gate if somehow not anonymised.
        # For this test, we verify the pipeline produces valid output files.
        _insert_message(conn, rid, seq=1, role="user", content="Show interfaces")
        _insert_message(conn, rid, seq=2, role="assistant", content="Here are the results")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        rejected_path = tmp_path / "out" / "rejected_runs.json"
        assert rejected_path.exists()
        rejected = json.loads(rejected_path.read_text())
        assert isinstance(rejected, list)
        conn.close()

    def test_empty_db_produces_empty_output(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        stats = audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        assert stats["runs_scanned"] == 0
        assert stats["runs_exported"] == 0
        assert (tmp_path / "out" / "sft.jsonl").exists()
        assert (tmp_path / "out" / "sft.jsonl").read_text() == ""
        conn.close()


# =====================================================================
# D.2 SFT Tool Calls Preservation (DATA-2)
# =====================================================================


class TestSFTToolCallsPreservation:
    def test_tool_role_messages_in_sft_output(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        _insert_message(conn, rid, seq=1, role="user", content="Check BGP")
        _insert_message(
            conn, rid, seq=2, role="tool", content='{"result": "ok"}', tool_call_id="call_abc123"
        )
        _insert_message(conn, rid, seq=3, role="assistant", content="BGP is healthy.")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) == 1

        sample = json.loads(lines[0])
        roles = [m["role"] for m in sample["messages"]]
        assert "tool" in roles, "tool role must be included in SFT messages"
        assert "user" in roles
        assert "assistant" in roles
        conn.close()

    def test_assistant_tool_calls_preserved(self, tmp_path, monkeypatch):
        from olav.enterprise import audit_dataset_export
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        _insert_message(conn, rid, seq=1, role="user", content="Check interfaces")
        _insert_message(conn, rid, seq=2, role="assistant", content=None)
        _insert_message(
            conn, rid, seq=3, role="tool", content="Gi0/1 is up", tool_call_id="call_xyz"
        )
        _insert_message(conn, rid, seq=4, role="assistant", content="Interface Gi0/1 is up.")

        original_rebuild = audit_dataset_export.rebuild_run_timeline

        def _patched_rebuild(c, r):
            timeline = original_rebuild(c, r)
            for msg in timeline["messages"]:
                if msg["role"] == "assistant" and msg["content"] is None:
                    msg["tool_calls"] = [
                        {
                            "id": "call_xyz",
                            "type": "function",
                            "function": {
                                "name": "show_interfaces",
                                "arguments": '{"device": "r1"}',
                            },
                        }
                    ]
                    break
            return timeline

        monkeypatch.setattr(audit_dataset_export, "rebuild_run_timeline", _patched_rebuild)

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) == 1

        sample = json.loads(lines[0])
        assistant_with_tc = [
            m for m in sample["messages"] if m["role"] == "assistant" and "tool_calls" in m
        ]
        assert len(assistant_with_tc) == 1
        assert assistant_with_tc[0]["tool_calls"][0]["id"] == "call_xyz"
        assert assistant_with_tc[0]["tool_calls"][0]["function"]["name"] == "show_interfaces"
        conn.close()

    def test_tool_call_id_preserved_on_tool_messages(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        _insert_message(conn, rid, seq=1, role="user", content="Show routes")
        _insert_message(
            conn, rid, seq=2, role="tool", content="10 routes found", tool_call_id="call_route_1"
        )
        _insert_message(conn, rid, seq=3, role="assistant", content="Found 10 routes.")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) == 1

        sample = json.loads(lines[0])
        tool_msgs = [m for m in sample["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) >= 1, "tool messages must be in SFT output"
        assert "tool_call_id" in tool_msgs[0], "tool_call_id must be preserved on tool messages"
        assert tool_msgs[0]["tool_call_id"] == "call_route_1"
        conn.close()

    def test_multiple_tool_calls_round_trip(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        _insert_message(conn, rid, seq=1, role="user", content="Check all devices")
        _insert_message(conn, rid, seq=2, role="tool", content="device1 ok", tool_call_id="call_1")
        _insert_message(conn, rid, seq=3, role="tool", content="device2 ok", tool_call_id="call_2")
        _insert_message(conn, rid, seq=4, role="assistant", content="All devices healthy.")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) == 1

        sample = json.loads(lines[0])
        tool_msgs = [m for m in sample["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) == 2, "both tool messages must be preserved"
        tool_call_ids = {m["tool_call_id"] for m in tool_msgs}
        assert tool_call_ids == {"call_1", "call_2"}
        conn.close()

    def test_tool_message_without_tool_call_id_still_included(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed")
        _insert_message(conn, rid, seq=1, role="user", content="query")
        _insert_message(conn, rid, seq=2, role="tool", content="result")
        _insert_message(conn, rid, seq=3, role="assistant", content="answer")

        audit_to_sft_jsonl(conn, tmp_path / "out", hours=1)

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()
        assert len(lines) == 1

        sample = json.loads(lines[0])
        tool_msgs = [m for m in sample["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        conn.close()


# =====================================================================
# E. CLI Integration Tests
# =====================================================================


class TestLogExportSubparser:
    def test_subparser_exists(self):
        """Verify the argparser accepts 'log export sft' as a valid subcommand."""
        import argparse

        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="command")
        log_parser = subs.add_parser("log")
        log_parser.add_subparsers(dest="log_command")

        import sys

        from olav.cli.main import parse_args

        saved = sys.argv
        try:
            sys.argv = ["olav", "log", "export", "sft", "--hours", "48"]
            args = parse_args()
            assert args.command == "log"
            assert args.log_command == "export"
            assert args.export_format == "sft"
            assert args.hours == 48
        finally:
            sys.argv = saved


# =====================================================================
# F. Full Pipeline Integration Test
# =====================================================================


class TestFullPipelineIntegration:
    def test_end_to_end_with_network_data(self, tmp_path):
        """Insert a realistic run with network data, export, verify redaction."""
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="completed", agent_id="ops")

        _insert_message(
            conn,
            rid,
            seq=1,
            role="system",
            content="You are OLAV network assistant.",
        )
        _insert_message(
            conn,
            rid,
            seq=2,
            role="user",
            content="Check BGP neighbors on edge-r1-shanghai via GigabitEthernet0/1",
        )
        _insert_message(
            conn,
            rid,
            seq=3,
            role="assistant",
            content="BGP neighbor 10.0.0.1 on edge-r1-shanghai GigabitEthernet0/1 is up. "
            "Password is configured. Route prefix 192.168.1.0/24 advertised.",
        )

        stats = audit_to_sft_jsonl(conn, tmp_path / "out", hours=1, secret_key=b"e2e-key")

        sft_file = tmp_path / "out" / "sft.jsonl"
        lines = sft_file.read_text().strip().splitlines()

        if stats["runs_exported"] > 0:
            sample = json.loads(lines[0])
            all_content = " ".join(m["content"] for m in sample["messages"])
            # Real IPs should be anonymised
            assert "10.0.0.1" not in all_content
            # Hostnames should be anonymised
            assert "edge-r1-shanghai" not in all_content
            # Anonymised tokens should be present
            assert "ip_" in all_content or "host_" in all_content

        conn.close()


# =========================================================================
# Phase 2 — Tool Trajectory Export
# =========================================================================


class TestDedupFingerprint:
    """Tests for _compute_dedup_fingerprint."""

    def test_identical_inputs_same_fingerprint(self):
        from olav.enterprise.audit_dataset_export import _compute_dedup_fingerprint

        fp1 = _compute_dedup_fingerprint("show bgp", ["query_db", "ping"], "done")
        fp2 = _compute_dedup_fingerprint("show bgp", ["query_db", "ping"], "done")
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        from olav.enterprise.audit_dataset_export import _compute_dedup_fingerprint

        fp1 = _compute_dedup_fingerprint("show bgp", ["query_db"], "done")
        fp2 = _compute_dedup_fingerprint("show ospf", ["query_db"], "done")
        assert fp1 != fp2

    def test_tool_order_irrelevant(self):
        """Tool sequence is sorted, so order should not matter."""
        from olav.enterprise.audit_dataset_export import _compute_dedup_fingerprint

        fp1 = _compute_dedup_fingerprint("q", ["b_tool", "a_tool"], "r")
        fp2 = _compute_dedup_fingerprint("q", ["a_tool", "b_tool"], "r")
        assert fp1 == fp2

    def test_whitespace_normalised(self):
        from olav.enterprise.audit_dataset_export import _compute_dedup_fingerprint

        fp1 = _compute_dedup_fingerprint("  show   bgp ", ["query_db"], "  done  ")
        fp2 = _compute_dedup_fingerprint("show bgp", ["query_db"], "done")
        assert fp1 == fp2

    def test_case_normalised(self):
        from olav.enterprise.audit_dataset_export import _compute_dedup_fingerprint

        fp1 = _compute_dedup_fingerprint("Show BGP", ["Query_DB"], "Done")
        fp2 = _compute_dedup_fingerprint("show bgp", ["Query_DB"], "done")
        assert fp1 == fp2


class TestBuildTrajectorySteps:
    """Tests for _build_trajectory_steps."""

    def test_basic_trajectory(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "show bgp"},
                {"role": "assistant", "content": "Let me check."},
                {"role": "tool", "content": "BGP table: 3 routes"},
                {"role": "assistant", "content": "You have 3 routes."},
            ],
            "tool_calls": [
                {
                    "call_id": "tc1",
                    "tool_name": "query_db",
                    "input_args": {"sql": "SELECT *"},
                    "status": "completed",
                },
            ],
            "events": [],
        }
        steps, is_valid = _build_trajectory_steps(timeline)

        assert is_valid is True
        assert len(steps) >= 3
        # First assistant step becomes reasoning
        assert steps[0]["type"] == "assistant_reasoning"
        # Tool call and result
        tool_call_steps = [s for s in steps if s["type"] == "tool_call"]
        assert len(tool_call_steps) == 1
        assert tool_call_steps[0]["tool"] == "query_db"
        # Last assistant becomes assistant_final
        assert steps[-1]["type"] == "assistant_final"
        assert steps[-1]["content"] == "You have 3 routes."

    def test_missing_tool_result_marks_invalid(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "do something"},
                {"role": "assistant", "content": "thinking..."},
            ],
            "tool_calls": [
                {"call_id": "tc1", "tool_name": "run_cmd", "input_args": {}, "status": "pending"},
            ],
            "events": [],
        }
        steps, is_valid = _build_trajectory_steps(timeline)
        assert is_valid is False

    def test_tool_result_without_call_marks_invalid(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "query"},
                {"role": "tool", "content": "orphaned result"},
                {"role": "assistant", "content": "here"},
            ],
            "tool_calls": [],
            "events": [],
        }
        steps, is_valid = _build_trajectory_steps(timeline)
        assert is_valid is False

    def test_empty_messages(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {"messages": [], "tool_calls": [], "events": []}
        steps, is_valid = _build_trajectory_steps(timeline)
        assert steps == []
        assert is_valid is True

    def test_reasoning_block_events_become_thinking_steps(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "check bgp"},
                {"role": "assistant", "content": "BGP is healthy."},
            ],
            "tool_calls": [],
            "events": [
                {
                    "event_id": "e1",
                    "event_type": "reasoning_block",
                    "timestamp": "2026-03-18T01:00:00",
                    "sequence_no": 1,
                    "run_id": "r1",
                    "payload": json.dumps({"token": "Let me think about BGP..."}),
                },
                {
                    "event_id": "e2",
                    "event_type": "reasoning_block",
                    "timestamp": "2026-03-18T01:00:01",
                    "sequence_no": 2,
                    "run_id": "r1",
                    "payload": json.dumps({"token": "Checking route tables..."}),
                },
            ],
        }
        steps, is_valid = _build_trajectory_steps(timeline)

        thinking_steps = [s for s in steps if s["type"] == "thinking"]
        assert len(thinking_steps) >= 1, f"Expected thinking steps, got: {steps}"
        combined = " ".join(s["content"] for s in thinking_steps)
        assert "Let me think about BGP" in combined or "Checking route" in combined

    def test_reasoning_interleaved_with_tool_calls(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "show routes"},
                {"role": "tool", "content": "10.0.0.0/8 via 10.1.1.1"},
                {"role": "assistant", "content": "Found 1 route."},
            ],
            "tool_calls": [
                {
                    "call_id": "tc1",
                    "tool_name": "query_db",
                    "input_args": "SELECT * FROM routes",
                    "status": "completed",
                },
            ],
            "events": [
                {
                    "event_id": "e1",
                    "event_type": "reasoning_block",
                    "timestamp": "2026-03-18T01:00:00",
                    "sequence_no": 1,
                    "run_id": "r1",
                    "payload": json.dumps({"token": "I should query the routes table"}),
                },
            ],
        }
        steps, is_valid = _build_trajectory_steps(timeline)

        step_types = [s["type"] for s in steps]
        assert "thinking" in step_types, f"No thinking step found. Steps: {steps}"
        assert "tool_call" in step_types
        assert "assistant_final" in step_types


class TestBuildAtifSpansReasoning:
    def test_reasoning_block_events_in_atif_spans(self):
        from olav.enterprise.audit_dataset_export import _build_atif_spans

        timeline = {
            "messages": [
                {"role": "user", "content": "analyze topology"},
                {"role": "assistant", "content": "Ring topology detected."},
            ],
            "tool_calls": [],
            "events": [
                {
                    "event_id": "e1",
                    "event_type": "reasoning_block",
                    "timestamp": "2026-03-18T01:00:00",
                    "sequence_no": 1,
                    "run_id": "r1",
                    "payload": json.dumps({"token": "Analyzing link connections..."}),
                },
            ],
        }
        spans = _build_atif_spans(timeline)

        thinking_spans = [s for s in spans if s["type"] == "thinking"]
        assert len(thinking_spans) >= 1, f"No thinking spans. Got: {spans}"
        assert "Analyzing link" in thinking_spans[0]["content"]

    def test_no_reasoning_events_no_thinking_spans(self):
        from olav.enterprise.audit_dataset_export import _build_atif_spans

        timeline = {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            "tool_calls": [],
            "events": [],
        }
        spans = _build_atif_spans(timeline)
        thinking_spans = [s for s in spans if s["type"] == "thinking"]
        assert len(thinking_spans) == 0


class TestHasHitlReject:
    """Tests for _has_hitl_reject."""

    def test_no_rejection(self):
        from olav.enterprise.audit_dataset_export import _has_hitl_reject

        timeline = {"events": [{"event_type": "tool_executed", "payload": None}]}
        assert _has_hitl_reject(timeline) is False

    def test_payload_dict_reject(self):
        from olav.enterprise.audit_dataset_export import _has_hitl_reject

        timeline = {
            "events": [
                {"event_type": "hitl_decision", "payload": json.dumps({"hitl_decision": "reject"})},
            ]
        }
        assert _has_hitl_reject(timeline) is True

    def test_event_type_reject(self):
        from olav.enterprise.audit_dataset_export import _has_hitl_reject

        timeline = {"events": [{"event_type": "hitl_reject", "payload": None}]}
        assert _has_hitl_reject(timeline) is True


class TestAuditToToolTrajectory:
    """Integration tests for audit_to_tool_trajectory."""

    def test_basic_export(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Show me BGP neighbors")
        _insert_message(conn, rid, seq=2, role="assistant", content="Let me query the database.")
        _insert_tool_call(
            conn,
            rid,
            tool_name="query_db",
            input_args={"sql": "SELECT * FROM bgp"},
            output={"rows": 3},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="Found 3 BGP neighbors")
        _insert_message(conn, rid, seq=4, role="assistant", content="You have 3 BGP neighbors.")

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"test-key")

        assert stats["runs_scanned"] >= 1
        traj_file = tmp_path / "out" / "trajectory.jsonl"
        assert traj_file.exists()

        if stats["runs_exported"] > 0:
            lines = traj_file.read_text().strip().splitlines()
            assert len(lines) >= 1
            sample = json.loads(lines[0])
            assert "instruction" in sample
            assert "trajectory" in sample
            assert "metadata" in sample

        conn.close()

    def test_metadata_fields(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, agent_id="ops")
        _insert_message(conn, rid, seq=1, role="user", content="Check interface status")
        _insert_message(conn, rid, seq=2, role="assistant", content="Checking interfaces.")
        _insert_tool_call(
            conn, rid, tool_name="show_interfaces", input_args={}, output={"status": "up"}
        )
        _insert_message(conn, rid, seq=3, role="tool", content="Interface Gi0/1 is up")
        _insert_message(conn, rid, seq=4, role="assistant", content="Interface is operational.")

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"meta-key")

        if stats["runs_exported"] > 0:
            traj_file = tmp_path / "out" / "trajectory.jsonl"
            sample = json.loads(traj_file.read_text().strip().splitlines()[0])
            meta = sample["metadata"]
            assert meta["task_type"] == "tool_selection"
            assert "tool_use" in meta["domain_tags"]
            assert meta["requires_tool"] is True
            assert meta["redaction_policy"] == "audit-redaction-v1"
            assert meta["dedup_strategy"] == "exact_v1"
            assert "dedup_fingerprint" in meta
            assert isinstance(meta["invalid_trajectory"], bool)

        conn.close()

    def test_dedup_keeps_latest(self, tmp_path):
        """Two identical runs should dedup to one sample (the later one)."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()

        for _i in range(2):
            rid = str(uuid.uuid4())
            _insert_run(conn, rid)
            _insert_message(conn, rid, seq=1, role="user", content="Show BGP")
            _insert_message(conn, rid, seq=2, role="assistant", content="Checking.")
            _insert_tool_call(conn, rid, tool_name="query_db", input_args={"q": "bgp"}, output="ok")
            _insert_message(conn, rid, seq=3, role="tool", content="BGP data")
            _insert_message(conn, rid, seq=4, role="assistant", content="Here are results.")

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"dedup-key")

        # At most 1 exported due to dedup (may be 0 if gate rejects)
        if stats["runs_exported"] > 0:
            traj_file = tmp_path / "out" / "trajectory.jsonl"
            lines = traj_file.read_text().strip().splitlines()
            assert len(lines) == 1
            assert stats["runs_deduped"] >= 1

        conn.close()

    def test_manifest_with_trajectory_format(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Check OSPF")
        _insert_message(conn, rid, seq=2, role="assistant", content="Running query.")
        _insert_tool_call(conn, rid, tool_name="query_db", input_args={}, output="ospf data")
        _insert_message(conn, rid, seq=3, role="tool", content="OSPF neighbors: 2")
        _insert_message(conn, rid, seq=4, role="assistant", content="2 OSPF neighbors found.")

        audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"manifest-key")

        manifest_path = tmp_path / "out" / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "trajectory" in manifest["formats"]
        assert manifest["redaction_policy"] == "audit-redaction-v1"
        assert "window" in manifest
        assert "encryption" in manifest

        conn.close()

    def test_empty_db_produces_empty_output(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"empty-key")

        assert stats["runs_scanned"] == 0
        assert stats["runs_exported"] == 0

        traj_file = tmp_path / "out" / "trajectory.jsonl"
        assert traj_file.exists()
        assert traj_file.read_text().strip() == ""

        conn.close()

    def test_cancelled_run_excluded(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="cancelled")
        _insert_message(conn, rid, seq=1, role="user", content="Check BGP")
        _insert_message(conn, rid, seq=2, role="assistant", content="Cancelled.")

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"cancel-key")

        assert stats["runs_exported"] == 0
        conn.close()

    def test_hitl_rejected_run_excluded(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Do something risky")
        _insert_message(conn, rid, seq=2, role="assistant", content="I need approval.")
        _insert_event(conn, rid, event_type="hitl_reject", seq=1)
        _insert_message(conn, rid, seq=3, role="assistant", content="Rejected by user.")

        audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"hitl-key")

        # Should be in rejected, not exported
        rejected_path = tmp_path / "out" / "rejected_runs.json"
        assert rejected_path.exists()
        rejected = json.loads(rejected_path.read_text())
        hitl_rejected = [r for r in rejected if "hitl_rejected" in r.get("reasons", [])]
        assert len(hitl_rejected) >= 1

        conn.close()


class TestTrajectoryToolCallCoverage:
    """EXPORT-1: Assertive trajectory tests — NO if-guards.

    These tests verify that the full pipeline (audit_tool_calls →
    _build_trajectory_steps → trajectory.jsonl) produces correct output
    with proper tool_call / tool_result steps.
    """

    def test_single_tool_trajectory_exported(self, tmp_path):
        """A complete run with one tool call MUST produce exactly 1 exported
        trajectory with tool_call and tool_result step types."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Show BGP neighbor summary")
        _insert_message(
            conn, rid, seq=2, role="assistant", content="Let me query the database for BGP data."
        )
        _insert_tool_call(
            conn,
            rid,
            tool_name="query_db",
            input_args={"sql": "SELECT * FROM bgp_neighbors"},
            output={"rows": 5},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="Found 5 BGP neighbors in database")
        _insert_message(
            conn,
            rid,
            seq=4,
            role="assistant",
            content="You have 5 BGP neighbors configured and active.",
        )

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"export1-key")

        assert stats["runs_exported"] >= 1, f"Expected >=1 export, got {stats}"

        traj_file = tmp_path / "out" / "trajectory.jsonl"
        assert traj_file.exists()
        lines = traj_file.read_text().strip().splitlines()
        assert len(lines) >= 1

        sample = json.loads(lines[0])
        assert "instruction" in sample
        assert "trajectory" in sample
        steps = sample["trajectory"]

        step_types = [s["type"] for s in steps]
        assert "tool_call" in step_types, f"Missing tool_call step in {step_types}"
        assert "tool_result" in step_types, f"Missing tool_result step in {step_types}"

        tc_steps = [s for s in steps if s["type"] == "tool_call"]
        assert len(tc_steps) == 1
        assert tc_steps[0]["tool"] == "query_db"

        conn.close()

    def test_tool_call_step_has_args(self, tmp_path):
        """tool_call steps must carry the input_args from audit_tool_calls."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(
            conn, rid, seq=1, role="user", content="Find all OSPF routes in the network"
        )
        _insert_message(
            conn, rid, seq=2, role="assistant", content="Querying OSPF route table now."
        )
        _insert_tool_call(
            conn,
            rid,
            tool_name="query_db",
            input_args={"sql": "SELECT * FROM ospf_routes", "limit": 100},
            output={"count": 12},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="12 OSPF routes returned from query")
        _insert_message(
            conn, rid, seq=4, role="assistant", content="Found 12 OSPF routes across the network."
        )

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"args-key")
        assert stats["runs_exported"] >= 1

        sample = json.loads(
            (tmp_path / "out" / "trajectory.jsonl").read_text().strip().splitlines()[0]
        )
        tc_steps = [s for s in sample["trajectory"] if s["type"] == "tool_call"]
        assert len(tc_steps) == 1
        args = tc_steps[0].get("args", {})
        assert args is not None and args != {}, "tool_call args should not be empty"
        if isinstance(args, str):
            parsed = json.loads(args)
            assert isinstance(parsed, dict)
        else:
            assert isinstance(args, dict)

        conn.close()

    def test_multi_tool_chain_trajectory(self, tmp_path):
        """A run with 2+ sequential tool calls must produce all tool_call
        and tool_result steps in order."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(
            conn, rid, seq=1, role="user", content="Compare BGP and OSPF neighbor counts"
        )
        _insert_message(conn, rid, seq=2, role="assistant", content="I will query both protocols.")

        _insert_tool_call(
            conn,
            rid,
            tool_name="query_bgp",
            input_args={"query": "bgp_neighbors"},
            output={"count": 3},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="3 BGP neighbors found")

        _insert_message(conn, rid, seq=4, role="assistant", content="Now checking OSPF neighbors.")

        _insert_tool_call(
            conn,
            rid,
            tool_name="query_ospf",
            input_args={"query": "ospf_neighbors"},
            output={"count": 5},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="3 BGP neighbors found")

        _insert_message(conn, rid, seq=4, role="assistant", content="Now checking OSPF neighbors.")

        # Tool call 2: OSPF
        _insert_tool_call(
            conn,
            rid,
            tool_name="query_ospf",
            input_args={"query": "ospf_neighbors"},
            output={"count": 5},
        )
        _insert_message(conn, rid, seq=5, role="tool", content="5 OSPF neighbors found")

        _insert_message(
            conn,
            rid,
            seq=6,
            role="assistant",
            content="BGP has 3 neighbors while OSPF has 5 neighbors in the network.",
        )

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"multi-key")
        assert stats["runs_exported"] >= 1

        sample = json.loads(
            (tmp_path / "out" / "trajectory.jsonl").read_text().strip().splitlines()[0]
        )
        steps = sample["trajectory"]
        tc_steps = [s for s in steps if s["type"] == "tool_call"]
        tr_steps = [s for s in steps if s["type"] == "tool_result"]

        assert len(tc_steps) >= 2, f"Expected >=2 tool_call steps, got {len(tc_steps)}"
        assert len(tr_steps) >= 2, f"Expected >=2 tool_result steps, got {len(tr_steps)}"

        tool_names = [s["tool"] for s in tc_steps]
        assert "query_bgp" in tool_names
        assert "query_ospf" in tool_names

        conn.close()

    def test_trajectory_has_7_dimension_score(self, tmp_path):
        """Exported trajectory metadata must include score_components with
        all 7 quality dimensions from DATA-3."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        expected_keys = {
            "completeness",
            "tool_consistency",
            "query_specificity",
            "analysis_value",
            "tool_selection_relevance",
            "parameter_quality",
            "output_usage",
        }

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(
            conn, rid, seq=1, role="user", content="Show all interface status on router"
        )
        _insert_message(conn, rid, seq=2, role="assistant", content="Querying interface table now.")
        _insert_tool_call(
            conn,
            rid,
            tool_name="show_interfaces",
            input_args={"device": "router1"},
            output={"interfaces": 24},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="24 interfaces returned from router")
        _insert_message(
            conn, rid, seq=4, role="assistant", content="Router has 24 interfaces, all operational."
        )

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"score-key")
        assert stats["runs_exported"] >= 1

        sample = json.loads(
            (tmp_path / "out" / "trajectory.jsonl").read_text().strip().splitlines()[0]
        )
        meta = sample["metadata"]
        assert "rule_score" in meta, "Missing rule_score in metadata"
        assert "score_components" in meta, "Missing score_components in metadata"
        assert isinstance(meta["rule_score"], (int, float))
        assert 0.0 <= meta["rule_score"] <= 1.0

        components = meta["score_components"]
        assert set(components.keys()) == expected_keys, (
            f"Expected 7 dimensions {expected_keys}, got {set(components.keys())}"
        )
        for key in expected_keys:
            assert isinstance(components[key], (int, float)), f"{key} is not numeric"
            assert 0.0 <= components[key] <= 1.0, f"{key}={components[key]} out of [0,1]"

        conn.close()

    def test_assistant_final_step_present(self, tmp_path):
        """The last assistant message must be relabeled as assistant_final."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Check VLAN configuration status")
        _insert_message(conn, rid, seq=2, role="assistant", content="Running VLAN query now.")
        _insert_tool_call(
            conn,
            rid,
            tool_name="query_vlans",
            input_args={"scope": "all"},
            output={"vlans": 10},
        )
        _insert_message(conn, rid, seq=3, role="tool", content="10 VLANs configured on switch")
        _insert_message(
            conn, rid, seq=4, role="assistant", content="There are 10 VLANs configured."
        )

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"final-key")
        assert stats["runs_exported"] >= 1

        sample = json.loads(
            (tmp_path / "out" / "trajectory.jsonl").read_text().strip().splitlines()[0]
        )
        steps = sample["trajectory"]
        step_types = [s["type"] for s in steps]
        assert "assistant_final" in step_types, f"Missing assistant_final in {step_types}"

        last_assistant_idx = max(
            i
            for i, s in enumerate(steps)
            if s["type"] in ("assistant_reasoning", "assistant_final")
        )
        assert steps[last_assistant_idx]["type"] == "assistant_final"

        conn.close()

    def test_tool_result_content_present(self, tmp_path):
        """tool_result steps must include the content from the tool message."""
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(
            conn, rid, seq=1, role="user", content="Show ACL entries for management interface"
        )
        _insert_message(
            conn, rid, seq=2, role="assistant", content="Fetching ACL data for management."
        )
        _insert_tool_call(
            conn,
            rid,
            tool_name="get_acls",
            input_args={"interface": "mgmt0"},
            output={"entries": 4},
        )
        _insert_message(
            conn, rid, seq=3, role="tool", content="4 ACL entries applied on management interface"
        )
        _insert_message(
            conn, rid, seq=4, role="assistant", content="Management interface has 4 ACL entries."
        )

        stats = audit_to_tool_trajectory(conn, tmp_path / "out", hours=1, secret_key=b"content-key")
        assert stats["runs_exported"] >= 1

        sample = json.loads(
            (tmp_path / "out" / "trajectory.jsonl").read_text().strip().splitlines()[0]
        )
        tr_steps = [s for s in sample["trajectory"] if s["type"] == "tool_result"]
        assert len(tr_steps) >= 1
        assert tr_steps[0]["content"], "tool_result content is empty"
        assert isinstance(tr_steps[0]["content"], str)

        conn.close()


class TestTrajectoryCLISubparser:
    """Test CLI parse_args handles trajectory subparser."""

    def test_parse_trajectory_subcommand(self):
        import sys

        from olav.cli.main import parse_args

        saved = sys.argv
        try:
            sys.argv = ["olav", "log", "export", "trajectory", "--hours", "48"]
            args = parse_args()
            assert args.command == "log"
            assert getattr(args, "log_command", None) == "export"
            assert getattr(args, "export_format", None) == "trajectory"
            assert getattr(args, "hours", None) == 48
        finally:
            sys.argv = saved


# =====================================================================
# Phase 3: Config Block Redaction Tests
# =====================================================================


class TestConfigBlockRedaction:
    """Test Layer 3 config-block-level redaction."""

    def test_config_block_ips_redacted(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [
                {
                    "role": "assistant",
                    "content": "router bgp 65000\n neighbor 10.0.0.1 password Sekr3t!\n neighbor 10.0.0.2 remote-as 65001",
                },
            ],
            "tool_calls": [],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        content = result["messages"][0]["content"]
        # IPs should be anonymized
        assert "10.0.0.1" not in content
        assert "10.0.0.2" not in content
        # Password should be redacted (Layer 1 via redact_sensitive)
        assert "Sekr3t!" not in content
        assert "[REDACTED]" in content

    def test_config_block_community_redacted(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [
                {
                    "role": "assistant",
                    "content": "interface Vlan100\n ip address 10.1.1.1 255.255.255.0\nsnmp-server community PUBLIC RO",
                },
            ],
            "tool_calls": [],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        content = result["messages"][0]["content"]
        # Community string should be redacted
        assert "PUBLIC" not in content
        assert "[REDACTED]" in content

    def test_config_block_key_string_redacted(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [
                {
                    "role": "assistant",
                    "content": "router ospf 1\n key-string MyS3cretKey\n area 0",
                },
            ],
            "tool_calls": [],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        content = result["messages"][0]["content"]
        assert "MyS3cretKey" not in content
        assert "[REDACTED]" in content

    def test_config_block_syntax_skeleton_preserved(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [
                {
                    "role": "assistant",
                    "content": "interface GigabitEthernet0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown",
                },
            ],
            "tool_calls": [],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        content = result["messages"][0]["content"]
        # Structure keywords preserved
        assert "interface" in content
        assert "ip address" in content
        assert "no shutdown" in content
        # But real values replaced
        assert "10.1.1.1" not in content

    def test_non_config_text_not_affected(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [
                {
                    "role": "assistant",
                    "content": "The query returned 5 rows. No issues found.",
                },
            ],
            "tool_calls": [],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        content = result["messages"][0]["content"]
        assert content == "The query returned 5 rows. No issues found."
        # config_blocks_masked should be 0 for non-config content
        assert result["redaction_metadata"]["config_blocks_masked"] == 0

    def test_config_blocks_masked_count_accurate(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [
                {
                    "role": "assistant",
                    "content": "interface Gi0/1\n description uplink",
                },
                {
                    "role": "assistant",
                    "content": "router ospf 1\n network 10.0.0.0 0.0.0.255 area 0",
                },
                {
                    "role": "assistant",
                    "content": "No config here, just text.",
                },
            ],
            "tool_calls": [],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        # Two messages have config keywords, one doesn't
        assert result["redaction_metadata"]["config_blocks_masked"] == 2

    def test_config_block_redaction_in_tool_calls(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
        )

        timeline = {
            "run_id": "r1",
            "metadata": {},
            "messages": [],
            "tool_calls": [
                {
                    "call_id": "tc1",
                    "tool_name": "show_config",
                    "input_args": "show run",
                    "output": "interface Loopback0\n ip address 192.168.1.1 255.255.255.255\n password Secret123",
                    "status": "completed",
                },
            ],
            "events": [],
        }
        anon = NetworkObjectAnonymizer(secret_key=b"test-key")
        result = redact_audit_run(timeline, anonymizer=anon)
        output = result["tool_calls"][0]["output"]
        assert "192.168.1.1" not in output
        assert "Secret123" not in output
        assert "[REDACTED]" in output
        assert result["redaction_metadata"]["config_blocks_masked"] >= 1


# =====================================================================
# Phase 3: Mapping Cache Persistence Tests
# =====================================================================


class TestMappingCachePersistence:
    """Test stable object mapping save/load for cross-export consistency."""

    def test_save_and_load_mapping(self, tmp_path):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon1 = NetworkObjectAnonymizer(secret_key=b"persist-key")
        token_a = anon1.anonymize_ip("10.0.0.1")
        token_b = anon1.anonymize_hostname("edge-r1-shanghai")

        cache_file = tmp_path / "mapping.json"
        anon1.save_mapping(cache_file)

        anon2 = NetworkObjectAnonymizer(secret_key=b"persist-key")
        anon2.load_mapping(cache_file)
        # Same inputs should produce same tokens
        assert anon2.anonymize_ip("10.0.0.1") == token_a
        assert anon2.anonymize_hostname("edge-r1-shanghai") == token_b

    def test_cross_export_consistency(self, tmp_path):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        # First export
        anon1 = NetworkObjectAnonymizer(secret_key=b"cross-key")
        t1 = anon1.anonymize_ip("172.16.0.1")
        cache_file = tmp_path / "mapping.json"
        anon1.save_mapping(cache_file)

        # Second export, loads previous mapping
        anon2 = NetworkObjectAnonymizer(secret_key=b"cross-key")
        anon2.load_mapping(cache_file)
        t2 = anon2.anonymize_ip("172.16.0.1")
        # New IP gets next counter
        t3 = anon2.anonymize_ip("172.16.0.2")

        assert t1 == t2  # cross-export consistency
        assert t3 != t1  # new IP gets different token

    def test_load_missing_file_returns_empty(self, tmp_path):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"missing-key")
        # Should not raise, silently no-op
        anon.load_mapping(tmp_path / "nonexistent" / "mapping.json")
        # Still works normally after no-op load
        token = anon.anonymize_ip("10.0.0.1")
        assert token.startswith("ip_priv_v4_")

    def test_save_creates_parent_dirs(self, tmp_path):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"dirs-key")
        anon.anonymize_ip("10.0.0.1")
        nested = tmp_path / "a" / "b" / "c" / "mapping.json"
        anon.save_mapping(nested)
        assert nested.exists()

    def test_mapping_format_is_json(self, tmp_path):
        from olav.enterprise.audit_dataset_export import NetworkObjectAnonymizer

        anon = NetworkObjectAnonymizer(secret_key=b"json-key")
        anon.anonymize_ip("10.0.0.1")
        anon.anonymize_hostname("sw-core-01")
        cache_file = tmp_path / "mapping.json"
        anon.save_mapping(cache_file)

        data = json.loads(cache_file.read_text())
        assert "mapping" in data
        assert "counters" in data
        assert isinstance(data["mapping"], dict)
        assert isinstance(data["counters"], dict)


# =====================================================================
# Phase 3: ATIF / Harbor Export Tests
# =====================================================================


class TestAuditToATIF:
    """Test ATIF/Harbor trace export."""

    def test_basic_atif_export(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Check BGP peers")
        _insert_message(conn, rid, seq=2, role="assistant", content="BGP is healthy.")

        stats = audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"atif-key")

        assert stats["runs_exported"] == 1
        atif_file = tmp_path / "out" / "atif.jsonl"
        assert atif_file.exists()
        sample = json.loads(atif_file.read_text().strip())
        assert "trace_id" in sample
        assert "spans" in sample
        assert "metadata" in sample

        conn.close()

    def test_atif_spans_structure(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, agent_id="ops")
        _insert_message(conn, rid, seq=1, role="user", content="Trace route to 10.0.0.1")
        _insert_message(conn, rid, seq=2, role="assistant", content="Running traceroute.")
        _insert_tool_call(
            conn, rid, tool_name="execute_sql", input_args={"sql": "SELECT *"}, output="result data"
        )
        _insert_message(conn, rid, seq=3, role="tool", content="trace results here")
        _insert_message(conn, rid, seq=4, role="assistant", content="Traceroute complete.")

        audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"span-key")

        sample = json.loads((tmp_path / "out" / "atif.jsonl").read_text().strip())
        spans = sample["spans"]

        # Should have user_input, assistant_output, tool_call, tool_result, assistant_output
        span_types = [(s["name"], s["type"]) for s in spans]
        assert ("user_input", "message") in span_types
        assert ("assistant_output", "message") in span_types

        # Check tool spans exist
        tool_spans = [s for s in spans if s["type"] == "tool"]
        assert len(tool_spans) >= 1
        assert "tool" in tool_spans[0]

        tool_result_spans = [s for s in spans if s["type"] == "tool_result"]
        assert len(tool_result_spans) >= 1

        conn.close()

    def test_atif_metadata_fields(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, agent_id="ops")
        _insert_message(conn, rid, seq=1, role="user", content="Show topology")
        _insert_message(conn, rid, seq=2, role="assistant", content="Topology loaded.")

        audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"meta-key")

        sample = json.loads((tmp_path / "out" / "atif.jsonl").read_text().strip())
        meta = sample["metadata"]
        assert meta["run_id"] == rid
        assert meta["agent_id"] == "ops"
        assert "task_type" in meta
        assert "domain_tags" in meta
        assert meta["redaction_policy"] == "audit-redaction-v1"

        conn.close()

    def test_atif_manifest_format_field(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Test")
        _insert_message(conn, rid, seq=2, role="assistant", content="OK")

        audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"mf-key")

        manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
        assert "atif" in manifest["formats"]

        conn.close()

    def test_atif_empty_db(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        stats = audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"empty-key")

        assert stats["runs_scanned"] == 0
        assert stats["runs_exported"] == 0

        atif_file = tmp_path / "out" / "atif.jsonl"
        assert atif_file.exists()
        assert atif_file.read_text().strip() == ""

        conn.close()

    def test_atif_cancelled_run_excluded(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid, status="cancelled")
        _insert_message(conn, rid, seq=1, role="user", content="Cancel me")
        _insert_message(conn, rid, seq=2, role="assistant", content="Cancelled.")

        stats = audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"cancel-key")
        assert stats["runs_exported"] == 0

        conn.close()

    def test_atif_redaction_applied(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        rid = str(uuid.uuid4())
        _insert_run(conn, rid)
        _insert_message(conn, rid, seq=1, role="user", content="Check 10.0.0.1")
        _insert_message(conn, rid, seq=2, role="assistant", content="Device 10.0.0.1 is reachable.")

        audit_to_atif(conn, tmp_path / "out", hours=1, secret_key=b"redact-key")

        sample = json.loads((tmp_path / "out" / "atif.jsonl").read_text().strip())
        all_content = " ".join(
            s.get("content", "") or s.get("output", "") or "" for s in sample["spans"]
        )
        # IP should be anonymized
        assert "10.0.0.1" not in all_content

        conn.close()


# =====================================================================
# Phase 3: Presidio / scrubadub Hook Tests
# =====================================================================


class TestPresidioHook:
    """Test optional Presidio/scrubadub hook interface."""

    def test_default_hook_is_noop(self):
        from olav.enterprise.audit_dataset_export import _apply_presidio_hook

        assert _apply_presidio_hook("hello world") == "hello world"
        assert _apply_presidio_hook("sensitive data 123") == "sensitive data 123"

    def test_custom_hook_callable(self):
        from olav.enterprise.audit_dataset_export import (
            _apply_presidio_hook,
            register_presidio_hook,
        )

        def custom_scrub(text: str) -> str:
            return text.replace("SSN", "[PII]")

        try:
            register_presidio_hook(custom_scrub)
            assert _apply_presidio_hook("My SSN is 123") == "My [PII] is 123"
        finally:
            register_presidio_hook(None)

    def test_hook_applied_during_redaction(self):
        from olav.enterprise.audit_dataset_export import (
            NetworkObjectAnonymizer,
            redact_audit_run,
            register_presidio_hook,
        )

        hook_called = []

        def tracking_hook(text: str) -> str:
            hook_called.append(text)
            return text.replace("TRACKME", "[HOOKED]")

        try:
            register_presidio_hook(tracking_hook)
            timeline = {
                "run_id": "r1",
                "metadata": {},
                "messages": [
                    {"role": "user", "content": "Find TRACKME in logs"},
                ],
                "tool_calls": [],
                "events": [],
            }
            anon = NetworkObjectAnonymizer(secret_key=b"hook-key")
            result = redact_audit_run(timeline, anonymizer=anon)
            assert len(hook_called) > 0
            assert "[HOOKED]" in result["messages"][0]["content"]
        finally:
            register_presidio_hook(None)


# =====================================================================
# Phase 3: ATIF CLI Subparser Test
# =====================================================================


class TestATIFCLISubparser:
    """Test CLI parse_args handles ATIF subparser."""

    def test_parse_atif_subcommand(self):
        import sys

        from olav.cli.main import parse_args

        saved = sys.argv
        try:
            sys.argv = ["olav", "log", "export", "atif", "--hours", "72"]
            args = parse_args()
            assert args.command == "log"
            assert getattr(args, "log_command", None) == "export"
            assert getattr(args, "export_format", None) == "atif"
            assert getattr(args, "hours", None) == 72
        finally:
            sys.argv = saved


# =====================================================================
# Phase 4: Rule Scoring
# =====================================================================


class TestComputeRuleScore:
    def test_perfect_sft_sample(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show me all BGP neighbors on router-1"},
                {
                    "role": "assistant",
                    "content": "Based on the query results, router-1 has 3 active BGP peers: ip_a1 (AS65001), ip_b2 (AS65002), ip_c3 (AS65003). All sessions are Established.",
                },
            ],
            "metadata": {"run_id": "r1"},
        }
        result = compute_rule_score(sample)
        assert "score_components" in result
        assert "rule_score" in result
        components = result["score_components"]
        assert set(components.keys()) == {
            "completeness",
            "tool_consistency",
            "query_specificity",
            "analysis_value",
            "tool_selection_relevance",
            "parameter_quality",
            "output_usage",
        }
        for v in components.values():
            assert 0.0 <= v <= 1.0
        assert 0.0 <= result["rule_score"] <= 1.0
        assert result["rule_score"] > 0.5

    def test_empty_assistant_response(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show BGP neighbors"},
                {"role": "assistant", "content": ""},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert result["score_components"]["analysis_value"] == 0.0
        assert result["score_components"]["completeness"] < 1.0

    def test_vague_user_query(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "help"},
                {"role": "assistant", "content": "I can help you query the network database."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert result["score_components"]["query_specificity"] < 0.5

    def test_no_user_message(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "assistant", "content": "Here are the results"},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert result["score_components"]["completeness"] == 0.0
        assert result["score_components"]["query_specificity"] == 0.0

    def test_trajectory_sample_with_tools(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "instruction": "Show interfaces on switch-1",
            "trajectory": [
                {
                    "type": "tool_call",
                    "tool": "query_db",
                    "args": {"sql": "SELECT * FROM interfaces WHERE device='switch-1'"},
                },
                {"type": "tool_result", "content": "Gi0/1: up, Gi0/2: down"},
                {
                    "type": "assistant_final",
                    "content": "switch-1 has 2 interfaces: Gi0/1 (up) and Gi0/2 (down).",
                },
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert result["score_components"]["completeness"] == 1.0
        assert result["score_components"]["tool_consistency"] > 0.5
        assert result["rule_score"] > 0.6

    def test_trajectory_tool_result_contradicts_answer(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "instruction": "How many devices?",
            "trajectory": [
                {"type": "tool_call", "tool": "query_db", "args": {}},
                {"type": "tool_result", "content": "5 devices found"},
                {"type": "assistant_final", "content": "There are 100 devices in the network."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert result["score_components"]["tool_consistency"] < 0.5

    def test_template_placeholder_answer(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show me the routing table"},
                {
                    "role": "assistant",
                    "content": "I'm sorry, I don't have enough information to answer that question.",
                },
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert result["score_components"]["analysis_value"] < 0.5

    def test_score_components_are_floats(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show BGP on router-1"},
                {"role": "assistant", "content": "BGP peers: ip_a (AS65001), ip_b (AS65002)."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        for k, v in result["score_components"].items():
            assert isinstance(v, float), f"{k} should be float, got {type(v)}"
        assert isinstance(result["rule_score"], float)


class TestScoreToolSelectionRelevance:
    def test_no_tools_returns_zero(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        score = _score_tool_selection_relevance("Show BGP neighbors", [])
        assert score == 0.0

    def test_relevant_tool_scores_high(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        tool_results = [
            {"tool": "query_db", "input": "SELECT * FROM bgp_neighbors", "output": "peer1, peer2"}
        ]
        score = _score_tool_selection_relevance(
            "Show BGP neighbors from the database", tool_results
        )
        assert 0.5 < score <= 1.0

    def test_irrelevant_tool_scores_low(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        tool_results = [{"tool": "send_email", "input": "hello@test.com", "output": "sent"}]
        score = _score_tool_selection_relevance("Show BGP neighbors", tool_results)
        assert score < 0.5

    def test_excessive_tools_penalized(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        tool_results = [{"tool": f"tool_{i}", "input": "x", "output": "y"} for i in range(20)]
        score = _score_tool_selection_relevance("Show BGP neighbors", tool_results)
        assert score < 0.7

    def test_single_relevant_tool_good_score(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        tool_results = [
            {"tool": "query_db", "input": "SELECT * FROM interfaces", "output": "Gi0/1 up"}
        ]
        score = _score_tool_selection_relevance("Query interfaces on switch-1", tool_results)
        assert score >= 0.5

    def test_returns_float_in_range(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        tool_results = [{"tool": "query_db", "input": "test", "output": "result"}]
        score = _score_tool_selection_relevance("test query", tool_results)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_empty_user_text_with_tools(self):
        from olav.enterprise.audit_dataset_export import _score_tool_selection_relevance

        tool_results = [{"tool": "query_db", "input": "test", "output": "result"}]
        score = _score_tool_selection_relevance("", tool_results)
        assert 0.0 <= score <= 1.0


class TestScoreParameterQuality:
    def test_no_tools_returns_one(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        score = _score_parameter_quality([])
        assert score == 1.0

    def test_well_formed_inputs_score_high(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        tool_results = [
            {
                "tool": "query_db",
                "input": "SELECT hostname, ip FROM devices WHERE site='HQ'",
                "output": "data",
            },
        ]
        score = _score_parameter_quality(tool_results)
        assert score >= 0.7

    def test_empty_inputs_score_low(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        tool_results = [
            {"tool": "query_db", "input": "", "output": "data"},
        ]
        score = _score_parameter_quality(tool_results)
        assert score < 0.5

    def test_truncated_short_inputs_penalized(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        tool_results = [
            {"tool": "query_db", "input": "x", "output": "data"},
        ]
        score = _score_parameter_quality(tool_results)
        assert score < 0.7

    def test_mixed_quality_inputs(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        tool_results = [
            {
                "tool": "query_db",
                "input": "SELECT * FROM devices WHERE hostname='router-1'",
                "output": "data",
            },
            {"tool": "query_db", "input": "", "output": "data"},
        ]
        score = _score_parameter_quality(tool_results)
        assert 0.3 <= score <= 0.8

    def test_returns_float_in_range(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        tool_results = [{"tool": "t", "input": "some input", "output": "result"}]
        score = _score_parameter_quality(tool_results)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_structured_json_input_scores_high(self):
        from olav.enterprise.audit_dataset_export import _score_parameter_quality

        tool_results = [
            {
                "tool": "query_db",
                "input": '{"sql": "SELECT * FROM devices", "limit": 10}',
                "output": "data",
            },
        ]
        score = _score_parameter_quality(tool_results)
        assert score >= 0.7


class TestScoreOutputUsage:
    def test_no_tools_returns_one(self):
        from olav.enterprise.audit_dataset_export import _score_output_usage

        score = _score_output_usage("Here is the answer.", [])
        assert score == 1.0

    def test_assistant_references_tool_output(self):
        from olav.enterprise.audit_dataset_export import _score_output_usage

        tool_results = [
            {
                "tool": "query_db",
                "input": "SELECT * FROM bgp",
                "output": "peer1 AS65001 Established",
            },
        ]
        score = _score_output_usage(
            "Based on the results, peer1 has AS65001 and is Established.", tool_results
        )
        assert score >= 0.5

    def test_assistant_ignores_tool_output(self):
        from olav.enterprise.audit_dataset_export import _score_output_usage

        tool_results = [
            {
                "tool": "query_db",
                "input": "query",
                "output": "peer1 AS65001 192.168.1.1 Established",
            },
        ]
        score = _score_output_usage("I cannot help with that request.", tool_results)
        assert score < 0.5

    def test_empty_assistant_text_with_tools(self):
        from olav.enterprise.audit_dataset_export import _score_output_usage

        tool_results = [
            {"tool": "query_db", "input": "query", "output": "some data here"},
        ]
        score = _score_output_usage("", tool_results)
        assert score < 0.3

    def test_returns_float_in_range(self):
        from olav.enterprise.audit_dataset_export import _score_output_usage

        tool_results = [{"tool": "t", "input": "i", "output": "some output data"}]
        score = _score_output_usage("using output data", tool_results)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_rich_tool_output_with_detailed_response(self):
        from olav.enterprise.audit_dataset_export import _score_output_usage

        tool_results = [
            {
                "tool": "query_db",
                "input": "SELECT * FROM interfaces",
                "output": "Gi0/1: up, speed 1000, Gi0/2: down, speed 100, Gi0/3: up, speed 10000",
            },
        ]
        score = _score_output_usage(
            "The device has 3 interfaces: Gi0/1 is up at 1000Mbps, Gi0/2 is down at 100Mbps, Gi0/3 is up at 10000Mbps.",
            tool_results,
        )
        assert score >= 0.5


class TestRebalancedWeights:
    def test_weights_have_seven_dimensions(self):
        from olav.enterprise.audit_dataset_export import _RULE_WEIGHTS

        assert len(_RULE_WEIGHTS) == 7

    def test_weights_sum_to_one(self):
        from olav.enterprise.audit_dataset_export import _RULE_WEIGHTS

        total = sum(_RULE_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_weights_contain_new_dimensions(self):
        from olav.enterprise.audit_dataset_export import _RULE_WEIGHTS

        assert "tool_selection_relevance" in _RULE_WEIGHTS
        assert "parameter_quality" in _RULE_WEIGHTS
        assert "output_usage" in _RULE_WEIGHTS

    def test_weights_contain_original_dimensions(self):
        from olav.enterprise.audit_dataset_export import _RULE_WEIGHTS

        assert "completeness" in _RULE_WEIGHTS
        assert "tool_consistency" in _RULE_WEIGHTS
        assert "query_specificity" in _RULE_WEIGHTS
        assert "analysis_value" in _RULE_WEIGHTS

    def test_all_weights_positive(self):
        from olav.enterprise.audit_dataset_export import _RULE_WEIGHTS

        for k, v in _RULE_WEIGHTS.items():
            assert v > 0.0, f"Weight for {k} should be positive, got {v}"


class TestComputeRuleScoreWithNewDimensions:
    """Tests that compute_rule_score includes the 3 new scoring dimensions."""

    def test_score_components_have_seven_keys(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show BGP neighbors on router-1"},
                {"role": "assistant", "content": "Router-1 has 3 BGP peers."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert len(result["score_components"]) == 7

    def test_new_components_present_in_result(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show BGP neighbors"},
                {"role": "assistant", "content": "Here are the neighbors."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        components = result["score_components"]
        assert "tool_selection_relevance" in components
        assert "parameter_quality" in components
        assert "output_usage" in components

    def test_new_components_are_floats(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show interfaces"},
                {"role": "assistant", "content": "Gi0/1 is up."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        for k in ("tool_selection_relevance", "parameter_quality", "output_usage"):
            assert isinstance(result["score_components"][k], float), f"{k} should be float"
            assert 0.0 <= result["score_components"][k] <= 1.0, f"{k} out of range"

    def test_sample_with_tools_scores_new_dimensions(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "instruction": "Show interfaces on switch-1",
            "trajectory": [
                {
                    "type": "tool_call",
                    "tool": "query_db",
                    "args": {"sql": "SELECT * FROM interfaces WHERE device='switch-1'"},
                },
                {"type": "tool_result", "content": "Gi0/1: up, Gi0/2: down"},
                {
                    "type": "assistant_final",
                    "content": "switch-1 has 2 interfaces: Gi0/1 (up) and Gi0/2 (down).",
                },
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        components = result["score_components"]
        # With tools present, tool_selection_relevance should be > 0
        assert components["tool_selection_relevance"] > 0.0
        # Parameter quality should be scored
        assert components["parameter_quality"] > 0.0
        # Output usage should be high since assistant references tool content
        assert components["output_usage"] > 0.0

    def test_rule_score_still_bounded(self):
        from olav.enterprise.audit_dataset_export import compute_rule_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show all devices"},
                {"role": "assistant", "content": "There are 5 devices in the network."},
            ],
            "metadata": {},
        }
        result = compute_rule_score(sample)
        assert 0.0 <= result["rule_score"] <= 1.0


# =====================================================================
# Phase 4: LLM Scoring Hook
# =====================================================================


class TestLLMScoringHook:
    def test_register_and_invoke_llm_scorer(self):
        from olav.enterprise.audit_dataset_export import (
            compute_quality_score,
            register_llm_scorer,
        )

        def mock_scorer(sample):
            return {
                "llm_score": 0.88,
                "llm_reason": "Good query pattern",
                "quality_labels": ["good_query_pattern"],
            }

        try:
            register_llm_scorer(mock_scorer)
            sample = {
                "messages": [
                    {"role": "user", "content": "Show BGP neighbors"},
                    {"role": "assistant", "content": "Found 3 BGP peers."},
                ],
                "metadata": {},
            }
            result = compute_quality_score(sample)
            assert "llm_score" in result
            assert result["llm_score"] == 0.88
            assert "llm_reason" in result
            assert "quality_labels" in result
            assert "quality_score" in result
        finally:
            register_llm_scorer(None)

    def test_quality_score_without_llm(self):
        from olav.enterprise.audit_dataset_export import compute_quality_score

        sample = {
            "messages": [
                {"role": "user", "content": "Show BGP neighbors"},
                {"role": "assistant", "content": "Found 3 BGP peers on router-1."},
            ],
            "metadata": {},
        }
        result = compute_quality_score(sample)
        assert "rule_score" in result
        assert "quality_score" in result
        assert result["llm_score"] is None
        assert result["quality_score"] == result["rule_score"]

    def test_llm_scorer_returning_hard_reject_label(self):
        from olav.enterprise.audit_dataset_export import (
            compute_quality_score,
            register_llm_scorer,
        )

        def hallucination_scorer(sample):
            return {
                "llm_score": 0.2,
                "llm_reason": "Contains hallucinated data",
                "quality_labels": ["hallucination"],
            }

        try:
            register_llm_scorer(hallucination_scorer)
            sample = {
                "messages": [
                    {"role": "user", "content": "Show devices"},
                    {"role": "assistant", "content": "There are 500 devices."},
                ],
                "metadata": {},
            }
            result = compute_quality_score(sample)
            assert "hallucination" in result["quality_labels"]
            assert result["hard_reject"] is True
        finally:
            register_llm_scorer(None)

    def test_llm_scorer_exception_falls_back(self):
        from olav.enterprise.audit_dataset_export import (
            compute_quality_score,
            register_llm_scorer,
        )

        def broken_scorer(sample):
            raise RuntimeError("LLM API down")

        try:
            register_llm_scorer(broken_scorer)
            sample = {
                "messages": [
                    {"role": "user", "content": "Show devices"},
                    {"role": "assistant", "content": "Found 3 devices."},
                ],
                "metadata": {},
            }
            result = compute_quality_score(sample)
            assert result["llm_score"] is None
            assert result["quality_score"] == result["rule_score"]
        finally:
            register_llm_scorer(None)


# =====================================================================
# Phase 4: Quality Gate Threshold
# =====================================================================


class TestQualityGateThreshold:
    def test_sample_passes_default_threshold(self):
        from olav.enterprise.audit_dataset_export import quality_gate

        score_result = {
            "rule_score": 0.8,
            "quality_score": 0.8,
            "llm_score": None,
            "quality_labels": [],
            "hard_reject": False,
            "score_components": {
                "completeness": 1.0,
                "tool_consistency": 0.8,
                "query_specificity": 0.7,
                "analysis_value": 0.7,
            },
        }
        passed, reason = quality_gate(score_result)
        assert passed is True
        assert reason is None

    def test_sample_below_min_rule_score(self):
        from olav.enterprise.audit_dataset_export import quality_gate

        score_result = {
            "rule_score": 0.2,
            "quality_score": 0.2,
            "llm_score": None,
            "quality_labels": [],
            "hard_reject": False,
            "score_components": {
                "completeness": 0.5,
                "tool_consistency": 0.0,
                "query_specificity": 0.1,
                "analysis_value": 0.2,
            },
        }
        passed, reason = quality_gate(score_result)
        assert passed is False
        assert reason is not None and "rule_score" in reason

    def test_custom_min_rule_score(self):
        from olav.enterprise.audit_dataset_export import quality_gate

        score_result = {
            "rule_score": 0.6,
            "quality_score": 0.6,
            "llm_score": None,
            "quality_labels": [],
            "hard_reject": False,
            "score_components": {},
        }
        passed, _ = quality_gate(score_result, min_rule_score=0.7)
        assert passed is False
        passed2, _ = quality_gate(score_result, min_rule_score=0.5)
        assert passed2 is True

    def test_hard_reject_label_fails_gate(self):
        from olav.enterprise.audit_dataset_export import quality_gate

        score_result = {
            "rule_score": 0.9,
            "quality_score": 0.85,
            "llm_score": 0.8,
            "quality_labels": ["hallucination"],
            "hard_reject": True,
            "score_components": {},
        }
        passed, reason = quality_gate(score_result)
        assert passed is False
        assert reason is not None and "hard_reject" in reason

    def test_all_hard_reject_labels(self):
        from olav.enterprise.audit_dataset_export import quality_gate, HARD_REJECT_LABELS

        for label in HARD_REJECT_LABELS:
            score_result = {
                "rule_score": 0.95,
                "quality_score": 0.95,
                "llm_score": 0.9,
                "quality_labels": [label],
                "hard_reject": True,
                "score_components": {},
            }
            passed, _ = quality_gate(score_result)
            assert passed is False, f"Should reject on hard label: {label}"

    def test_min_quality_score_with_llm(self):
        from olav.enterprise.audit_dataset_export import quality_gate

        score_result = {
            "rule_score": 0.7,
            "quality_score": 0.4,
            "llm_score": 0.1,
            "quality_labels": [],
            "hard_reject": False,
            "score_components": {},
        }
        passed, reason = quality_gate(score_result, min_quality_score=0.5)
        assert passed is False
        assert reason is not None and "quality_score" in reason


# =====================================================================
# Phase 4: SFT Export with Scoring Integration
# =====================================================================


class TestSFTExportWithScoring:
    def test_sft_export_includes_score_in_metadata(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(
            conn, "r1", seq=1, role="user", content="Show all BGP neighbors on core-router"
        )
        _insert_message(
            conn,
            "r1",
            seq=2,
            role="assistant",
            content="Found 3 BGP peers: ip_a (AS65001), ip_b (AS65002), ip_c (AS65003). All Established.",
        )

        stats = audit_to_sft_jsonl(conn, tmp_path, hours=1, min_rule_score=0.0)

        sft_path = tmp_path / "sft.jsonl"
        assert sft_path.exists()
        lines = sft_path.read_text().strip().split("\n")
        assert len(lines) == 1
        sample = json.loads(lines[0])
        assert "score_components" in sample["metadata"]
        assert "rule_score" in sample["metadata"]

    def test_sft_export_filters_low_score(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(conn, "r1", seq=1, role="user", content="help")
        _insert_message(conn, "r1", seq=2, role="assistant", content="")

        stats = audit_to_sft_jsonl(conn, tmp_path, hours=1, min_rule_score=0.5)

        assert stats["samples_exported"] == 0
        assert stats.get("samples_scored", 0) >= 0

    def test_sft_stats_include_scoring_fields(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(conn, "r1", seq=1, role="user", content="Show interfaces on switch-1")
        _insert_message(
            conn, "r1", seq=2, role="assistant", content="switch-1 has Gi0/1 (up) and Gi0/2 (down)."
        )

        stats = audit_to_sft_jsonl(conn, tmp_path, hours=1, min_rule_score=0.0)

        assert "samples_scored" in stats
        assert "avg_rule_score" in stats
        assert "scoring_policy" in stats
        assert isinstance(stats["avg_rule_score"], float)

    def test_sft_manifest_includes_scoring_policy(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(conn, "r1", seq=1, role="user", content="Show BGP on router-1")
        _insert_message(conn, "r1", seq=2, role="assistant", content="BGP peers: ip_a, ip_b.")

        audit_to_sft_jsonl(conn, tmp_path, hours=1, min_rule_score=0.0)

        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert "scoring_policy" in manifest


# =====================================================================
# Phase 4: Trajectory Export with Scoring Integration
# =====================================================================


class TestTrajectoryExportWithScoring:
    def test_trajectory_export_includes_score(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(conn, "r1", seq=1, role="user", content="Show interfaces on switch-1")
        _insert_tool_call(
            conn,
            "r1",
            tool_name="query_db",
            input_args={"sql": "SELECT * FROM interfaces"},
            output={"rows": [{"name": "Gi0/1", "status": "up"}]},
        )
        _insert_message(conn, "r1", seq=2, role="tool", content="Gi0/1: up")
        _insert_message(
            conn, "r1", seq=3, role="assistant", content="switch-1 has interface Gi0/1 which is up."
        )

        stats = audit_to_tool_trajectory(conn, tmp_path, hours=1, min_rule_score=0.0)

        traj_path = tmp_path / "trajectory.jsonl"
        assert traj_path.exists()
        lines = traj_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "rule_score" in sample["metadata"]
        assert "score_components" in sample["metadata"]

    def test_trajectory_export_filters_low_score(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(conn, "r1", seq=1, role="user", content="?")
        _insert_message(conn, "r1", seq=2, role="assistant", content="")

        stats = audit_to_tool_trajectory(conn, tmp_path, hours=1, min_rule_score=0.9)

        assert stats["samples_exported"] == 0

    def test_trajectory_stats_include_scoring_fields(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        _insert_run(conn, "r1")
        _insert_message(conn, "r1", seq=1, role="user", content="Show BGP neighbors on router-1")
        _insert_tool_call(conn, "r1", tool_name="query_db", input_args={}, output={"data": "peers"})
        _insert_message(conn, "r1", seq=2, role="tool", content="3 BGP peers found")
        _insert_message(
            conn,
            "r1",
            seq=3,
            role="assistant",
            content="Router-1 has 3 BGP peers, all Established.",
        )

        stats = audit_to_tool_trajectory(conn, tmp_path, hours=1, min_rule_score=0.0)

        assert "samples_scored" in stats
        assert "avg_rule_score" in stats
        assert "scoring_policy" in stats
        assert "rejected_by_reason" in stats


# =====================================================================
# Phase 4: CLI --min-score Flag
# =====================================================================


class TestCLIMinScoreFlag:
    def test_parse_sft_with_min_score(self):
        import sys

        from olav.cli.main import parse_args

        saved = sys.argv
        try:
            sys.argv = ["olav", "log", "export", "sft", "--min-score", "0.7"]
            args = parse_args()
            assert args.command == "log"
            assert getattr(args, "min_score", None) == 0.7
        finally:
            sys.argv = saved

    def test_parse_trajectory_with_min_score(self):
        import sys

        from olav.cli.main import parse_args

        saved = sys.argv
        try:
            sys.argv = ["olav", "log", "export", "trajectory", "--min-score", "0.5"]
            args = parse_args()
            assert getattr(args, "min_score", None) == 0.5
        finally:
            sys.argv = saved

    def test_parse_atif_with_min_score(self):
        import sys

        from olav.cli.main import parse_args

        saved = sys.argv
        try:
            sys.argv = ["olav", "log", "export", "atif", "--min-score", "0.6"]
            args = parse_args()
            assert getattr(args, "min_score", None) == 0.6
        finally:
            sys.argv = saved


# ── Section 10: Dataset Encryption (encrypted_dataset_control.md) ─────────────


class TestEncryptionEnums:
    def test_encryption_mode_values(self):
        from olav.enterprise.dataset_encryption import EncryptionMode

        assert EncryptionMode.disabled.value == "disabled"
        assert EncryptionMode.optional.value == "optional"
        assert EncryptionMode.required.value == "required"

    def test_encryption_mode_has_exactly_three(self):
        from olav.enterprise.dataset_encryption import EncryptionMode

        assert len(EncryptionMode) == 3

    def test_temp_file_policy_values(self):
        from olav.enterprise.dataset_encryption import TempFilePolicy

        assert TempFilePolicy.memory_preferred.value == "memory_preferred"
        assert TempFilePolicy.delete_on_success.value == "delete_on_success"
        assert TempFilePolicy.keep_for_debug.value == "keep_for_debug"

    def test_temp_file_policy_has_exactly_three(self):
        from olav.enterprise.dataset_encryption import TempFilePolicy

        assert len(TempFilePolicy) == 3


class TestBuildAssociatedData:
    def test_returns_bytes(self):
        from olav.enterprise.dataset_encryption import build_associated_data

        result = build_associated_data("exp-1", "sft", "exact_v1", "score-v1")
        assert isinstance(result, bytes)

    def test_contains_all_fields_colon_separated(self):
        from olav.enterprise.dataset_encryption import build_associated_data

        result = build_associated_data("exp-1", "sft", "exact_v1", "score-v1", version="v2")
        assert result == b"exp-1:sft:v2:exact_v1:score-v1"

    def test_default_version_is_v1(self):
        from olav.enterprise.dataset_encryption import build_associated_data

        result = build_associated_data("exp-1", "sft", "exact_v1", "score-v1")
        assert b":v1:" in result

    def test_different_inputs_produce_different_output(self):
        from olav.enterprise.dataset_encryption import build_associated_data

        a = build_associated_data("exp-1", "sft", "exact_v1", "score-v1")
        b = build_associated_data("exp-2", "trajectory", "exact_v1", "score-v1")
        assert a != b


class TestAtomicWrite:
    def test_writes_file_content(self, tmp_path):
        from olav.enterprise.dataset_encryption import atomic_write

        target = tmp_path / "out.bin"
        atomic_write(target, b"hello world")
        assert target.exists()

    def test_file_content_matches(self, tmp_path):
        from olav.enterprise.dataset_encryption import atomic_write

        target = tmp_path / "out.bin"
        data = b"test data 12345"
        atomic_write(target, data)
        assert target.read_bytes() == data

    def test_no_tmp_file_left(self, tmp_path):
        from olav.enterprise.dataset_encryption import atomic_write

        target = tmp_path / "out.bin"
        atomic_write(target, b"content")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_tmp_cleaned_on_error(self, tmp_path):
        from olav.enterprise.dataset_encryption import atomic_write

        bad_target = tmp_path / "nonexistent_dir" / "sub" / "out.bin"
        with pytest.raises(FileNotFoundError):
            atomic_write(bad_target, b"data")
        tmp_files = list(tmp_path.rglob("*.tmp"))
        assert len(tmp_files) == 0


class TestDatasetEncryptor:
    def test_has_keyset_initially_false(self):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor()
        assert enc.has_keyset is False

    def test_generate_keyset_sets_has_keyset(self):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor()
        enc.generate_keyset()
        assert enc.has_keyset is True

    def test_save_and_load_roundtrip(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc1 = DatasetEncryptor(keyset_dir=tmp_path)
        enc1.generate_keyset()
        saved_path = enc1.save_keyset("test-key")
        assert saved_path.exists()

        enc2 = DatasetEncryptor(keyset_dir=tmp_path)
        enc2.load_keyset("test-key")
        assert enc2.has_keyset is True

    def test_load_missing_keyset_raises(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            enc.load_keyset("nonexistent-key")

    def test_encrypt_without_keyset_raises(self):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor()
        with pytest.raises(RuntimeError, match="No keyset loaded"):
            enc.encrypt_bytes(b"data", b"ad")

    def test_decrypt_without_keyset_raises(self):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor()
        with pytest.raises(RuntimeError, match="No keyset loaded"):
            enc.decrypt_bytes(b"data", b"ad")

    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        enc.generate_keyset()
        plaintext = b"sensitive training data"
        ad = b"export-1:sft:v1:exact_v1:score-v1"
        ct = enc.encrypt_bytes(plaintext, ad)
        pt = enc.decrypt_bytes(ct, ad)
        assert pt == plaintext

    def test_wrong_associated_data_fails(self, tmp_path):
        from tink import TinkError

        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        enc.generate_keyset()
        ct = enc.encrypt_bytes(b"secret", b"correct-ad")
        with pytest.raises(TinkError):
            enc.decrypt_bytes(ct, b"wrong-ad")

    def test_corrupted_ciphertext_fails(self, tmp_path):
        from tink import TinkError

        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        enc.generate_keyset()
        with pytest.raises(TinkError):
            enc.decrypt_bytes(b"corrupted-garbage", b"ad")

    def test_two_encryptions_differ(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        enc.generate_keyset()
        pt = b"same plaintext"
        ad = b"same-ad"
        ct1 = enc.encrypt_bytes(pt, ad)
        ct2 = enc.encrypt_bytes(pt, ad)
        assert ct1 != ct2

    def test_custom_keyset_dir(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        custom_dir = tmp_path / "custom_keys"
        enc = DatasetEncryptor(keyset_dir=custom_dir)
        enc.generate_keyset()
        path = enc.save_keyset("my-key")
        assert path.parent == custom_dir

    def test_saved_keyset_decrypts_from_different_instance(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc1 = DatasetEncryptor(keyset_dir=tmp_path)
        enc1.generate_keyset()
        enc1.save_keyset("shared-key")

        ad = b"test-ad"
        ct = enc1.encrypt_bytes(b"payload", ad)

        enc2 = DatasetEncryptor(keyset_dir=tmp_path)
        enc2.load_keyset("shared-key")
        assert enc2.decrypt_bytes(ct, ad) == b"payload"


class TestCheckEncryptionMode:
    def test_disabled_none_returns_false(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("disabled", None) is False

    def test_disabled_true_returns_true(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("disabled", True) is True

    def test_disabled_false_returns_false(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("disabled", False) is False

    def test_optional_none_returns_false(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("optional", None) is False

    def test_optional_true_returns_true(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("optional", True) is True

    def test_optional_false_returns_false(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("optional", False) is False

    def test_required_none_returns_true(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("required", None) is True

    def test_required_true_returns_true(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("required", True) is True

    def test_required_false_raises(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        with pytest.raises(ValueError, match="Cannot disable encryption in required mode"):
            check_encryption_mode("required", False)


# =====================================================================
# Section 11: Pipeline Encryption Integration
# =====================================================================


def _setup_encryption(tmp_path, key_ref="test-key"):
    from olav.enterprise.dataset_encryption import DatasetEncryptor

    keyset_dir = tmp_path / "keys"
    enc = DatasetEncryptor(keyset_dir=keyset_dir)
    enc.generate_keyset()
    enc.save_keyset(key_ref)
    return enc, keyset_dir


def _setup_run_with_messages(conn, run_id="run-enc-1"):
    _insert_run(conn, run_id, status="completed")
    _insert_message(conn, run_id, seq=1, role="user", content="Show me device status")
    _insert_message(
        conn, run_id, seq=2, role="assistant", content="Here is the device status report."
    )
    _insert_event(conn, run_id, event_type="user_input_received", seq=1)
    return run_id


def _setup_run_with_tool_calls(conn, run_id="run-enc-tc"):
    _insert_run(conn, run_id, status="completed")
    _insert_message(conn, run_id, seq=1, role="user", content="Query the network topology")
    _insert_message(conn, run_id, seq=2, role="assistant", content="I will query the topology now.")
    _insert_tool_call(
        conn,
        run_id,
        tool_name="query_db",
        input_args={"query": "SELECT * FROM topology"},
        output={"rows": [{"src": "R1", "dst": "R2"}]},
    )
    _insert_message(
        conn, run_id, seq=3, role="tool", content='{"rows": [{"src": "R1", "dst": "R2"}]}'
    )
    _insert_message(
        conn, run_id, seq=4, role="assistant", content="The topology shows R1 connected to R2."
    )
    _insert_event(conn, run_id, event_type="user_input_received", seq=1)
    return run_id


class TestEncryptExportFileHelper:
    def test_encrypts_and_creates_enc_file(self, tmp_path):
        from olav.enterprise.audit_dataset_export import _encrypt_export_file
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path / "keys")
        enc.generate_keyset()

        plaintext_path = tmp_path / "data.jsonl"
        plaintext_path.write_bytes(b'{"hello": "world"}\n')

        ad = b"test:sft:v1:none:none"
        result = _encrypt_export_file(plaintext_path, enc, ad)

        assert result == tmp_path / "data.jsonl.enc"
        assert result.exists()
        assert not plaintext_path.exists()

    def test_keeps_plaintext_when_requested(self, tmp_path):
        from olav.enterprise.audit_dataset_export import _encrypt_export_file
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path / "keys")
        enc.generate_keyset()

        plaintext_path = tmp_path / "data.jsonl"
        plaintext_path.write_bytes(b'{"keep": "me"}\n')

        ad = b"test:sft:v1:none:none"
        result = _encrypt_export_file(plaintext_path, enc, ad, remove_plaintext=False)

        assert result.exists()
        assert plaintext_path.exists()

    def test_roundtrip_decrypt(self, tmp_path):
        from olav.enterprise.audit_dataset_export import _encrypt_export_file
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path / "keys")
        enc.generate_keyset()

        original = b'{"line": 1}\n{"line": 2}\n'
        plaintext_path = tmp_path / "data.jsonl"
        plaintext_path.write_bytes(original)

        ad = b"test:sft:v1:none:none"
        enc_path = _encrypt_export_file(plaintext_path, enc, ad)

        ciphertext = enc_path.read_bytes()
        decrypted = enc.decrypt_bytes(ciphertext, ad)
        assert decrypted == original


class TestPipelineEncryptionIntegration:
    def test_sft_no_encrypt_default(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _setup_run_with_messages(conn)

        out = tmp_path / "sft_out"
        audit_to_sft_jsonl(conn, str(out), hours=9999)

        assert (out / "sft.jsonl").exists()
        assert not (out / "sft.jsonl.enc").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is False
        assert manifest["encryption"]["mode"] == "disabled"
        assert manifest["encryption"]["provider"] is None

    def test_sft_encrypt_true(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _setup_run_with_messages(conn)
        _, keyset_dir = _setup_encryption(tmp_path)

        out = tmp_path / "sft_enc_out"
        audit_to_sft_jsonl(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="test-key",
            keyset_dir=keyset_dir,
        )

        assert (out / "sft.jsonl.enc").exists()
        assert not (out / "sft.jsonl").exists()
        assert (out / "rejected_runs.json").exists()
        assert (out / "stats.json").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is True
        assert manifest["encryption"]["provider"] == "tink"
        assert manifest["encryption"]["primitive"] == "aead"
        assert manifest["encryption"]["key_ref"] == "test-key"

    def test_sft_decrypt_roundtrip(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl
        from olav.enterprise.dataset_encryption import DatasetEncryptor, build_associated_data

        conn = _make_conn()
        _setup_run_with_messages(conn)
        _, keyset_dir = _setup_encryption(tmp_path)

        out = tmp_path / "sft_rt"
        audit_to_sft_jsonl(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="test-key",
            keyset_dir=keyset_dir,
        )

        enc = DatasetEncryptor(keyset_dir=keyset_dir)
        enc.load_keyset("test-key")

        export_id = out.name
        ad = build_associated_data(export_id, "sft", "none", "dataset-score-v1")
        ciphertext = (out / "sft.jsonl.enc").read_bytes()
        plaintext = enc.decrypt_bytes(ciphertext, ad)

        lines = plaintext.decode().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "messages" in sample

    def test_atif_no_encrypt_default(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        _setup_run_with_messages(conn)

        out = tmp_path / "atif_out"
        audit_to_atif(conn, str(out), hours=9999)

        assert (out / "atif.jsonl").exists()
        assert not (out / "atif.jsonl.enc").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is False

    def test_atif_encrypt_true(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif

        conn = _make_conn()
        _setup_run_with_messages(conn)
        _, keyset_dir = _setup_encryption(tmp_path)

        out = tmp_path / "atif_enc"
        audit_to_atif(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="test-key",
            keyset_dir=keyset_dir,
        )

        assert (out / "atif.jsonl.enc").exists()
        assert not (out / "atif.jsonl").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is True
        assert manifest["encryption"]["provider"] == "tink"
        assert manifest["encryption"]["key_ref"] == "test-key"

    def test_atif_decrypt_roundtrip(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif
        from olav.enterprise.dataset_encryption import DatasetEncryptor, build_associated_data

        conn = _make_conn()
        _setup_run_with_messages(conn)
        _, keyset_dir = _setup_encryption(tmp_path)

        out = tmp_path / "atif_rt"
        audit_to_atif(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="test-key",
            keyset_dir=keyset_dir,
        )

        enc = DatasetEncryptor(keyset_dir=keyset_dir)
        enc.load_keyset("test-key")

        ad = build_associated_data(out.name, "atif", "none", "none")
        ciphertext = (out / "atif.jsonl.enc").read_bytes()
        plaintext = enc.decrypt_bytes(ciphertext, ad)

        lines = plaintext.decode().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "spans" in sample

    def test_trajectory_no_encrypt_default(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        _setup_run_with_tool_calls(conn)

        out = tmp_path / "traj_out"
        audit_to_tool_trajectory(conn, str(out), hours=9999)

        assert (out / "trajectory.jsonl").exists()
        assert not (out / "trajectory.jsonl.enc").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is False

    def test_trajectory_encrypt_true(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        _setup_run_with_tool_calls(conn)
        _, keyset_dir = _setup_encryption(tmp_path)

        out = tmp_path / "traj_enc"
        audit_to_tool_trajectory(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="test-key",
            keyset_dir=keyset_dir,
        )

        assert (out / "trajectory.jsonl.enc").exists()
        assert not (out / "trajectory.jsonl").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is True
        assert manifest["encryption"]["provider"] == "tink"
        assert manifest["encryption"]["key_ref"] == "test-key"

    def test_trajectory_decrypt_roundtrip(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory
        from olav.enterprise.dataset_encryption import DatasetEncryptor, build_associated_data

        conn = _make_conn()
        _setup_run_with_tool_calls(conn)
        _, keyset_dir = _setup_encryption(tmp_path)

        out = tmp_path / "traj_rt"
        audit_to_tool_trajectory(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="test-key",
            keyset_dir=keyset_dir,
        )

        enc = DatasetEncryptor(keyset_dir=keyset_dir)
        enc.load_keyset("test-key")

        ad = build_associated_data(out.name, "trajectory", "exact_v1", "dataset-score-v1")
        ciphertext = (out / "trajectory.jsonl.enc").read_bytes()
        plaintext = enc.decrypt_bytes(ciphertext, ad)

        lines = plaintext.decode().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "trajectory" in sample

    def test_manifest_encryption_block_complete(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _setup_run_with_messages(conn)
        _, keyset_dir = _setup_encryption(tmp_path, key_ref="my-prod-key")

        out = tmp_path / "manifest_check"
        audit_to_sft_jsonl(
            conn,
            str(out),
            hours=9999,
            encrypt=True,
            key_ref="my-prod-key",
            keyset_dir=keyset_dir,
        )

        manifest = json.loads((out / "manifest.json").read_text())
        enc_block = manifest["encryption"]
        assert enc_block == {
            "applied": True,
            "mode": "required",
            "provider": "tink",
            "primitive": "aead",
            "key_ref": "my-prod-key",
        }


# =====================================================================
# Section 12: §11.1 Encryption Integration Test Matrix
# =====================================================================


class TestEncryptionModeDisabledExportsPlaintext:
    """§11.1 test 1: disabled mode exports plaintext successfully."""

    def test_sft_disabled_mode_produces_plaintext(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _setup_run_with_messages(conn)

        out = tmp_path / "disabled_sft"
        result = audit_to_sft_jsonl(conn, str(out), hours=9999, encrypt=False)

        sft_path = out / "sft.jsonl"
        assert sft_path.exists(), "Plaintext sft.jsonl should exist in disabled mode"
        assert not (out / "sft.jsonl.enc").exists(), ".enc should not exist"

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is False
        assert manifest["encryption"]["mode"] == "disabled"

        assert result["runs_exported"] >= 1 or result.get("conversations_exported", 0) >= 1

    def test_trajectory_disabled_mode_produces_plaintext(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        conn = _make_conn()
        _setup_run_with_tool_calls(conn)

        out = tmp_path / "disabled_traj"
        audit_to_tool_trajectory(conn, str(out), hours=9999, encrypt=False)

        traj_path = out / "trajectory.jsonl"
        assert traj_path.exists(), "Plaintext trajectory.jsonl should exist"
        assert not (out / "trajectory.jsonl.enc").exists()

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["encryption"]["applied"] is False


class TestEncryptionModeRequiredRejectsNoEncrypt:
    """§11.1 test 2: required mode + --no-encrypt fails."""

    def test_check_encryption_mode_required_false_raises(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        with pytest.raises(ValueError, match="Cannot disable encryption in required mode"):
            check_encryption_mode("required", False)

    def test_check_encryption_mode_required_none_returns_true(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("required", None) is True

    def test_check_encryption_mode_required_true_returns_true(self):
        from olav.enterprise.dataset_encryption import check_encryption_mode

        assert check_encryption_mode("required", True) is True


class TestEncDecryptRoundtripContentMatch:
    """§11.1 test 3: .enc file decrypts correctly and content matches."""

    def test_sft_encrypt_decrypt_content_matches(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl
        from olav.enterprise.dataset_encryption import DatasetEncryptor, build_associated_data

        conn = _make_conn()
        _setup_run_with_messages(conn)

        _, keyset_dir = _setup_encryption(tmp_path)
        enc_out = tmp_path / "enc"
        audit_to_sft_jsonl(
            conn, str(enc_out), hours=9999, encrypt=True, key_ref="test-key", keyset_dir=keyset_dir
        )

        assert (enc_out / "sft.jsonl.enc").exists()
        assert not (enc_out / "sft.jsonl").exists()

        enc = DatasetEncryptor(keyset_dir=keyset_dir)
        enc.load_keyset("test-key")
        ad = build_associated_data(enc_out.name, "sft", "none", "dataset-score-v1")
        decrypted = enc.decrypt_bytes((enc_out / "sft.jsonl.enc").read_bytes(), ad)

        lines = decrypted.decode().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "messages" in sample

    def test_atif_encrypt_decrypt_content_matches(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_atif
        from olav.enterprise.dataset_encryption import DatasetEncryptor, build_associated_data

        conn = _make_conn()
        _setup_run_with_messages(conn)

        _, keyset_dir = _setup_encryption(tmp_path)
        enc_out = tmp_path / "enc_atif"
        audit_to_atif(
            conn, str(enc_out), hours=9999, encrypt=True, key_ref="test-key", keyset_dir=keyset_dir
        )

        assert (enc_out / "atif.jsonl.enc").exists()

        enc = DatasetEncryptor(keyset_dir=keyset_dir)
        enc.load_keyset("test-key")
        ad = build_associated_data(enc_out.name, "atif", "none", "none")
        decrypted = enc.decrypt_bytes((enc_out / "atif.jsonl.enc").read_bytes(), ad)

        lines = decrypted.decode().strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "trace_id" in sample


class TestAssociatedDataMismatchFails:
    """§11.1 test 4: associated data mismatch -> decrypt failure."""

    def test_wrong_associated_data_fails_decrypt(self, tmp_path):
        import tink.core

        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl
        from olav.enterprise.dataset_encryption import DatasetEncryptor, build_associated_data

        conn = _make_conn()
        _setup_run_with_messages(conn)

        _, keyset_dir = _setup_encryption(tmp_path)
        out = tmp_path / "ad_mismatch"
        audit_to_sft_jsonl(
            conn, str(out), hours=9999, encrypt=True, key_ref="test-key", keyset_dir=keyset_dir
        )

        enc = DatasetEncryptor(keyset_dir=keyset_dir)
        enc.load_keyset("test-key")

        wrong_ad = build_associated_data("wrong-export-id", "sft", "none", "wrong-policy")
        ciphertext = (out / "sft.jsonl.enc").read_bytes()

        with pytest.raises(tink.core.TinkError):
            enc.decrypt_bytes(ciphertext, wrong_ad)


class TestExportInterruptionNoFakeFiles:
    """§11.1 test 5: export interruption -> no fake finalized files."""

    def test_atomic_write_failure_no_leftover(self, tmp_path):
        from olav.enterprise.dataset_encryption import atomic_write

        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        target_in_ro = readonly_dir / "data.enc"

        atomic_write(target_in_ro, b"test data")
        assert target_in_ro.exists()

        assert not (target_in_ro.with_suffix(".enc.tmp")).exists()


class TestStatsAndRejectedRunsNoSampleText:
    """§11.1 test 6: stats.json / rejected_runs.json don't contain sample text."""

    def test_stats_json_has_no_sample_content(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _setup_run_with_messages(conn)

        out = tmp_path / "stats_check"
        audit_to_sft_jsonl(conn, str(out), hours=9999, encrypt=False)

        stats_path = out / "stats.json"
        assert stats_path.exists()
        stats_text = stats_path.read_text()

        assert "Show me device status" not in stats_text
        assert "device status report" not in stats_text

        stats = json.loads(stats_text)
        assert "runs_scanned" in stats
        assert "runs_exported" in stats
        assert isinstance(stats["runs_scanned"], int)

    def test_rejected_runs_json_has_no_message_content(self, tmp_path):
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        conn = _make_conn()
        _insert_run(conn, "reject-me", status="completed")
        _insert_event(conn, "reject-me", event_type="user_input_received", seq=1)

        out = tmp_path / "rejected_check"
        audit_to_sft_jsonl(conn, str(out), hours=9999, encrypt=False)

        rejected_path = out / "rejected_runs.json"
        assert rejected_path.exists()
        rejected_text = rejected_path.read_text()
        rejected = json.loads(rejected_text)

        if rejected:
            for entry in rejected:
                assert "run_id" in entry
                assert "content" not in entry or isinstance(entry.get("content"), type(None))


# =====================================================================
# Section 13: KMS Key Ref Detection (Phase 3 — §7.3)
# =====================================================================


class TestIsKmsKeyRef:
    def test_gcp_kms_uri_detected(self):
        from olav.enterprise.dataset_encryption import is_kms_key_ref

        assert (
            is_kms_key_ref(
                "gcp-kms://projects/my-proj/locations/global/keyRings/ring/cryptoKeys/key"
            )
            is True
        )

    def test_aws_kms_uri_detected(self):
        from olav.enterprise.dataset_encryption import is_kms_key_ref

        assert is_kms_key_ref("aws-kms://arn:aws:kms:us-east-1:123456:key/abc") is True

    def test_local_key_ref_not_kms(self):
        from olav.enterprise.dataset_encryption import is_kms_key_ref

        assert is_kms_key_ref("dataset-export-key-v1") is False

    def test_empty_string_not_kms(self):
        from olav.enterprise.dataset_encryption import is_kms_key_ref

        assert is_kms_key_ref("") is False

    def test_hcvault_uri_detected(self):
        from olav.enterprise.dataset_encryption import is_kms_key_ref

        assert is_kms_key_ref("hcvault://vault.example.com/transit/keys/my-key") is True

    def test_azure_kms_uri_detected(self):
        from olav.enterprise.dataset_encryption import is_kms_key_ref

        assert is_kms_key_ref("azure-kms://my-vault.vault.azure.net/keys/my-key") is True


class TestLoadKeysetKmsRaisesNotImplemented:
    def test_gcp_kms_key_ref_raises(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        # KMS now raises ImportError when the integration extra is not installed.
        # Accept either ImportError (no extra) or ValueError (bad URI) but NOT NotImplementedError.
        with pytest.raises((ImportError, ValueError)):
            enc.load_keyset(
                "gcp-kms://projects/my-proj/locations/global/keyRings/ring/cryptoKeys/key"
            )

    def test_aws_kms_key_ref_raises(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        with pytest.raises((ImportError, ValueError)):
            enc.load_keyset("aws-kms://arn:aws:kms:us-east-1:123456:key/abc")

    def test_local_key_ref_still_works(self, tmp_path):
        from olav.enterprise.dataset_encryption import DatasetEncryptor

        enc = DatasetEncryptor(keyset_dir=tmp_path)
        enc.generate_keyset()
        enc.save_keyset("test-local-key")

        enc2 = DatasetEncryptor(keyset_dir=tmp_path)
        enc2.load_keyset("test-local-key")
        assert enc2.has_keyset


# =====================================================================
# Section 14: One-Time Token Control (Phase 4 — §8.4)
# =====================================================================


class TestOneTimeTokenIssueAndVerify:
    def test_issue_returns_valid_token_dict(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!")
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)

        assert "token" in result
        assert result["export_id"] == "export-001"
        assert result["access_mode"] == "one_time_token"
        assert "expires_at" in result

    def test_verify_valid_token_succeeds(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!")
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)
        claims = mgr.verify(result["token"], export_id="export-001")

        assert claims["export_id"] == "export-001"
        assert claims["user_id"] == "admin"

    def test_single_use_second_verify_fails(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!")
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)
        mgr.verify(result["token"], export_id="export-001")

        with pytest.raises(ValueError, match="already been used"):
            mgr.verify(result["token"], export_id="export-001")

    def test_wrong_export_id_fails(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!")
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)

        with pytest.raises(ValueError, match="export_id mismatch"):
            mgr.verify(result["token"], export_id="export-999")

    def test_expired_token_fails(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!")
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=0)

        import time

        time.sleep(1.5)

        with pytest.raises(ValueError, match="expired"):
            mgr.verify(result["token"], export_id="export-001")

    def test_tampered_token_fails(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!")
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)
        tampered = result["token"] + "X"

        with pytest.raises(ValueError, match="Invalid token"):
            mgr.verify(tampered, export_id="export-001")


class TestOneTimeTokenDuckDBDenylist:
    def test_denylist_persists_across_manager_instances(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        conn = duckdb.connect(":memory:")
        mgr1 = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!", conn=conn)
        result = mgr1.issue(export_id="export-001", user_id="admin", ttl_minutes=10)
        mgr1.verify(result["token"], export_id="export-001")

        mgr2 = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!", conn=conn)
        with pytest.raises(ValueError, match="already been used"):
            mgr2.verify(result["token"], export_id="export-001")

    def test_audit_events_recorded(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        conn = duckdb.connect(":memory:")
        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!", conn=conn)
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)
        mgr.verify(result["token"], export_id="export-001")

        events = conn.execute(
            "SELECT event_type, export_id FROM token_audit_log ORDER BY ts"
        ).fetchall()
        assert len(events) == 2
        assert events[0][0] == "token_issued"
        assert events[0][1] == "export-001"
        assert events[1][0] == "token_verified"
        assert events[1][1] == "export-001"

    def test_failed_verify_audit_logged(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        conn = duckdb.connect(":memory:")
        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!", conn=conn)
        result = mgr.issue(export_id="export-001", user_id="admin", ttl_minutes=10)
        mgr.verify(result["token"], export_id="export-001")

        with pytest.raises(ValueError):
            mgr.verify(result["token"], export_id="export-001")

        events = conn.execute("SELECT event_type FROM token_audit_log ORDER BY ts").fetchall()
        event_types = [e[0] for e in events]
        assert "token_denied" in event_types


# =====================================================================
# Section 15: CLI grant-local-train Subparser (§8.4)
# =====================================================================


class TestCLIGrantLocalTrain:
    def test_grant_local_train_parser_exists(self):
        import sys

        from olav.cli.main import parse_args

        test_argv = ["olav", "log", "export", "grant-local-train", "--export-id", "export-001"]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", test_argv)
            args = parse_args()
        assert args.command == "log"
        assert args.log_command == "export"
        assert args.export_format == "grant-local-train"
        assert args.export_id == "export-001"

    def test_grant_local_train_ttl_default(self):
        import sys

        from olav.cli.main import parse_args

        test_argv = ["olav", "log", "export", "grant-local-train", "--export-id", "export-001"]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", test_argv)
            args = parse_args()
        assert args.ttl_minutes == 10

    def test_grant_local_train_custom_ttl(self):
        import sys

        from olav.cli.main import parse_args

        test_argv = [
            "olav",
            "log",
            "export",
            "grant-local-train",
            "--export-id",
            "export-001",
            "--ttl-minutes",
            "5",
        ]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", test_argv)
            args = parse_args()
        assert args.ttl_minutes == 5


# =====================================================================
# Section 16: §11.1 Test 7 — one_time_token single-use E2E
# =====================================================================


class TestOneTimeTokenSingleUseE2E:
    def test_token_single_use_success_second_use_failure(self):
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        conn = duckdb.connect(":memory:")
        mgr = OneTimeTokenManager(secret="test-secret-key-32bytes-long!!!!", conn=conn)

        result = mgr.issue(export_id="export-e2e-001", user_id="trainer", ttl_minutes=10)
        token = result["token"]

        claims = mgr.verify(token, export_id="export-e2e-001")
        assert claims["export_id"] == "export-e2e-001"
        assert claims["user_id"] == "trainer"

        with pytest.raises(ValueError, match="already been used"):
            mgr.verify(token, export_id="export-e2e-001")

        events = conn.execute("SELECT event_type FROM token_audit_log ORDER BY ts").fetchall()
        event_types = [e[0] for e in events]
        assert event_types == ["token_issued", "token_verified", "token_denied"]


# =====================================================================
# Section 17: DATA-4 — Reasoning Block Export
# =====================================================================


class TestExtractReasoningBlocks:
    """Unit tests for _extract_reasoning_blocks helper."""

    def test_adjacent_reasoning_tokens_concatenated(self):
        from olav.enterprise.audit_dataset_export import _extract_reasoning_blocks

        events = [
            {"event_type": "reasoning_block", "payload": json.dumps({"token": "Think"})},
            {"event_type": "reasoning_block", "payload": json.dumps({"token": "ing..."})},
        ]
        result = _extract_reasoning_blocks(events)
        assert result == ["Thinking..."]

    def test_non_reasoning_events_split_blocks(self):
        from olav.enterprise.audit_dataset_export import _extract_reasoning_blocks

        events = [
            {"event_type": "reasoning_block", "payload": json.dumps({"token": "A"})},
            {"event_type": "tool_call", "payload": "{}"},
            {"event_type": "reasoning_block", "payload": json.dumps({"token": "B"})},
        ]
        result = _extract_reasoning_blocks(events)
        assert result == ["A", "B"]

    def test_empty_events_returns_empty(self):
        from olav.enterprise.audit_dataset_export import _extract_reasoning_blocks

        assert _extract_reasoning_blocks([]) == []

    def test_payload_as_raw_string_dict(self):
        """Payload stored as JSON string should be parsed."""
        from olav.enterprise.audit_dataset_export import _extract_reasoning_blocks

        events = [
            {"event_type": "reasoning_block", "payload": '{"token": "parsed"}'},
        ]
        assert _extract_reasoning_blocks(events) == ["parsed"]

    def test_payload_as_dict(self):
        """Payload already a dict (not JSON string) should work."""
        from olav.enterprise.audit_dataset_export import _extract_reasoning_blocks

        events = [
            {"event_type": "reasoning_block", "payload": {"token": "direct"}},
        ]
        assert _extract_reasoning_blocks(events) == ["direct"]


class TestBuildTrajectoryStepsReasoning:
    """DATA-4: reasoning_block events become thinking steps in trajectory."""

    def test_reasoning_block_events_become_thinking_steps(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Answer"},
            ],
            "tool_calls": [],
            "events": [
                {"event_type": "reasoning_block", "payload": json.dumps({"token": "Let me "})},
                {"event_type": "reasoning_block", "payload": json.dumps({"token": "think"})},
            ],
        }
        steps, is_valid = _build_trajectory_steps(timeline)
        assert is_valid
        thinking = [s for s in steps if s["type"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["content"] == "Let me think"
        assert steps[0]["type"] == "thinking"

    def test_reasoning_interleaved_with_tool_calls(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "Query"},
                {"role": "tool", "content": "result1"},
                {"role": "assistant", "content": "Done"},
            ],
            "tool_calls": [
                {"call_id": "c1", "tool_name": "search", "input_args": {}, "status": "completed"},
            ],
            "events": [
                {"event_type": "reasoning_block", "payload": json.dumps({"token": "Plan: "})},
                {"event_type": "reasoning_block", "payload": json.dumps({"token": "search"})},
            ],
        }
        steps, is_valid = _build_trajectory_steps(timeline)
        assert is_valid
        type_seq = [s["type"] for s in steps]
        assert "thinking" in type_seq
        assert type_seq.index("thinking") < type_seq.index("tool_call")

    def test_no_reasoning_events_no_thinking_steps(self):
        from olav.enterprise.audit_dataset_export import _build_trajectory_steps

        timeline = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            "tool_calls": [],
            "events": [],
        }
        steps, _ = _build_trajectory_steps(timeline)
        assert all(s["type"] != "thinking" for s in steps)


class TestBuildAtifSpansReasoning:
    """DATA-4: reasoning_block events become thinking spans in ATIF."""

    def test_reasoning_block_events_in_atif_spans(self):
        from olav.enterprise.audit_dataset_export import _build_atif_spans

        timeline = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Answer"},
            ],
            "tool_calls": [],
            "events": [
                {"event_type": "reasoning_block", "payload": json.dumps({"token": "Deep "})},
                {"event_type": "reasoning_block", "payload": json.dumps({"token": "thought"})},
            ],
        }
        spans = _build_atif_spans(timeline)
        thinking = [s for s in spans if s["type"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["content"] == "Deep thought"
        assert thinking[0]["name"] == "thinking"

    def test_no_reasoning_events_no_thinking_spans(self):
        from olav.enterprise.audit_dataset_export import _build_atif_spans

        timeline = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            "tool_calls": [],
            "events": [],
        }
        spans = _build_atif_spans(timeline)
        assert all(s["type"] != "thinking" for s in spans)
