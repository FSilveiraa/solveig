"""Integration test for TreeRequirement plugin with real filesystem operations."""

import tempfile
from pathlib import Path

import pytest

from scripts.run import main_loop
from solveig.plugins.schema.tree import TreeRequirement
from solveig.schema.message import LLMMessage
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


@pytest.mark.no_file_mocking
class TestTreePlugin:
    """Test TreeRequirement plugin with real filesystem operations."""

    def test_tree_plugin_with_real_files(self):
        """Test tree plugin creates visual directory tree from real filesystem."""

        # TODO: use str result for visual value
        # expected_tree = """
        # ┌─── Tree: {tmp_path} ─────────────────────
        # │ 🗁 {tmp_name}
        # │ ├─🗎 file1.txt
        # │ ├─🗎 file2.py
        # │ └─🗁 subdir
        # │   └─🗎 nested.md
        # └───────────────────────────────────────────
        # """.strip()

        # Create real directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "file1.txt").write_text("content1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "nested.md").write_text("# Nested file")

            # LLM requests tree inspection
            llm_response = LLMMessage(
                comment="I'll show you the directory structure.",
                requirements=[
                    TreeRequirement(comment="", path=str(temp_path), max_depth=2),
                ],
            )

            mock_client = create_mock_client(llm_response)
            interface = MockInterface()
            interface.set_user_inputs(["y", "exit"])  # Accept tree, then exit

            # Execute conversation
            try:
                main_loop(
                    DEFAULT_CONFIG,
                    interface,
                    f"Show me what's in {temp_dir}",
                    llm_client=mock_client,
                )
            except ValueError:
                pass

            # Verify tree output contains expected structure
            output = interface.get_all_output()
            assert "Tree:" in output
            assert "file1.txt" in output
            assert "file2.py" in output
            assert "subdir" in output
            assert "nested.md" in output
