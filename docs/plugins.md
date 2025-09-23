# Plugin Development Guide

Solveig's plugin system allows you to extend functionality without modifying core code. There are two types of plugins you can create.

## Plugin Types

### Hook Plugins
Use `@before` and `@after` decorators to validate or modify existing requirements.

### Requirement Plugins  
Create new operations that the LLM can request, like database queries or API calls.

## Quick Examples

### Requirement Plugin: DateTime

Create `solveig/plugins/schema/datetime.py`:

```python
from datetime import datetime
from typing import Literal

from solveig.interface import SolveigInterface
from solveig.schema import register_requirement
from solveig.schema.requirements.base import Requirement
from solveig.schema.results.base import RequirementResult


class DateTimeResult(RequirementResult):
    """Result containing ISO timestamp."""
    timestamp: str | None = None


@register_requirement
class DateTimeRequirement(Requirement):
    """Get current date and time as ISO timestamp."""
    title: Literal["datetime"] = "datetime"

    @classmethod
    def get_description(cls) -> str:
        return "datetime(): get current date and time as ISO timestamp"

    def create_error_result(self, error_message: str, accepted: bool) -> DateTimeResult:
        return DateTimeResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
        )

    def actually_solve(self, config, interface: SolveigInterface) -> DateTimeResult:
        """Get current timestamp."""
        timestamp = datetime.now().astimezone().isoformat()
        return DateTimeResult(
            requirement=self,
            accepted=True,
            timestamp=timestamp,
        )


# Fix forward references
DateTimeResult.model_rebuild()
```

### @before Hook: Rate Limiting

Create `solveig/plugins/hooks/rate_limit.py`:

```python
import time
from solveig.plugins.hooks import before
from solveig.exceptions import SecurityError
from solveig.schema.requirements import Requirement

# Track last request time per requirement type
_last_request_times = {}

@before(requirements=(Requirement,))  # Apply to all requirements
def rate_limit_requests(config, interface, requirement):
    """Prevent rapid-fire requests."""
    req_type = type(requirement).__name__
    current_time = time.time()
    
    if req_type in _last_request_times:
        time_since_last = current_time - _last_request_times[req_type]
        if time_since_last < 1.0:  # 1 second minimum between requests
            raise SecurityError(f"Rate limit: Wait {1.0 - time_since_last:.1f}s before next {req_type}")
    
    _last_request_times[req_type] = current_time
```

### @after Hook: UTC Conversion

Create `solveig/plugins/hooks/utc_normalize.py`:

```python
from datetime import datetime
from solveig.plugins.hooks import after
from solveig.plugins.schema.datetime import DateTimeRequirement, DateTimeResult

@after(requirements=(DateTimeRequirement,))
def normalize_to_utc(config, interface, requirement, result: DateTimeResult):
    """Convert timestamp to UTC."""
    if result.timestamp and result.accepted:
        # Parse the ISO timestamp and convert to UTC
        dt = datetime.fromisoformat(result.timestamp)
        utc_dt = dt.utctimetuple()
        result.timestamp = datetime(*utc_dt[:6]).isoformat() + 'Z'
```

## Plugin Registration

### Hook Plugins
Just create the file with decorators - they auto-register when Solveig loads.

### Requirement Plugins
1. Create the requirement file as shown above
2. Add import to `solveig/schema/requirements/__init__.py`:
   ```python
   from solveig.plugins.schema.datetime import DateTimeRequirement
   ```

## Plugin Configuration

Add plugin settings to your config file:

```json
{
  "plugins": {
    "rate_limit": {
      "enabled": true,
      "min_interval": 2.0
    },
    "utc_normalize": {
      "enabled": true
    }
  }
}
```

Access config in plugins:
```python
@before(requirements=(SomeRequirement,))
def my_hook(config, interface, requirement):
    plugin_config = config.plugins.get("my_plugin", {})
    if not plugin_config.get("enabled", True):
        return  # Skip if disabled
```

## Testing Plugins

Create `tests/plugins/test_datetime.py`:

```python
from datetime import datetime
from solveig.plugins.schema.datetime import DateTimeRequirement
from tests.mocks import MockInterface, DEFAULT_CONFIG

class TestDateTimeRequirement:
    def test_datetime_requirement_success(self):
        """Test datetime requirement returns valid ISO timestamp."""
        interface = MockInterface()
        requirement = DateTimeRequirement()
        
        result = requirement.solve(DEFAULT_CONFIG, interface)
        
        assert result.accepted
        assert result.timestamp is not None
        # Verify it's valid ISO format
        datetime.fromisoformat(result.timestamp.replace('Z', '+00:00'))
```

## Plugin Guidelines

### Best Practices
- **Keep it simple**: Plugins should do one thing well
- **Handle errors**: Always use try/except and return appropriate error results
- **Test thoroughly**: Write tests for both success and failure cases
- **Document behavior**: Clear docstrings explaining what the plugin does

### Security Considerations
- **Validate inputs**: Never trust requirement data without validation
- **Fail safely**: When in doubt, block the operation
- **Log actions**: Use the interface to communicate what's happening

### Performance Tips
- **Cache when possible**: Store expensive computations
- **Avoid blocking**: Don't make long network requests in @before hooks
- **Clean up**: Release resources properly

## Advanced Examples

See existing plugins for more complex examples:
- `solveig/plugins/hooks/shellcheck.py` - Command validation with external tool
- `solveig/plugins/schema/tree.py` - Directory tree generation requirement