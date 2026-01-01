"""Integration test for TreeTool plugin with real filesystem operations."""

import tempfile
from pathlib import Path, PurePath

import pytest

from solveig.plugins.tools.tree import TreeTool
from solveig.run import run_async
from solveig.schema.message import AssistantMessage
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestTreePlugin:
    """Test TreeTool plugin with real filesystem operations."""

    async def test_tree_plugin_with_real_files(self, load_plugins):
        """Test tree plugin creates visual directory tree from real filesystem."""
        # Enable the tree plugin for this test
        config = DEFAULT_CONFIG.with_(plugins=["tree"])
        await load_plugins(config)

        # Create real directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "file1.txt").write_text("content1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "nested.md").write_text("# Nested file")

            # LLM requests tree inspection
            assistant_responses = [
                AssistantMessage(
                    comment="I'll show you the directory structure.",
                    tools=[
                        TreeTool(comment="", path=str(temp_path), max_depth=2),
                    ],
                ),
                AssistantMessage(comment="Everything looks nice!"),
            ]

            mock_client = create_mock_client(*assistant_responses)
            interface = MockInterface(choices=[0])

            # Execute conversation
            await run_async(
                config=DEFAULT_CONFIG,
                interface=interface,
                llm_client=mock_client,
                user_prompt=f"Show me what's in {temp_dir}",
            )

            # Verify tree output contains expected structure
            output = interface.get_all_output()
            assert "Tree:" in output
            assert "file1.txt" in output
            assert "file2.py" in output
            assert "subdir" in output
            assert "nested.md" in output

    async def test_tree_tool_creation_and_validation(self):
        """Test TreeTool creation, validation, and configuration."""
        # Valid creation with default settings
        req = TreeTool(path="     /test/dir   ", comment="Generate tree listing")
        assert req.path == "/test/dir"  # test whitespace stripping
        assert req.comment == "Generate tree listing"
        assert req.max_depth == -1  # Default unlimited depth

        # Custom max_depth configuration
        req_limited = TreeTool(path="/test", max_depth=3, comment="test")
        assert req_limited.max_depth == 3

        # Validation: empty path should fail
        with pytest.raises(ValueError):
            TreeTool(path="", comment="empty path")

        # Class description
        description = TreeTool.get_description()
        assert "tree(path)" in description
        assert "directory tree structure" in description

    async def test_tree_tool_display_and_error_handling(self):
        """Test TreeTool display functionality and error result creation."""
        req = TreeTool(path="/test/dir", comment="Generate tree listing")
        interface = MockInterface()

        # Test display header
        await req.display_header(interface)
        output = interface.get_all_output()
        assert "Generate tree listing" in output

        # Test error result creation
        error_result = req.create_error_result("Directory not found", accepted=False)

        # This import has to occur locally since Python reloads the plugin re.quirement class
        # before each test and gives it a different class ID
        from solveig.plugins.tools.tree import TreeResult

        assert isinstance(error_result, TreeResult)

        assert error_result.tool == req
        assert error_result.accepted is False
        assert error_result.error == "Directory not found"
        assert error_result.metadata is None
        assert str(error_result.path).startswith("/")  # Path should be absolute

    @pytest.mark.no_file_mocking
    async def test_tree_depth_limiting_and_user_interaction(self, load_plugins):
        """Test tree with depth limits and user interaction through solve() method."""
        # Enable the tree plugin for this test
        config = DEFAULT_CONFIG.with_(plugins=["tree"])
        await load_plugins(config)
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

            req = TreeTool(
                path=str(temp_path), max_depth=2, comment="Limited depth tree"
            )
            interface = MockInterface(choices=[0])  # read+send tree

            result = await req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is True
            # we have until subdir3
            assert result.metadata.listing[str(PurePath(temp_path / "subdir6/"))]
            final_level_metadata = result.metadata.listing[
                str(PurePath(temp_path / "subdir2/"))
            ].listing[str(PurePath(temp_path / "subdir2/subdir3/"))]
            # however we don't get the metadata further down, even though it exists
            assert not final_level_metadata.listing
            assert final_subdir.exists()

            # Test user interaction with error case
            # decline to send error for non-existent path
            interface = MockInterface(choices=[1])

            error_req = TreeTool(
                path=str(temp_path / "nonexistent"), comment="Test tree"
            )
            result = await error_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False
            assert result.error
