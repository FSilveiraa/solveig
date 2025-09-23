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

All code must pass these checks (same as CI):

```bash
# Format code
black .

# Lint code  
ruff check . --fix

# Type checking
mypy solveig/ scripts/ --ignore-missing-imports

# Run tests with coverage
pytest ./tests/ --cov=solveig --cov=scripts --cov-report=term-missing -v
```

### Full CI Command

```bash
# Run everything at once (what CI runs)
black . && ruff check . && mypy solveig/ scripts/ --ignore-missing-imports && pytest ./tests/ --cov=solveig --cov=scripts --cov-report=term-missing -vv
```

## Testing

### Test Structure

- `tests/unit/` - Unit tests with full mocking (fast, safe)
- `tests/integration/` - Integration tests with real filesystem (slower)
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

- **Unit tests**: Automatically mock file I/O, subprocess, user input
- **Integration tests**: Use real files (in temp directories) but mock user interaction
- Tests are safe to run - they won't modify your system

## Plugin Development

Solveig supports two types of plugins:
- **Hook plugins**: Validate or modify existing requirements (see the [shellcheck plugin](/solveig/plugins/hooks/shellcheck.py))
- **Requirement plugins**: Add new LLM capabilities (see the [tree plugin](/solveig/plugins/schema/tree.py))

For detailed plugin development guide, see [Plugins](./plugins.md).
