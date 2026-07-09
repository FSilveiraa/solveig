"""Integration tests for the `read` tool function.

`read` is a plain `async def read(ctx, path, metadata_only, line_ranges=None)
-> ToolResult` now - no `ReadTool` Pydantic model, no `.solve()`/
`.display_header()`/`.get_description()`. Called directly through `ctx`.

`ToolResult` has no `accepted`/`metadata`/`path` fields. `read()` puts
exactly one thing in `result.content` depending on what was actually sent:
a `FileMetadata` instance (metadata sends, including every directory read),
plain file-content text (accepted content reads), or a human-readable
decline string ("User declined to send metadata."/"...to send anything.").
Unlike the old `ReadResult`, a successful content read carries no metadata
alongside it - `content` is just the text.
"""

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.schema.deps import SolveigContext, SolveigDeps
from solveig.schema.tools.core.read import read
from solveig.utils.file import FileMetadata
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigDeps(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestReadValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await read(make_ctx(), path="", metadata_only=False)

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await read(make_ctx(), path="   \t\n   ", metadata_only=False)

    async def test_path_strips_whitespace(self, tmp_path):
        test_file = tmp_path / "f.txt"
        test_file.write_text("hi")
        interface = MockInterface(choices=[0])

        result = await read(
            make_ctx(interface=interface), path=f"  {test_file}  ", metadata_only=False
        )

        assert result.content == "hi"

    async def test_header_shows_group_and_request_description(self, tmp_path):
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("dummy content")
        interface = MockInterface(choices=[0])

        await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        output = interface.get_all_output()
        assert f"Read: {test_file}" in output
        assert str(test_file) in output
        assert "Content and metadata" in output


class TestDirectoryOperations:
    async def test_directory_read_accept(self, tmp_path):
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("print('hello')")
        (tmp_path / "subdir").mkdir()

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=str(tmp_path), metadata_only=True
        )

        assert isinstance(result.content, FileMetadata)
        assert result.content.is_directory
        assert len(result.content.listing) == 3

    async def test_directory_read_decline(self, tmp_path):
        interface = MockInterface(choices=[1])
        result = await read(
            make_ctx(interface=interface), path=str(tmp_path), metadata_only=True
        )

        assert result.content == "User declined to send metadata."


class TestFileContentFlow:
    async def test_choice_0_direct_read_send(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_content = "Hello direct read!"
        test_file.write_text(test_content)

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        assert result.content == test_content

    async def test_choice_1_inspect_then_send_content(self, tmp_path):
        test_file = tmp_path / "inspect.txt"
        test_content = "Inspect me first!"
        test_file.write_text(test_content)

        interface = MockInterface(choices=[1, 0])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        assert result.content == test_content

    async def test_choice_1_inspect_then_send_metadata_only(self, tmp_path):
        test_file = tmp_path / "metadata_only.txt"
        test_file.write_text("Secret content")

        interface = MockInterface(choices=[1, 1])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        assert isinstance(result.content, FileMetadata)

    async def test_choice_1_inspect_then_send_nothing(self, tmp_path):
        test_file = tmp_path / "nothing.txt"
        test_file.write_text("Super secret")

        interface = MockInterface(choices=[1, 2])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        assert result.content == "User declined to send anything."

    async def test_choice_2_send_metadata_only(self, tmp_path):
        test_file = tmp_path / "metadata.txt"
        test_file.write_text("Not read")

        interface = MockInterface(choices=[2])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        assert isinstance(result.content, FileMetadata)

    async def test_choice_3_send_nothing(self, tmp_path):
        test_file = tmp_path / "nothing.txt"
        test_file.write_text("Nothing sent")

        interface = MockInterface(choices=[3])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=False
        )

        assert result.content == "User declined to send anything."

    async def test_metadata_only_request_fulfilled(self, tmp_path):
        test_file = tmp_path / "metadata_request.txt"
        test_file.write_text("Content not requested")

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=True
        )

        assert isinstance(result.content, FileMetadata)

    async def test_choice_equivalence_direct_vs_inspect(self, tmp_path):
        test_file = tmp_path / "equivalent.txt"
        test_content = "Same result expected"
        test_file.write_text(test_content)

        result1 = await read(
            make_ctx(interface=MockInterface(choices=[0])),
            path=str(test_file),
            metadata_only=False,
        )
        result2 = await read(
            make_ctx(interface=MockInterface(choices=[1, 0])),
            path=str(test_file),
            metadata_only=False,
        )

        assert result1.content == result2.content == test_content


class TestAutoAllowedPaths:
    async def test_auto_allowed_file(self, tmp_path):
        test_file = tmp_path / "auto.txt"
        test_content = "Auto-allowed content"
        test_file.write_text(test_content)

        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()
        result = await read(
            make_ctx(config, interface), path=str(test_file), metadata_only=False
        )

        assert result.content == test_content
        assert len(interface.questions) == 0

    async def test_auto_allowed_directory(self, tmp_path):
        (tmp_path / "file.txt").write_text("content")

        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[str(tmp_path)])
        interface = MockInterface()
        result = await read(
            make_ctx(config, interface), path=str(tmp_path), metadata_only=True
        )

        assert isinstance(result.content, FileMetadata)
        assert result.content.is_directory
        assert len(interface.questions) == 0


