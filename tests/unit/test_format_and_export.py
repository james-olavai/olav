"""Unit tests for format_and_export tool.

Tests cover:
- CSV export with heterogeneous dict data (bug fix validation)
- JSON/YAML/Markdown format detection and export
- Edge cases: empty data, single dict, nested structures
- Security: path traversal prevention

Run: pytest tests/unit/test_format_and_export.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest

# Import the tool - handle both direct import and module import
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / ".olav" / "workspace" / "ops" / "tools"))

from format_and_export import format_and_export, _write_csv, _detect_format


class TestCSVExport:
    """CSV export tests - validates fieldnames bug fix."""

    def test_heterogeneous_dicts_all_fields_present(self, tmp_path: Path) -> None:
        """Test CSV export with dicts having DIFFERENT fields.

        BUG FIX: Previously only used first dict's keys as fieldnames.
        This caused: ValueError: dict contains fields not in fieldnames
        """
        data = [
            {"table": "devices", "total": 6, "active": 6},
            {
                "table": "parsed_outputs",
                "total_rows": 202,
                "unique_commands": 5,
                "top_commands": ["show version"],
            },
            {"table": "commands", "unique_devices": 6, "top_devices": ["R1", "R2"]},
        ]

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_heterogeneous",
                "format": "csv",
            }
        )

        assert result["format"] == "csv"
        assert Path(result["absolute_path"]).exists()

        # Verify ALL fields are present in CSV header
        content = Path(result["absolute_path"]).read_text()
        header = content.split("\n")[0]

        # All unique fields from all dicts should be in header
        assert "table" in header
        assert "total" in header
        assert "active" in header
        assert "total_rows" in header
        assert "unique_commands" in header
        assert "unique_devices" in header

    def test_uniform_dicts(self, tmp_path: Path) -> None:
        """Test CSV export with uniform dict structure (standard case)."""
        data = [
            {"hostname": "R1", "ip": "10.0.0.1", "status": "up"},
            {"hostname": "R2", "ip": "10.0.0.2", "status": "up"},
            {"hostname": "R3", "ip": "10.0.0.3", "status": "down"},
        ]

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_uniform",
                "format": "csv",
            }
        )

        assert result["format"] == "csv"
        content = Path(result["absolute_path"]).read_text()

        # Verify data integrity
        assert "R1" in content
        assert "R2" in content
        assert "R3" in content
        assert "10.0.0.1" in content

    def test_single_dict(self, tmp_path: Path) -> None:
        """Test CSV export with a single dict."""
        data = {"key": "value", "count": 42}

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_single_dict",
                "format": "csv",
            }
        )

        assert result["format"] == "csv"
        content = Path(result["absolute_path"]).read_text()
        assert "key" in content
        assert "value" in content

    def test_empty_list(self, tmp_path: Path) -> None:
        """Test CSV export with empty list."""
        result = format_and_export.invoke(
            {
                "data": [],
                "filename": "test_empty",
                "format": "csv",
            }
        )

        assert result["format"] == "csv"
        assert Path(result["absolute_path"]).exists()

    def test_json_string_input(self, tmp_path: Path) -> None:
        """Test CSV export with JSON string input (LLM tool call pattern)."""
        json_string = '[{"name": "test1", "value": 1}, {"name": "test2", "value": 2}]'

        result = format_and_export.invoke(
            {
                "data": json_string,
                "filename": "test_json_string",
                "format": "csv",
            }
        )

        assert result["format"] == "csv"
        content = Path(result["absolute_path"]).read_text()
        assert "test1" in content
        assert "test2" in content


class TestFormatDetection:
    """Auto format detection tests."""

    def test_detect_markdown(self) -> None:
        """Markdown detection: starts with # or contains ##."""
        assert _detect_format("# Title\nContent") == "md"
        assert _detect_format("Content\n## Section") == "md"
        assert _detect_format("## Section\n### Subsection") == "md"

    def test_detect_json_object(self) -> None:
        """JSON detection: dict type or string starting with {."""
        assert _detect_format({"key": "value"}) == "json"
        assert _detect_format('{"key": "value"}') == "json"

    def test_detect_json_array(self) -> None:
        """JSON detection: list type or string starting with [."""
        assert _detect_format([{"key": "value"}]) == "json"
        assert _detect_format('[{"key": "value"}]') == "json"

    def test_detect_csv_string(self) -> None:
        """CSV detection: consistent comma-separated lines."""
        csv_string = "name,value\ntest,1\nother,2"
        assert _detect_format(csv_string) == "csv"

    def test_detect_text_default(self) -> None:
        """Text detection: fallback for unknown patterns."""
        assert _detect_format("plain text without special markers") == "txt"


