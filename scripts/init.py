#!/usr/bin/env python3
"""
Solveig initialization script.

This script helps users set up their environment for optimal use with Solveig,
including optional bash history timestamping for better context awareness.
This replaces the old setup.sh script with proper Python integration.
"""

import sys
from pathlib import Path

from solveig.interface import CLIInterface, SolveigInterface


def add_bash_timestamps(interface: SolveigInterface) -> bool:
    """
    Add timestamp formatting to bash history.

    This is the functionality from the original setup.sh, now properly integrated.
    Helps Solveig understand when commands were executed for better context.

    Returns:
        bool: True if timestamps were successfully added, False otherwise.
    """
    bashrc_path = Path.home() / ".bashrc"
    timestamp_line = 'export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "'

    with interface.with_group("Bash History Timestamps"):
        interface.display_text_block(
            "Adding timestamps to your bash history helps Solveig understand "
            + "when you executed commands, providing better context for assistance."
        )
        if interface.ask_yes_no("Would you like to enable bash history timestamps?"):
            try:
                # Check if timestamps are already configured
                if bashrc_path.exists():
                    content = bashrc_path.read_text()
                    if "HISTTIMEFORMAT" in content:
                        interface.show(
                            "✓ Bash history timestamps are already configured."
                        )
                        return True

                # Add timestamp configuration
                # file_utils.write_file_or_directory()
                with open(bashrc_path, "a") as f:
                    f.write("\n# Added by Solveig for better context awareness\n")
                    f.write(f"{timestamp_line}\n")

                interface.show("✓ Added bash history timestamps to ~/.bashrc")
                interface.show(
                    "Run 'source ~/.bashrc' or restart your terminal to apply changes."
                )
                return True

            except Exception as e:
                interface.display_error(f"Failed to add bash timestamps: {e}")
                return False
        else:
            interface.show("○ Skipped bash history timestamp setup.")
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
            interface.show("✓ All required dependencies are installed.")
            return True


# def check_optional_tools(interface: SolveigInterface) -> None:
#     """Check for optional tools that enhance Solveig's functionality."""
#     import shutil
#
#     optional_tools = {
#         "shellcheck": "Command validation (recommended for security)",
#         "git": "Version control integration",
#     }
#
#     print("\nOptional tools:")
#     for tool, description in optional_tools.items():
#         if shutil.which(tool):
#             print(f"✓ {tool} - {description}")
#         else:
#             print(f"○ {tool} - {description} (not found)")


def create_config_directory(interface: SolveigInterface) -> bool:
    """Create the default configuration directory."""
    config_dir = Path.home() / ".config"

    try:
        config_dir.mkdir(exist_ok=True)
        interface.show(f"✓ Configuration directory ready: {config_dir}")
        return True
    except Exception as e:
        interface.display_error(f"Failed to create config directory: {e}")
        return False


def main(interface: SolveigInterface | None = None) -> int:
    """Main initialization function."""
    # All defaults for now
    interface = interface or CLIInterface()

    interface.display_section("Setup")
    interface.show("Setting up Solveig")

    # Check dependencies first
    if not check_dependencies(interface):
        return 1

    # Create config directory
    if not create_config_directory(interface):
        return 1

    # Check optional tools
    # check_optional_tools()
    # print()

    # Ask about bash history timestamps (replaces old setup.sh functionality)
    add_bash_timestamps(interface)

    # if interface.ask_yes_no("Would you like to enable bash history timestamps?"):
    #     add_bash_timestamps(interface)
    # else:
    #     print("○ Skipped bash history timestamp setup.")

    # print()
    interface.show("Solveig setup complete!")

    quick_start_str = """
# Run a local model:
solveig -u "http://localhost:5001/v1" "Tell me a joke"

# Run from a remote API like OpenRouter:
solveig -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free" "Summarize my day"
    """.strip()
    interface.display_text_block(quick_start_str, title="Quick start:")

    # print("  solveig --help                    # Show available options")
    # print("  solveig 'Tell me about this dir' # Start a conversation")
    # print()
    # print("For more information, see: README.md")

    return 0


if __name__ == "__main__":
    sys.exit()
