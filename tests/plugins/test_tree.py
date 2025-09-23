"""Integration test for TreeRequirement plugin with real filesystem operations."""

import tempfile
from pathlib import Path, PurePath

import pytest

from scripts.run import main_loop
from solveig.plugins.schema.tree import TreeRequirement
from solveig.schema.message import AssistantMessage
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
            llm_response = AssistantMessage(
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

    def test_tree_requirement_creation_and_validation(self):
        """Test TreeRequirement creation, validation, and configuration."""
        # Valid creation with default settings
        req = TreeRequirement(path="     /test/dir   ", comment="Generate tree listing")
        assert req.path == "/test/dir"  # test whitespace stripping
        assert req.comment == "Generate tree listing"
        assert req.max_depth == -1  # Default unlimited depth

        # Custom max_depth configuration
        req_limited = TreeRequirement(path="/test", max_depth=3, comment="test")
        assert req_limited.max_depth == 3

        # Validation: empty path should fail
        with pytest.raises(ValueError):
            TreeRequirement(path="", comment="empty path")

        # Class description
        description = TreeRequirement.get_description()
        assert "tree(path)" in description
        assert "directory tree structure" in description

    def test_tree_requirement_display_and_error_handling(self):
        """Test TreeRequirement display functionality and error result creation."""
        req = TreeRequirement(path="/test/dir", comment="Generate tree listing")
        interface = MockInterface()

        # Test display header
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Generate tree listing" in output

        # Test error result creation
        error_result = req.create_error_result("Directory not found", accepted=False)

        # Python reloads the plugin requirement class before each test and gives it a different class ID
        from solveig.plugins.schema.tree import TreeResult

        assert isinstance(error_result, TreeResult)

        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Directory not found"
        assert error_result.metadata is None
        assert str(error_result.path).startswith("/")  # Path should be absolute

    @pytest.mark.no_file_mocking
    def test_tree_depth_limiting_and_user_interaction(self):
        """Test tree with depth limits and user interaction through solve() method."""
        # Create temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            file1 = temp_path / "file1.txt"
            file1.write_text("content1")
            file2 = temp_path / "file2.py"
            file2.write_text("print('hello')")
            subdir1 = temp_path / "subdir1"
            subdir1.mkdir()
            final_subdir = temp_path / "subdir2/subdir3/subdir4/subdir5"
            final_subdir.mkdir(parents=True)
            file3 = temp_path / "subdir2/subdir3/file3.txt"
            file3.touch()
            file4 = temp_path / "subdir2/subdir3/subdir4/file4.txt"
            file4.touch()
            (temp_path / "subdir6").mkdir()

            req = TreeRequirement(
                path=str(temp_path), max_depth=2, comment="Limited depth tree"
            )
            interface = MockInterface()
            interface.set_user_inputs(["y"])

            result = req.actually_solve(DEFAULT_CONFIG, interface)
            assert result.accepted is True
            # we have until subdir3
            assert result.metadata.listing[PurePath(temp_path / "subdir6/")]
            final_level_metadata = result.metadata.listing[
                PurePath(temp_path / "subdir2/")
            ].listing[PurePath(temp_path / "subdir2/subdir3/")]
            # however we don't get the metadata further down, even though it exists
            assert not final_level_metadata.listing
            assert final_subdir.exists()

            # Test user interaction with error case
            interface.clear()
            interface.set_user_inputs(["n"])  # User declines if error prompt appears

            error_req = TreeRequirement(
                path=str(temp_path / "nonexistent"), comment="Test tree"
            )
            result = error_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False
            assert result.error
