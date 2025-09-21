"""Tests for scripts.init module."""

import tempfile
from pathlib import PurePath
from unittest.mock import patch

import pytest

from scripts.init import (
    add_bash_timestamps,
    check_dependencies,
    create_example_config,
    main,
)
from solveig import SolveigConfig
from solveig.utils.file import Filesystem
from tests.mocks import MockInterface


class TestBashTimestamps:
    """Test bash timestamp functionality."""

    _BASHRC_CONTENT = """
# Source global definitions
if [ -f /etc/bashrc ]; then
	. /etc/bashrc
fi

# User specific environment
if ! [[ "$PATH" =~ "$HOME/.local/bin:$HOME/bin:" ]]
then
	PATH="$HOME/.local/bin:$HOME/bin:$PATH"
fi
export PATH
"""

    @pytest.mark.no_file_mocking
    def test_add_bash_timestamps_new_bashrc(self):
        """Test adding timestamps to empty .bashrc."""
        with tempfile.NamedTemporaryFile(mode="r+", suffix=".bashrc") as temp_bashrc:
            # Write a regular .bashrc without HISTTIMEFORMAT=
            config_path = PurePath(temp_bashrc.name)
            Filesystem.write_file(config_path, self._BASHRC_CONTENT)
            temp_bashrc.flush()

            with patch("scripts.init.DEFAULT_BASHRC_PATH", config_path):
                # Ensure the mock worked correctly
                from scripts.init import DEFAULT_BASHRC_PATH

                assert config_path == DEFAULT_BASHRC_PATH

                interface = MockInterface()
                interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

                result = add_bash_timestamps(interface)

                assert result is True
                assert (
                    "export HISTTIMEFORMAT="
                    in Filesystem.read_file(config_path).content
                )

    @pytest.mark.no_file_mocking
    def test_add_bash_timestamps_already_configured(self):
        """Test when timestamps are already configured."""
        with tempfile.NamedTemporaryFile(mode="r+", suffix=".bashrc") as temp_bashrc:
            # Create bashrc with timestamps already configured
            bashrc_content = (
                'export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "\nexport PS1="$ "'
            )
            config_path = PurePath(temp_bashrc.name)
            Filesystem.write_file(config_path, bashrc_content)
            temp_bashrc.flush()

            with patch("scripts.init.DEFAULT_BASHRC_PATH", config_path):
                interface = MockInterface()
                interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

                result = add_bash_timestamps(interface)

                assert result is True

    @pytest.mark.no_file_mocking
    def test_add_bash_timestamps_exception(self):
        """Test handling exceptions during timestamp setup."""
        with tempfile.NamedTemporaryFile(mode="r+", suffix=".bashrc") as temp_bashrc:
            config_path = PurePath(temp_bashrc.name)

            with (
                patch("scripts.init.DEFAULT_BASHRC_PATH", config_path),
                patch(
                    "solveig.utils.file.Filesystem.exists",
                    side_effect=PermissionError("Access denied"),
                ),
            ):
                interface = MockInterface()
                interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

                result = add_bash_timestamps(interface)

                assert result is False


class TestDependencyCheck:
    """Test dependency checking functionality."""

    @patch("builtins.__import__")
    def test_check_dependencies_all_available(self, mock_import):
        """Test when all dependencies are available."""
        mock_import.return_value = True  # All imports succeed
        interface = MockInterface()

        result = check_dependencies(interface)

        assert result is True
        # Check that success message appears in interface output
        output_text = " ".join(interface.outputs)
        assert "All required dependencies are installed." in output_text

    @patch("builtins.__import__")
    def test_check_dependencies_missing(self, mock_import):
        """Test when some dependencies are missing."""
        mock_import.side_effect = [
            True,
            ImportError(),
            True,
            True,
            True,
        ]  # Second import fails
        interface = MockInterface()

        result = check_dependencies(interface)

        assert result is False
        # Check that missing packages message appears in interface output
        output_text = " ".join(interface.outputs)
        assert "Found missing packages" in output_text


