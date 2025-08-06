"""Test utilities for creating mocked Solveig objects."""

from unittest.mock import Mock

from solveig.config import SolveigConfig, APIType
from solveig.schema.message import LLMMessage
from solveig.schema.requirement import ReadRequirement, WriteRequirement, CommandRequirement


DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=False
)

VERBOSE_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=True
)


class MockRequirementMixin:
    """Mixin to add mocking capabilities to requirement classes."""
    
    def __init__(self, *args, solve_return=None, **kwargs):
        # Set a default solve_return based on class name if not provided
        if solve_return is None:
            class_name = self.__class__.__name__.replace('Mock', '').replace('Requirement', '')
            solve_return = f"{class_name} result"
        
        super().__init__(**kwargs)
        self._solve_mock = Mock(return_value=solve_return)
    
    def solve(self, config):
        """Override solve method to return mock result."""
        return self._solve_mock(config)

    @property
    def solve_mock(self):
        """Access to the underlying mock for assertions."""
        return self._solve_mock


class MockReadRequirement(MockRequirementMixin, ReadRequirement):
    """ReadRequirement subclass that allows mocking solve() method."""
    pass


class MockWriteRequirement(MockRequirementMixin, WriteRequirement):
    """WriteRequirement subclass that allows mocking solve() method."""
    pass


class MockCommandRequirement(MockRequirementMixin, CommandRequirement):
    """CommandRequirement subclass that allows mocking solve() method."""
    pass


class RequirementFactory:
    """Factory for creating requirements with mocked solve() methods."""
    
    # Class mappings and their default values
    _REQUIREMENT_TYPES = {
        'read': {
            'class': MockReadRequirement,
            'defaults': {
                "path": "/test/file.txt",
                "only_read_metadata": False,
                "comment": "I need to read file.txt"
            }
        },
        'write': {
            'class': MockWriteRequirement,
            'defaults': {
                "path": "/test/output.txt",
                "content": "test content",
                "comment": "It's required to create an output.txt file",
                "is_directory": False
            }
        },
        'command': {
            'class': MockCommandRequirement,
            'defaults': {
                "command": "ls -la",
                "comment": "After that let's see if all expected files are there"
            }
        }
    }
    
    @staticmethod
    def _create_requirement(req_type, solve_return=None, **kwargs):
        """Generic requirement creation method."""
        config = RequirementFactory._REQUIREMENT_TYPES[req_type]
        defaults = config['defaults'].copy()
        defaults.update(kwargs)
        
        return config['class'](solve_return=solve_return, **defaults)
    
    @staticmethod
    def create_read_requirement(solve_return=None, **kwargs):
        """Create a ReadRequirement with mocked solve() method."""
        return RequirementFactory._create_requirement('read', solve_return, **kwargs)
    
    @staticmethod
    def create_write_requirement(solve_return=None, **kwargs):
        """Create a WriteRequirement with mocked solve() method."""
        return RequirementFactory._create_requirement('write', solve_return, **kwargs)
    
    @staticmethod
    def create_command_requirement(solve_return=None, **kwargs):
        """Create a CommandRequirement with mocked solve() method."""
        return RequirementFactory._create_requirement('command', solve_return, **kwargs)
    
    @staticmethod
    def create_mixed_requirements():
        """Create a list of read, write, and command requirements."""
        return [
            RequirementFactory.create_read_requirement(),
            RequirementFactory.create_write_requirement(),
            RequirementFactory.create_command_requirement()
        ]


class MessageFactory:
    """Factory for creating LLM messages with requirements."""
    
    @staticmethod
    def create_llm_message(comment="I need to read a file, write another file, and run a command.", 
                          requirements=None):
        """Create an LLM message with mock requirements.
        
        Args:
            comment: Message comment
            requirements: List of requirements (if None, creates mixed requirements)
            
        Returns:
            Real LLMMessage with mock requirements that pass isinstance() checks
        """
        if requirements is None:
            requirements = RequirementFactory.create_mixed_requirements()
        
        return LLMMessage(comment=comment, requirements=requirements)


# Single default message that works everywhere
DEFAULT_MESSAGE = MessageFactory.create_llm_message()
