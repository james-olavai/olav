"""TDD tests for SNAPSHOT-SPLIT-1: Split exports/snapshots/ into separated structure.

Tests cover:
  1. config.py exports BACKUP_DIR, TMP_SNAPSHOTS_DIR, TMP_STAGING_DIR
  2. PathsConfig has backup_dir, tmp_snapshots_dir, tmp_staging_dir properties
  3. BACKUP_DIR points to exports/backup
  4. TMP_SNAPSHOTS_DIR points to tmp/snapshots
  5. TMP_STAGING_DIR points to tmp/staging
  6. calculate_diffs.py uses BACKUP_DIR (not SNAPSHOTS_DIR) for config diffs
  7. create_olav_directories() includes new paths
  8. SNAPSHOTS_DIR still exists (backward compat)
"""

from __future__ import annotations

from pathlib import Path


class TestConfigExportsNewConstants:
    def test_backup_dir_exported(self):
        from olav.core.config import BACKUP_DIR

        assert isinstance(BACKUP_DIR, Path)

    def test_tmp_snapshots_dir_exported(self):
        from olav.core.config import TMP_SNAPSHOTS_DIR

        assert isinstance(TMP_SNAPSHOTS_DIR, Path)

    def test_tmp_staging_dir_exported(self):
        from olav.core.config import TMP_STAGING_DIR

        assert isinstance(TMP_STAGING_DIR, Path)

    def test_snapshots_dir_still_exists(self):
        from olav.core.config import SNAPSHOTS_DIR

        assert isinstance(SNAPSHOTS_DIR, Path)


class TestNewPathValues:
    def test_backup_dir_under_exports(self):
        from olav.core.config import BACKUP_DIR, EXPORTS_DIR

        assert BACKUP_DIR == EXPORTS_DIR / "backup"

    def test_tmp_snapshots_dir_under_tmp(self):
        from olav.core.config import TMP_SNAPSHOTS_DIR

        assert TMP_SNAPSHOTS_DIR.parts[-2:] == ("tmp", "snapshots")

    def test_tmp_staging_dir_under_tmp(self):
        from olav.core.config import TMP_STAGING_DIR

        assert TMP_STAGING_DIR.parts[-2:] == ("tmp", "staging")


class TestPathsConfigProperties:
    def test_paths_config_has_backup_dir(self):
        from olav.core.config import get_paths_config

        pc = get_paths_config()
        assert hasattr(pc, "backup_dir")
        assert "backup" in pc.backup_dir

    def test_paths_config_has_tmp_snapshots_dir(self):
        from olav.core.config import get_paths_config

        pc = get_paths_config()
        assert hasattr(pc, "tmp_snapshots_dir")
        assert "tmp" in pc.tmp_snapshots_dir

    def test_paths_config_has_tmp_staging_dir(self):
        from olav.core.config import get_paths_config

        pc = get_paths_config()
        assert hasattr(pc, "tmp_staging_dir")
        assert "staging" in pc.tmp_staging_dir


class TestCalculateDiffsUsesBackupDir:
    def test_calculate_diffs_imports_backup_dir(self):
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "calculate_diffs.py"
        tree = ast.parse(src.read_text())
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "config" in node.module:
                imported_names.extend(alias.name for alias in node.names)
        assert "BACKUP_DIR" in imported_names, (
            f"calculate_diffs.py should import BACKUP_DIR from config, got: {imported_names}"
        )


class TestCreateOlavDirectoriesNewPaths:
    def test_subdirs_include_exports_backup(self):
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "utils.py"
        source = src.read_text()
        assert "exports/backup" in source, (
            "utils.py create_olav_directories should include exports/backup"
        )

    def test_subdirs_include_tmp_snapshots(self):
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "utils.py"
        source = src.read_text()
        assert "tmp/snapshots" in source, (
            "utils.py create_olav_directories should include tmp/snapshots"
        )

    def test_subdirs_include_tmp_staging(self):
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "utils.py"
        source = src.read_text()
        assert "tmp/staging" in source, (
            "utils.py create_olav_directories should include tmp/staging"
        )
