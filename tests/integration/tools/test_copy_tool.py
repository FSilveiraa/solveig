"""Integration tests for the `CopyTool` tool.

`CopyTool(source_path=..., destination_path=...)` is constructed (field
validators run on construction), then run via `await tool.execute(ctx)`.
`ToolResult` has no `accepted`/`error`/`source_path`/`destination_path`
fields: a successful copy's `result.content` is
`f"Copied {abs_source} to {abs_destination}"` (which doubles as the
path-resolution check the old tests did via `.source_path`/`.destination_path`),
a decline is the literal `"User declined the copy."`, and failures land in
`result.issues`.

`display_header` (the `Source:`/`Destination:` lines) is rendered by the
orchestration wrapper, not `execute()`, so the header test calls it directly.
"""

from pathlib import Path

import pytest

from solveig.context import build_run_context
from solveig.tools.core.copy import CopyTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None):
    return build_run_context(config, interface or MockInterface())


class TestCopyValidation:
    async def test_empty_source_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            CopyTool(source_path="", destination_path="/valid")

    async def test_empty_destination_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            CopyTool(source_path="/valid", destination_path="")

    async def test_header_shows_source_and_destination(self, tmp_path):
        source_file = tmp_path / "test.txt"
        dest_file = tmp_path / "dest.txt"
        source_file.write_text("hi")
        interface = MockInterface()

        await CopyTool(
            source_path=str(source_file), destination_path=str(dest_file)
        ).display_header(interface)

        output = interface.get_all_output()
        assert str(source_file) in output
        assert str(dest_file) in output


class TestFileOperations:
    async def test_copy_file_accept(self, tmp_path):
        source_file = tmp_path / "source.txt"
        dest_file = tmp_path / "dest.txt"
        source_file.write_text("This file will be copied")
        interface = MockInterface(choices=[0])

        result = await CopyTool(
            source_path=str(source_file), destination_path=str(dest_file)
        ).execute(make_ctx(interface=interface))

        assert result.issues == []
        assert source_file.exists()
        assert dest_file.read_text() == "This file will be copied"

    async def test_copy_file_decline(self, tmp_path):
        source_file = tmp_path / "source.txt"
        dest_file = tmp_path / "dest.txt"
        source_file.write_text("This file should not be copied")
        interface = MockInterface(choices=[1])

        result = await CopyTool(
            source_path=str(source_file), destination_path=str(dest_file)
        ).execute(make_ctx(interface=interface))

        assert result.content == "User declined the copy."
        assert source_file.exists()
        assert not dest_file.exists()

    async def test_copy_directory_accept(self, tmp_path):
        source_dir = tmp_path / "source_dir"
        dest_dir = tmp_path / "dest_dir"
        source_dir.mkdir()
        (source_dir / "file1.txt").write_text("Content 1")
        subdir = source_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested content")
        interface = MockInterface(choices=[0])

        result = await CopyTool(
            source_path=str(source_dir), destination_path=str(dest_dir)
        ).execute(make_ctx(interface=interface))

        assert result.issues == []
        assert source_dir.exists()
        assert (dest_dir / "file1.txt").read_text() == "Content 1"
        assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested content"

    async def test_copy_directory_decline(self, tmp_path):
        source_dir = tmp_path / "source_dir"
        dest_dir = tmp_path / "dest_dir"
        source_dir.mkdir()
        (source_dir / "important.txt").write_text("Important data")
        interface = MockInterface(choices=[1])

        result = await CopyTool(
            source_path=str(source_dir), destination_path=str(dest_dir)
        ).execute(make_ctx(interface=interface))

        assert result.content == "User declined the copy."
        assert source_dir.exists()
        assert not dest_dir.exists()


class TestAutoAllowedPaths:
    async def test_auto_allowed_file_copy(self, tmp_path):
        source_file = tmp_path / "auto_source.txt"
        dest_file = tmp_path / "auto_dest.txt"
        source_file.write_text("Auto-copy content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await CopyTool(
            source_path=str(source_file), destination_path=str(dest_file)
        ).execute(make_ctx(config, interface))

        assert result.issues == []
        assert dest_file.read_text() == "Auto-copy content"
        assert len(interface.questions) == 0
        assert "auto_allowed_paths" in interface.get_all_output()

    async def test_auto_allowed_directory_copy(self, tmp_path):
        source_dir = tmp_path / "auto_source"
        dest_dir = tmp_path / "auto_dest"
        source_dir.mkdir()
        (source_dir / "content.txt").write_text("Directory content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await CopyTool(
            source_path=str(source_dir), destination_path=str(dest_dir)
        ).execute(make_ctx(config, interface))

        assert result.issues == []
        assert (dest_dir / "content.txt").read_text() == "Directory content"
        assert len(interface.questions) == 0

    async def test_partial_auto_allowed_requires_choice(self, tmp_path):
        auto_file = tmp_path / "auto" / "source.txt"
        manual_file = tmp_path / "manual" / "dest.txt"
        auto_file.parent.mkdir()
        manual_file.parent.mkdir()
        auto_file.write_text("Source content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/auto/**"])
        interface = MockInterface(choices=[0])

        result = await CopyTool(
            source_path=str(auto_file), destination_path=str(manual_file)
        ).execute(make_ctx(config, interface))

        assert result.issues == []
        assert manual_file.exists()
        assert len(interface.questions) == 1


