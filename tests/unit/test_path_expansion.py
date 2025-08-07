"""Test path expansion functionality across all requirement types.

Condensed tests focusing on the core path expansion behavior that's actually
critical for security and system consistency.
"""

from pathlib import Path

import pytest

from tests.test_utils import DEFAULT_CONFIG, MockRequirementFactory


class TestPathExpansion:
    """Test core path expansion behavior."""

    def test_tilde_expansion_single_path_requirements(self):
        """Test that single-path requirements expand tilde paths consistently."""
        home = str(Path.home())

        # Test all single-path requirement types
        requirements = [
            MockRequirementFactory.create_read_requirement(
                path="~/test.txt", comment="Test"
            ),
            MockRequirementFactory.create_write_requirement(
                path="~/test.txt", comment="Test"
            ),
            MockRequirementFactory.create_delete_requirement(
                path="~/test.txt", comment="Test"
            ),
        ]

        for req in requirements:
            result = req.solve(DEFAULT_CONFIG)
            assert str(result.path).startswith(home)
            assert "~" not in str(result.path)
            assert str(result.path).endswith("test.txt")

    def test_tilde_expansion_dual_path_requirements(self):
        """Test that dual-path requirements expand both source and destination paths."""
        home = str(Path.home())

        # Test dual-path requirement types
        requirements = [
            MockRequirementFactory.create_move_requirement(
                source_path="~/source.txt",
                destination_path="~/dest.txt",
                comment="Test",
            ),
            MockRequirementFactory.create_copy_requirement(
                source_path="~/source.txt",
                destination_path="~/dest.txt",
                comment="Test",
            ),
        ]

        for req in requirements:
            result = req.solve(DEFAULT_CONFIG)
            assert str(result.source_path).startswith(home)
            assert str(result.destination_path).startswith(home)
            assert "~" not in str(result.source_path)
            assert "~" not in str(result.destination_path)

    def test_command_preserves_original_text(self):
        """Test that commands preserve tilde and other path text exactly."""
        req = MockRequirementFactory.create_command_requirement(
            command="ls ~/Documents && cat ~/.bashrc", comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        # Command should be preserved exactly (no path expansion)
        assert result.command == "ls ~/Documents && cat ~/.bashrc"
        assert "~" in result.command

    def test_already_absolute_paths_preserved(self):
        """Test that absolute paths remain absolute and resolved."""
        req = MockRequirementFactory.create_read_requirement(
            path="/tmp/absolute.txt", comment="Test"
        )
        result = req.solve(DEFAULT_CONFIG)

        assert Path(str(result.path)).is_absolute()
        assert str(result.path).endswith("absolute.txt")

    def test_empty_path_validation(self):
        """Test that empty paths are rejected by validation."""
        with pytest.raises(ValueError):
            MockRequirementFactory.create_read_requirement(
                path="", comment="Test"
            ).solve(DEFAULT_CONFIG)

    def test_complex_path_expansion(self):
        """Test expansion of complex paths with subdirectories and spaces."""
        # Test path with subdirectories
        req1 = MockRequirementFactory.create_read_requirement(
            path="~/Documents/projects/file.txt", comment="Test"
        )
        result1 = req1.solve(DEFAULT_CONFIG)
        expected = str(Path.home() / "Documents" / "projects" / "file.txt")
        assert str(result1.path) == expected

        # Test path with spaces
        req2 = MockRequirementFactory.create_read_requirement(
            path="~/my file with spaces.txt", comment="Test"
        )
        result2 = req2.solve(DEFAULT_CONFIG)
        assert "my file with spaces.txt" in str(result2.path)
        assert str(result2.path).startswith(str(Path.home()))