class TestErrorHandling:
    async def test_nonexistent_file(self):
        interface = MockInterface()
        result = await read(
            make_ctx(interface=interface),
            path="/nonexistent/file.txt",
            metadata_only=False,
        )

        assert len(result.issues) == 1
        assert "does not exist" in str(result.issues[0]).lower()

    async def test_permission_denied(self, tmp_path):
        restricted_file = tmp_path / "restricted.txt"
        restricted_file.write_text("Secret")
        restricted_file.chmod(0o000)

        interface = MockInterface()
        try:
            result = await read(
                make_ctx(interface=interface),
                path=str(restricted_file),
                metadata_only=False,
            )
            assert len(result.issues) == 1
        finally:
            restricted_file.chmod(0o644)

    async def test_binary_file_handling(self, tmp_path):
        binary_file = tmp_path / "test.bin"
        binary_data = bytes([0x89, 0x50, 0x4E, 0x47])  # PNG header
        binary_file.write_bytes(binary_data)

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=str(binary_file), metadata_only=False
        )

        assert result.content == "(binary content)"


class TestPathSecurity:
    async def test_tilde_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

        test_file = tmp_path / "tilde_test.txt"
        test_content = "Tilde test content"
        test_file.write_text(test_content)

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface),
            path="~/tilde_test.txt",
            metadata_only=False,
        )

        assert result.content == test_content
        assert str(test_file) in interface.get_all_output()

    async def test_path_traversal_resolution(self, tmp_path):
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        secret_file = secret_dir / "data.txt"
        secret_file.write_text("Secret data")

        public_dir = tmp_path / "public" / "subdir"
        public_dir.mkdir(parents=True)

        traversal_path = str(public_dir / ".." / ".." / "secret" / "data.txt")
        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=traversal_path, metadata_only=True
        )

        assert isinstance(result.content, FileMetadata)
        assert ".." not in result.content.path
        assert "secret/data.txt" in result.content.path


class TestLineRanges:
    async def test_too_many_ranges_raises(self):
        with pytest.raises(ValueError, match="Maximum 3 line ranges"):
            await read(
                make_ctx(),
                path="/tmp/whatever",
                metadata_only=False,
                line_ranges=[[1, 2], [3, 4], [5, 6], [7, 8]],
            )

    async def test_range_wrong_length_raises(self):
        with pytest.raises(ValueError, match="exactly 2 elements"):
            await read(
                make_ctx(),
                path="/tmp/whatever",
                metadata_only=False,
                line_ranges=[[1, 2, 3]],
            )

    async def test_range_start_below_one_raises(self):
        with pytest.raises(ValueError, match="Start line must be >= 1"):
            await read(
                make_ctx(),
                path="/tmp/whatever",
                metadata_only=False,
                line_ranges=[[0, 5]],
            )

    async def test_range_end_before_start_raises(self):
        with pytest.raises(ValueError, match="End line must be"):
            await read(
                make_ctx(),
                path="/tmp/whatever",
                metadata_only=False,
                line_ranges=[[5, 2]],
            )

    async def test_reads_specific_line_range(self, tmp_path):
        test_file = tmp_path / "lines.txt"
        test_file.write_text("\n".join(f"line{i}" for i in range(1, 11)))

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface),
            path=str(test_file),
            metadata_only=False,
            line_ranges=[[2, 4]],
        )

        assert result.content == "line2\nline3\nline4"

    async def test_reads_to_end_with_negative_one(self, tmp_path):
        test_file = tmp_path / "lines.txt"
        test_file.write_text("\n".join(f"line{i}" for i in range(1, 6)))

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface),
            path=str(test_file),
            metadata_only=False,
            line_ranges=[[3, -1]],
        )

        assert result.content == "line3\nline4\nline5"


class TestIntegrationScenarios:
    async def test_large_directory_listing(self, tmp_path):
        for i in range(50):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"Content {i}")
        for i in range(5):
            (tmp_path / f"subdir_{i}").mkdir()

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=str(tmp_path), metadata_only=True
        )

        assert result.content.is_directory
        assert len(result.content.listing) == 55

    async def test_metadata_only_flag_bypasses_content_choices(self, tmp_path):
        test_file = tmp_path / "metadata_test.txt"
        test_file.write_text("Should not be read")

        interface = MockInterface(choices=[0])
        result = await read(
            make_ctx(interface=interface), path=str(test_file), metadata_only=True
        )

        assert isinstance(result.content, FileMetadata)
        assert len(interface.questions) == 1
        assert "metadata" in interface.questions[0].lower()
