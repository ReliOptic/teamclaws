"""Tests for the agent system."""

import pytest

from teamclaws.security.validator import sanitize_input, validate_conversation_id
from teamclaws.security.policy import check_permission, get_permissions


class TestSanitizeInput:
    """Tests for input sanitization."""

    def test_normal_input(self):
        result = sanitize_input("Hello, how are you?")
        assert result == "Hello, how are you?"

    def test_strip_control_chars(self):
        result = sanitize_input("Hello\x00\x01\x02World")
        assert result == "HelloWorld"

    def test_preserve_newline_and_tab(self):
        result = sanitize_input("Line 1\nLine 2\tTabbed")
        assert "\n" in result
        assert "\t" in result

    def test_max_length(self):
        long_input = "a" * 5000
        result = sanitize_input(long_input)
        assert len(result) == 4000

    def test_empty_input(self):
        assert sanitize_input("") == ""

    def test_non_string_input(self):
        assert sanitize_input(None) == ""
        assert sanitize_input(123) == ""


class TestValidateConversationId:
    """Tests for conversation ID validation."""

    def test_valid_id(self):
        assert validate_conversation_id("conv-123") == "conv-123"

    def test_valid_with_underscore(self):
        assert validate_conversation_id("tg_user_456") == "tg_user_456"

    def test_strip_special_chars(self):
        result = validate_conversation_id("conv!@#123")
        assert result == "conv123"

    def test_empty_id(self):
        with pytest.raises(ValueError):
            validate_conversation_id("")

    def test_only_special_chars(self):
        with pytest.raises(ValueError):
            validate_conversation_id("!@#$%")

    def test_max_length(self):
        long_id = "a" * 200
        result = validate_conversation_id(long_id)
        assert len(result) == 128


class TestPermissions:
    """Tests for permission checking."""

    def test_ceo_has_all(self):
        assert check_permission("ceo", "list_files")
        assert check_permission("ceo", "read_file")
        assert check_permission("ceo", "write_file")
        assert check_permission("ceo", "delete_file")
        assert check_permission("ceo", "add_numbers")
        assert check_permission("ceo", "run_python")

    def test_researcher_limited(self):
        assert check_permission("researcher", "list_files")
        assert check_permission("researcher", "read_file")
        assert not check_permission("researcher", "delete_file")
        assert not check_permission("researcher", "run_python")

    def test_executor_permissions(self):
        assert check_permission("executor", "run_python")
        assert check_permission("executor", "delete_file")
        assert not check_permission("executor", "add_numbers")

    def test_unknown_role(self):
        assert not check_permission("unknown_role", "list_files")

    def test_get_permissions(self):
        perms = get_permissions("ceo")
        assert "list_files" in perms
        assert len(perms) == 6
