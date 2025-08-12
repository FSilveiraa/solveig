"""
Unit tests for solveig.interface.cli module.
Tests the CLIInterface implementation using MockInterface.
"""
from pathlib import Path

import pytest

from solveig.interface.cli import CLIInterface
from solveig.schema.message import LLMMessage
from solveig.schema.requirement import (
    CommandRequirement,
    ReadRequirement,
    WriteRequirement,
)
from solveig.utils.filesystem import Metadata
from tests.mocks.interface import MockInterface


class TestCLIInterface:
    """Test CLIInterface functionality using MockInterface."""

    def setup_method(self):
        """Setup for each test method."""
        self.interface = MockInterface()

    def test_initialization(self):
        """Test CLIInterface initialization."""
        interface = CLIInterface(indent_base=4, max_lines=10, verbosity=1)
        assert interface.indent_base == 4
        assert interface.max_lines == 10
        assert interface.verbosity == 1
        assert interface.current_level == 0

    def test_display_section(self):
        """Test section header display."""
        self.interface.display_section("Test Section")

        # Should produce section header output
        assert len(self.interface.outputs) == 1
        output = self.interface.outputs[0]
        assert (
            "─── Test Section " in output
        )  # Title with prefix, may not have trailing dashes with MockInterface
        assert output.startswith("\n")

    def test_display_section_no_title(self):
        """Test section header with no title."""
        self.interface.display_section("")

        # Should produce line of dashes
        assert len(self.interface.outputs) == 1
        output = self.interface.outputs[0]
        assert output.startswith("\n")
        assert "─" in output

    def test_display_text_block_simple(self):
        """Test simple text block display."""
        self.interface.display_text_block("Test content", title="Test")

        # Should produce bordered output
        assert len(self.interface.outputs) >= 3  # Top, content, bottom
        output_text = " ".join(self.interface.outputs)
        assert "┌─── Test" in output_text  # Top border with title
        assert "Test content" in output_text  # Content
        assert "└" in output_text  # Bottom border

    def test_display_text_block_multiline(self):
        """Test multiline text block display."""
        self.interface.display_text_block("Line 1\nLine 2\nLine 3", title="Multi")

        # Should produce bordered output with multiple content lines
        output_text = " ".join(self.interface.outputs)
        assert "Line 1" in output_text
        assert "Line 2" in output_text
        assert "Line 3" in output_text
        assert "┌─── Multi" in output_text

    def test_display_text_block_line_limit(self):
        """Test text block with line limit."""
        self.interface.max_lines = 2
        long_text = "\n".join([f"Line {i}" for i in range(5)])
        self.interface.display_text_block(long_text, title="Limited")

        # Should truncate content
        output_text = " ".join(self.interface.outputs)
        assert "Line 0" in output_text
        assert "Line 1" in output_text
        # Should show truncation indicator
        assert "more" in output_text.lower()

    def test_display_tree_file(self):
        """Test displaying file metadata tree."""
        metadata = Metadata(
            path=Path("/test/file.txt"),
            size=1024,
            modified_time="2024-01-01",
            is_directory=False,
            owner_name="user",
            group_name="group",
            is_readable=True,
            is_writable=True,
        )

        self.interface.display_tree(metadata, listing=None, title="File Info")

        # MockInterface implementation should capture tree display
        assert len(self.interface.outputs) >= 1
        output_text = " ".join(self.interface.outputs)
        # assert "TREE: File Info" in output_text
        assert "/test/file.txt" in output_text

    def test_display_tree_directory_with_listing(self):
        """Test displaying directory metadata tree with file listing."""
        base_metadata = {
            "path": "/test/dir",
            "modified_time": "2024-01-01",
            "is_directory": True,
            "owner_name": "user",
            "group_name": "group",
            "size": 1024,
            "is_readable": True,
            "is_writable": True,
        }
        file_metadata = {
            "is_directory": False,
            "path": Path("/test/dir/file1.txt"),
            **base_metadata
        }
        subdir_metadata = {
            "is_directory": True,
            "path": Path("/test/dir/subdir"),
            **base_metadata
        }

        listing = {
            Path("/test/dir/file1.txt"): Metadata(**file_metadata),
            Path("/test/dir/subdir"): Metadata(**subdir_metadata),
        }

        self.interface.display_tree(Metadata(**base_metadata), listing=listing)

        # MockInterface should capture tree with listing count
        output_text = self.interface.get_all_output()
        # assert "TREE:" in output_text
        assert "dir" in output_text
        assert "file1.txt" in output_text


    def test_display_error_with_string(self):
        """Test error display with string message."""
        self.interface.display_error("Test error message")

        # Should format with error symbol
        output_text = " ".join(self.interface.outputs)
        assert "✖  Test error message" in output_text

    def test_display_error_with_exception(self):
        """Test error display with exception object."""
        exception = ValueError("Test exception")

        self.interface.display_error(exception)

        # Should format exception with class name and show traceback
        output_text = " ".join(self.interface.outputs)
        assert "ValueError: Test exception" in output_text
        # Should also show traceback in text block
        assert "Error" in output_text  # Traceback block title


