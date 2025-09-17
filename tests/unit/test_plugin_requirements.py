"""Unit tests for plugin requirements system."""

from pathlib import Path

import pytest

from solveig.plugins.schema.tree import TreeRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface


class TestTreeRequirement:
    """Test TreeRequirement plugin functionality."""

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

    def test_tree_complete_execution_flow(self, mock_filesystem):
        """Test complete tree execution: filesystem interaction, display, and result generation."""
        # clear the filesystem and write a smaller structure to ensure it fits on the window
        mock_filesystem._entries.clear()
        mock_filesystem.create_directory("/test")
        mock_filesystem.write_file("/test/file.txt", "file one here shntpdsohnwtd")
        mock_filesystem.create_directory("/test/subdir")
        mock_filesystem.write_file(
            "/test/subdir/nested.txt", "file two ufsufutfuuuuuudurrrr"
        )

        # Execute tree requirement
        req = TreeRequirement(path="/test", comment="Test tree")
        interface = MockInterface()

        result = req.actually_solve(DEFAULT_CONFIG, interface)

        # Python reloads the plugin requirement class before each test and gives it a different class ID
        from solveig.plugins.schema.tree import TreeResult
        assert isinstance(result, TreeResult)

        # Verify complete result
        assert result.accepted is True
        assert result.error is None

        assert result.metadata.path == Path("/test")

        # Verify tree visualization was displayed
        output = interface.get_all_output()
        assert "Tree:" in output
        assert "🗁  test" in output  # Root directory
        assert "🗎 file.txt" in output  # Root file
        assert "🗁  subdir" in output  # Subdirectory
        assert "🗎 nested.txt" in output  # Nested file

        # Verify filesystem was called correctly
        mock_filesystem.read_metadata.assert_called_with(
            Path("/test"), descend_level=-1
        )

    def test_tree_depth_limiting_and_user_interaction(self, mock_filesystem):
        """Test tree with depth limits and user interaction through solve() method."""
        # Create directory structure in mock filesystem
        mock_filesystem.create_directory("/test")
        mock_filesystem.write_file("/test/file1.txt", "content1")
        mock_filesystem.create_directory("/test/subdir")
        mock_filesystem.write_file("/test/subdir/file2.txt", "content2")

        req = TreeRequirement(path="/test", max_depth=2, comment="Limited depth tree")
        interface = MockInterface()

        result = req.actually_solve(DEFAULT_CONFIG, interface)

        # Verify depth limit was passed to filesystem
        call_args = mock_filesystem.read_metadata.call_args
        assert str(call_args[0][0]) == "/test"  # First argument (path)
        assert call_args[1]["descend_level"] == 2  # Depth limit
        assert result.accepted is True

        # Test user interaction with error case
        interface.clear()
        interface.set_user_inputs(["n"])  # User declines if error prompt appears

        error_req = TreeRequirement(path="/nonexistent", comment="Test tree")
        result = error_req.solve(DEFAULT_CONFIG, interface)

        # Should return a result regardless of success/failure
        from solveig.plugins.schema.tree import TreeResult
        assert isinstance(result, TreeResult)
        assert result.requirement == error_req
