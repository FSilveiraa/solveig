"""
Tests for solveig.utils.filesystem module.

The tool tests were first implemented and they already test the actual file
operations, so this file focuses on testing the metadata class.
"""

import dataclasses
from datetime import datetime
from pathlib import Path as SyncPath

import pytest
from anyio import Path

from solveig.utils.file import FileMetadata, Filesystem

pytestmark = pytest.mark.anyio


class TestMetadata:
    """Test FileMetadata dataclass."""

    async def test_metadata_creation(self):
        """Test creating metadata object."""
        metadata = FileMetadata(
            owner_name="test_user",
            group_name="test_group",
            path="/test/file.txt",
            size=1024,
            modified_time=int(
                datetime.fromisoformat("2024-01-01T12:00:00").timestamp()
            ),
            is_directory=False,
            is_readable=True,
            is_writable=True,
        )
        assert metadata.owner_name == "test_user"
        assert metadata.size == 1024
        assert metadata.is_directory is False

    def test_modified_time_is_required_not_defaulted_to_a_field_object(self):
        """A pydantic Field() as a stdlib-dataclass default is a value, not a
        requirement - it silently made modified_time optional and typed it wrong."""
        field = next(
            f
            for f in dataclasses.fields(FileMetadata)
            if f.name == "modified_time"
        )
        assert field.default is dataclasses.MISSING
        assert field.default_factory is dataclasses.MISSING
        assert field.metadata["description"]


@pytest.mark.no_file_mocking
class TestWorkingDirectory:
    """`Filesystem` is the door to Solveig's one working directory.

    The process cwd is the single source of truth - not a copy kept beside it -
    so these assert that moving through the one writer is what every reader
    sees."""

    def test_change_moves_what_a_relative_path_means(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "target.txt").touch()

        Filesystem.change_current_dir(tmp_path / "sub")

        assert Filesystem.get_absolute_path("./target.txt") == Filesystem.get_absolute_path(
            tmp_path / "sub" / "target.txt"
        )

    def test_no_argument_answers_where_we_are(self, tmp_path):
        Filesystem.change_current_dir(tmp_path)
        assert Filesystem.get_absolute_path() == Filesystem.get_absolute_path(tmp_path)

    def test_change_returns_where_it_landed(self, tmp_path):
        assert Filesystem.change_current_dir(tmp_path) == Filesystem.get_absolute_path(
            tmp_path
        )

    def test_change_refuses_a_directory_that_is_not_there(self, tmp_path):
        origin = Filesystem.get_absolute_path()
        with pytest.raises(OSError):
            Filesystem.change_current_dir(tmp_path / "nope")
        assert Filesystem.get_absolute_path() == origin

    def test_display_path_shortens_home_and_follows_us(self, tmp_path):
        Filesystem.change_current_dir(tmp_path)
        assert Filesystem.get_simple_path() == str(tmp_path)
        assert Filesystem.get_simple_path(SyncPath.home() / "x") == "~/x"


@pytest.mark.no_file_mocking
class TestPathPatterns:
    """`ignored_paths`/`auto_allowed_paths` are safety rules, so a pattern that
    silently matches nothing is worse than one that errors."""

    def test_double_star_matches_at_any_depth(self):
        """`PurePath.match` treats `**` as a single `*`, which made a recursive
        ignore pattern block nothing at all. `full_match` is why this passes."""
        deep = Path("/home/u/proj/a/b/c.log")
        assert Filesystem.path_matches_patterns(deep, [Path("/home/u/proj/**/*.log")])

    def test_single_star_stays_one_level(self):
        assert Filesystem.path_matches_patterns(
            Path("/home/u/proj/c.log"), [Path("/home/u/proj/*.log")]
        )
        assert not Filesystem.path_matches_patterns(
            Path("/home/u/proj/a/c.log"), [Path("/home/u/proj/*.log")]
        )

    def test_pattern_is_anchored_not_matched_from_the_right(self):
        """`match` would accept a bare suffix anywhere in the tree; an absolute
        safety pattern has to mean the place it names."""
        assert not Filesystem.path_matches_patterns(
            Path("/elsewhere/proj/c.log"), [Path("/home/u/proj/*.log")]
        )

    def test_no_patterns_matches_nothing(self):
        assert not Filesystem.path_matches_patterns(Path("/home/u/x"), [])
