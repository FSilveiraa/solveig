"""Tests for scripts.init module."""

from pathlib import Path
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


# @patch("scripts.init.DEFAULT_CONFIG_PATH", new=Path("/home/_test_user_/solveig_config.json"))
class TestBashTimestamps:
    """Test bash timestamp functionality."""

    def test_add_bash_timestamps_new_bashrc(self, mock_all_file_operations):
        """Test adding timestamps to empty .bashrc."""
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

        result = add_bash_timestamps(interface)

        assert result is True
        assert Path("/home/_test_user_/.bashrc") in mock_all_file_operations._paths
        assert (
            "export HISTTIMEFORMAT="
            in mock_all_file_operations._paths[
                Path("/home/_test_user_/.bashrc")
            ].content
        )

    def test_add_bash_timestamps_already_configured(self, mock_all_file_operations):
        """Test when timestamps are already configured."""
        # Create a bashrc file with timestamps already configured
        bashrc_path = "/home/_test_user_/.bashrc"
        bashrc_content = 'export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "\nexport PS1="$ "'
        mock_all_file_operations.write_file(bashrc_path, bashrc_content)

        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

        result = add_bash_timestamps(interface)

        assert result is True

    def test_add_bash_timestamps_exception(self, mock_all_file_operations):
        """Test handling exceptions during timestamp setup."""
        mock_all_file_operations.mocks.exists.side_effect = [
            PermissionError("Access denied")
        ]
        # mock_exists.side_effect = PermissionError("Access denied")
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

    @patch(
        "scripts.init.DEFAULT_CONFIG_PATH",
        new=Path("/home/_test_user_/solveig_config.json"),
    )
    def test_create_config_success(self, mock_all_file_operations):
        """Test successful config directory creation."""
        # User agrees to create an example config
        interface = MockInterface()
        interface.set_user_inputs(["y"])

        default_config_path = Path("/home/_test_user_/solveig_config.json")
        # Show the files doesn't exist before
        assert not mock_all_file_operations._mock_exists(default_config_path)
        assert not mock_all_file_operations._mock_exists(default_config_path.parent)
        # Confirm using the mocks is the same as calling Path.exists() directly
        assert not Filesystem._exists(default_config_path)
        assert not Filesystem._exists(default_config_path.parent)

        # Execute
        create_example_config(interface)

        # Check that success message appears in interface output
        assert (
            f"Created example config file at {default_config_path}"
            in interface.get_all_output()
        )

        # Confirm the config path was created
        assert default_config_path in mock_all_file_operations._paths
        assert default_config_path.parent in mock_all_file_operations._paths
        # Use Filesystem methods to confirm mocks are working, despite obviously this path not existing
        # in the real filesystem
        assert Filesystem._exists(default_config_path.parent)
        content, _ = Filesystem.read_file(default_config_path)
        assert content == SolveigConfig().to_json()
        mock_content = mock_all_file_operations._mock_read_text(default_config_path)
        assert content == mock_content

    @patch(
        "scripts.init.DEFAULT_CONFIG_PATH",
        new=Path("/home/_test_user_/solveig_config.json"),
    )
    def test_create_config_denial(self, mock_all_file_operations):
        """Test successful config directory creation."""
        default_config_path = Path("/home/_test_user_/solveig_config.json")

        # User denies to create an example config
        interface = MockInterface()
        interface.set_user_inputs(["n"])

        # Show the files doesn't exist before
        assert not Filesystem._exists(default_config_path.parent)
        assert not Filesystem._exists(default_config_path)

        create_example_config(interface)

        # Check that success message appears in interface output
        assert "○ Skipped config file creation." in interface.get_all_output()

        # Confirm the config path was not created
        assert not Filesystem._exists(default_config_path.parent)
        assert not Filesystem._exists(default_config_path)

    @patch(
        "scripts.init.DEFAULT_CONFIG_PATH",
        new=Path("/home/_test_user_/solveig_config.json"),
    )
    def test_create_config_exception(self, mock_all_file_operations):
        """Test handling exceptions during directory creation."""
        # Set up the mock to fail when trying to create directories
        mock_all_file_operations.mocks.create_directory.side_effect = PermissionError(
            "Access denied"
        )
        default_config_path = Path("/home/_test_user_/solveig_config.json")

        # User agrees to creating the file config
        interface = MockInterface()
        interface.set_user_inputs(["y"])

        # The file doesn't exist before
        assert not Filesystem._exists(default_config_path)

        create_example_config(interface)

        assert not Filesystem._exists(default_config_path)
        assert (
            "Failed to create config file: Access denied" in interface.get_all_output()
        )

        # assert "/home/test/.config" not in mock_all_file_operations.files
        # assert "/home/test/.config/solveig.json" not in mock_all_file_operations.files


class TestOptionalTools:
    """Test optional tools checking."""

    # @patch("builtins.print")
    # @patch("shutil.which")
    # def test_check_optional_tools(self, mock_which, mock_print):
    #     """Test checking for optional tools."""
    #     mock_which.side_effect = lambda tool: tool == "git"  # Only git available
    #
    #     check_optional_tools()
    #
    #     # Should print status for both tools
    #     print_calls = [call.args[0] for call in mock_print.call_args_list]
    #     assert any("git" in call for call in print_calls)
    #     assert any("shellcheck" in call for call in print_calls)


# class TestYesNoPrompt:
#     """Test yes/no prompt functionality."""
#
#     @patch("builtins.input", return_value="y")
#     def test_ask_yes_no_yes(self, mock_input):
#         """Test yes response."""
#         result = ask_yes_no("Test question?")
#         assert result is True
#
#     @patch("builtins.input", return_value="n")
#     def test_ask_yes_no_no(self, mock_input):
#         """Test no response."""
#         result = ask_yes_no("Test question?")
#         assert result is False
#
#     @patch("builtins.input", return_value="")
#     def test_ask_yes_no_default_true(self, mock_input):
#         """Test default True response."""
#         result = ask_yes_no("Test question?", default=True)
#         assert result is True
#
#     @patch("builtins.input", return_value="")
#     def test_ask_yes_no_default_false(self, mock_input):
#         """Test default False response."""
#         result = ask_yes_no("Test question?", default=False)
#         assert result is False
#
#     @patch("builtins.print")
#     @patch("builtins.input")
#     def test_ask_yes_no_invalid_then_valid(self, mock_input, mock_print):
#         """Test invalid input followed by valid input."""
#         mock_input.side_effect = ["maybe", "yes"]
#
#         result = ask_yes_no("Test question?")
#
#         assert result is True
#         mock_print.assert_called_with("Please answer 'y' or 'n'")


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
