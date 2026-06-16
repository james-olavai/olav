"""P1a — Pydantic models for the portable-ingest bundle contract.

Validates the schema declared in ``dev_docs/76 §3``:

  * ``Manifest`` (manifest.yaml) — schema_version, collector, hosts_collected,
    redaction (pre_scrubbed/salt_fingerprint), content_sha256.
  * ``DeviceMeta`` (devices/<host>/_meta.yaml) — hostname, mgmt_ip, platform,
    vendor, optional os_version/model, command counts.
  * ``CommandFile`` — the two-line header (``# command:`` + ``# collected_at:``)
    parsed off the per-command txt file.

Failure modes the tests pin:
  * missing schema_version → ValidationError
  * unknown schema_version → ValidationError (only v1 supported in P1a)
  * required DeviceMeta fields enforced
  * command-file header round-trips correctly
"""
from __future__ import annotations

import pytest


# ── Manifest ──────────────────────────────────────────────────────────


class TestManifest:
    def test_parses_canonical(self):
        from olav.core.ingest.schema import Manifest
        m = Manifest.model_validate({
            "schema_version": 1,
            "collector": {
                "name": "olav-collector",
                "version": "0.1.0",
                "invocation": "olav-collect run --inventory hosts.yml --out x.zip",
            },
            "collected_at": "2026-05-15T11:08:42Z",
            "collected_by": "jchen@jumphost-tor1",
            "workspace_id": "site-tor1",
            "hosts_collected": 6,
            "hosts_failed": 0,
            "redaction": {
                "pre_scrubbed": True,
                "salt_fingerprint": "a3f2c891",
                "netconan_version": "0.13.0",
            },
            "content_sha256": "9f3a" * 16,
            "signature": None,
        })
        assert m.schema_version == 1
        assert m.collector.name == "olav-collector"
        assert m.hosts_collected == 6
        assert m.redaction.pre_scrubbed is True
        assert m.signature is None

    def test_rejects_missing_schema_version(self):
        from olav.core.ingest.schema import Manifest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Manifest.model_validate({
                "collector": {"name": "x", "version": "0"},
                "hosts_collected": 0,
                "redaction": {"pre_scrubbed": False},
                "content_sha256": "0" * 64,
            })

    def test_rejects_unknown_schema_version(self):
        from olav.core.ingest.schema import Manifest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Manifest.model_validate({
                "schema_version": 99,
                "collector": {"name": "x", "version": "0"},
                "hosts_collected": 0,
                "redaction": {"pre_scrubbed": False},
                "content_sha256": "0" * 64,
            })


# ── DeviceMeta ────────────────────────────────────────────────────────


class TestDeviceMeta:
    def test_parses_minimal(self):
        from olav.core.ingest.schema import DeviceMeta
        m = DeviceMeta.model_validate({
            "hostname": "R2",
            "mgmt_ip": "10.0.0.2",
            "platform": "cisco_ios",
            "vendor": "Cisco",
        })
        assert m.hostname == "R2"
        assert m.os_version is None  # optional
        assert m.model is None        # optional

    def test_required_fields_enforced(self):
        from olav.core.ingest.schema import DeviceMeta
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DeviceMeta.model_validate({"hostname": "R2"})  # missing platform/vendor/mgmt_ip


# ── CommandFile header ────────────────────────────────────────────────


class TestCommandFileHeader:
    def test_parses_two_line_header(self):
        from olav.core.ingest.schema import CommandFile
        raw = (
            "# command: show ip bgp summary\n"
            "# collected_at: 2026-05-15T11:08:42Z\n"
            "# pre_scrubbed: true\n"
            "\n"
            "BGP router identifier 2.2.2.2, local AS number 65001\n"
            "BGP table version is 1, main routing table version 1\n"
        )
        cf = CommandFile.from_text(raw)
        assert cf.command == "show ip bgp summary"
        assert cf.collected_at_iso == "2026-05-15T11:08:42Z"
        assert cf.pre_scrubbed is True
        assert cf.body.startswith("BGP router identifier")

    def test_missing_command_header_falls_back_to_filename(self):
        from olav.core.ingest.schema import CommandFile
        raw = "BGP router identifier 2.2.2.2\nNeighbor V  AS ...\n"
        cf = CommandFile.from_text(raw, filename_hint="show_ip_bgp_summary.txt")
        # When no `# command:` header is present, the reader uses the
        # filename to recover the original command string.
        assert cf.command == "show ip bgp summary"
        assert cf.body.startswith("BGP router identifier")

    def test_header_pre_scrubbed_false_recognised(self):
        from olav.core.ingest.schema import CommandFile
        raw = (
            "# command: show version\n"
            "# pre_scrubbed: false\n"
            "\n"
            "Cisco IOS XE Software, Version 17.01.01\n"
        )
        cf = CommandFile.from_text(raw)
        assert cf.pre_scrubbed is False
