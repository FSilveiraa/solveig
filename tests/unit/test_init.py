"""Tests for scripts.init module."""

from pathlib import Path
from unittest.mock import mock_open, patch

from scripts.init import (
    add_bash_timestamps,
    check_dependencies,
    create_config_directory,
    main,
)
from tests.utils.mocks import MockInterface


class TestBashTimestamps:
    """Test bash timestamp functionality."""

    @patch("scripts.init.Path.home")
    @patch("pathlib.Path.read_text")
    @patch("pathlib.Path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_add_bash_timestamps_new_bashrc(
        self, mock_open_file, mock_exists, mock_read, mock_home
    ):
        """Test adding timestamps to empty .bashrc."""
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = True
        mock_read.return_value = "# Empty bashrc"
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

        result = add_bash_timestamps(interface)

        assert result is True
        mock_open_file.assert_called()

    @patch("scripts.init.Path.home")
    @patch("pathlib.Path.read_text")
    @patch("pathlib.Path.exists")
    def test_add_bash_timestamps_already_configured(
        self, mock_exists, mock_read, mock_home
    ):
        """Test when timestamps are already configured."""
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = True
        mock_read.return_value = 'export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "'
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User says yes to enabling timestamps

        result = add_bash_timestamps(interface)

        assert result is True

    @patch("scripts.init.Path.home")
    @patch("pathlib.Path.read_text")
    @patch("pathlib.Path.exists")
    def test_add_bash_timestamps_exception(
        self, mock_exists, mock_read, mock_home
    ):
        """Test handling exceptions during timestamp setup."""
        mock_home.return_value = Path("/home/test")
        mock_exists.side_effect = PermissionError("Access denied")
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
        assert "✓ All required dependencies are installed." in output_text

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

    @patch("scripts.init.Path.home")
    def test_create_config_directory_success(self, mock_home):
        """Test successful config directory creation."""
        interface = MockInterface()
        mock_home.return_value = Path("/home/test")
        
        result = create_config_directory(interface)

        assert result is True
        # Check that success message appears in interface output
        output_text = " ".join(interface.outputs)
        assert "Configuration directory ready" in output_text

    @patch("scripts.init.Path.home")
    @patch("pathlib.Path.mkdir")
    def test_create_config_directory_exception(self, mock_mkdir, mock_home):
        """Test handling exceptions during directory creation."""
        mock_home.return_value = Path("/home/test")
        mock_mkdir.side_effect = PermissionError("Access denied")
        interface = MockInterface()

        result = create_config_directory(interface)

        assert result is False


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

    @patch("scripts.init.create_config_directory")
    @patch("scripts.init.check_dependencies")
    @patch("scripts.init.add_bash_timestamps")
    def test_main_success_with_bash_setup(
        self,
        mock_add_bash,
        mock_create_config,
        mock_check_tools,
    ):
        """Test main function with successful bash setup."""
        mock_interface = MockInterface()
        mock_interface.set_user_inputs(["y"])  # User says yes to bash setup
        mock_create_config.return_value = True
        mock_check_tools.return_value = True  # check_dependencies returns True
        mock_add_bash.return_value = True

        result = main(interface=mock_interface)

        assert result == 0
        mock_create_config.assert_called_once()
        mock_check_tools.assert_called_once()
        mock_add_bash.assert_called_once()

    @patch("scripts.init.create_config_directory")
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

    @patch("scripts.init.create_config_directory")
    @patch("scripts.init.check_dependencies")
    def test_main_config_directory_failure(
        self, mock_check_deps, mock_create_config
    ):
        """Test main function when config directory creation fails."""
        mock_check_deps.return_value = True
        mock_create_config.return_value = False
        interface = MockInterface()

        result = main(interface)

        assert result == 1
