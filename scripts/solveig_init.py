#!/usr/bin/env python3
"""
Solveig initialization script.

This script helps users set up their environment for optimal use with Solveig,
including optional bash history timestamping for better context awareness.
This replaces the old setup.sh script with proper Python integration.
"""

import sys
from pathlib import Path


def add_bash_timestamps() -> bool:
    """
    Add timestamp formatting to bash history.

    This is the functionality from the original setup.sh, now properly integrated.
    Helps Solveig understand when commands were executed for better context.

    Returns:
        bool: True if timestamps were successfully added, False otherwise.
    """
    bashrc_path = Path.home() / ".bashrc"
    timestamp_line = 'export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "'

    try:
        # Check if timestamps are already configured
        if bashrc_path.exists():
            content = bashrc_path.read_text()
            if "HISTTIMEFORMAT" in content:
                print("✓ Bash history timestamps are already configured.")
                return True

        # Add timestamp configuration
        with open(bashrc_path, "a") as f:
            f.write("\n# Added by Solveig for better context awareness\n")
            f.write(f"{timestamp_line}\n")

        print("✓ Added bash history timestamps to ~/.bashrc")
        print("  Run 'source ~/.bashrc' or restart your terminal to apply changes.")
        return True

    except Exception as e:
        print(f"✗ Failed to add bash timestamps: {e}")
        return False


def check_dependencies() -> bool:
    """Check if all required dependencies are installed."""
    required_packages = [
        "distro",
        "instructor",
        "openai",
        "pydantic",
        "tiktoken",
    ]

    missing_packages = []

    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print("✗ Missing required packages:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\nRun: pip install -e .")
        return False
    else:
        print("✓ All required dependencies are installed.")
        return True


def check_optional_tools() -> None:
    """Check for optional tools that enhance Solveig's functionality."""
    import shutil

    optional_tools = {
        "shellcheck": "Command validation (recommended for security)",
        "git": "Version control integration",
    }

    print("\nOptional tools:")
    for tool, description in optional_tools.items():
        if shutil.which(tool):
            print(f"✓ {tool} - {description}")
        else:
            print(f"○ {tool} - {description} (not found)")


def create_config_directory() -> bool:
    """Create the default configuration directory."""
    config_dir = Path.home() / ".config"

    try:
        config_dir.mkdir(exist_ok=True)
        print(f"✓ Configuration directory ready: {config_dir}")
        return True
    except Exception as e:
        print(f"✗ Failed to create config directory: {e}")
        return False


def ask_yes_no(question: str, default: bool = True) -> bool:
    """Ask a yes/no question with a default answer."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{question} [{default_str}]: ").strip().lower()

        if not response:
            return default
        elif response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            print("Please answer 'y' or 'n'")


def main() -> int:
    """Main initialization function."""
    print("🛡️  Solveig Setup")
    print("================")
    print("Setting up your environment for secure AI-system integration.")
    print()

    # Check dependencies first
    if not check_dependencies():
        return 1

    # Create config directory
    if not create_config_directory():
        return 1

    # Check optional tools
    check_optional_tools()
    print()

    # Ask about bash history timestamps (replaces old setup.sh functionality)
    print("Bash History Timestamps")
    print("-" * 23)
    print("Adding timestamps to your bash history helps Solveig understand")
    print("when you executed commands, providing better context for assistance.")
    print("This is the same functionality as the old setup.sh script.")
    print()

    if ask_yes_no("Would you like to enable bash history timestamps?"):
        add_bash_timestamps()
    else:
        print("○ Skipped bash history timestamp setup.")

    print()
    print("🎉 Solveig setup complete!")
    print()
    print("Quick start:")
    print("  solveig --help                    # Show available options")
    print("  solveig 'Tell me about this dir' # Start a conversation")
    print()
    print("For more information, see: README.md")

    return 0


if __name__ == "__main__":
    sys.exit(main())
