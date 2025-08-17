#!/usr/bin/env python3
"""
Solveig initialization script.

This script helps users set up their environment for optimal use with Solveig,
including optional bash history timestamping for better context awareness.
This replaces the old setup.sh script with proper Python integration.
"""

import sys

from solveig.config import DEFAULT_CONFIG_PATH, SolveigConfig
from solveig.interface import CLIInterface, SolveigInterface
from solveig.utils.file import Filesystem

DEFAULT_BASHRC_PATH = Filesystem.get_absolute_path("~/.bashrc")


def add_bash_timestamps(interface: SolveigInterface) -> bool:
    """
    Add timestamp formatting to bash history.

    This is the functionality from the original setup.sh, now properly integrated.
    Helps Solveig understand when commands were executed for better context.

    Returns:
        bool: True if timestamps were successfully added, False otherwise.
    """
    bashrc_path = DEFAULT_BASHRC_PATH
    timestamp_line = """
# Added by Solveig
export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "
"""

    with interface.with_group("Bash History Timestamps"):
        interface.display_text_block(
            "Adding timestamps to your bash history helps Solveig understand "
            + "when you executed commands, providing better context for assistance."
        )
        if interface.ask_yes_no("Would you like to enable bash history timestamps?"):
            try:
                # Check if timestamps are already configured
                abs_bashrc_path = Filesystem.get_absolute_path(bashrc_path)
                if Filesystem._exists(abs_bashrc_path):
                    content, _ = Filesystem.read_file(bashrc_path)
                    if "HISTTIMEFORMAT" in content:
                        interface.display_success(
                            "Bash history timestamps were already configured"
                        )
                        return True

                Filesystem.write_file(bashrc_path, timestamp_line, append=True)

                interface.display_success("Added bash history timestamps to ~/.bashrc")
                interface.show(
                    "Run 'source ~/.bashrc' or restart your terminal to apply changes."
                )
                return True

            except Exception as e:
                interface.display_error(f"Failed to add bash timestamps: {e}")
                return False
        else:
            interface.show("○ Skipped bash history timestamp setup")
            return False


def check_dependencies(interface: SolveigInterface) -> bool:
    """Check if all required dependencies are installed."""
    required_packages = [
        "distro",
        "instructor",
        "openai",
        "pydantic",
        "tiktoken",
    ]

    missing_packages = []

    with interface.with_group("Dependencies"):
        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                missing_packages.append(package)

        if missing_packages:
            interface.display_error("Found missing packages")
            with interface.with_group("Missing", count=len(missing_packages)):
                for package in missing_packages:
                    interface.display_error(f"{package}")
            interface.display_error("Run: pip install -e .")
            return False
        else:
            interface.display_success("All required dependencies are installed.")
            return True


def create_example_config(interface: SolveigInterface):
    """Create an example configuration file with defaults."""
    # Check if a readable config file exists
    try:
        Filesystem.validate_read_access(DEFAULT_CONFIG_PATH)
        _config_file_exists = True
    except Exception:
        _config_file_exists = False

    if _config_file_exists:
        interface.display_warning(f"Config file already exists: {DEFAULT_CONFIG_PATH}")

    if interface.ask_yes_no(
        f"Create example config file at {DEFAULT_CONFIG_PATH}? [y/N]"
    ):
        try:
            # Create a default config instance and export it
            default_config = SolveigConfig().to_json(indent=2)
            Filesystem.write_file(DEFAULT_CONFIG_PATH, default_config)

            interface.display_success(
                f"Created example config file at {DEFAULT_CONFIG_PATH}"
            )
            interface.show("Edit this file to customize your settings")

        except Exception as e:
            interface.display_error(f"Failed to create config file: {e}")
    else:
        interface.show("○ Skipped config file creation.")


def main(interface: SolveigInterface | None = None) -> int:
    """Main initialization function."""
    # All defaults for now
    interface = interface or CLIInterface()

    interface.display_section("Setup")
    interface.show("Setting up Solveig")

    # Check dependencies first
    if not check_dependencies(interface):
        return 1

    with interface.with_group("Configuration"):
        # Offer to create example config file
        create_example_config(interface)

    # Ask about bash history timestamps (replaces old setup.sh functionality)
    add_bash_timestamps(interface)

    interface.display_success("Solveig setup complete!")
    quick_start_str = """
# Run a local model:
solveig -u "http://localhost:5001/v1" "Tell me a joke"

# Run from a remote API like OpenRouter:
solveig -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free" "Summarize my day"
    """.strip()
    interface.display_text_block(quick_start_str, title="Quick start:")

    return 0


if __name__ == "__main__":
    sys.exit()
