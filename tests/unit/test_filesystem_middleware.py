"""Unit tests for FilesystemMiddleware.

Tests cover:
- read_file() with line ranges
- write_file() with HITL approval
- list_files() with glob patterns
- delete_file() with HITL approval
- _validate_path() security checks
- cache_tool_result() / get_cached_result()
"""

from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from olav.core.middleware import FilesystemMiddleware


@pytest.fixture
def test_workspace(tmp_path):
    """Create temporary workspace for testing."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def filesystem(test_workspace):
    """Create FilesystemMiddleware instance with test workspace."""
    checkpointer = MemorySaver()
    return FilesystemMiddleware(
        checkpointer=checkpointer,
        workspace_root=str(test_workspace),
        audit_enabled=False,  # Disable audit for tests
        hitl_enabled=False,   # Disable HITL for tests
    )


class TestPathValidation:
    """Test _validate_path() security checks."""

    def test_validate_simple_path(self, filesystem):
        """Test validation of simple relative path."""
        result = filesystem._validate_path("test.txt")
        assert result.name == "test.txt"
        assert result.is_absolute()

    def test_validate_nested_path(self, filesystem):
        """Test validation of nested path."""
        result = filesystem._validate_path("subdir/file.txt")
        assert "subdir" in str(result)
        assert result.name == "file.txt"

    def test_reject_parent_traversal(self, filesystem):
        """Test rejection of ../ path traversal."""
        with pytest.raises(ValueError, match="Path traversal not allowed"):
            filesystem._validate_path("../etc/passwd")

    def test_reject_home_expansion(self, filesystem):
        """Test rejection of ~/ home expansion."""
        with pytest.raises(ValueError, match="Path traversal not allowed"):
            filesystem._validate_path("~/secrets.txt")

    def test_reject_escaping_workspace(self, filesystem, tmp_path):
        """Test rejection of paths escaping workspace root."""
        # Try to access parent of workspace
        evil_path = str(tmp_path / "evil.txt")
        with pytest.raises(ValueError, match="Path escapes workspace root"):
            filesystem._validate_path(evil_path)

    def test_allowed_prefixes(self, filesystem):
        """Test allowed_prefixes filtering."""
        # Should pass - in allowed prefix
        result = filesystem._validate_path(
            "cache/result.json",
            allowed_prefixes=["cache", "logs"],
        )
        assert "cache" in str(result)

        # Should fail - not in allowed prefix
        with pytest.raises(ValueError, match="Path not in allowed prefixes"):
            filesystem._validate_path(
                "config/secret.yaml",
                allowed_prefixes=["cache", "logs"],
            )


class TestReadFile:
    """Test read_file() functionality."""

    @pytest.mark.asyncio
    async def test_read_full_file(self, filesystem, test_workspace):
        """Test reading entire file."""
        # Create test file
        test_file = test_workspace / "test.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        content = await filesystem.read_file("test.txt")
        assert content == "line 1\nline 2\nline 3\n"

    @pytest.mark.asyncio
    async def test_read_with_line_range(self, filesystem, test_workspace):
        """Test reading with line range (partial file)."""
        # Create test file with 10 lines
        test_file = test_workspace / "large.txt"
        test_file.write_text("\n".join(f"line {i}" for i in range(1, 11)) + "\n")

        # Read lines 2-4 (0-indexed: start_line=1, num_lines=3)
        content = await filesystem.read_file("large.txt", start_line=1, num_lines=3)

        # Should have line numbers
        assert "2 line 2" in content
        assert "3 line 3" in content
        assert "4 line 4" in content
        assert "1 line 1" not in content  # Before range
        assert "5 line 5" not in content  # After range

    @pytest.mark.asyncio
    async def test_read_empty_file(self, filesystem, test_workspace):
        """Test reading empty file."""
        test_file = test_workspace / "empty.txt"
        test_file.write_text("")

        content = await filesystem.read_file("empty.txt")
        assert content == "System reminder: File exists but has empty contents"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, filesystem):
        """Test reading file that doesn't exist."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            await filesystem.read_file("nonexistent.txt")


