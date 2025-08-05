"""Test utilities for creating mocked Solveig objects."""

from unittest.mock import Mock
from solveig.schema.message import LLMMessage
from solveig.schema.requirement import ReadRequirement, WriteRequirement, CommandRequirement


class MockReadRequirement(ReadRequirement):
    """ReadRequirement subclass that allows mocking solve() method."""
    
    def __init__(self, solve_return="Read result", **kwargs):
        super().__init__(**kwargs)
        self._solve_return = solve_return
        self._solve_mock = Mock(return_value=solve_return)
    
    def solve(self, config):
        """Override solve method to return mock result."""
        return self._solve_mock(config)
    
    @property
    def solve_mock(self):
        """Access to the underlying mock for assertions."""
        return self._solve_mock


class MockWriteRequirement(WriteRequirement):
    """WriteRequirement subclass that allows mocking solve() method."""
    
    def __init__(self, solve_return="Write result", **kwargs):
        super().__init__(**kwargs)
        self._solve_return = solve_return
        self._solve_mock = Mock(return_value=solve_return)
    
    def solve(self, config):
        """Override solve method to return mock result."""
        return self._solve_mock(config)
    
    @property
    def solve_mock(self):
        """Access to the underlying mock for assertions."""
        return self._solve_mock


class MockCommandRequirement(CommandRequirement):
    """CommandRequirement subclass that allows mocking solve() method."""
    
    def __init__(self, solve_return="Command result", **kwargs):
        super().__init__(**kwargs)
        self._solve_return = solve_return
        self._solve_mock = Mock(return_value=solve_return)
    
    def solve(self, config):
        """Override solve method to return mock result."""
        return self._solve_mock(config)
    
    @property
    def solve_mock(self):
        """Access to the underlying mock for assertions."""
        return self._solve_mock


class RequirementFactory:
    """Factory for creating requirements with mocked solve() methods."""
    
    @staticmethod
    def create_read_requirement(solve_return="Read result", **kwargs):
        """Create a ReadRequirement with mocked solve() method.
        
        Args:
            solve_return: Return value for the solve() method
            **kwargs: Additional arguments for ReadRequirement constructor
            
        Returns:
            MockReadRequirement instance that passes isinstance(req, ReadRequirement)
        """
        defaults = {
            "path": "/test/file.txt",
            "only_read_metadata": False,
            "comment": "I need to read file.txt"
        }
        defaults.update(kwargs)
        
        return MockReadRequirement(solve_return=solve_return, **defaults)
    
    @staticmethod
    def create_write_requirement(solve_return="Write result", **kwargs):
        """Create a WriteRequirement with mocked solve() method."""
        defaults = {
            "path": "/test/output.txt",
            "content": "test content",
            "comment": "It's required to create an output.txt file",
            "is_directory": False
        }
        defaults.update(kwargs)
        
        return MockWriteRequirement(solve_return=solve_return, **defaults)
    
    @staticmethod
    def create_command_requirement(solve_return="Command result", **kwargs):
        """Create a CommandRequirement with mocked solve() method."""
        defaults = {
            "command": "ls -la",
            "comment": "After that let's see if all expected files are there"
        }
        defaults.update(kwargs)
        
        return MockCommandRequirement(solve_return=solve_return, **defaults)
    
    @staticmethod
    def create_mixed_requirements():
        """Create a list of read, write, and command requirements."""
        return [
            RequirementFactory.create_read_requirement(),
            RequirementFactory.create_write_requirement(),
            RequirementFactory.create_command_requirement()
        ]
    
    @staticmethod
    def create_simple_mock_requirements():
        """Create simple Mock objects (for tests that don't need isinstance checks)."""
        mock_req1 = Mock()
        mock_req1.solve.return_value = "Read result"
        
        mock_req2 = Mock()
        mock_req2.solve.return_value = "Write result"
        
        mock_req3 = Mock()
        mock_req3.solve.return_value = "Command result"
        
        return [mock_req1, mock_req2, mock_req3]


class MessageFactory:
    """Factory for creating LLM messages with requirements."""
    
    @staticmethod
    def create_llm_message_with_inheritance(comment="I need to read a file, write another file, and run a command.", 
                                          requirements=None):
        """Create an LLM message using inherited mock requirements.
        
        Args:
            comment: Message comment
            requirements: List of requirements (if None, creates mixed requirements)
            
        Returns:
            Real LLMMessage with mock requirements that pass isinstance() checks
        """
        if requirements is None:
            requirements = RequirementFactory.create_mixed_requirements()
        
        return LLMMessage(comment=comment, requirements=requirements)
    
    @staticmethod
    def create_mock_message_simple(comment="I need to read a file, write another file, and run a command.", 
                                  requirements=None):
        """Create a mock LLM message with simple mock requirements.
        
        Args:
            comment: Message comment  
            requirements: List of requirements (if None, creates simple mocks)
            
        Returns:
            Mock LLMMessage with simple mock requirements
        """
        if requirements is None:
            requirements = RequirementFactory.create_simple_mock_requirements()
        
        mock_message = Mock(spec=LLMMessage)
        mock_message.comment = comment
        mock_message.requirements = requirements
        return mock_message


# Convenience instances - now both use the same approach!
DEFAULT_MOCK_MESSAGE = MessageFactory.create_mock_message_simple()
DEFAULT_INHERITANCE_MESSAGE = MessageFactory.create_llm_message_with_inheritance()

# Use inheritance-based approach for both, since it works everywhere
DEFAULT_PROCESS_MESSAGE = DEFAULT_INHERITANCE_MESSAGE  
DEFAULT_SUMMARIZE_MESSAGE = DEFAULT_INHERITANCE_MESSAGE