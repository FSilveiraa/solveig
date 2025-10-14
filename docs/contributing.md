# Contributing to Solveig

## Development Setup

### Installation

```bash
# Clone and install with dev dependencies
git clone https://github.com/FSilveiraa/solveig.git
cd solveig
pip install -e .[dev]
```

### Dependencies

The `[dev]` optional dependencies include:
- `pytest` + `pytest-cov` for testing
- `black`, `ruff`, `mypy` for code quality
- `anthropic`, `google-generativeai` for API testing

## Code Quality

### Required Checks

All code submitted to the `main` branch must pass these checks (same as CI):

```bash
# Format code
black .

# Lint code  
ruff check . --fix

# Type checking
mypy solveig/ scripts/ --ignore-missing-imports

# Run tests with coverage
pytest ./tests/ --cov=solveig --cov-report=term-missing -v
```

### Full CI Command

```bash
# Run everything at once (what CI runs)
black . && ruff check . && mypy solveig/ --ignore-missing-imports && pytest ./tests/ --cov=solveig --cov-report=term-missing -vv
```

## Testing

### Test Structure

- `tests/unit/` - Unit tests for individual components
- `tests/integration/` - Integration tests (requirements)
- `tests/system/` - Full end-to-end tests (mocks LLM client and CLI interface)
- `tests/plugins/` - Tests specifically for plugins
- `tests/mocks/` - Mock utilities and test helpers

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/ -v

# Integration tests only  
pytest tests/integration/ -v

# With coverage
pytest --cov=solveig --cov-report=term-missing
```

### Test Safety

Solveig's test suite involved a lot of effort to achieve a high coverage with multiple scenarios, while
mostly not touching the user's system unless absolutely necessary.

- **Blocked Side-effects** - tests are blocked from using files, running commands or doing any kind of I/O 
unless the test explicitly allows it. This explicit marking ensures it's always easy to find potentially
dangerous tests.
- **Mock Interface** - allows easy setup of user inputs and retrieval of outputs.
- **Temporary Directories** - when tests do actual filesystem usage, it is always done using temporary
directories created through the `tempfile` module.

## Plugin Development

Solveig supports two types of plugins:
- **Hook plugins**: Validate or modify existing requirements (see the [shellcheck plugin](/solveig/plugins/hooks/shellcheck.py))
- **Requirement plugins**: Add new LLM capabilities (see the [tree plugin](/solveig/plugins/schema/tree.py))

For detailed plugin development guide, see [Plugins](./plugins.md).
