"""P1a — Bundle reader: discovers layout, parses manifest + per-device meta +
per-command files, yields a normalized iterable of ``(host, command, body)``.

Driven by the canonical fixture at
``tests/fixtures/portable_ingest/synthetic_2host_bundle/`` — 2 hosts
(R1 junos / R2 cisco_ios), 5 commands total (R1 has 1, R2 has 4).
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest


_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "portable_ingest" / "synthetic_2host_bundle"


# ── Directory input ───────────────────────────────────────────────────


class TestBundleReaderDirectory:
    def test_discovers_canonical_layout(self):
        from olav.core.ingest.bundle_reader import BundleReader
        reader = BundleReader.open(_FIXTURE_DIR)
        records = list(reader.iter_command_outputs())
        assert len(records) == 5  # R1 x 1 + R2 x 4

    def test_record_carries_command_string_not_filename(self):
        from olav.core.ingest.bundle_reader import BundleReader
        reader = BundleReader.open(_FIXTURE_DIR)
        cmds = sorted({r.command for r in reader.iter_command_outputs()})
        # All 4 IOS commands + the Junos show-version (== "show version").
        assert "show version" in cmds
        assert "show ip bgp summary" in cmds
        assert "show ip interface brief" in cmds
        assert "show ip route" in cmds
        # Safe filename ``show_ip_bgp_summary`` should NEVER appear in records.
        assert not any("show_ip_bgp_summary" == r.command for r in reader.iter_command_outputs())

    def test_record_has_host_and_platform(self):
        from olav.core.ingest.bundle_reader import BundleReader
        reader = BundleReader.open(_FIXTURE_DIR)
        by_host = {r.host: r for r in reader.iter_command_outputs()}
        assert by_host["R1"].platform == "juniper_junos"
        assert by_host["R2"].platform == "cisco_ios"

    def test_manifest_is_exposed(self):
        from olav.core.ingest.bundle_reader import BundleReader
        reader = BundleReader.open(_FIXTURE_DIR)
        m = reader.manifest
        assert m.schema_version == 1
        assert m.hosts_collected == 2
        assert m.collector.name == "olav-collector"


# ── Zip input ─────────────────────────────────────────────────────────


@pytest.fixture()
def zipped_fixture(tmp_path):
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in _FIXTURE_DIR.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(_FIXTURE_DIR))
    return zip_path


class TestBundleReaderZip:
    def test_zip_yields_same_records_as_dir(self, zipped_fixture):
        from olav.core.ingest.bundle_reader import BundleReader
        dir_records = sorted(
            (r.host, r.command) for r in BundleReader.open(_FIXTURE_DIR).iter_command_outputs()
        )
        zip_records = sorted(
            (r.host, r.command) for r in BundleReader.open(zipped_fixture).iter_command_outputs()
        )
        assert dir_records == zip_records

    def test_zip_manifest_loadable(self, zipped_fixture):
        from olav.core.ingest.bundle_reader import BundleReader
        reader = BundleReader.open(zipped_fixture)
        assert reader.manifest.hosts_collected == 2


# ── Error paths ───────────────────────────────────────────────────────


class TestBundleReaderErrors:
    def test_missing_manifest_raises(self, tmp_path):
        from olav.core.ingest.bundle_reader import BundleReader
        # Copy fixture but remove manifest.
        dest = tmp_path / "broken"
        shutil.copytree(_FIXTURE_DIR, dest)
        (dest / "manifest.yaml").unlink()
        with pytest.raises(FileNotFoundError):
            BundleReader.open(dest)

    def test_missing_devices_dir_raises(self, tmp_path):
        from olav.core.ingest.bundle_reader import BundleReader
        dest = tmp_path / "broken"
        dest.mkdir()
        (dest / "manifest.yaml").write_text(
            (Path(_FIXTURE_DIR) / "manifest.yaml").read_text(),
            encoding="utf-8",
        )
        with pytest.raises(FileNotFoundError):
            list(BundleReader.open(dest).iter_command_outputs())
