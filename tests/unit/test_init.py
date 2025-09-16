"""Tests for scripts.init module."""

from unittest.mock import patch

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

    def test_add_bash_timestamps_new_bashrc(self, mock_filesystem):
        """Test adding timestamps to empty .bashrc."""
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

        result = add_bash_timestamps(interface)

        assert result is True
        assert (
            "export HISTTIMEFORMAT="
            in mock_filesystem.read_file(
                mock_filesystem.mocks.default_bashrc_path
            ).content
        )

    def test_add_bash_timestamps_already_configured(self, mock_filesystem):
        """Test when timestamps are already configured."""
        # Create a bashrc file with timestamps already configured
        bashrc_path = mock_filesystem.mocks.default_bashrc_path
        bashrc_content = 'export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "\nexport PS1="$ "'
        mock_filesystem.write_file(bashrc_path, bashrc_content)

        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

        result = add_bash_timestamps(interface)

        assert result is True

    def test_add_bash_timestamps_exception(self, mock_filesystem):
        """Test handling exceptions during timestamp setup."""
        mock_filesystem.mocks.exists.side_effect = [PermissionError("Access denied")]
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

    def test_create_config_success(self, mock_filesystem):
        """Test successful config directory creation."""
        # User agrees to create an example config
        interface = MockInterface()
        interface.set_user_inputs(["y"])

        # Show the files doesn't exist before
        config_path = mock_filesystem.mocks.default_config_path
        assert not mock_filesystem.exists(config_path)
        assert not mock_filesystem.exists(config_path.parent)
        # Confirm using the mocks is the same as calling Path.exists() directly
        assert not Filesystem.exists(config_path)
        assert not Filesystem.exists(config_path.parent)

        # Execute
        create_example_config(interface)

        # Check that success message appears in interface output
        assert (
            f"Created example config file at {config_path}"
            in interface.get_all_output()
        )

        # Confirm the config path was created
        assert config_path in mock_filesystem._entries
        assert config_path.parent in mock_filesystem._entries
        # Use Filesystem methods to confirm mocks are working, despite obviously
        # this path not existing in the real filesystem
        assert Filesystem.exists(config_path.parent)
        content = Filesystem.read_file(config_path).content
        assert content == SolveigConfig().to_json()
        mock_content = mock_filesystem._mock_read_text(config_path)
        assert content == mock_content

    def test_create_config_denial(self, mock_filesystem):
        """Test successful config directory creation."""
        # default_config_path = Path("/home/_test_user_/solveig_config.json")
        default_config_path = mock_filesystem.mocks.default_config_path

        # User denies to create an example config
        interface = MockInterface()
        interface.set_user_inputs(["n"])

        # Show the files doesn't exist before
        assert not Filesystem.exists(default_config_path.parent)
        assert not Filesystem.exists(default_config_path)

        create_example_config(interface)

        # Check that success message appears in interface output
        assert "Skipped config file creation." in interface.get_all_output()

        # Confirm the config path was not created
        assert not Filesystem.exists(default_config_path.parent)
        assert not Filesystem.exists(default_config_path)

    def test_create_config_exception(self, mock_filesystem):
        """Test handling exceptions during directory creation."""
        # Set up the mock to fail when trying to create directories
        mock_filesystem.mocks.create_directory.side_effect = PermissionError(
            "Access denied"
        )
        default_config_path = mock_filesystem.mocks.default_config_path

        # User agrees to creating the file config
        interface = MockInterface()
        interface.set_user_inputs(["y"])

        # The file doesn't exist before
        assert not Filesystem.exists(default_config_path)

        create_example_config(interface)

        assert not Filesystem.exists(default_config_path)
        assert (
            "Failed to create config file: Access denied" in interface.get_all_output()
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
