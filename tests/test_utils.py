# """Test utilities for creating mocked Solveig objects."""
# from abc import ABC
# from pathlib import Path
# from unittest.mock import Mock
#
# from solveig.config import APIType, SolveigConfig
# from solveig.interface.base import SolveigInterface, RequirementPresentation
# from solveig.schema.message import LLMMessage
# from solveig.schema.requirement import (
#     CommandRequirement,
#     CopyRequirement,
#     DeleteRequirement,
#     MoveRequirement,
#     ReadRequirement,
#     WriteRequirement,
# )
# from solveig.schema.result import (
#     CommandResult,
#     CopyResult,
#     DeleteResult,
#     MoveResult,
#     ReadResult,
#     WriteResult,
# )
#
# DEFAULT_CONFIG = SolveigConfig(
#     api_type=APIType.OPENAI,
#     api_key="test-key",
#     url="test-url",
#     model="test-model",
#     temperature=0.5,
#
#     verbose=False,
# )
#
# VERBOSE_CONFIG = SolveigConfig(
#     api_type=APIType.OPENAI,
#     api_key="test-key",
#     url="test-url",
#     model="test-model",
#     temperature=0.5,
#     verbose=True,
# )
#
#
# class BaseMockRequirement(ABC):
#     """Mixin to add mocking capabilities to requirement classes using MockInterface for I/O."""
#
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         # Interface to use in requests
#         self._mock_interface = MockInterface()
#
#         # Add tracking for _actually_solve calls
#         self._actually_solve_call_count = 0
#         self._original_actually_solve = self._actually_solve
#         self._actually_solve = self._tracked_actually_solve
#
#         # Store accepted parameter for later use
#         # self._mock_accepted = accepted
#         self._mock_interface = None  # Will be created lazily
#         self._setup_mocks() # accepted)
#
#     def _tracked_actually_solve(self, config, interface):
#         """Wrapper around _actually_solve to track calls."""
#         self._actually_solve_call_count += 1
#         return self._original_actually_solve(config, interface)
#
#     # def _get_mock_interface(self):
#     #     """Lazily create and configure mock interface."""
#     #     if self._mock_interface is None:
#     #         # # Import here to avoid circular imports
#     #         # self._mock_interface = MockInterface()
#     #         # if it's a mock interface, the accepts/deny
#     #         # self._configure_mock_interface(self._mock_accepted)
#     #     return self._mock_interface
#
#     # def _configure_mock_interface(self, accepted: bool = True):
#     #     """Configure the mock interface with pre-configured responses."""
#     #     # Set up default user inputs based on accepted parameter
#     #     if accepted:
#     #         self._mock_interface.set_user_inputs(["y"] * 10)  # Plenty of 'yes' responses
#     #     else:
#     #         self._mock_interface.set_user_inputs(["n"] * 10)  # Plenty of 'no' responses
#
#     def _setup_mocks(self): #, accepted: bool = True):
#         """Set up mocks for OS interaction methods. Override in subclasses."""
#         pass
#
#     @property
#     def actually_solve_called(self) -> bool:
#         """Check if _actually_solve() was called (i.e., not blocked by plugins)."""
#         return self._actually_solve_call_count > 0
#
#     @property
#     def actually_solve_call_count(self) -> int:
#         """Get the number of times _actually_solve() was called."""
#         return self._actually_solve_call_count
#
# class MockReadRequirement(BaseMockRequirement, ReadRequirement):
#     """ReadRequirement subclass that mocks OS interactions and uses MockInterface for user I/O."""
#
#     def _setup_mocks(self): # , accepted: bool = True):
#         """Set up mocks for ReadRequirement OS interactions."""
#         # Mock OS interactions only
#         self._validate_read_access = Mock()
#         self._read_file_with_metadata = Mock(
#             return_value={
#                 "metadata": {
#                     "path": str(Path(self.path).expanduser().resolve()),
#                     "size": 1024,
#                     "mtime": "2024-01-01T00:00:00",
#                 },
#                 "content": "Mock file content",
#                 "encoding": "text",
#                 "directory_listing": None,
#             }
#         )
#
#     def _ask_directory_consent(self) -> bool:
#         """Use mock interface for directory consent."""
#         return self._get_mock_interface().ask_yes_no("Allow reading directory listing and metadata?")
#
#     def _ask_file_read_choice(self) -> str:
#         """Use mock interface for file read choice."""
#         response = self._get_mock_interface().prompt_user("Allow reading file? [y=content+metadata / m=metadata / N=skip]:")
#         return response.lower() if response else "n"
#
#     def _ask_final_consent(self, has_content: bool) -> bool:
#         """Use mock interface for final consent."""
#         prompt = f"Allow sending {'file content and ' if has_content else ''}metadata?"
#         return self._get_mock_interface().ask_yes_no(prompt)
#
#
# class MockWriteRequirement(BaseMockRequirement, WriteRequirement):
#     """WriteRequirement subclass that mocks OS interactions and uses MockInterface for user I/O."""
#
#     def _setup_mocks(self): # , accepted: bool = True):
#         """Set up mocks for WriteRequirement OS interactions."""
#         # Mock OS interactions only
#         self._resolve_path = Mock(return_value=Path(self.path))
#         self._path_exists = Mock(return_value=False)  # Default: path doesn't exist
#         self._validate_write_access = Mock()
#         self._write_file_or_directory = Mock()
#
#     def _ask_write_consent(self, operation_type: str, content_desc: str) -> bool:
#         """Use mock interface for write consent."""
#         prompt = f"Allow writing {operation_type}{content_desc}?"
#         return self._get_mock_interface().ask_yes_no(prompt)
#
#
# class MockCommandRequirement(BaseMockRequirement, CommandRequirement):
#     """CommandRequirement subclass that mocks OS interactions and uses MockInterface for user I/O."""
#
#     def _setup_mocks(self):
#         """Set up mocks for CommandRequirement OS interactions."""
#         # Mock OS interactions only
#         self._execute_command = Mock(return_value=("Mock command output", None))
#
#     def _ask_run_consent(self) -> bool:
#         """Use mock interface for run consent."""
#         return self._get_mock_interface().ask_yes_no("Allow running command?")
#
#     def _ask_output_consent(self) -> bool:
#         """Use mock interface for output consent."""
#         return self._get_mock_interface().ask_yes_no("Allow sending output?")
#
#
# class MockMoveRequirement(BaseMockRequirement, MoveRequirement):
#     """MoveRequirement subclass that mocks OS interactions and uses MockInterface for user I/O."""
#
#     def _setup_mocks(self) :#, accepted: bool = True):
#         """Set up mocks for MoveRequirement OS interactions."""
#         # Mock OS interactions only
#         self._validate_move_access = Mock()
#         self._move_file_or_directory = Mock()
#
#     def _ask_move_consent(self) -> bool:
#         """Use mock interface for move consent."""
#         prompt = f"Allow moving '{self.source_path}' to '{self.destination_path}'?"
#         return self._get_mock_interface().ask_yes_no(prompt)
#
#
# class MockCopyRequirement(BaseMockRequirement, CopyRequirement):
#     """CopyRequirement subclass that mocks OS interactions and uses MockInterface for user I/O."""
#
#     def _setup_mocks(self): #, accepted: bool = True):
#         """Set up mocks for CopyRequirement OS interactions."""
#         # Mock OS interactions only
#         self._validate_copy_access = Mock()
#         self._copy_file_or_directory = Mock()
#
#     def _ask_copy_consent(self) -> bool:
#         """Use mock interface for copy consent."""
#         prompt = f"Allow copying '{self.source_path}' to '{self.destination_path}'?"
#         return self._get_mock_interface().ask_yes_no(prompt)
#
#
# class MockDeleteRequirement(BaseMockRequirement, DeleteRequirement):
#     """DeleteRequirement subclass that mocks OS interactions and uses MockInterface for user I/O."""
#
#     def _setup_mocks(self): #, accepted: bool = True):
#         """Set up mocks for DeleteRequirement OS interactions."""
#         # Mock OS interactions only
#         self._validate_delete_access = Mock()
#         self._delete_file_or_directory = Mock()
#
#     def _ask_delete_consent(self) -> bool:
#         """Use mock interface for delete consent."""
#         prompt = f"Permanently delete '{self.path}'?"
#         return self._get_mock_interface().ask_yes_no(prompt)
#
#
# class MockRequirementFactory:
#     """Factory for creating requirements with mocked OS interactions."""
#
#     # Class mappings and their default values
#     _REQUIREMENT_TYPES = {
#         "read": {
#             "class": MockReadRequirement,
#             "defaults": {
#                 "path": "/test/file.txt",
#                 "only_read_metadata": False,
#                 "comment": "I need to read file.txt",
#             },
#         },
#         "write": {
#             "class": MockWriteRequirement,
#             "defaults": {
#                 "path": "/test/output.txt",
#                 "content": "test content",
#                 "comment": "It's required to create an output.txt file",
#                 "is_directory": False,
#             },
#         },
#         "command": {
#             "class": MockCommandRequirement,
#             "defaults": {
#                 "command": "ls -la",
#                 "comment": "After that let's see if all expected files are there",
#             },
#         },
#         "move": {
#             "class": MockMoveRequirement,
#             "defaults": {
#                 "source_path": "/test/source.txt",
#                 "destination_path": "/test/destination.txt",
#                 "comment": "I need to move the source file to destination",
#             },
#         },
#         "copy": {
#             "class": MockCopyRequirement,
#             "defaults": {
#                 "source_path": "/test/original.txt",
#                 "destination_path": "/test/copy.txt",
#                 "comment": "I need to copy the original file",
#             },
#         },
#         "delete": {
#             "class": MockDeleteRequirement,
#             "defaults": {
#                 "path": "/test/unwanted.txt",
#                 "comment": "I need to delete this unwanted file",
#             },
#         },
#     }
#
#     @staticmethod
#     def _create_requirement(req_type, **kwargs):
#         """Generic requirement creation method."""
#         config = MockRequirementFactory._REQUIREMENT_TYPES[req_type]
#         defaults = config["defaults"].copy()
#         defaults.update(kwargs)
#
#         return config["class"](**defaults)
#
#     @staticmethod
#     def create_read_requirement(**kwargs):
#         """Create a ReadRequirement with mocked OS interactions."""
#         return MockRequirementFactory._create_requirement("read", **kwargs)
#
#     @staticmethod
#     def create_write_requirement(**kwargs):
#         """Create a WriteRequirement with mocked OS interactions."""
#         return MockRequirementFactory._create_requirement("write", **kwargs)
#
#     @staticmethod
#     def create_command_requirement(**kwargs):
#         """Create a CommandRequirement with mocked OS interactions."""
#         return MockRequirementFactory._create_requirement("command", **kwargs)
#
#     @staticmethod
#     def create_move_requirement(**kwargs):
#         """Create a MoveRequirement with mocked OS interactions."""
#         return MockRequirementFactory._create_requirement("move", **kwargs)
#
#     @staticmethod
#     def create_copy_requirement(**kwargs):
#         """Create a CopyRequirement with mocked OS interactions."""
#         return MockRequirementFactory._create_requirement("copy", **kwargs)
#
#     @staticmethod
#     def create_delete_requirement(**kwargs):
#         """Create a DeleteRequirement with mocked OS interactions."""
#         return MockRequirementFactory._create_requirement("delete", **kwargs)
#
#     @staticmethod
#     def create_mixed_requirements(**kwargs):
#         """Create a list of read, write, and command requirements."""
#         return [
#             MockRequirementFactory.create_read_requirement(**kwargs),
#             MockRequirementFactory.create_write_requirement(**kwargs),
#             MockRequirementFactory.create_command_requirement(**kwargs),
#         ]
#
#     @staticmethod
#     def create_all_requirements(**kwargs):
#         """Create a list of all requirement types."""
#         return [
#             MockRequirementFactory.create_read_requirement(**kwargs),
#             MockRequirementFactory.create_write_requirement(**kwargs),
#             MockRequirementFactory.create_command_requirement(**kwargs),
#             MockRequirementFactory.create_move_requirement(**kwargs),
#             MockRequirementFactory.create_copy_requirement(**kwargs),
#             MockRequirementFactory.create_delete_requirement(**kwargs),
#         ]
#
#
# class MessageFactory:
#     """Factory for creating LLM messages with requirements."""
#
#     @staticmethod
#     def create_llm_message(
#         comment="I need to read a file, write another file, and run a command.",
#         requirements=None,
#         **kwargs,
#     ):
#         """Create an LLM message with mock requirements.
#
#         Args:
#             comment: Message comment
#             requirements: List of requirements (if None, creates mixed requirements)
#
#         Returns:
#             Real LLMMessage with mock requirements that pass isinstance() checks
#         """
#         if requirements is None:
#             requirements = MockRequirementFactory.create_mixed_requirements(**kwargs)
#
#         return LLMMessage(comment=comment, requirements=requirements)
#
#
# # Rebuild Pydantic models to resolve forward references after all classes are defined
# ReadResult.model_rebuild()
# WriteResult.model_rebuild()
# CommandResult.model_rebuild()
# MoveResult.model_rebuild()
# CopyResult.model_rebuild()
# DeleteResult.model_rebuild()
#
# # Single default message that works everywhere
# DEFAULT_MESSAGE = MessageFactory.create_llm_message()
# ALL_REQUIREMENTS_MESSAGE = MessageFactory.create_llm_message(
#     comment="I need to read, write, run commands, move, copy, and delete files",
#     requirements=MockRequirementFactory.create_all_requirements(),
# )
#
#