class TestWriteFile:
    """Test write_file() functionality."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, filesystem, test_workspace):
        """Test writing new file."""
        await filesystem.write_file("new.txt", "content here")

        # Verify file exists
        result_file = test_workspace / "new.txt"
        assert result_file.exists()
        assert result_file.read_text() == "content here"

    @pytest.mark.asyncio
    async def test_write_with_subdirs(self, filesystem, test_workspace):
        """Test writing file in nested subdirectories."""
        await filesystem.write_file("sub/dir/file.txt", "nested content")

        # Verify file exists
        result_file = test_workspace / "sub" / "dir" / "file.txt"
        assert result_file.exists()
        assert result_file.read_text() == "nested content"

    @pytest.mark.asyncio
    async def test_write_overwrite_existing(self, filesystem, test_workspace):
        """Test overwriting existing file."""
        # Create initial file
        test_file = test_workspace / "overwrite.txt"
        test_file.write_text("old content")

        # Overwrite
        await filesystem.write_file("overwrite.txt", "new content")

        assert test_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_write_with_hitl_enabled(self, test_workspace):
        """Test write with HITL approval required."""
        checkpointer = MemorySaver()
        fs = FilesystemMiddleware(
            checkpointer=checkpointer,
            workspace_root=str(test_workspace),
            audit_enabled=False,
            hitl_enabled=True,  # Enable HITL
        )

        # Should succeed with auto-approval (for now)
        # TODO: Mock HITL interrupt when implemented
        await fs.write_file("hitl_test.txt", "content")

        result_file = test_workspace / "hitl_test.txt"
        assert result_file.exists()


class TestListFiles:
    """Test list_files() functionality."""

    @pytest.mark.asyncio
    async def test_list_all_files(self, filesystem, test_workspace):
        """Test listing all files."""
        # Create test files
        (test_workspace / "file1.txt").write_text("1")
        (test_workspace / "file2.txt").write_text("2")
        (test_workspace / "file3.json").write_text("{}")

        files = await filesystem.list_files("*")
        assert len(files) == 3
        assert "file1.txt" in files
        assert "file2.txt" in files
        assert "file3.json" in files

    @pytest.mark.asyncio
    async def test_list_with_pattern(self, filesystem, test_workspace):
        """Test listing with glob pattern."""
        # Create test files
        (test_workspace / "test1.txt").write_text("1")
        (test_workspace / "test2.txt").write_text("2")
        (test_workspace / "other.json").write_text("{}")

        files = await filesystem.list_files("*.txt")
        assert len(files) == 2
        assert "test1.txt" in files
        assert "test2.txt" in files
        assert "other.json" not in files

    @pytest.mark.asyncio
    async def test_list_recursive(self, filesystem, test_workspace):
        """Test listing files recursively."""
        # Create nested structure
        (test_workspace / "root.txt").write_text("root")
        subdir = test_workspace / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested")

        files = await filesystem.list_files("*.txt", recursive=True)
        assert len(files) == 2
        assert "root.txt" in files
        assert "subdir/nested.txt" in files or "subdir\\nested.txt" in files

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, filesystem):
        """Test listing empty directory."""
        files = await filesystem.list_files("*")
        assert len(files) == 0


class TestDeleteFile:
    """Test delete_file() functionality."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, filesystem, test_workspace):
        """Test deleting existing file."""
        # Create test file
        test_file = test_workspace / "delete_me.txt"
        test_file.write_text("content")

        await filesystem.delete_file("delete_me.txt")

        assert not test_file.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, filesystem):
        """Test deleting file that doesn't exist."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            await filesystem.delete_file("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_delete_with_hitl_enabled(self, test_workspace):
        """Test delete with HITL approval required."""
        checkpointer = MemorySaver()
        fs = FilesystemMiddleware(
            checkpointer=checkpointer,
            workspace_root=str(test_workspace),
            audit_enabled=False,
            hitl_enabled=True,  # Enable HITL
        )

        # Create test file
        test_file = test_workspace / "hitl_delete.txt"
        test_file.write_text("content")

        # Should succeed with auto-approval (for now)
        # TODO: Mock HITL interrupt when implemented
        await fs.delete_file("hitl_delete.txt")

        assert not test_file.exists()


class TestCaching:
    """Test cache_tool_result() and get_cached_result()."""

    @pytest.mark.asyncio
    async def test_cache_and_retrieve(self, filesystem):
        """Test caching and retrieving tool results."""
        query = "show ip bgp summary"
        result = {"output": "BGP table version is 42", "success": True}

        # Cache result
        await filesystem.cache_tool_result(query, result)

        # Retrieve cached result
        cached = await filesystem.get_cached_result(query)
        assert cached is not None
        assert cached["output"] == "BGP table version is 42"
        assert cached["success"] is True

    @pytest.mark.asyncio
    async def test_get_nonexistent_cache(self, filesystem):
        """Test retrieving cache that doesn't exist."""
        cached = await filesystem.get_cached_result("nonexistent query")
        assert cached is None

    @pytest.mark.asyncio
    async def test_cache_key_consistency(self, filesystem):
        """Test cache key generation is consistent."""
        query = "show version"
        key1 = filesystem.get_cache_key(query)
        key2 = filesystem.get_cache_key(query)

        assert key1 == key2
        assert key1.startswith("tool_results/")
        assert key1.endswith(".json")

    @pytest.mark.asyncio
    async def test_cache_key_uniqueness(self, filesystem):
        """Test cache keys are unique for different queries."""
        key1 = filesystem.get_cache_key("query 1")
        key2 = filesystem.get_cache_key("query 2")

        assert key1 != key2

    @pytest.mark.asyncio
    async def test_cache_handles_unicode(self, filesystem):
        """Test caching handles Unicode content."""
        query = "查询 BGP 状态"
        result = {"output": "BGP 状态: 正常"}

        await filesystem.cache_tool_result(query, result)
        cached = await filesystem.get_cached_result(query)

        assert cached is not None
        assert cached["output"] == "BGP 状态: 正常"


class TestAuditLogging:
    """Test audit logging functionality."""

    @pytest.mark.asyncio
    async def test_audit_enabled(self, test_workspace):
        """Test audit logging when enabled."""
        checkpointer = MemorySaver()
        fs = FilesystemMiddleware(
            checkpointer=checkpointer,
            workspace_root=str(test_workspace),
            audit_enabled=True,  # Enable audit
            hitl_enabled=False,
        )

        # Create test file
        (test_workspace / "test.txt").write_text("content")

        with patch("olav.core.middleware.filesystem.logger") as mock_logger:
            await fs.read_file("test.txt")

            # Verify audit log was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "Filesystem audit" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_audit_disabled(self, test_workspace):
        """Test audit logging when disabled."""
        checkpointer = MemorySaver()
        fs = FilesystemMiddleware(
            checkpointer=checkpointer,
            workspace_root=str(test_workspace),
            audit_enabled=False,  # Disable audit
            hitl_enabled=False,
        )

        # Create test file
        (test_workspace / "test.txt").write_text("content")

        with patch("olav.core.middleware.filesystem.logger") as mock_logger:
            await fs.read_file("test.txt")

            # Verify audit log was NOT called (only file read log)
            info_calls = mock_logger.info.call_args_list
            audit_calls = [c for c in info_calls if "Filesystem audit" in str(c)]
            assert len(audit_calls) == 0
