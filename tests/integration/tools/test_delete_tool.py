"""Integration tests for the `delete` tool function.

`delete` is a plain `async def delete(ctx, path) -> ToolResult` now - no
`DeleteTool` Pydantic model, no `.solve()`/`.display_header()`/
`.create_error_result()`/`.get_description()`. Called directly through `ctx`.

`ToolResult` has no `accepted`/`error`/`path` fields. A successful delete's
`result.content` is `f"Deleted {abs_path}"` - which doubles as the
path-resolution check the old tests did via `result.path`. Declines are the
literal string `"User declined the delete."`; failures land in
`result.issues`, not `.error`.
"""

from pathlib import Path

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.schema.deps import SolveigContext, SolveigDeps
from solveig.schema.tools.core.delete import delete
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigDeps(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestDeleteValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await delete(make_ctx(), path="")

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await delete(make_ctx(), path="   \t\n   ")

    async def test_header_shows_permanence_warning(self, tmp_path):
        test_file = tmp_path / "delete_me.txt"
        test_file.write_text("x")
        interface = MockInterface(choices=[1])

        await delete(make_ctx(interface=interface), path=str(test_file))

        output = interface.get_all_output()
        assert f"Delete: {test_file}" in output
        assert "permanent" in output.lower()
        assert "cannot be undone" in output.lower()


class TestFileOperations:
    async def test_delete_file_accept(self, tmp_path):
        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("This file will be deleted")
        interface = MockInterface(choices=[0])

        result = await delete(make_ctx(interface=interface), path=str(test_file))

        assert result.issues == []
        assert not test_file.exists()

    async def test_delete_file_decline(self, tmp_path):
        test_file = tmp_path / "to_preserve.txt"
        test_file.write_text("This file should be preserved")
        interface = MockInterface(choices=[1])

        result = await delete(make_ctx(interface=interface), path=str(test_file))

        assert result.content == "User declined the delete."
        assert test_file.exists()
        assert test_file.read_text() == "This file should be preserved"

    async def test_delete_directory_accept(self, tmp_path):
        test_dir = tmp_path / "to_delete_dir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("Content 1")
        (test_dir / "file2.txt").write_text("Content 2")
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested content")
        interface = MockInterface(choices=[0])

        result = await delete(make_ctx(interface=interface), path=str(test_dir))

        assert result.issues == []
        assert not test_dir.exists()

    async def test_delete_directory_decline(self, tmp_path):
        test_dir = tmp_path / "to_preserve_dir"
        test_dir.mkdir()
        (test_dir / "important.txt").write_text("Important data")
        interface = MockInterface(choices=[1])

        result = await delete(make_ctx(interface=interface), path=str(test_dir))

        assert result.content == "User declined the delete."
        assert test_dir.exists()
        assert (test_dir / "important.txt").read_text() == "Important data"

    async def test_delete_empty_directory(self, tmp_path):
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        interface = MockInterface(choices=[0])

        result = await delete(make_ctx(interface=interface), path=str(empty_dir))

        assert result.issues == []
        assert not empty_dir.exists()


class TestAutoAllowedPaths:
    async def test_auto_allowed_file_deletion(self, tmp_path):
        test_file = tmp_path / "auto_delete_file.txt"
        test_file.write_text("Auto-delete content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await delete(make_ctx(config, interface), path=str(test_file))

        assert result.issues == []
        assert not test_file.exists()
        assert len(interface.questions) == 0
        assert "auto_allowed_paths" in interface.get_all_output()

    async def test_auto_allowed_directory_deletion(self, tmp_path):
        test_dir = tmp_path / "auto_delete_dir"
        test_dir.mkdir()
        (test_dir / "content.txt").write_text("Directory content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await delete(make_ctx(config, interface), path=str(test_dir))

        assert result.issues == []
        assert not test_dir.exists()
        assert len(interface.questions) == 0

    async def test_auto_allowed_vs_manual_choice(self, tmp_path):
        auto_file = tmp_path / "auto" / "delete_me.txt"
        auto_file.parent.mkdir()
        auto_file.write_text("Auto content")

        manual_file = tmp_path / "manual" / "delete_me.txt"
        manual_file.parent.mkdir()
        manual_file.write_text("Manual content")

        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/auto/**"])

        interface1 = MockInterface()
        result1 = await delete(make_ctx(config, interface1), path=str(auto_file))
        assert result1.issues == []
        assert not auto_file.exists()
        assert len(interface1.questions) == 0

        interface2 = MockInterface(choices=[0])
        result2 = await delete(make_ctx(config, interface2), path=str(manual_file))
        assert result2.issues == []
        assert not manual_file.exists()
        assert len(interface2.questions) == 1


class TestErrorHandling:
    async def test_delete_nonexistent_file(self):
        interface = MockInterface()

        result = await delete(
            make_ctx(interface=interface), path="/nonexistent/file.txt"
        )

        assert len(result.issues) == 1
        assert any(
            phrase in str(result.issues[0]).lower()
            for phrase in ["not found", "does not exist", "no such file"]
        )

    async def test_delete_permission_denied(self, tmp_path):
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        test_file = restricted_dir / "protected.txt"
        test_file.write_text("Protected content")
        restricted_dir.chmod(0o444)
        interface = MockInterface()

        try:
            result = await delete(make_ctx(interface=interface), path=str(test_file))
            assert len(result.issues) == 1
            assert "permission" in str(result.issues[0]).lower()
        finally:
            restricted_dir.chmod(0o755)


class TestPathSecurity:
    async def test_tilde_expansion(self):
        temp_file_path = Path.home() / ".solveig_test_delete.txt"
        temp_file_path.write_bytes(b"Tilde expansion test")
        try:
            interface = MockInterface(choices=[0])

            result = await delete(
                make_ctx(interface=interface), path=f"~/{temp_file_path.name}"
            )

            assert result.issues == []
            assert "~" not in result.content
            assert str(Path.home()) in result.content
            assert not temp_file_path.exists()
        finally:
            if temp_file_path.exists():
                temp_file_path.unlink()

    async def test_path_traversal_resolution(self, tmp_path):
        subdir = tmp_path / "public" / "subdir"
        subdir.mkdir(parents=True)
        target_file = tmp_path / "target.txt"
        target_file.write_text("Target file")
        traversal_path = str(subdir / ".." / ".." / "target.txt")
        interface = MockInterface(choices=[0])

        result = await delete(make_ctx(interface=interface), path=traversal_path)

        assert result.issues == []
        assert ".." not in result.content
        assert not target_file.exists()


class TestIntegrationScenarios:
    async def test_delete_large_directory_tree(self, tmp_path):
        large_dir = tmp_path / "large_tree"
        large_dir.mkdir()
        for i in range(20):
            (large_dir / f"file_{i:03d}.txt").write_text(f"Content {i}")
        for i in range(5):
            subdir = large_dir / f"subdir_{i}"
            subdir.mkdir()
            for j in range(10):
                (subdir / f"nested_{j}.txt").write_text(f"Nested content {i}-{j}")
        interface = MockInterface(choices=[0])

        result = await delete(make_ctx(interface=interface), path=str(large_dir))

        assert result.issues == []
        assert not large_dir.exists()

    async def test_delete_special_files(self, tmp_path):
        special_files = [
            "file with spaces.txt",
            "file-with-dashes.txt",
            "file.with.dots.txt",
            "file_with_underscores.txt",
        ]
        for filename in special_files:
            (tmp_path / filename).write_text(f"Content of {filename}")

        interface = MockInterface(choices=[0] * len(special_files))

        for filename in special_files:
            file_path = tmp_path / filename
            result = await delete(make_ctx(interface=interface), path=str(file_path))
            assert result.issues == []
            assert not file_path.exists()

    async def test_file_vs_directory_messaging(self, tmp_path):
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("File content")
        test_dir = tmp_path / "test_directory"
        test_dir.mkdir()

        interface1 = MockInterface(choices=[1])
        await delete(make_ctx(interface=interface1), path=str(test_file))
        questions1 = " ".join(interface1.questions).lower()
        assert "delete file" in questions1
        assert "directory" not in questions1

        interface2 = MockInterface(choices=[1])
        await delete(make_ctx(interface=interface2), path=str(test_dir))
        questions2 = " ".join(interface2.questions).lower()
        assert "delete directory" in questions2
