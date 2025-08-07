"""
Tests for the refactored exception-based plugin system.
"""

from solveig.config import SolveigConfig
from solveig.plugins import hooks
from solveig.plugins.exceptions import ProcessingError, SecurityError, ValidationError
from solveig.schema import CommandResult
from solveig.schema.requirement import CommandRequirement, ReadRequirement
from tests.test_utils import (
    DEFAULT_CONFIG,
    MockRequirementFactory,
    MockRequirementMixin,
)


class TestPluginExceptions:
    """Test plugin exception classes."""

    def test_validation_error_inheritance(self):
        """Test that ValidationError inherits properly."""
        error = ValidationError("test message")
        assert str(error) == "test message"
        assert isinstance(error, ValidationError)
        assert isinstance(error, Exception)

    def test_security_error_inheritance(self):
        """Test that SecurityError inherits from ValidationError."""
        error = SecurityError("security issue")
        assert str(error) == "security issue"
        assert isinstance(error, SecurityError)
        assert isinstance(error, ValidationError)

    def test_processing_error_inheritance(self):
        """Test that ProcessingError inherits properly."""
        error = ProcessingError("processing failed")
        assert str(error) == "processing failed"
        assert isinstance(error, ProcessingError)
        assert isinstance(error, Exception)


class TestPluginHookSystem:
    """Test the exception-based plugin hook system."""

    def setup_method(self):
        """Store original hooks and clear for isolated testing."""
        # assign copies of the hook lists
        self.original_before = hooks.HOOKS.before[:]
        self.original_after = hooks.HOOKS.after[:]
        # clear the hooks before each test
        hooks.HOOKS.before.clear()
        hooks.HOOKS.after.clear()

    def teardown_method(self):
        """Restore original hooks."""
        # clears existing list and re-inserts elements from originals into it
        # ensuring all references to it stay valid
        hooks.HOOKS.before[:] = self.original_before
        hooks.HOOKS.after[:] = self.original_after

    def test_before_hook_validation_error(self):
        """Test that before hooks can raise ValidationError to stop processing."""

        # Setup
        @hooks.before(requirements=(CommandRequirement,))
        def failing_validator(config: SolveigConfig, requirement: CommandRequirement):
            if "fail" in requirement.command:
                raise ValidationError("Command validation failed")

        req = MockRequirementFactory.create_command_requirement(
            comment="Test", command="fail this command"
        )

        # Execute
        result = req.solve(DEFAULT_CONFIG)

        # Verify
        assert not result.accepted
        assert result.error == "Pre-processing failed: Command validation failed"
        assert not result.success

    def test_before_hook_security_error(self):
        """Test that before hooks can raise SecurityError for dangerous commands."""

        # Setup
        @hooks.before(requirements=(CommandRequirement,))
        def security_validator(config: SolveigConfig, requirement: CommandRequirement):
            if "rm -rf" in requirement.command:
                raise SecurityError("Dangerous command detected")

        req = MockRequirementFactory.create_command_requirement(
            comment="Test", command="rm -rf /important/data"
        )

        # Execute
        result = req.solve(DEFAULT_CONFIG)

        # Verify
        assert not result.accepted
        assert result.error == "Pre-processing failed: Dangerous command detected"
        assert not result.success

    def test_before_hook_success_continues(self):
        """Test that before hooks that don't raise exceptions allow processing to continue."""

        # Setup
        @hooks.before(requirements=(CommandRequirement,))
        def passing_validator(config: SolveigConfig, requirement: CommandRequirement):
            # Just validate, don't throw
            assert requirement.command is not None

        req = MockRequirementFactory.create_command_requirement(
            comment="Test",
            command="echo hello",
            accepted=False,
        )

        # Execute
        result = req.solve(DEFAULT_CONFIG)

        # Verify
        # Should get to user interaction (not stopped by plugin)
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error

    def test_after_hook_processing_error(self):
        """Test that after hooks can raise ProcessingError."""

        # Setup
        @hooks.after(requirements=(CommandRequirement,))
        def failing_processor(
            config: SolveigConfig,
            requirement: CommandRequirement,
            result: CommandResult,
        ):
            if result.accepted:
                raise ProcessingError("Post-processing failed")

        req = MockRequirementFactory.create_command_requirement(
            comment="Test", command="echo hello"
        )

        # Execute
        result = req.solve(DEFAULT_CONFIG)

        # Verify
        assert result.accepted  # Command was accepted originally
        assert result.error == "Post-processing failed: Post-processing failed"

    def test_multiple_before_hooks(self):
        """Test that multiple before hooks are executed in order."""
        # Setup
        execution_order = []

        @hooks.before(requirements=(CommandRequirement,))
        def first_validator(config, requirement):
            execution_order.append("first")

        @hooks.before(requirements=(CommandRequirement,))
        def second_validator(config, requirement):
            execution_order.append("second")

        req = MockRequirementFactory.create_command_requirement(
            comment="Test", command="echo test"
        )

        # Execute
        req.solve(DEFAULT_CONFIG)

        # Verify
        assert execution_order == ["first", "second"]

    def test_hook_requirement_filtering(self):
        """Test that hooks only run for specified requirement types."""
        # Setup
        called = []

        @hooks.before(requirements=(CommandRequirement,))
        def command_only_hook(config, requirement):
            called.append("command_hook")

        @hooks.before(requirements=(ReadRequirement,))
        def read_only_hook(config, requirement):
            called.append("read_hook")

        # Execute
        # Test with CommandRequirement
        cmd_req = MockRequirementFactory.create_command_requirement(
            comment="Test", command="echo test"
        )
        cmd_req.solve(DEFAULT_CONFIG)

        # Test with ReadRequirement
        read_req = MockRequirementFactory.create_read_requirement(
            comment="Test", path="/test/file", only_read_metadata=True
        )
        read_req.solve(DEFAULT_CONFIG)

        # Verify
        assert "command_hook" in called
        assert "read_hook" in called
        assert len(called) == 2  # Each hook called once

    def test_hook_without_requirement_filter(self):
        """Test that hooks without requirement filters run for all requirement types."""
        # Setup
        called = []

        def get_requirement_name(requirement: MockRequirementMixin) -> str:
            return f"universal_{type(requirement).__name__}"

        @hooks.before()  # No schema filter
        def universal_hook(config, requirement):
            called.append(get_requirement_name(requirement))

        # Test with different requirement types
        cmd_req = MockRequirementFactory.create_command_requirement(
            comment="Test", command="echo test"
        )
        read_req = MockRequirementFactory.create_read_requirement(
            comment="Test", path="/test/file", only_read_metadata=True
        )

        # Execute
        cmd_req.solve(DEFAULT_CONFIG)
        read_req.solve(DEFAULT_CONFIG)

        # Verify
        assert get_requirement_name(cmd_req) in called
        assert get_requirement_name(read_req) in called
