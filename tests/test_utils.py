"""Test utilities for creating mocked Solveig objects."""

from pathlib import Path
from unittest.mock import Mock

from solveig.config import APIType, SolveigConfig
from solveig.schema.message import LLMMessage
from solveig.schema.requirement import (
    CommandRequirement,
    ReadRequirement,
    WriteRequirement,
)
from solveig.schema.result import CommandResult, ReadResult, WriteResult

DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=False,
)

VERBOSE_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=True,
)


class MockRequirementMixin:
    """Mixin to add mocking capabilities to requirement classes by mocking OS interactions only."""

    def __init__(self, *args, accepted: bool = True, **kwargs):
        super().__init__(**kwargs)
        self._setup_mocks(accepted)

    def _setup_mocks(self, accepted: bool = True):
        """Set up mocks for OS interaction methods. Override in subclasses."""
        pass


class MockReadRequirement(MockRequirementMixin, ReadRequirement):
    """ReadRequirement subclass that mocks only OS interactions."""

    def _setup_mocks(self, accepted: bool = True):
        """Set up mocks for ReadRequirement OS interactions."""
        # Mock OS interactions
        self._validate_read_access = Mock()
        self._read_file_with_metadata = Mock(
            return_value={
                "metadata": {
                    "path": str(self.path),
                    "size": 1024,
                    "mtime": "2024-01-01T00:00:00",
                },
                "content": "Mock file content",
                "encoding": "text",
                "directory_listing": None,
            }
        )
        # Mock user interactions - default behavior based on accepted parameter
        self._ask_directory_consent = Mock(return_value=accepted)
        self._ask_file_read_choice = Mock(return_value="y" if accepted else "n")
        self._ask_final_consent = Mock(return_value=accepted)


class MockWriteRequirement(MockRequirementMixin, WriteRequirement):
    """WriteRequirement subclass that mocks only OS interactions."""

    def _setup_mocks(self, accepted: bool = True):
        """Set up mocks for WriteRequirement OS interactions."""
        # Mock OS interactions
        self._resolve_path = Mock(return_value=Path(self.path))
        self._path_exists = Mock(return_value=False)  # Default: path doesn't exist
        self._validate_write_access = Mock()
        self._write_file_or_directory = Mock()
        # Mock user interactions - default behavior based on accepted parameter
        self._ask_write_consent = Mock(return_value=accepted)


class MockCommandRequirement(MockRequirementMixin, CommandRequirement):
    """CommandRequirement subclass that mocks only OS interactions."""

    def _setup_mocks(self, accepted: bool = True):
        """Set up mocks for CommandRequirement OS interactions."""
        # Mock OS interactions
        self._execute_command = Mock(return_value=("Mock command output", None))
        # Mock user interactions - default behavior based on accepted parameter
        self._ask_run_consent = Mock(return_value=accepted)
        self._ask_output_consent = Mock(return_value=accepted)


class MockRequirementFactory:
    """Factory for creating requirements with mocked OS interactions."""

    # Class mappings and their default values
    _REQUIREMENT_TYPES = {
        "read": {
            "class": MockReadRequirement,
            "defaults": {
                "path": "/test/file.txt",
                "only_read_metadata": False,
                "comment": "I need to read file.txt",
            },
        },
        "write": {
            "class": MockWriteRequirement,
            "defaults": {
                "path": "/test/output.txt",
                "content": "test content",
                "comment": "It's required to create an output.txt file",
                "is_directory": False,
            },
        },
        "command": {
            "class": MockCommandRequirement,
            "defaults": {
                "command": "ls -la",
                "comment": "After that let's see if all expected files are there",
            },
        },
    }

    @staticmethod
    def _create_requirement(req_type, **kwargs):
        """Generic requirement creation method."""
        config = MockRequirementFactory._REQUIREMENT_TYPES[req_type]
        defaults = config["defaults"].copy()
        defaults.update(kwargs)

        return config["class"](**defaults)

    @staticmethod
    def create_read_requirement(**kwargs):
        """Create a ReadRequirement with mocked OS interactions."""
        return MockRequirementFactory._create_requirement("read", **kwargs)

    @staticmethod
    def create_write_requirement(**kwargs):
        """Create a WriteRequirement with mocked OS interactions."""
        return MockRequirementFactory._create_requirement("write", **kwargs)

    @staticmethod
    def create_command_requirement(**kwargs):
        """Create a CommandRequirement with mocked OS interactions."""
        return MockRequirementFactory._create_requirement("command", **kwargs)

    @staticmethod
    def create_mixed_requirements(**kwargs):
        """Create a list of read, write, and command requirements."""
        return [
            MockRequirementFactory.create_read_requirement(**kwargs),
            MockRequirementFactory.create_write_requirement(**kwargs),
            MockRequirementFactory.create_command_requirement(**kwargs),
        ]


class MessageFactory:
    """Factory for creating LLM messages with requirements."""

    @staticmethod
    def create_llm_message(
        comment="I need to read a file, write another file, and run a command.",
        requirements=None,
        **kwargs,
    ):
        """Create an LLM message with mock requirements.

        Args:
            comment: Message comment
            requirements: List of requirements (if None, creates mixed requirements)

        Returns:
            Real LLMMessage with mock requirements that pass isinstance() checks
        """
        if requirements is None:
            requirements = MockRequirementFactory.create_mixed_requirements(**kwargs)

        return LLMMessage(comment=comment, requirements=requirements)


# Rebuild Pydantic models to resolve forward references after all classes are defined
ReadResult.model_rebuild()
WriteResult.model_rebuild()
CommandResult.model_rebuild()

# Single default message that works everywhere
DEFAULT_MESSAGE = MessageFactory.create_llm_message()