class TestConfigDirectory:
    """Test configuration directory creation."""

    @pytest.mark.no_file_mocking
    def test_create_config_success(self):
        """Test successful config directory creation."""
        with tempfile.NamedTemporaryFile(mode="r+", suffix=".json") as temp_config:
            config_path = PurePath(temp_config.name)

            with patch("scripts.init.DEFAULT_CONFIG_PATH", config_path):
                # User agrees to create an example config
                interface = MockInterface()
                interface.set_user_inputs(["y"])

                # Execute
                create_example_config(interface)

                # Check that success message appears in interface output
                assert (
                    f"Created example config file at {config_path}"
                    in interface.get_all_output()
                )

                # Verify the config was written correctly
                content = Filesystem.read_file(config_path).content
                assert content == SolveigConfig().to_json()

    @pytest.mark.no_file_mocking
    def test_create_config_denial(self):
        """Test config creation denial."""
        with tempfile.NamedTemporaryFile(mode="r+", suffix=".json") as temp_config:
            config_path = PurePath(temp_config.name)

            with patch("scripts.init.DEFAULT_CONFIG_PATH", config_path):
                # User denies to create an example config
                interface = MockInterface()
                interface.set_user_inputs(["n"])

                create_example_config(interface)

                # Check that skip message appears in interface output
                assert "Skipped config file creation." in interface.get_all_output()

    def test_create_config_exception(self):
        """Test handling exceptions during directory creation."""
        with tempfile.NamedTemporaryFile(mode="r+", suffix=".json") as temp_config:
            config_path = PurePath(temp_config.name)

            with (
                patch("scripts.init.DEFAULT_CONFIG_PATH", config_path),
                patch(
                    "solveig.utils.file.Filesystem.write_file",
                    side_effect=PermissionError("Access denied"),
                ),
            ):
                # User agrees to creating the file config
                interface = MockInterface()
                interface.set_user_inputs(["y"])

                create_example_config(interface)

                assert (
                    "Failed to create config file: Access denied"
                    in interface.get_all_output()
                )


class TestMainFunction:
    """Test main initialization function."""

    @patch("scripts.init.create_example_config")
    @patch("scripts.init.check_dependencies")
    @patch("scripts.init.add_bash_timestamps")
    def test_main_success_with_bash_setup(
        self,
        mock_add_bash,
        mock_check_dependencies,
        mock_create_config,
    ):
        """Test main function with successful bash setup."""
        mock_interface = MockInterface()
        mock_interface.set_user_inputs(["y"])  # User says yes to bash setup
        mock_create_config.return_value = True
        mock_check_dependencies.return_value = True  # check_dependencies returns True
        mock_add_bash.return_value = True

        result = main(interface=mock_interface)

        assert result == 0
        mock_create_config.assert_called_once()
        mock_check_dependencies.assert_called_once()
        mock_add_bash.assert_called_once()

    @patch("scripts.init.create_example_config")
    @patch("scripts.init.check_dependencies")
    def test_main_skip_bash_setup(
        self,
        mock_check_deps,
        mock_create_config,
    ):
        """Test main function when user skips bash setup."""
        mock_check_deps.return_value = True
        mock_create_config.return_value = True

        mock_interface = MockInterface()
        # check dependencies,
        mock_interface.user_inputs.append("n")
        result = main(interface=mock_interface)

        assert result == 0
        # Should print skip message
        print_calls = [str(call) for call in mock_interface.outputs]
        assert any("Skipped bash history" in call for call in print_calls)

    @patch("scripts.init.check_dependencies")
    def test_main_dependency_failure(self, mock_check_deps):
        """Test main function when dependencies are missing."""
        mock_check_deps.return_value = False
        interface = MockInterface()

        result = main(interface)

        assert result == 1
