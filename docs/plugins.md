# Plugins

Solveig's plugin system allows you to extend functionality without modifying core code.
**Plugins must be explicitly enabled in the file configuration to be active.**

Currently, the following plugins are included:
- **tree**: Generate directory tree structures (`tree(path)`)
- **shellcheck**: Validate shell commands before execution (hook plugin)

## Using Plugins

- Place the plugin_name.py file in `solveig/plugins/schema/` or `solveig/plugins/requirements/`
- Enable and configure the plugins in your `solveig.json` config file

### Configuration

Add plugins to the `plugins` section of your config file to enable them.
You can set individual parameters or use an empty configuration (`{}`) to keep all defaults:

```json
{
  "plugins": {
    "tree": {},
    "shellcheck": {
      "shell": "bash"
    }
  }
}
```

**Important**: Plugins not listed in the `plugins` config section are automatically skipped, even if installed.

## Developing Plugins

*Note: If a plugin includes both requirements and hooks, it needs to be split up into 2 files.
Due to the way Hooks depend on Requirements for type filtering, all Requirements (core+plugins) have to be
defined before any hooks are imported. Currently, the only way to assure this always happens is to use separate
files.* 

## Plugin Types

### Requirement Plugins
Requirements represent resources and operations that the LLM can request. You can add new functionalities
available to the assistant like database queries and HTTP requests by implementing them as Requirement plugins.


### Hook Plugins
Hooks can interact with existing requirement for data validation, displaying, altering, etc.
Use `@before` and `@after` decorators, optionally filtered by a set of requirements to apply to:

```python
from solveig.schema.requirements import Requirement, WriteRequirement, DeleteRequirement
from solveig.plugins.hooks import before

# Runs for all requirements
@before()
def run_for_all(config, interface, requirement):
    interface(f"Running for requirement type={type(requirement)}")

# Runs only for write/delete
@before(requirements=(WriteRequirement, DeleteRequirement))
def run_for_all(config, interface, requirement):
    req_type = type(requirement)
    assert req_type in { WriteRequirement, DeleteRequirement }
    interface(f"Running for requirement type={type(requirement)}")
```

## Quick Examples

### Requirement Plugin: DateTime

- Create a class that inherits from `solveig.schema.requirements.base.Requirement`
- Implement 3 required methods (you can optionally also re-define the display method)
- Register your new Requirement with `@register_requirement`

```python
import zoneinfo
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

    def display_header(
            self, interface: SolveigInterface, detailed: bool = False
    ) -> None:
        """Display datetime requirement header."""
        super().display_header(interface, detailed=detailed)  # displays self.comment

    def create_error_result(self, error_message: str, accepted: bool) -> DateTimeResult:
        return DateTimeResult(
            requirement=self,
            accepted=accepted,
            error=error_message,
        )

    def actually_solve(self, config, interface: SolveigInterface) -> DateTimeResult:
        """Get current timestamp."""
        timezone = config.plugins.get("datetime", {}).get("timezone") # ex: "America/Los_Angeles"
        tz = zoneinfo.ZoneInfo(timezone) if timezone else None
        timestamp = datetime.now(tz=tz).isoformat()
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

### @after Hook: Timezone Conversion

Assuming we have the above `datetime.py` plugin inside `solveig/plugins/requirements/`
create `solveig/plugins/hooks/utc_normalize.py`:

```python
from datetime import datetime
import zoneinfo
from solveig.plugins.hooks import after
from solveig.plugins.schema.datetime import DateTimeRequirement, DateTimeResult

@after(requirements=(DateTimeRequirement,))
def normalize_to_utc(config, interface, requirement, result: DateTimeResult):
    """Convert timestamp to another timezone, defaulting to UTC if not configured."""
    if result.timestamp and result.accepted:
        plugin_config = config.plugins.get("utc_normalize", {})
        timezone = zoneinfo.ZoneInfo(plugin_config.get("timezone", "UTC"))
        dt = datetime.fromisoformat(result.timestamp)
        result.timestamp = dt.astimezone(timezone).isoformat()
```

## Testing

Plugins are expected to include tests.
See [contributing.md](../CONTRIBUTING.md) for comprehensive testing guidelines and mock infrastructure.

## Plugin Guidelines

### Best Practices
- **Keep it simple**: Plugins should do one thing well.
- **Interface integration**: Use the interface to communicate what's happening. Avoid directs print() or input().
- **Handle errors**: Always use try/except and return appropriate error results.
- **Test thoroughly**: Write tests for both success and failure cases. Use the existing mocks.
- **Document behavior**: Use docstrings explaining what the plugin does - this is especially relevant for requirements,
where the description string gets sent to the assistant and is crucial to ensure proper usage.
- **Validate inputs**: Requirements are generated from the LLM - never trust requirement data without validation.
- **Cache when possible**: Store expensive computations for re-using.
- **Avoid blocking**: Don't make long network operations unless necessary. If you do, use the interface animations.

## Advanced Examples

See existing plugins for more complex examples:
- `solveig/plugins/hooks/shellcheck.py` - Command validation with external tool
- `solveig/plugins/schema/tree.py` - Directory tree generation requirement
