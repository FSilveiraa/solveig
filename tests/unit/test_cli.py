"""Unit tests for solveig.interface.cli module."""

import re
from pathlib import Path

from solveig.interface.cli import CLIInterface
from solveig.schema.message import LLMMessage
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from solveig.utils.file import Metadata
from tests.mocks.interface import MockInterface


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

    @staticmethod
    def create_complex_tree_metadata() -> Metadata:
        """Create a complex nested directory structure like /home/francisco/Sync."""
        # Create deepest files first
        f3 = Metadata(
            path=Path("/test/d1/sub-d1/sub-d2/sub-d3/f3"),
            is_directory=False, size=100, modified_time="2024-01-01",
            owner_name="user", group_name="group", is_readable=True, is_writable=True
        )

        f4 = Metadata(path=Path("/test/d1/sub-d1/sub-d2/f4"), is_directory=False, size=100, modified_time="2024-01-01",
                      owner_name="user", group_name="group", is_readable=True, is_writable=True)
        f5 = Metadata(path=Path("/test/d1/sub-d1/sub-d2/f5"), is_directory=False, size=100, modified_time="2024-01-01",
                      owner_name="user", group_name="group", is_readable=True, is_writable=True)
        f6 = Metadata(path=Path("/test/d1/sub-d1/sub-d2/f6"), is_directory=False, size=100, modified_time="2024-01-01",
                      owner_name="user", group_name="group", is_readable=True, is_writable=True)

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

        sub_f1 = Metadata(path=Path("/test/d1/sub-f1"), is_directory=False, size=100, modified_time="2024-01-01",
                          owner_name="user", group_name="group", is_readable=True, is_writable=True)

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
        dev_sh = Metadata(path=Path("/test/dev.sh"), is_directory=False, size=200, modified_time="2024-01-01",
                          owner_name="user", group_name="group", is_readable=True, is_writable=True)
        f1 = Metadata(path=Path("/test/f1"), is_directory=False, size=50, modified_time="2024-01-01", owner_name="user",
                      group_name="group", is_readable=True, is_writable=True)
        hello_py = Metadata(path=Path("/test/hello.py"), is_directory=False, size=150, modified_time="2024-01-01",
                            owner_name="user", group_name="group", is_readable=True, is_writable=True)
        j1_json = Metadata(path=Path("/test/j1.json"), is_directory=False, size=300, modified_time="2024-01-01",
                           owner_name="user", group_name="group", is_readable=True, is_writable=True)
        run_sh_bak = Metadata(path=Path("/test/run.sh.bak"), is_directory=False, size=250, modified_time="2024-01-01",
                              owner_name="user", group_name="group", is_readable=True, is_writable=True)
        stuff_txt = Metadata(path=Path("/test/stuff.txt"), is_directory=False, size=80, modified_time="2024-01-01",
                             owner_name="user", group_name="group", is_readable=True, is_writable=True)

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

    def test_display_complex_directory_tree_complete_structure(self):
        """Test displaying complex nested directory structure with full depth visualization."""
        interface = MockInterface()
        interface.max_lines = -1  # Ensure we see full structure
        
        complex_tree = self.create_complex_tree_metadata()
        interface.display_tree(complex_tree)

        expected_lines = f"""
┌─── {complex_tree.path} ────────────────
│ 🗁 {complex_tree.path.name}                   
│   ├─🗁 d1                 
│   │  ├─🗁 sub-d1          
│   │  │  └─🗁 sub-d2       
│   │  │    ├─🗎 f4         
│   │  │    ├─🗎 f5         
│   │  │    ├─🗎 f6         
│   │  │    └─🗁 sub-d3     
│   │  │      └─🗎 f3       
│   │  └─🗎 sub-f1          
│   ├─🗎 dev.sh             
│   ├─🗎 f1                 
│   ├─🗎 hello.py           
│   ├─🗎 j1.json            
│   ├─🗎 run.sh.bak         
│   └─🗎 stuff.txt          
└──────────────────────────
        """.strip().splitlines()

        output_lines = interface.get_all_output().split("\n")
        for expected_line in expected_lines:
            # strip() the expected_line since in the future we may add metadata to the tree view
            assert any(expected_line.strip() in output_line for output_line in output_lines)


class TestLLMResponseAndErrorDisplay:
    """Test LLM response and error display functionality."""

    def test_display_llm_response(self):
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
