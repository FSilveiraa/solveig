# Run `just --list` to see all available recipes.

# Paths for lint/format/check: the package plus the mock test infra. The rest
# of tests/ is deliberately excluded (deferred test-restoration debt would
# otherwise fail the suite).
src := "solveig/ tests/mocks/"

# Auto-format code (pass extra flags, e.g. `just format --check`)
format *flags:
    ruff format {{src}} {{flags}}

# Static checks: ruff lint + mypy (both always run; recipe fails if either did)
check *flags:
    #!/usr/bin/env bash
    fail=0
    ruff check {{src}} {{flags}} || fail=1
    mypy {{src}} --ignore-missing-imports || fail=1
    exit $fail

# Run the test suite with coverage (pass extra flags/paths, e.g. `just test tests/unit/test_config.py`)
test *flags:
    pytest --cov=solveig --cov-report=term-missing {{flags}}

# Run the full CI suite: format, static checks (lint + mypy), test
ci: format check test

# Run the interactive Textual demo with a mock LLM client (optionally replaying a stored session)
mock session="":
    python -m tests.mocks.demo {{session}}

# Start the local mock MCP server for manual /mcp connect testing
mcp:
    python tests/mocks/mcp.py
