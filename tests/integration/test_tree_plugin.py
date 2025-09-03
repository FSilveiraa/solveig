"""Integration test for TreeRequirement plugin using mock LLM client."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run import main_loop
from solveig.plugins.schema.tree import TreeRequirement
from solveig.schema.message import LLMMessage
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


@pytest.mark.no_file_mocking
class TestTreePlugin:
    """Test TreeRequirement plugin with real filesystem operations."""

    @patch("scripts.run.llm.get_instructor_client")
    def test_tree_inspection_request(self, mock_get_client):
        """Test: User asks to inspect a directory, LLM requests tree, we display and return it."""

        expected_tree = """
    ┌─── Tree: {tmp_path} ─────────────────────
    │ 🗁 {tmp_name}            
    │ ├─🗎 file1.txt                
    │ ├─🗎 file2.py                 
    │ └─🗁 subdir                                                               
    │   └─🗎 nested.md              
    └───────────────────────────────────────────
    """.strip()

        # Create a temporary directory structure for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            expected_lines = [
                line.strip()
                for line in expected_tree.format(
                    tmp_path=temp_path, tmp_name=temp_path.name
                ).splitlines()
            ]

            # Create a simple directory structure
            (temp_path / "file1.txt").write_text("content1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "nested.md").write_text("# Nested file")

            # Setup mock system prompt
            # mock_get_prompt.return_value = "You can inspect directories using tree command."

            # LLM response requesting tree inspection of our temp directory
            llm_response = LLMMessage(
                comment=f"I'll inspect the directory structure of {temp_dir}.",
                requirements=[
                    TreeRequirement(
                        comment="",
                        path=str(temp_path),
                        max_depth=2,
                    ),
                ],
            )

            # Setup mock LLM client
            mock_client = create_mock_client(llm_response)
            mock_get_client.return_value = mock_client

            # Setup mock interface with user accepting the tree request
            interface = MockInterface()
            interface.set_user_inputs(
                [
                    "y",  # Accept tree command
                    "exit",  # End conversation
                ]
            )

            # Execute the conversation loop
            try:
                main_loop(
                    DEFAULT_CONFIG,
                    interface,
                    f"Can you show me what's in this directory: {temp_dir}",
                )
            except ValueError:
                pass  # Expected when conversation ends

            for line in expected_lines:
                assert line in interface.get_all_output()

            # Verify LLM client was called exactly once
            assert mock_client.get_call_count() == 1
