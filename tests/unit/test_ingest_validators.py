"""P1b — Bundle validators: sha256 + manifest sanity.

The validator never touches the DB.  It's the cheap pre-flight call:
``validate_bundle(path) → ValidationReport`` answering "is this bundle
internally consistent enough to feed the landing pipeline?"

Failure modes pinned:
  * No manifest at the root → hard error
  * content_sha256 mismatch (one byte flipped in a command file) → hard error
  * Hosts declared in manifest but missing in devices/ → warning, not error
  * Empty devices/ → warning
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_FIXTURE_DIR = (
    Path(__file__).parent.parent
    / "fixtures" / "portable_ingest" / "synthetic_2host_bundle"
)


@pytest.fixture()
def working_copy(tmp_path):
    """Copy of the canonical fixture so each test can mutate freely."""
    dest = tmp_path / "bundle"
    shutil.copytree(_FIXTURE_DIR, dest)
    return dest


class TestValidateBundle:
    def test_passes_on_canonical_fixture(self, working_copy):
        from olav.core.ingest.validators import validate_bundle
        report = validate_bundle(working_copy)
        assert report.ok is True
        assert report.errors == []

    def test_missing_manifest_is_hard_error(self, working_copy):
        from olav.core.ingest.validators import validate_bundle
        (working_copy / "manifest.yaml").unlink()
        report = validate_bundle(working_copy)
        assert report.ok is False
        assert any("manifest" in e.lower() for e in report.errors)

    def test_sha256_mismatch_is_hard_error(self, working_copy):
        from olav.core.ingest.validators import validate_bundle
        # Flip one byte in a command file — content hash should no longer
        # match the value declared in manifest.yaml.
        target = working_copy / "devices" / "R2" / "show_version.txt"
        original = target.read_text(encoding="utf-8")
        target.write_text(original + "TAMPERED\n", encoding="utf-8")
        report = validate_bundle(working_copy)
        assert report.ok is False
        assert any("sha256" in e.lower() or "hash" in e.lower() for e in report.errors)

    def test_hosts_count_mismatch_is_warning(self, working_copy):
        """Manifest declares 2 hosts; we delete one.  Validator warns
        but does not fail outright — partial bundles are acceptable."""
        from olav.core.ingest.validators import validate_bundle
        shutil.rmtree(working_copy / "devices" / "R1")
        # Strip R1's command-file bytes from the hash before re-running,
        # else the hash check fires first and masks the host-count warning.
        # We instead rebuild the bundle's hash by recomputing — for this
        # test we rely on the validator surfacing BOTH a warning AND an
        # error. Either way ``host count`` should appear in warnings.
        report = validate_bundle(working_copy)
        # ok may be False due to sha256, but warnings should still include
        # the host-count drift; that's what we pin here.
        assert any("host" in w.lower() for w in report.warnings)

    def test_unsupported_schema_version_is_hard_error(self, working_copy):
        from olav.core.ingest.validators import validate_bundle
        manifest = (working_copy / "manifest.yaml").read_text(encoding="utf-8")
        broken = manifest.replace("schema_version: 1", "schema_version: 99")
        (working_copy / "manifest.yaml").write_text(broken, encoding="utf-8")
        report = validate_bundle(working_copy)
        assert report.ok is False
        assert any("schema" in e.lower() for e in report.errors)

    def test_report_carries_stats(self, working_copy):
        from olav.core.ingest.validators import validate_bundle
        report = validate_bundle(working_copy)
        assert report.hosts_seen == 2
        assert report.commands_seen == 5
