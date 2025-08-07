"""Test path expansion functionality across all requirement types.

This module tests that paths are properly expanded from relative/tilde notation
to absolute paths in RequirementResults, which is critical for security and
consistent behavior across the system.
"""

from pathlib import Path

import pytest

from solveig.schema.requirement import (
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)
from solveig.schema.result import (
    CommandResult,
    CopyResult,
    DeleteResult,
    MoveResult,
    ReadResult,
    WriteResult,
)
from tests.test_utils import DEFAULT_CONFIG, MockRequirementFactory


class TestPathExpansionInResults:
    """Test that RequirementResults properly expand paths from requirements."""

    def test_read_result_path_expansion(self):
        """Test ReadResult expands tilde paths from ReadRequirement."""
        # Test with tilde path
        req = MockRequirementFactory.create_read_requirement(
            path="~/test.txt", only_read_metadata=False, comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Path should be expanded to absolute
        assert str(result.path).startswith(str(Path.home()))
        assert "~" not in str(result.path)
        assert str(result.path).endswith("test.txt")

    def test_write_result_path_expansion(self):
        """Test WriteResult expands tilde paths from WriteRequirement."""
        req = MockRequirementFactory.create_write_requirement(
            path="~/output.txt", is_directory=False, content="test", comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Path should be expanded to absolute
        assert str(result.path).startswith(str(Path.home()))
        assert "~" not in str(result.path)
        assert str(result.path).endswith("output.txt")

    def test_delete_result_path_expansion(self):
        """Test DeleteResult expands tilde paths from DeleteRequirement."""
        req = MockRequirementFactory.create_delete_requirement(path="~/unwanted.txt", comment="Test")
        result = req.solve(DEFAULT_CONFIG)

        # Path should be expanded to absolute
        assert str(result.path).startswith(str(Path.home()))
        assert "~" not in str(result.path)
        assert str(result.path).endswith("unwanted.txt")

    def test_move_result_path_expansion(self):
        """Test MoveResult expands both source and destination paths."""
        req = MockRequirementFactory.create_move_requirement(
            source_path="~/source.txt", destination_path="~/dest.txt", comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Both paths should be expanded
        assert str(result.source_path).startswith(str(Path.home()))
        assert str(result.destination_path).startswith(str(Path.home()))
        assert "~" not in str(result.source_path)
        assert "~" not in str(result.destination_path)
        assert str(result.source_path).endswith("source.txt")
        assert str(result.destination_path).endswith("dest.txt")

    def test_copy_result_path_expansion(self):
        """Test CopyResult expands both source and destination paths."""
        req = MockRequirementFactory.create_copy_requirement(
            source_path="~/original.txt",
            destination_path="~/backup.txt",
            comment="Test",
        )
        result = req.solve(DEFAULT_CONFIG)

        # Both paths should be expanded
        assert str(result.source_path).startswith(str(Path.home()))
        assert str(result.destination_path).startswith(str(Path.home()))
        assert "~" not in str(result.source_path)
        assert "~" not in str(result.destination_path)
        assert str(result.source_path).endswith("original.txt")
        assert str(result.destination_path).endswith("backup.txt")

    def test_command_result_no_path_expansion(self):
        """Test CommandResult preserves command exactly as provided."""
        req = MockRequirementFactory.create_command_requirement(command="ls ~/Documents", comment="Test")
        result = req.solve(DEFAULT_CONFIG)

        # Command should be preserved exactly (no path expansion for commands)
        assert result.command == "ls ~/Documents"
        assert "~" in result.command  # Tilde should remain in command

    def test_already_absolute_path_unchanged(self):
        """Test that already absolute paths are preserved."""
        absolute_path = "/absolute/path/test.txt"
        req = MockRequirementFactory.create_read_requirement(
            path=absolute_path,
            only_read_metadata=False,
            comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Path should remain the same (but resolved)
        assert Path(str(result.path)).is_absolute()
        assert str(result.path).endswith("test.txt")


class TestPathExpansionInRequirements:
    """Test path expansion logic within requirement processing."""

    def test_requirement_internal_path_expansion(self):
        """Test that requirements internally expand paths for processing."""
        req = MockRequirementFactory.create_read_requirement(
            path="~/test.txt", only_read_metadata=False, comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Validate was called with original path, but result has expanded path
        req._validate_read_access.assert_called_once()
        assert result.accepted
        assert str(result.path).startswith(str(Path.home()))


class TestPathExpansionEdgeCases:
    """Test edge cases in path expansion."""

    def test_empty_path_handling(self):
        """Test handling of edge cases like empty paths."""
        # This should be handled gracefully by Pydantic validation
        # Use the actual requirement here
        with (pytest.raises(ValueError)):
            MockRequirementFactory\
                .create_read_requirement(path="", only_read_metadata=False, comment="Test")\
                .solve(DEFAULT_CONFIG)

    def test_complex_tilde_paths(self):
        """Test complex tilde paths with subdirectories."""
        req = MockRequirementFactory.create_read_requirement(
            path="~/Documents/projects/solveig/test.txt",
            only_read_metadata=False,
            comment="Test",
        )
        result = req.solve(DEFAULT_CONFIG)

        # Should expand the tilde part but preserve directory structure
        expected_start = str(Path.home() / "Documents" / "projects" / "solveig")
        assert str(result.path).startswith(expected_start)
        assert str(result.path).endswith("test.txt")

    def test_path_with_spaces(self):
        """Test path expansion with spaces in filenames."""
        req = MockRequirementFactory.create_read_requirement(
            path="~/Documents/my file with spaces.txt",
            only_read_metadata=False,
            comment="Test",
        )
        result = req.solve(DEFAULT_CONFIG)

        # Spaces should be preserved in expanded path
        assert "my file with spaces.txt" in str(result.path)
        assert str(result.path).startswith(str(Path.home()))

    def test_symlink_resolution(self):
        """Test that symlinks are resolved in path expansion."""
        # This tests the Path.resolve() behavior
        req = MockRequirementFactory.create_read_requirement(
            path="~/test.txt", only_read_metadata=False, comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Path should be resolved (symlinks followed)
        assert Path(str(result.path)).is_absolute()
        # Note: We can't easily test actual symlink resolution without creating real symlinks


class TestPathExpansionConsistency:
    """Test that path expansion is consistent across the system."""

    def test_all_file_results_expand_paths(self):
        """Test that all file-related results expand their paths consistently."""
        home = str(Path.home())

        # Test all single-path requirements
        single_path_cases = [
            MockRequirementFactory.create_read_requirement(
                path="~/test.txt", only_read_metadata=False, comment="Test"
            ),
            MockRequirementFactory.create_write_requirement(
                path="~/test.txt", is_directory=False, comment="Test"
            ),
            MockRequirementFactory.create_delete_requirement(path="~/test.txt", comment="Test")
        ]

        for req in single_path_cases:
            result = req.solve(config=DEFAULT_CONFIG)
            assert str(result.path).startswith(home)
            assert "~" not in str(result.path)

        # Test dual-path requirements
        dual_path_cases = [
            MockRequirementFactory.create_move_requirement(
                source_path="~/src.txt",
                destination_path="~/dst.txt",
                comment="Test",
            ),
            MockRequirementFactory.create_copy_requirement(
                source_path="~/src.txt",
                destination_path="~/dst.txt",
                comment="Test",
            ),
        ]

        for req in dual_path_cases:
            result = req.solve(config=DEFAULT_CONFIG)
            assert str(result.source_path).startswith(home)
            assert str(result.destination_path).startswith(home)
            assert "~" not in str(result.source_path)
            assert "~" not in str(result.destination_path)
