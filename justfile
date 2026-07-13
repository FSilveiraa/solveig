# Run `just --list` to see all available recipes.

# Paths to lint/format: the package plus the mock test infra. The rest of
# tests/ is deliberately excluded (deferred test-restoration debt would
# otherwise fail the suite); typecheck stays solveig/-only below.
src := "solveig/ tests/mocks/"

# Auto-format code (pass extra flags, e.g. `just format --check`)
format *flags:
    ruff format {{src}} {{flags}}

# Lint code (pass extra flags, e.g. `just lint --fix`)
lint *flags:
    ruff check {{src}} {{flags}}

# Static type checking (pass extra flags/paths)
typecheck *flags:
    mypy solveig/ --ignore-missing-imports {{flags}}

# Run the test suite with coverage (pass extra flags/paths, e.g. `just test tests/unit/test_config.py`)
test *flags:
    pytest --cov=solveig --cov-report=term-missing {{flags}}

# Run the full CI suite: format, lint, typecheck, test
ci: format lint typecheck test

# Run the interactive Textual demo with a mock LLM client (optionally replaying a stored session)
mock session="":
    python -m tests.mocks.run_mock {{session}}

# Start the local mock MCP server for manual /mcp connect testing
mcp:
    python tests/mocks/mock_mcp.py
