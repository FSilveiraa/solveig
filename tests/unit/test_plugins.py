"""
Tests for the refactored exception-based plugin system.
"""

import pytest
from unittest.mock import patch, Mock

from solveig.config import SolveigConfig
from solveig.schema.requirement import CommandRequirement, ReadRequirement, WriteRequirement
from solveig.plugins.exceptions import ValidationError, SecurityError, ProcessingError
from solveig.plugins import hooks
from tests.test_utils import DEFAULT_CONFIG


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
        self.original_before = hooks.HOOKS.before[:]
        self.original_after = hooks.HOOKS.after[:]
        hooks.HOOKS.before.clear()
        hooks.HOOKS.after.clear()
    
    def teardown_method(self):
        """Restore original hooks."""
        hooks.HOOKS.before[:] = self.original_before
        hooks.HOOKS.after[:] = self.original_after
    
    def test_before_hook_validation_error(self):
        """Test that before hooks can raise ValidationError to stop processing."""
        
        @hooks.before(requirements=(CommandRequirement,))
        def failing_validator(config, requirement):
            if "fail" in requirement.command:
                raise ValidationError("Command validation failed")
        
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="fail this command")
        
        result = req.solve(config)
        
        assert not result.accepted
        assert result.error == "Pre-processing failed: Command validation failed"
        assert not result.success
    
    def test_before_hook_security_error(self):
        """Test that before hooks can raise SecurityError for dangerous commands."""
        
        @hooks.before(requirements=(CommandRequirement,))
        def security_validator(config, requirement):
            if "rm -rf" in requirement.command:
                raise SecurityError("Dangerous command detected")
        
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="rm -rf /important/data")
        
        result = req.solve(config)
        
        assert not result.accepted
        assert result.error == "Pre-processing failed: Dangerous command detected"
        assert not result.success
    
    def test_before_hook_success_continues(self):
        """Test that before hooks that don't raise exceptions allow processing to continue."""
        
        @hooks.before(requirements=(CommandRequirement,))
        def passing_validator(config, requirement):
            # Just validate, don't throw
            assert requirement.command is not None
        
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="echo hello")
        
        # Mock user interaction to decline running command
        with patch('solveig.utils.misc.ask_yes', return_value=False):
            result = req.solve(config)
        
        # Should get to user interaction (not stopped by plugin)
        assert not result.accepted  # Declined by user
        assert result.error is None  # No plugin error
    
    def test_after_hook_processing_error(self):
        """Test that after hooks can raise ProcessingError."""
        
        @hooks.after(requirements=(CommandRequirement,))
        def failing_processor(config, requirement, result):
            if result.accepted:
                raise ProcessingError("Post-processing failed")
        
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="echo hello")
        
        # Mock user interaction to accept running command  
        with patch('solveig.utils.misc.ask_yes', return_value=True), \
             patch('subprocess.run') as mock_subprocess:
            
            mock_subprocess.return_value = Mock(
                returncode=0, stdout="hello", stderr=""
            )
            
            result = req.solve(config)
        
        assert result.accepted  # Command was accepted originally
        assert result.error == "Post-processing failed: Post-processing failed"
    
    def test_multiple_before_hooks(self):
        """Test that multiple before hooks are executed in order."""
        execution_order = []
        
        @hooks.before(requirements=(CommandRequirement,))
        def first_validator(config, requirement):
            execution_order.append("first")
        
        @hooks.before(requirements=(CommandRequirement,))
        def second_validator(config, requirement):
            execution_order.append("second")
        
        config = DEFAULT_CONFIG
        req = CommandRequirement(comment="Test", command="echo test")
        
        with patch('solveig.utils.misc.ask_yes', return_value=False):
            req.solve(config)
        
        assert execution_order == ["first", "second"]
    
    def test_hook_requirement_filtering(self):
        """Test that hooks only run for specified requirement types."""
        called = []
        
        @hooks.before(requirements=(CommandRequirement,))
        def command_only_hook(config, requirement):
            called.append("command_hook")
        
        @hooks.before(requirements=(ReadRequirement,))
        def read_only_hook(config, requirement):
            called.append("read_hook")
        
        config = DEFAULT_CONFIG
        
        # Test with CommandRequirement
        cmd_req = CommandRequirement(comment="Test", command="echo test")
        with patch('solveig.utils.misc.ask_yes', return_value=False):
            cmd_req.solve(config)
        
        # Test with ReadRequirement  
        read_req = ReadRequirement(comment="Test", path="/test/file", only_read_metadata=True)
        with patch('solveig.utils.misc.ask_yes', return_value=False):
            read_req.solve(config)
        
        assert "command_hook" in called
        assert "read_hook" in called
        assert len(called) == 2  # Each hook called once
    
    def test_hook_without_requirement_filter(self):
        """Test that hooks without requirement filters run for all requirement types."""
        called = []
        
        @hooks.before()  # No schema filter
        def universal_hook(config, requirement):
            called.append(f"universal_{type(requirement).__name__}")
        
        config = DEFAULT_CONFIG
        
        # Test with different requirement types
        cmd_req = CommandRequirement(comment="Test", command="echo test")
        read_req = ReadRequirement(comment="Test", path="/test/file", only_read_metadata=True)
        
        with patch('solveig.utils.misc.ask_yes', return_value=False):
            cmd_req.solve(config)
            read_req.solve(config)
        
        assert "universal_CommandRequirement" in called
        assert "universal_ReadRequirement" in called


class TestPluginSystemIntegration:
    """Test core plugin system integration with Solveig."""
    
    def test_plugin_loading_mechanism(self):
        """Test that the plugin loading mechanism can discover plugin files."""
        # Test that the loading mechanism can discover plugin files
        import pkgutil
        from solveig.plugins.hooks import __path__, __name__ as pkg_name
        
        discovered = []
        for _, module_name, is_pkg in pkgutil.iter_modules(__path__, pkg_name + "."):
            if not is_pkg and not module_name.endswith(".__init__"):
                discovered.append(module_name.split(".")[-1])
        
        assert len(discovered) >= 1, "Should discover at least one plugin module"
        assert "shellcheck" in discovered, "Should discover shellcheck plugin"
    
    def test_plugin_discovery_system(self):
        """Test that the plugin discovery system finds plugin files."""
        # Store original state
        original_before = hooks.HOOKS.before[:]
        original_after = hooks.HOOKS.after[:]
        
        try:
            hooks.HOOKS.before.clear() 
            hooks.HOOKS.after.clear()
            
            # Import the load_hooks function to test discovery
            import pkgutil
            import importlib
            from solveig.plugins.hooks import __path__, __name__ as pkg_name
            
            discovered_modules = []
            for _, module_name, is_pkg in pkgutil.iter_modules(__path__, pkg_name + "."):
                if not is_pkg and not module_name.endswith(".__init__"):
                    discovered_modules.append(module_name.split(".")[-1])
            
            assert len(discovered_modules) >= 1, "Should discover plugin modules"
            assert "shellcheck" in discovered_modules, "Should discover shellcheck plugin"
            
        finally:
            # Restore original state
            hooks.HOOKS.before[:] = original_before  
            hooks.HOOKS.after[:] = original_after