class TestCLIInterfaceLLMResponse:
    """Test CLI interface LLM response display using MockInterface."""

    def setup_method(self):
        """Setup for each test method."""
        self.interface = MockInterface()

    def test_display_llm_response_comment_only(self):
        """Test displaying LLM response with only comment."""
        message = LLMMessage(comment="Just a simple response")

        self.interface.display_llm_response(message)

        # Should display the comment
        output_text = " ".join(self.interface.outputs)
        assert "Just a simple response" in output_text

    def test_display_llm_response_with_requirements(self):
        """Test displaying LLM response with requirements."""
        requirements = [
            ReadRequirement(
                path="/test/file.txt", only_read_metadata=False, comment="Read file"
            ),
            WriteRequirement(
                path="/test/output.txt",
                content="content",
                is_directory=False,
                comment="Write file",
            ),
            CommandRequirement(command="ls -la", comment="List files"),
        ]
        message = LLMMessage(
            comment="Response with requirements", requirements=requirements
        )

        self.interface.display_llm_response(message)

        # Should display comment and requirements
        output_text = " ".join(self.interface.outputs)
        assert "Response with requirements" in output_text
        # Requirements should be grouped and displayed
        assert "Read file" in output_text
        assert "Write file" in output_text
        assert "List files" in output_text

    def test_display_llm_response_grouped_requirements(self):
        """Test that requirements are properly grouped by type."""
        requirements = [
            ReadRequirement(
                path="/test/file1.txt", only_read_metadata=False, comment="Read file 1"
            ),
            ReadRequirement(
                path="/test/file2.txt", only_read_metadata=True, comment="Read file 2"
            ),
            WriteRequirement(
                path="/test/output.txt",
                content="content",
                is_directory=False,
                comment="Write file",
            ),
        ]
        message = LLMMessage(comment="Grouped requirements", requirements=requirements)

        self.interface.display_llm_response(message)

        # Should group requirements by type
        output_text = " ".join(self.interface.outputs)
        assert "Grouped requirements" in output_text
        assert "Read file 1" in output_text
        assert "Read file 2" in output_text
        assert "Write file" in output_text


class TestCLIInterfaceIO:
    """Test CLI interface I/O methods."""

    def test_default_input_prompt(self):
        """Test default input prompt value."""
        interface = CLIInterface()
        assert interface.DEFAULT_INPUT_PROMPT == "Reply:\n > "

    def test_mock_interface_input_capture(self):
        """Test MockInterface input capture functionality."""
        interface = MockInterface()
        interface.set_user_inputs(["test response"])

        # Mock interface should capture input prompts
        response = interface._input("Test prompt: ")
        assert response == "test response"
        assert "Test prompt: " in interface.questions

    def test_mock_interface_output_capture(self):
        """Test MockInterface output capture functionality."""
        interface = MockInterface()

        interface._output("Test output")

        assert "Test output" in interface.outputs

    def test_mock_interface_max_width(self):
        """Test MockInterface terminal width behavior."""
        interface = MockInterface()
        # MockInterface returns fixed width for consistent testing
        assert interface._get_max_output_width() == 80


class TestCLIInterfaceConstants:
    """Test CLI interface constants and text box characters."""

    def test_text_box_constants(self):
        """Test text box drawing constants."""
        interface = CLIInterface()

        # Test basic box characters are defined
        assert interface.TEXT_BOX.H == "─"
        assert interface.TEXT_BOX.V == "│"
        assert interface.TEXT_BOX.TL == "┌"
        assert interface.TEXT_BOX.TR == "┐"
        assert interface.TEXT_BOX.BL == "└"
        assert interface.TEXT_BOX.BR == "┘"

        # Test junction characters
        assert interface.TEXT_BOX.VL == "┤"
        assert interface.TEXT_BOX.VR == "├"
        assert interface.TEXT_BOX.HB == "┬"
        assert interface.TEXT_BOX.HT == "┴"
        assert interface.TEXT_BOX.X == "┼"

    def test_text_box_usage_in_display(self):
        """Test that text box constants are used in display methods."""
        interface = MockInterface()

        interface.display_text_block("test", title="Test")

        # Check that box characters are used in output
        output_text = " ".join(interface.outputs)
        assert interface.TEXT_BOX.TL in output_text  # Top-left corner
        assert interface.TEXT_BOX.H in output_text  # Horizontal line
        assert interface.TEXT_BOX.V in output_text  # Vertical line


class TestMockInterfaceHelpers:
    """Test MockInterface helper methods."""

    def setup_method(self):
        """Setup for each test method."""
        self.interface = MockInterface()

    def test_get_all_output(self):
        """Test getting all output as single string."""
        self.interface._output("Line 1")
        self.interface._output("Line 2")

        all_output = self.interface.get_all_output()
        assert all_output == "Line 1\nLine 2"

    def test_assert_output_contains(self):
        """Test output contains assertion."""
        self.interface._output("Test message with content")

        # Should pass
        self.interface.assert_output_contains("content")

        # Should fail
        with pytest.raises(AssertionError, match="Output does not contain"):
            self.interface.assert_output_contains("missing")

    def test_assert_output_lines_equal(self):
        """Test exact output line matching."""
        self.interface._output("Line 1")
        self.interface._output("Line 2")

        # Should pass
        self.interface.assert_output_lines_equal(["Line 1", "Line 2"])

        # Should fail
        with pytest.raises(AssertionError, match="Output mismatch"):
            self.interface.assert_output_lines_equal(["Wrong", "Lines"])

    def test_clear(self):
        """Test clearing all captured data."""
        self.interface._output("test")
        self.interface.set_user_inputs(["input"])
        self.interface._input("prompt")
        self.interface.current_level = 2

        self.interface.clear()

        assert len(self.interface.outputs) == 0
        assert len(self.interface.user_inputs) == 0
        assert len(self.interface.questions) == 0
        assert self.interface.current_level == 0