class TestErrorHandling:
    async def test_copy_nonexistent_source(self, tmp_path):
        nonexistent_file = tmp_path / "nonexistent.txt"
        dest_file = tmp_path / "dest.txt"
        interface = MockInterface()

        result = await CopyTool(
            source_path=str(nonexistent_file), destination_path=str(dest_file)
        ).execute(make_ctx(interface=interface))

        assert len(result.issues) == 1
        assert any(
            phrase in str(result.issues[0]).lower()
            for phrase in ["not found", "does not exist", "no such file"]
        )

    async def test_copy_permission_denied_source(self, tmp_path):
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        source_file = restricted_dir / "protected.txt"
        source_file.write_text("Protected content")
        dest_file = tmp_path / "dest.txt"
        source_file.chmod(0o000)
        interface = MockInterface()

        try:
            result = await CopyTool(
                source_path=str(source_file), destination_path=str(dest_file)
            ).execute(make_ctx(interface=interface))
            assert len(result.issues) == 1
        finally:
            source_file.chmod(0o644)

    async def test_copy_permission_denied_destination(self, tmp_path):
        source_file = tmp_path / "source.txt"
        source_file.write_text("Source content")
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        dest_file = restricted_dir / "dest.txt"
        restricted_dir.chmod(0o444)
        interface = MockInterface()

        try:
            result = await CopyTool(
                source_path=str(source_file), destination_path=str(dest_file)
            ).execute(make_ctx(interface=interface))
            assert len(result.issues) == 1
            assert "permission" in str(result.issues[0]).lower()
        finally:
            restricted_dir.chmod(0o755)


class TestPathSecurity:
    async def test_tilde_expansion(self):
        source_file_path = Path.home() / ".solveig_test_copy_source.txt"
        dest_file_path = Path.home() / ".solveig_test_copy_dest.txt"
        source_file_path.write_bytes(b"Tilde expansion test")
        dest_file_path.unlink(missing_ok=True)
        try:
            interface = MockInterface(choices=[0])

            result = await CopyTool(
                source_path="~/.solveig_test_copy_source.txt",
                destination_path="~/.solveig_test_copy_dest.txt",
            ).execute(make_ctx(interface=interface))

            assert result.issues == []
            assert "~" not in result.content
            assert str(Path.home()) in result.content
            assert dest_file_path.exists()
        finally:
            if source_file_path.exists():
                source_file_path.unlink()
            if dest_file_path.exists():
                dest_file_path.unlink()

    async def test_path_traversal_resolution(self, tmp_path):
        subdir = tmp_path / "public" / "subdir"
        subdir.mkdir(parents=True)
        source_file = tmp_path / "source.txt"
        source_file.write_text("Source file")
        traversal_source = str(subdir / ".." / ".." / "source.txt")
        dest_file = str(subdir / "dest.txt")
        interface = MockInterface(choices=[0])

        result = await CopyTool(
            source_path=traversal_source, destination_path=dest_file
        ).execute(make_ctx(interface=interface))

        assert result.issues == []
        assert ".." not in result.content
        assert Path(dest_file).read_text() == "Source file"


class TestIntegrationScenarios:
    async def test_copy_large_directory_tree(self, tmp_path):
        source_dir = tmp_path / "large_source"
        dest_dir = tmp_path / "large_dest"
        source_dir.mkdir()
        for i in range(10):
            (source_dir / f"file_{i:03d}.txt").write_text(f"Content {i}")
        for i in range(3):
            subdir = source_dir / f"subdir_{i}"
            subdir.mkdir()
            for j in range(5):
                (subdir / f"nested_{j}.txt").write_text(f"Nested content {i}-{j}")
        interface = MockInterface(choices=[0])

        result = await CopyTool(
            source_path=str(source_dir), destination_path=str(dest_dir)
        ).execute(make_ctx(interface=interface))

        assert result.issues == []
        assert source_dir.exists()
        assert (dest_dir / "file_005.txt").read_text() == "Content 5"
        assert (
            dest_dir / "subdir_1" / "nested_3.txt"
        ).read_text() == "Nested content 1-3"

    async def test_copy_special_filenames(self, tmp_path):
        special_files = [
            "file with spaces.txt",
            "file-with-dashes.txt",
            "file.with.dots.txt",
            "file_with_underscores.txt",
        ]
        source_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        for filename in special_files:
            (source_dir / filename).write_text(f"Content of {filename}")
        interface = MockInterface(choices=[0])

        result = await CopyTool(
            source_path=str(source_dir), destination_path=str(dest_dir / "copied")
        ).execute(make_ctx(interface=interface))

        assert result.issues == []
        for filename in special_files:
            copied_file = dest_dir / "copied" / filename
            assert copied_file.read_text() == f"Content of {filename}"

    async def test_file_vs_directory_messaging(self, tmp_path):
        source_file = tmp_path / "source_file.txt"
        source_file.write_text("File content")
        dest_file = tmp_path / "dest_file.txt"
        source_dir = tmp_path / "source_directory"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest_directory"

        interface1 = MockInterface(choices=[1])
        await CopyTool(
            source_path=str(source_file), destination_path=str(dest_file)
        ).execute(make_ctx(interface=interface1))
        questions1 = " ".join(interface1.questions).lower()
        assert "copying file" in questions1
        assert "directory" not in questions1

        interface2 = MockInterface(choices=[1])
        await CopyTool(
            source_path=str(source_dir), destination_path=str(dest_dir)
        ).execute(make_ctx(interface=interface2))
        questions2 = " ".join(interface2.questions).lower()
        assert "copying directory" in questions2
        assert "file" not in questions2.replace("copying", "")
