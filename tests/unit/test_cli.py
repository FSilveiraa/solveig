"""Unit tests for solveig.interface.cli module."""

import re
from pathlib import Path

from solveig.interface.cli import CLIInterface
from solveig.schema.message import LLMMessage
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from solveig.utils.file import Metadata
from tests.mocks.interface import MockInterface


def create_complex_tree_metadata() -> Metadata:
    """Create a complex nested directory structure like /home/francisco/Sync."""
    # Create deepest files first
    f3 = Metadata(
        path=Path("/test/d1/sub-d1/sub-d2/sub-d3/f3"),
        is_directory=False, size=100, modified_time="2024-01-01",
        owner_name="user", group_name="group", is_readable=True, is_writable=True
    )
    
    f4 = Metadata(path=Path("/test/d1/sub-d1/sub-d2/f4"), is_directory=False, size=100, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    f5 = Metadata(path=Path("/test/d1/sub-d1/sub-d2/f5"), is_directory=False, size=100, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    f6 = Metadata(path=Path("/test/d1/sub-d1/sub-d2/f6"), is_directory=False, size=100, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    
    # Build directories from bottom up
    sub_d3 = Metadata(
        path=Path("/test/d1/sub-d1/sub-d2/sub-d3"), is_directory=True, size=4096, modified_time="2024-01-01",
        owner_name="user", group_name="group", is_readable=True, is_writable=True,
        listing={Path("/test/d1/sub-d1/sub-d2/sub-d3/f3"): f3}
    )
    
    sub_d2 = Metadata(
        path=Path("/test/d1/sub-d1/sub-d2"), is_directory=True, size=4096, modified_time="2024-01-01",
        owner_name="user", group_name="group", is_readable=True, is_writable=True,
        listing={
            Path("/test/d1/sub-d1/sub-d2/f4"): f4,
            Path("/test/d1/sub-d1/sub-d2/f5"): f5,
            Path("/test/d1/sub-d1/sub-d2/f6"): f6,
            Path("/test/d1/sub-d1/sub-d2/sub-d3"): sub_d3,
        }
    )
    
    sub_f1 = Metadata(path=Path("/test/d1/sub-f1"), is_directory=False, size=100, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    
    sub_d1 = Metadata(
        path=Path("/test/d1/sub-d1"), is_directory=True, size=4096, modified_time="2024-01-01",
        owner_name="user", group_name="group", is_readable=True, is_writable=True,
        listing={Path("/test/d1/sub-d1/sub-d2"): sub_d2}
    )
    
    d1 = Metadata(
        path=Path("/test/d1"), is_directory=True, size=4096, modified_time="2024-01-01",
        owner_name="user", group_name="group", is_readable=True, is_writable=True,
        listing={
            Path("/test/d1/sub-d1"): sub_d1,
            Path("/test/d1/sub-f1"): sub_f1,
        }
    )
    
    # Root level files
    dev_sh = Metadata(path=Path("/test/dev.sh"), is_directory=False, size=200, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    f1 = Metadata(path=Path("/test/f1"), is_directory=False, size=50, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    hello_py = Metadata(path=Path("/test/hello.py"), is_directory=False, size=150, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    j1_json = Metadata(path=Path("/test/j1.json"), is_directory=False, size=300, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    run_sh_bak = Metadata(path=Path("/test/run.sh.bak"), is_directory=False, size=250, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    stuff_txt = Metadata(path=Path("/test/stuff.txt"), is_directory=False, size=80, modified_time="2024-01-01", owner_name="user", group_name="group", is_readable=True, is_writable=True)
    
    # Root directory
    root = Metadata(
        path=Path("/test"), is_directory=True, size=4096, modified_time="2024-01-01",
        owner_name="user", group_name="group", is_readable=True, is_writable=True,
        listing={
            Path("/test/d1"): d1,
            Path("/test/dev.sh"): dev_sh,
            Path("/test/f1"): f1,
            Path("/test/hello.py"): hello_py,
            Path("/test/j1.json"): j1_json,
            Path("/test/run.sh.bak"): run_sh_bak,
            Path("/test/stuff.txt"): stuff_txt,
        }
    )
    
    return root


class TestCLIInterfaceCore:
    """Test core CLI interface functionality."""

    def test_initialization(self):
        """Test CLIInterface initialization with parameters."""
        interface = CLIInterface(indent_base=4, max_lines=10, verbose=True)
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
        lines = [f"Line {n}" for n in range(1, 5)] # 4 lines
        interface.display_text_block("\n".join(lines), title="Test Box")
        output_lines = [line for line in interface.get_all_output().split('\n') if line.strip()]

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
        output_lines = output.split('\n')
        assert "more..." in output_lines[-2].lower()


class TestTreeDisplay:
    """Test complex tree visualization functionality."""

    def test_display_complex_directory_tree_complete_structure(self):
        """Test displaying complex nested directory structure with full depth visualization."""
        interface = MockInterface()
        interface.max_lines = 50  # Ensure we see full structure
        
        complex_tree = create_complex_tree_metadata()
        interface.display_tree(complex_tree, listing=None)
        output = interface.get_all_output()
        
        # Verify complete nested structure is rendered
        assert "🗁 test" in output  # Root directory
        assert "🗁 d1" in output
        assert "🗁 sub-d1" in output
        assert "🗁 sub-d2" in output
        assert "🗁 sub-d3" in output  # 4 levels deep
        
        # Verify files at different nesting levels
        assert "🗎 sub-f1" in output  # File in d1
        assert "🗎 f3" in output      # File in deepest directory (sub-d3)
        assert "🗎 f4" in output      # Files in sub-d2
        assert "🗎 f5" in output
        assert "🗎 f6" in output
        
        # Verify all root level files
        root_files = ["🗎 dev.sh", "🗎 f1", "🗎 hello.py", "🗎 j1.json", "🗎 run.sh.bak", "🗎 stuff.txt"]
        for root_file in root_files:
            assert root_file in output
        
        # Verify tree structure uses proper drawing characters
        assert "├─" in output  # Branch connectors
        assert "└─" in output  # Last branch connectors  
        assert "│" in output   # Vertical continuation lines
        
        # Verify depth visualization - deeper files should have more complex indentation
        lines = output.split('\n')
        root_file_line = next((line for line in lines if "🗎 dev.sh" in line), "")
        deep_file_line = next((line for line in lines if "🗎 f3" in line), "")
        assert len(deep_file_line) > len(root_file_line)  # Deep file should be more indented

    def test_display_single_file_and_empty_directory(self):
        """Test tree display edge cases: single files and empty directories."""
        interface = MockInterface()
        
        # Test single file display
        file_metadata = Metadata(
            path=Path("simple.txt"), size=1024, modified_time="2024-01-01", 
            is_directory=False, owner_name="user", group_name="group",
            is_readable=True, is_writable=True
        )
        interface.display_tree(file_metadata, listing=None, title="File Info")
        file_output = interface.get_all_output()
        interface.clear()
        
        # Test empty directory
        empty_dir = Metadata(
            path=Path("empty"), is_directory=True, size=4096, modified_time="2024-01-01",
            owner_name="user", group_name="group", is_readable=True, is_writable=True,
            listing={}
        )
        interface.display_tree(empty_dir, listing=None)
        empty_output = interface.get_all_output()
        
        # File tests
        assert "File Info" in file_output
        assert "🗎 simple.txt" in file_output
        
        # Empty directory tests
        assert "🗁 empty" in empty_output
        # Should have minimal structure - just the directory name in borders
        lines = [line for line in empty_output.split('\n') if line.strip()]
        assert len(lines) >= 3  # Top border, content, bottom border


class TestLLMResponseAndErrorDisplay:
    """Test LLM response and error display functionality."""

    def test_llm_response_display_complete_behavior(self):
        """Test complete LLM response display with comments and grouped requirements."""
        interface = MockInterface()
        
        # Test response with both comment and multiple requirement types
        requirements = [
            ReadRequirement(path="/test/file1.txt", metadata_only=False, comment="Read first file"),
            ReadRequirement(path="/test/file2.txt", metadata_only=True, comment="Read second file metadata"),
            CommandRequirement(command="ls -la", comment="List files"),
            CommandRequirement(command="echo test", comment="Test command"),
        ]
        message = LLMMessage(
            comment="I'll analyze these files and run some commands.", 
            requirements=requirements
        )
        
        interface.display_llm_response(message)
        output = interface.get_all_output()
        interface.clear()
        
        # Test comment-only response
        simple_message = LLMMessage(comment="Just a simple response")
        interface.display_llm_response(simple_message)
        simple_output = interface.get_all_output()
        
        # Response with requirements tests
        assert "I'll analyze these files" in output
        assert "Requirements" in output  # Should show requirements section
        assert len(output) > len(message.comment)  # More content than just comment
        
        # Comment-only tests
        assert "Just a simple response" in simple_output
        assert "Requirements" not in simple_output  # No requirements section

    def test_error_display_complete_behavior(self):
        """Test complete error display for strings and exceptions with proper formatting."""
        interface = MockInterface()
        
        # Test string error
        interface.display_error("File not found: /test/missing.txt")
        string_error = interface.get_all_output()
        interface.clear()
        
        # Test exception error
        exception = ValueError("Invalid input parameter")
        interface.display_error(exception)
        exception_error = interface.get_all_output()
        
        # String error tests
        assert "✖  File not found: /test/missing.txt" in string_error
        
        # Exception error tests
        assert "ValueError: Invalid input parameter" in exception_error
        assert "Error" in exception_error  # Should show detailed error block


class TestInterfaceConstantsAndIntegration:
    """Test interface constants are properly defined and integrated."""

    def test_text_box_constants_and_usage_integration(self):
        """Test that text box drawing characters are defined and actually used in rendering."""
        interface = CLIInterface()
        
        # Test all essential text box characters are defined correctly
        essential_chars = {
            'H': "─", 'V': "│", 'TL': "┌", 'TR': "┐", 
            'BL': "└", 'BR': "┘", 'VL': "┤", 'VR': "├",
            'HB': "┬", 'HT': "┴", 'X': "┼"
        }
        
        for char_name, expected_char in essential_chars.items():
            assert hasattr(interface.TEXT_BOX, char_name)
            assert getattr(interface.TEXT_BOX, char_name) == expected_char
        
        # Test default input prompt is correctly defined
        assert interface.DEFAULT_INPUT_PROMPT == "Reply:\n > "
        
        # Test constants are actually used in rendering (integration test)
        mock_interface = MockInterface()
        mock_interface.display_text_block("test content", title="Integration Test")
        output = mock_interface.get_all_output()
        
        # Should contain the actual box characters in use
        essential_chars_in_use = [interface.TEXT_BOX.TL, interface.TEXT_BOX.H, 
                                interface.TEXT_BOX.V, interface.TEXT_BOX.BR]
        for char in essential_chars_in_use:
            assert char in output, f"Box character '{char}' not found in rendered output"