"""Unit tests for solveig.interface.cli module."""

import re

from solveig.schema.message import LLMMessage
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks.interface import MockInterface


class TestCLIInterfaceCore:
    """Test core CLI interface functionality."""

    def test_initialization(self):
        """Test CLIInterface initialization with parameters."""
        interface = MockInterface(indent_base=4, max_lines=10, verbose=True)
        assert interface.indent_base == 4
        assert interface.max_lines == 10
        assert interface.verbose
        assert interface.current_level == 0
        # starting a group should advance the indent level
        with interface.with_group("Group Name"):
            assert interface.current_level > 0
        assert interface.current_level == 0

    def test_section_display_behavior(self):
        """Test section header display with and without titles."""
        interface = MockInterface()

        # Test section display with title
        interface.display_section("Test Section")
        assert re.match("^─+ Test Section ─+$", interface.get_all_output().strip())
        interface.clear()

        # Test section display without title
        interface.display_section("")
        assert re.match("^─+$", interface.get_all_output().strip())

    def test_text_box_complete_rendering(self):
        """Test complete text box rendering: top border with title, content lines, bottom border, truncation."""
        interface = MockInterface()

        # Test complete text box with title and multiline content
        lines = [f"Line {n}" for n in range(1, 5)]  # 4 lines
        interface.display_text_block("\n".join(lines), title="Test Box")
        output_lines = [
            line for line in interface.get_all_output().split("\n") if line.strip()
        ]

        # Box header
        assert re.match("^┌─+ Test Box ─+┐$", output_lines[0].strip())

        # Box body
        output_body = output_lines[1:-1]
        for index, output_line in enumerate(output_body):
            output_line = output_line.strip()
            actual_line = lines[index].strip()
            assert output_line.startswith("│")
            assert actual_line in output_line
            assert output_line.endswith("│")

        # Box bottom
        assert re.match("^└─+┘$", output_lines[-1].strip())

    def test_text_box_truncation(self):
        """Test truncation behavior"""
        interface = MockInterface(max_lines=2)
        long_text = "\n".join([f"Line {i}" for i in range(5)])
        interface.display_text_block(long_text, title="Limited")

        output = interface.get_all_output().strip()
        output_lines = output.split("\n")
        assert "more..." in output_lines[-2].lower()


class TestTreeDisplay:
    """Test complex tree visualization functionality."""

    def test_display_complex_directory_tree_complete_structure(self, mock_filesystem):
        """Test displaying complex nested directory structure with full depth visualization."""
        interface = MockInterface()
        interface.max_lines = -1  # Ensure we see full structure

        # complex_tree = self.create_complex_tree_metadata()
        tree = mock_filesystem.read_metadata(
            mock_filesystem.get_absolute_path("/test/dir2/")
        )
        interface.display_tree(tree)
        expected_lines = f"""
┌─── {tree.path} ────────────────
│ 🗁  {tree.path.name}
│   ├─🗎 f1
│   └─🗁  sub-d1
│     ├─🗁  sub-d2
│     │  └─🗎 f4
│     └─🗁  sub-d3
│       └─🗎 f3
└────────────────────────────────
        """.strip().splitlines()

        output_lines = interface.get_all_output().split("\n")
        for expected_line in expected_lines:
            try:
                assert any(
                    expected_line.strip() in output_line for output_line in output_lines
                )
            except AssertionError as e:
                raise AssertionError(
                    f"{expected_line} not found in output:\n{output_lines}"
                ) from e


class TestLLMResponseAndErrorDisplay:
    """Test LLM response and error display functionality."""

    def test_display_llm_response(self):
        """Test complete LLM response display with comments and grouped requirements."""
        interface = MockInterface()

        # Test response with both comment and multiple requirement types
        requirements = [
            ReadRequirement(
                path="/test/file1.txt", metadata_only=False, comment="Read first file"
            ),
            ReadRequirement(
                path="/test/file2.txt",
                metadata_only=True,
                comment="Read second file metadata",
            ),
            CommandRequirement(command="ls -la", comment="List files"),
            CommandRequirement(command="echo test", comment="Test command"),
        ]
        message = LLMMessage(
            comment="I'll analyze these files and run some commands.",
            requirements=requirements,
        )

        interface.display_llm_response(message)
        output = interface.get_all_output()
        interface.clear()

        expected_lines = """
[ Requirements (4) ]
  [ Read (2) ]
    ❝  Read first file
    🗎  /test/file1.txt
    ❝  Read second file metadata
    🗎  /test/file2.txt
  [ Command (2) ]
    ❝  List files
    🗲  ls -la
    ❝  Test command
    🗲  echo test
        """.strip().splitlines()

        for line in expected_lines:
            assert line in output

        # Test comment-only response
        simple_message = LLMMessage(comment="Just a simple response")
        interface.display_llm_response(simple_message)
        assert "❝  Just a simple response" in interface.get_all_output()

    def test_display_error(self):
        """Test complete error display for strings and exceptions with proper formatting."""
        interface = MockInterface()

        # Test string error
        interface.display_error(exception=FileNotFoundError("/test/missing.txt"))
        assert "✖  FileNotFoundError: /test/missing.txt" in interface.get_all_output()
        interface.clear()

        # Test exception error
        exception = ValueError("Invalid input parameter")
        interface.display_error(exception)
        assert "ValueError: Invalid input parameter" in interface.get_all_output()
