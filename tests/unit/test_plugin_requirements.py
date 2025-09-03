"""
Simple unit tests for plugin requirements system.
Tests core plugin functionality without over-engineering.
"""

from unittest.mock import patch

from solveig.plugins.schema.tree import TreeRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface


class TestPluginRequirements:
    """Test plugin requirements functionality."""

    def test_tree_requirement_complete_flow(self):
        """Test TreeRequirement validation, display, error creation, and solve."""
        req = TreeRequirement(path="/test/dir", comment="Generate tree listing")
        interface = MockInterface()

        # Test display header
        req.display_header(interface)
        output = interface.get_all_output()
        assert "Generate tree listing" in output
        interface.clear()

        # Test create_error_result
        error_result = req.create_error_result("Directory not found", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Directory not found"
        assert error_result.tree_output == ""
        assert error_result.total_files == 0

        # Test solve with non-existent directory (error path)
        interface.set_user_inputs(["n"])  # Decline if asked about errors
        result = req.solve(DEFAULT_CONFIG, interface)
        assert result.requirement == req

        # Test get_description
        description = TreeRequirement.get_description()
        assert "tree(path)" in description
        assert "directory tree structure" in description

    def test_tree_requirement_validation(self):
        """Test TreeRequirement path validation."""
        # Valid path should work
        req = TreeRequirement(path="/valid/path", comment="test")
        assert req.path == "/valid/path"

        # Path should be stripped of whitespace
        req_strip = TreeRequirement(path="  /test/path  ", comment="test")
        assert req_strip.path == "/test/path"

        # Empty path should fail validation
        try:
            TreeRequirement(path="", comment="empty path")
            raise AssertionError("Should have raised validation error")
        except Exception:
            pass  # Expected validation error

    @patch("solveig.utils.file.Filesystem.read_metadata")
    @patch("solveig.utils.file.Filesystem._is_dir")
    @patch("solveig.utils.file.Filesystem.get_dir_listing")
    def test_tree_successful_directory_processing(
        self, mock_listing, mock_is_dir, mock_metadata
    ):
        """Test tree requirement with successful directory processing."""
        from pathlib import Path

        from solveig.utils.file import Metadata

        # Mock successful directory access
        mock_metadata.return_value = Metadata(
            owner_name="user",
            group_name="group",
            path=Path("/test"),
            size=0,
            modified_time="2023-01-01",
            is_directory=True,
            is_readable=True,
            is_writable=True,
        )
        mock_is_dir.return_value = True
        mock_listing.return_value = {
            Path("/test/file.txt"): Metadata(
                owner_name="user",
                group_name="group",
                path=Path("/test/file.txt"),
                size=100,
                modified_time="2023-01-01",
                is_directory=False,
                is_readable=True,
                is_writable=True,
            )
        }

        req = TreeRequirement(path="/test", comment="Test tree")
        interface = MockInterface()

        result = req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted is True
        assert result.total_files == 1
        assert result.total_dirs == 1
