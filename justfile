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

# Check import layering: a module may only import its own layer or below
import *flags:
    lint-imports {{flags}}

# Run the test suite with coverage (pass extra flags/paths, e.g. `just test tests/unit/test_config.py`)
test *flags:
    pytest --cov=solveig --cov-report=term-missing {{flags}}

# Run the full CI suite: format, static checks (lint + mypy), import layering, test
ci: format check import test

# Interactive Textual shell: you type, a mock LLM client replies with canned turns
mock:
    python -m tests.mocks.demo mock

# Hands-free replay: auto-types a conversation's user messages (sync_review story, or a stored session)
demo session="":
    python -m tests.mocks.demo demo {{session}}

# Start the local mock MCP server for manual /mcp connect testing
mcp:
    python tests/mocks/mcp_server.py

# Force Hermes to re-create podman containers with re-read config
hermes-restart:
    podman rm -f $(podman ps -aq --filter label=hermes-agent=1)
