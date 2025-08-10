"""
Unit test configuration that provides safe defaults for external operations.

This ensures unit tests don't accidentally make real system calls while
allowing pytest itself to work normally.
"""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def safe_external_operations():
    """Provide safe defaults for external operations in unit tests."""

    # Only patch the specific operations that our code uses, not system-wide operations
    with patch(
        "subprocess.run", return_value=Mock(returncode=0, stdout="", stderr="")
    ) as patch_subprocess:
        patch_subprocess.side_effect = OSError("Cannot run actual processes")
        with patch(
            "builtins.open", side_effect=FileNotFoundError("")
        ) as patch_open_file:
            patch_open_file.side_effect = OSError("Cannot use actual file I/O")
            with patch("builtins.input") as patch_input:
                patch_input.side_effect = OSError("Cannot use actual input")
                with patch("builtins.print") as patch_print:
                    patch_print.side_effect = OSError("Cannot use actual print")
        # with patch("solveig.utils.misc.ask_yes", return_value=False):
        #     # Only patch file operations in our solveig modules, not globally
        #     with patch(
        #         "solveig.utils.file.read_metadata_and_listing",
        #         return_value=({
        #             "metadata": {"path": "/test/path", "size": 100},
        #             "content": None,
        #             "encoding": None,
        #             "directory_listing": None,
        #         }, []),
        #     ):
        #         with patch("solveig.utils.file.read_file", return_value=None):
        #             with patch("solveig.utils.file.validate_read_access", return_value=None):
        #                 with patch("solveig.utils.file.validate_write_access", return_value=None):
        #                     with patch(
        #                         "solveig.utils.file.write_file_or_directory",
        #                         return_value=None,
        #                     ):
        #                         yield
