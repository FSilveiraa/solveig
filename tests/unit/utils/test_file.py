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

    def test_naming_a_directory_covers_everything_inside_it(self):
        """`ignored_paths: ["~/.ssh"]` has to block `~/.ssh/id_rsa`. Blocking the
        directory node alone and letting its contents through is the failure mode
        that makes a safety rule theatre."""
        blocked = [Path("/home/u/.ssh")]
        assert Filesystem.path_matches_patterns(Path("/home/u/.ssh"), blocked)
        assert Filesystem.path_matches_patterns(Path("/home/u/.ssh/id_rsa"), blocked)
        assert Filesystem.path_matches_patterns(
            Path("/home/u/.ssh/keys/backup/id_rsa"), blocked
        )

    def test_a_covered_directory_does_not_leak_to_its_siblings(self):
        blocked = [Path("/home/u/.ssh")]
        assert not Filesystem.path_matches_patterns(Path("/home/u/.sshfoo"), blocked)
        assert not Filesystem.path_matches_patterns(Path("/home/u"), blocked)
        assert not Filesystem.path_matches_patterns(Path("/home/u/notes.md"), blocked)

    def test_a_glob_directory_also_covers_its_contents(self):
        """One rule for both cases: ancestors are checked, so a pattern with glob
        characters covers a subtree exactly the way a literal one does."""
        assert Filesystem.path_matches_patterns(
            Path("/home/u/proj/a/secrets/key.pem"), [Path("/home/u/proj/*/secrets")]
        )

    def test_trailing_slash_is_the_same_pattern(self):
        """People should not have to fight path patterns; pathlib normalizes the
        trailing slash away on construction, so both spellings agree."""
        target = Path("/home/u/.ssh/id_rsa")
        assert Filesystem.path_matches_patterns(target, [Path("/home/u/.ssh/")])
        assert Filesystem.path_matches_patterns(target, [Path("/home/u/.ssh")])


@pytest.mark.no_file_mocking
class TestIgnoredPathsPruneTheListing:
    """The listing is what reaches the assistant, so an ignored entry has to be
    absent from the metadata - not merely undrawn by a frontend."""

    async def test_ignored_entry_is_absent_from_the_listing(self, tmp_path):
        (tmp_path / "keep.txt").touch()
        (tmp_path / ".ssh").mkdir()
        (tmp_path / ".ssh" / "id_rsa").touch()

        metadata = await Filesystem.read_metadata(
            Filesystem.get_absolute_path(tmp_path),
            ignored_paths=[Filesystem.get_absolute_path(tmp_path / ".ssh")],
        )

        assert metadata.listing is not None
        names = {SyncPath(p).name for p in metadata.listing}
        assert names == {"keep.txt"}

    async def test_ignored_subtree_is_never_walked(self, tmp_path):
        """Pruning happens before the recursion, so the excluded directory costs
        nothing and cannot raise on the way past."""
        (tmp_path / "secret").mkdir()
        (tmp_path / "secret" / "deep").mkdir()
        (tmp_path / "secret" / "deep" / "key.pem").touch()
        (tmp_path / "visible").mkdir()

        metadata = await Filesystem.read_metadata(
            Filesystem.get_absolute_path(tmp_path),
            descend_level=-1,
            ignored_paths=[Filesystem.get_absolute_path(tmp_path / "secret")],
        )

        assert metadata.listing is not None
        assert {SyncPath(p).name for p in metadata.listing} == {"visible"}

    async def test_no_patterns_lists_everything(self, tmp_path):
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()

        metadata = await Filesystem.read_metadata(
            Filesystem.get_absolute_path(tmp_path)
        )

        assert metadata.listing is not None
        assert {SyncPath(p).name for p in metadata.listing} == {"a.txt", "b.txt"}


@pytest.mark.no_file_mocking
class TestBareNamePatterns:
    """gitignore's rule, because it is the one users already have in their
    fingers: no separator means "wherever this appears", any separator anchors."""

    def test_bare_name_matches_at_any_depth(self):
        ignored = [Filesystem.resolve_pattern("node_modules")]
        assert Filesystem.path_matches_patterns(Path("/proj/node_modules/x"), ignored)
        assert Filesystem.path_matches_patterns(
            Path("/proj/src/a/node_modules/deep/x"), ignored
        )

    def test_bare_name_is_stored_unanchored(self):
        """Anchoring it would silently shrink `node_modules` to the single
        top-level copy - the failure this rule exists to prevent."""
        assert str(Filesystem.resolve_pattern("node_modules")) == "node_modules"

    def test_a_pattern_naming_a_directory_still_anchors(self):
        resolved = Filesystem.resolve_pattern("~/.ssh")
        assert resolved.is_absolute()
        assert Filesystem.path_matches_patterns(
            Filesystem.get_absolute_path("~/.ssh/id_rsa"), [resolved]
        )
        assert not Filesystem.path_matches_patterns(
            Path("/somewhere/else/.ssh/id_rsa"), [resolved]
        )

    def test_bare_glob_matches_by_name(self):
        ignored = [Filesystem.resolve_pattern("*.pem")]
        assert Filesystem.path_matches_patterns(Path("/proj/keys/server.pem"), ignored)
        assert not Filesystem.path_matches_patterns(Path("/proj/keys/server.txt"), ignored)

    def test_bare_name_does_not_match_a_partial_component(self):
        ignored = [Filesystem.resolve_pattern(".git")]
        assert Filesystem.path_matches_patterns(Path("/proj/src/.git/config"), ignored)
        assert not Filesystem.path_matches_patterns(Path("/proj/.gitignore"), ignored)