class TestJSONExport:
    """JSON export tests."""

    def test_json_dict(self, tmp_path: Path) -> None:
        """Test JSON export with dict."""
        data = {"devices": [{"hostname": "R1"}, {"hostname": "R2"}]}

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_json",
                "format": "json",
            }
        )

        assert result["format"] == "json"
        content = Path(result["absolute_path"]).read_text()
        parsed = json.loads(content)
        assert parsed["devices"][0]["hostname"] == "R1"

    def test_json_pretty_print(self, tmp_path: Path) -> None:
        """Test JSON is pretty-printed with indent."""
        data = {"key": "value"}

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_pretty",
                "format": "json",
            }
        )

        content = Path(result["absolute_path"]).read_text()
        # Pretty-printed JSON has newlines
        assert "\n" in content
        assert "  " in content  # indented


class TestMarkdownExport:
    """Markdown export tests."""

    def test_markdown_content(self, tmp_path: Path) -> None:
        """Test Markdown export preserves content."""
        content = """# Network Report

## Summary
- Device count: 6
- Issues: 0

## Details
All devices are operational.
"""

        result = format_and_export.invoke(
            {
                "data": content,
                "filename": "test_report",
            }
        )

        # Auto-detect should identify as markdown
        assert result["format"] == "md"

        exported = Path(result["absolute_path"]).read_text()
        assert "# Network Report" in exported
        assert "## Summary" in exported


class TestSecurity:
    """Security-related tests."""

    def test_path_traversal_sanitized(self, tmp_path: Path) -> None:
        """Test that path traversal is sanitized - PurePath().name extracts only filename."""
        result = format_and_export.invoke(
            {
                "data": "test",
                "filename": "../../../etc/passwd",
                "format": "txt",
            }
        )

        # PurePath().name extracts only "passwd" - writes to exports/reports/passwd.txt
        assert "passwd.txt" in result["path"]
        assert "etc" not in result["path"]
        assert ".." not in result["absolute_path"]

    def test_path_traversal_dots_sanitized(self, tmp_path: Path) -> None:
        """Test that .. in filename is sanitized."""
        result = format_and_export.invoke(
            {
                "data": "test",
                "filename": "test/../secret",
                "format": "txt",
            }
        )

        # PurePath().name extracts only "secret" - writes to exports/reports/secret.txt
        assert "secret.txt" in result["path"]
        assert ".." not in result["absolute_path"]

    def test_absolute_path_sanitized(self, tmp_path: Path) -> None:
        """Test that absolute paths are sanitized - PurePath().name extracts filename."""
        result = format_and_export.invoke(
            {
                "data": "test",
                "filename": "/etc/passwd",
                "format": "txt",
            }
        )

        # PurePath().name extracts only "passwd" - writes to exports/reports/passwd.txt
        assert "passwd.txt" in result["path"]
        assert "/etc" not in result["absolute_path"]


class TestWriteCSVFallback:
    """Test the non-pandas CSV fallback path."""

    def test_write_csv_heterogeneous(self, tmp_path: Path) -> None:
        """Test _write_csv handles heterogeneous dicts without pandas."""
        data = [
            {"a": 1},
            {"a": 2, "b": 3},
            {"a": 4, "b": 5, "c": 6},
        ]

        output = tmp_path / "test.csv"
        _write_csv(output, data)

        content = output.read_text()
        lines = content.strip().split("\n")

        # Header should have all columns
        header = lines[0]
        assert "a" in header
        assert "b" in header
        assert "c" in header

        # Should have 4 lines (header + 3 data rows)
        assert len(lines) == 4


class TestEdgeCases:
    """Edge case tests."""

    def test_unicode_content(self, tmp_path: Path) -> None:
        """Test Unicode characters are preserved."""
        data = [{"name": "测试设备", "status": "正常运行"}]

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_unicode",
                "format": "csv",
            }
        )

        content = Path(result["absolute_path"]).read_text(encoding="utf-8")
        assert "测试设备" in content
        assert "正常运行" in content

    def test_special_characters_in_values(self, tmp_path: Path) -> None:
        """Test CSV handles special characters (comma, quotes)."""
        data = [{"name": "Device, Inc.", "desc": 'Has "quotes"'}]

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_special",
                "format": "csv",
            }
        )

        # Should not crash - CSV writer handles escaping
        assert result["format"] == "csv"

    def test_numeric_keys(self, tmp_path: Path) -> None:
        """Test handling of numeric values."""
        data = [{"id": 1, "count": 100, "rate": 0.95}]

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_numeric",
                "format": "csv",
            }
        )

        content = Path(result["absolute_path"]).read_text()
        assert "100" in content
        assert "0.95" in content

    def test_none_values(self, tmp_path: Path) -> None:
        """Test handling of None values."""
        data = [{"name": "test", "value": None}]

        result = format_and_export.invoke(
            {
                "data": data,
                "filename": "test_none",
                "format": "csv",
            }
        )

        # Should not crash
        assert result["format"] == "csv"


# Run tests standalone
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
