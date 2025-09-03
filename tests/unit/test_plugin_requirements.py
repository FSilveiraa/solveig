"""Unit tests for plugin requirements system."""

from pathlib import Path
from unittest.mock import patch

from solveig.plugins.schema.tree import TreeRequirement, TreeResult
from solveig.utils.file import Metadata
from tests.mocks import DEFAULT_CONFIG, MockInterface


class TestTreeRequirement:
    """Test TreeRequirement plugin functionality."""

    def test_tree_requirement_creation_and_validation(self):
        """Test TreeRequirement creation, validation, and configuration."""
        # Valid creation with default settings
        req = TreeRequirement(path="     /test/dir   ", comment="Generate tree listing")
        assert req.path == "/test/dir" # test whitespace stripping
        assert req.comment == "Generate tree listing"
        assert req.max_depth == -1  # Default unlimited depth
        
        # Custom max_depth configuration
        req_limited = TreeRequirement(path="/test", max_depth=3, comment="test")
        assert req_limited.max_depth == 3
        
        # Validation: empty path should fail
        try:
            TreeRequirement(path="", comment="empty path")
            assert False, "Should have raised validation error for empty path"
        except Exception:
            pass  # Expected validation error
        
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
        
        assert isinstance(error_result, TreeResult)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Directory not found"
        assert error_result.metadata is None
        assert str(error_result.path).startswith("/")  # Path should be absolute

    @patch("solveig.utils.file.Filesystem.read_metadata")
    def test_tree_complete_execution_flow(self, mock_read_metadata):
        """Test complete tree execution: filesystem interaction, display, and result generation."""
        # Create realistic nested metadata structure
        file_metadata = Metadata(
            path=Path("/test/file.txt"), is_directory=False, size=100,
            modified_time="2023-01-01", owner_name="user", group_name="group",
            is_readable=True, is_writable=True
        )
        
        nested_file = Metadata(
            path=Path("/test/subdir/nested.txt"), is_directory=False, size=50,
            modified_time="2023-01-01", owner_name="user", group_name="group",
            is_readable=True, is_writable=True
        )
        
        subdir_metadata = Metadata(
            path=Path("/test/subdir"), is_directory=True, size=4096,
            modified_time="2023-01-01", owner_name="user", group_name="group",
            is_readable=True, is_writable=True, 
            listing={Path("/test/subdir/nested.txt"): nested_file}
        )
        
        root_metadata = Metadata(
            path=Path("/test"), is_directory=True, size=4096,
            modified_time="2023-01-01", owner_name="user", group_name="group",
            is_readable=True, is_writable=True,
            listing={
                Path("/test/file.txt"): file_metadata,
                Path("/test/subdir"): subdir_metadata,
            }
        )
        
        mock_read_metadata.return_value = root_metadata
        
        # Execute tree requirement
        req = TreeRequirement(path="/test", comment="Test tree")
        interface = MockInterface()
        
        result = req.actually_solve(DEFAULT_CONFIG, interface)
        
        # Verify complete result
        assert isinstance(result, TreeResult)
        assert result.accepted is True
        assert result.error is None
        assert result.metadata == root_metadata
        assert str(result.path) == "/test"
        
        # Verify tree visualization was displayed
        output = interface.get_all_output()
        assert "Tree:" in output
        assert "🗁 test" in output  # Root directory
        assert "🗎 file.txt" in output  # Root file
        assert "🗁 subdir" in output  # Subdirectory
        assert "🗎 nested.txt" in output  # Nested file
        
        # Verify filesystem was called correctly
        mock_read_metadata.assert_called_once_with("/test", descend_level=-1)

    @patch("solveig.utils.file.Filesystem.read_metadata") 
    def test_tree_depth_limiting_and_user_interaction(self, mock_read_metadata):
        """Test tree with depth limits and user interaction through solve() method."""
        # Test depth limiting
        root_metadata = Metadata(
            path=Path("/test"), is_directory=True, size=4096,
            modified_time="2023-01-01", owner_name="user", group_name="group",
            is_readable=True, is_writable=True, listing={}
        )
        mock_read_metadata.return_value = root_metadata
        
        req = TreeRequirement(path="/test", max_depth=2, comment="Limited depth tree")
        interface = MockInterface()
        
        result = req.actually_solve(DEFAULT_CONFIG, interface)
        
        # Verify depth limit was passed to filesystem
        mock_read_metadata.assert_called_once()
        call_args = mock_read_metadata.call_args
        assert str(call_args[0][0]) == "/test"  # First argument (path)
        assert call_args[1]["descend_level"] == 2  # Depth limit
        assert result.accepted is True
        
        # Test user interaction with error case
        interface.clear()
        interface.set_user_inputs(["n"])  # User declines if error prompt appears
        
        error_req = TreeRequirement(path="/nonexistent", comment="Test tree")
        result = error_req.solve(DEFAULT_CONFIG, interface)
        
        # Should return a result regardless of success/failure
        assert isinstance(result, TreeResult)
        assert result.requirement == error_req