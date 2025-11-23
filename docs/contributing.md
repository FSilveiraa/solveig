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
- `ruff`, `mypy` for code quality
- `anthropic`, `google-generativeai` for API testing

## Code Quality

### Required Checks

All code submitted to the `main` branch must pass these checks (same as CI):

```bash
# Format code
ruff format .

# Lint code  
ruff check . --fix

# Type checking
mypy solveig/ --ignore-missing-imports

# Run tests with coverage
pytest ./tests/ --cov=solveig --cov-report=term-missing -v
```

### Full CI Command

```bash
# Run everything at once (what CI runs)
ruff format . && ruff check . && mypy solveig/ --ignore-missing-imports && pytest ./tests/ --cov=solveig --cov-report=term-missing -vv
```

## User Interaction Philosophy

Solveig's core design principle is to balance agent autonomy with explicit user control and transparency. This is achieved through a layered UX model for all operations:

### 1. Auto-Approval for Full Autonomy

For operations (file access or command execution) that match pre-configured `auto_allowed_paths` or `auto_execute_commands` patterns, Solveig operates with full autonomy. The operation is executed, and its results (metadata, file content, or command output) are displayed to the user and then sent to the LLM immediately, without any further prompts. This enables a "get it done" workflow for trusted actions.

### 2. Manual Approval for Granular Control

For any operation not covered by auto-approval, the user is always prompted for explicit consent. These prompts offer a spectrum of control:

*   **Simple Yes/No:** For less complex decisions, like sending directory metadata, a straightforward "Yes/No" question is presented.
*   **Multi-Option Choices:** For file reading, users are presented with an initial multi-option choice, allowing them to select their desired depth of interaction:
    *   `Read and send content and metadata` (a "full-throttle" option)
    *   `Read and inspect content first` (an "ever-deeper" option)
    *   `Send metadata only`
    *   `Don't send anything`
*   **Transparency through Display:** Crucially, whenever file content or command output is generated, it is **always** displayed to the user in the interface. This ensures complete transparency, allowing the user to review the information before making any decisions about sending it to the LLM.
*   **Secondary Confirmation:** For "ever-deeper" options like "Read and inspect content first," a secondary prompt is presented *after* the content has been displayed. This provides an additional layer of user review and control before the information is shared with the LLM.

This layered approach ensures that Solveig remains a powerful, yet fully user-controlled, system assistant, always prioritizing user awareness and consent.

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

### Testing Philosophy and Safety

Solveig's test suite is built on a **"mock by default"** principle to ensure tests are fast, deterministic, and safe. By default, all external side effects (filesystem operations, subprocess creation) are blocked.

#### Unit Tests (`tests/unit/`)
- **Purpose**: Test a single component in complete isolation.
- **Implementation**: These tests rely on the default mocks. They should be fast and should not have any special `pytest` markers to disable mocks.

#### Integration Tests (`tests/integration/`)
- **Purpose**: Test how multiple components work together (e.g., running a real command).
- **Implementation**: To write an integration test, you must explicitly disable the default mocks using "escape hatch" markers.
  - **`@pytest.mark.no_subprocess_mocking`**: Allows real `asyncio` subprocesses to be created.
  - **`@pytest.mark.no_file_mocking`**: Allows real files to be opened.
- **Sandboxing is Mandatory**: Any integration test that performs side effects **must** be sandboxed.
  - For filesystem tests, use the `tmp_path` fixture to ensure all I/O is contained in a temporary directory.
  - For shell command tests, use the `sandboxed_shell` fixture, which provides a shell instance already operating inside a temporary directory.

#### The "No-Patch" Rule for Integration Tests
A key principle is to **avoid `unittest.mock.patch` in integration tests**. Instead of patching code to simulate a state, use the application's own logic to achieve it. For example, to test commands in a specific directory, use the `sandboxed_shell` fixture, which runs a real `cd` command, rather than patching `os.chdir`.

#### Key Fixtures for Testing
- **`clean_shell_state` (`autouse`)**: Automatically runs after every test to destroy the persistent shell, guaranteeing test isolation.
- **`sandboxed_shell`**: Provides a clean, ready-to-use shell that is already sandboxed in a temporary directory. This is the preferred way to write command integration tests.

### Writing Tests

#### Unit Tests
Unit tests focus on a single class or function in isolation. They should be fast and test only the component's internal logic. They must not perform any real I/O.

```python
# In tests/unit/test_my_component.py

# No markers needed. The default fixtures will mock subprocesses and files.
def test_my_component_logic(mock_asyncio_subprocess):
    # ... test logic that relies on the mocked subprocess ...
    result = my_component.do_something()
    assert result is True
    mock_asyncio_subprocess.exec.assert_called_once()
```

#### Integration Tests
Integration tests check the interaction between components (e.g., testing that a command correctly interacts with the real shell). To write an integration test, you must explicitly disable the default mocks using markers.

- **Use Markers to Opt-Out**: Mark your test with `@pytest.mark.no_file_mocking` or `@pytest.mark.no_subprocess_mocking` to disable the corresponding mock and allow real side effects.
- **Use Sandboxes**: When performing real I/O, always use `pytest`'s built-in `tmp_path` fixture to ensure all operations are contained within a safe, temporary directory that is automatically cleaned up.

```python
# In tests/integration/test_my_integration.py
import pytest

@pytest.mark.no_subprocess_mocking # Allow real subprocesses
@pytest.mark.no_file_mocking     # Allow real file I/O
def test_real_command_in_temp_dir(tmp_path):
    # This test runs a real command inside a temporary directory.
    # 'tmp_path' is a pathlib.Path object provided by pytest.
    
    # 1. Change directory to the safe, temporary path
    os.chdir(tmp_path)

    # 2. Run a real command
    result = await persistent_shell.run("touch new_file.txt")

    # 3. Assert on the real state of the filesystem
    assert (tmp_path / "new_file.txt").exists()
```

### Key Pytest Markers
- `@pytest.mark.anyio`: Required for any `async` test function. For convenience, you can apply this to a whole file by adding `pytestmark = pytest.mark.anyio` at the module level.
- `@pytest.mark.no_file_mocking`: Disables the `open()` mock, allowing real file I/O. **Must be used with `tmp_path`**.
- `@pytest.mark.no_subprocess_mocking`: Disables the `asyncio` subprocess mocks, allowing tests to create real processes.

## Plugin Development

Solveig supports two types of plugins:
- **Hook plugins**: Validate or modify existing requirements (see the [shellcheck plugin](/solveig/plugins/hooks/shellcheck.py))
- **Requirement plugins**: Add new LLM capabilities (see the [tree plugin](/solveig/plugins/schema/tree.py))

For detailed plugin development guide, see [Plugins](./plugins.md).


## Notes

- Solveig uses a Textual CLI that turns your terminal into a very rich display that usually doesn't work well
with most IDE's runners and debuggers. In Pycharm, you have to enable `Run/Debug Configurations -> Modify
Options -> Emulate terminal in output console` for all configurations (add it to the template).
