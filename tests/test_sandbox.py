"""Tests for the sandbox enforcement system."""

import os
import tempfile

import pytest

from teamclaws.tools.sandbox import init_sandbox, safe_path, validate_file_size


@pytest.fixture(autouse=True)
def setup_sandbox(tmp_path):
    """Initialize sandbox with a temp directory for each test."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_sandbox(str(workspace))
    yield workspace


class TestSafePath:
    """Tests for safe_path() directory traversal prevention."""

    def test_valid_path(self, setup_sandbox):
        """Normal relative path resolves within workspace."""
        result = safe_path("test.txt")
        assert result.startswith(str(setup_sandbox))
        assert result.endswith("test.txt")

    def test_valid_subdirectory(self, setup_sandbox):
        """Subdirectory path resolves within workspace."""
        result = safe_path("subdir/test.txt")
        assert result.startswith(str(setup_sandbox))

    def test_traversal_blocked(self, setup_sandbox):
        """Directory traversal with .. is blocked."""
        with pytest.raises(PermissionError, match="escapes workspace"):
            safe_path("../../etc/passwd")

    def test_traversal_double_blocked(self, setup_sandbox):
        """Multiple levels of traversal are blocked."""
        with pytest.raises(PermissionError, match="escapes workspace"):
            safe_path("../../../etc/shadow")

    def test_absolute_path_outside(self, setup_sandbox):
        """Absolute path outside workspace is blocked."""
        with pytest.raises(PermissionError, match="escapes workspace"):
            safe_path("/etc/passwd")

    def test_dot_path(self, setup_sandbox):
        """Current directory path resolves to workspace."""
        result = safe_path(".")
        assert result == str(setup_sandbox)

    def test_empty_path(self, setup_sandbox):
        """Empty path resolves to workspace root."""
        result = safe_path("")
        assert result == str(setup_sandbox)


class TestValidateFileSize:
    """Tests for file size validation."""

    def test_small_file_ok(self, setup_sandbox):
        """File under limit passes validation."""
        filepath = setup_sandbox / "small.txt"
        filepath.write_text("hello")
        validate_file_size(str(filepath), max_bytes=1024)

    def test_large_file_rejected(self, setup_sandbox):
        """File over limit raises ValueError."""
        filepath = setup_sandbox / "large.txt"
        filepath.write_bytes(b"x" * 100_000)
        with pytest.raises(ValueError, match="too large"):
            validate_file_size(str(filepath), max_bytes=50_000)

    def test_nonexistent_file_ok(self, setup_sandbox):
        """Non-existent file passes (nothing to check)."""
        validate_file_size(str(setup_sandbox / "nope.txt"))
