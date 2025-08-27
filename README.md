
# Solveig

[![PyPI](https://img.shields.io/pypi/v/solveig)](https://pypi.org/project/solveig)
[![CI](https://github.com/FranciscoSilveira/solveig/workflows/CI/badge.svg)](https://github.com/FranciscoSilveira/solveig/actions)
[![codecov](https://codecov.io/gh/FranciscoSilveira/solveig/branch/main/graph/badge.svg)](https://codecov.io/gh/FranciscoSilveira/solveig)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

![demo](solveig-demo.gif)

**A safe bridge between AI assistants and your computer.**

Solveig transforms any LLM into a practical assistant that can read files and run commands—with your explicit approval for every operation. No more copying and pasting between your terminal and ChatGPT.

🔒 **Safe** • 160+ tests with 83% coverage • Secure file API • Command validation  
🚀 **Useful** • Works with any OpenAI-compatible API • Handles real tasks efficiently  
🧩 **Extensible** • Drop-in plugin system • Easy to customize and extend

---

## 🚀 Quick start


```bash
# Install from source:
git clone https://github.com/FranciscoSilveira/solveig.git
cd solveig
pip install -e .

# Or install from PyPI:
pip install solveig

# Run a local model:
solveig -u "http://localhost:5001/v1" "Tell me a joke"

# Run from a remote API like OpenRouter:
solveig -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free" "Summarize my day"
```

---

<a href="https://vshymanskyy.github.io/StandWithUkraine">
	<img src="https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg">
</a>

---

## ❓ FAQ


### What is Solveig?

A terminal AI helper that can request file access and run commands with your explicit approval.

### Is Solveig an LLM like ChatGPT?

No, it's a safe interface between LLM services and your computer. It can use ChatGPT, Claude, or any OpenAI-compatible service.

### Why use Solveig instead of a plain LLM?

LLMs can only work with what you manually provide. If ChatGPT needs a file or command output, you have to copy-paste it yourself. Solveig lets the LLM request exactly what it needs, and you just approve or deny each request.

### Why use Solveig over other LLM‑to‑shell assistants?

Solveig focuses on preventing dangerous operations through explicit user consent and validation. It prefers direct file access over arbitrary commands when possible, and validates commands with Shellcheck before execution.

### Is Solveig safe to run?

Solveig requires your approval for every file read, write, or command execution. It uses Shellcheck to validate commands and catch dangerous patterns. However, you're ultimately responsible for reviewing and denying any request you don't understand.

This is still a tool that connects an AI to your computer - always review what it wants to do.

---

## 🎭 Examples

These were obtained with [Kimi K2](https://openrouter.ai/moonshotai/kimi-k2) on OpenRouter.

*click to expand:*

<details>
<summary><b>Do any of the files in ~/Sync look dangerous?</b></summary>

```
─── User ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
Reply:
 > Do any of the files in ~/Sync look dangerous?

⠇ Waiting... (Ctrl+C to stop)

─── Assistant ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
❝  I'll check the contents of your ~/Sync directory to identify any potentially dangerous files. Let me start by reading the directory structure and then examine the files within.
[ Requirements (1) ]
  [ Read (1) ]
    ❝  First, let me read the ~/Sync directory to see what files are present
    🗁  ~/Sync  (/home/francisco/Sync)

─── User ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
[ Results (1) ]
  [ Read ]
    ❝  First, let me read the ~/Sync directory to see what files are present
    🗁  ~/Sync  (/home/francisco/Sync)
    ┌─── Metadata ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
    │ 🗁 /home/francisco/Sync | owner_name=francisco | group_name=francisco | path=/home/francisco/Sync | size=4096 | modified_time=Wed ... │
    │ ├─🗁 d1                                                                                                                               │
    │ ├─🗎 dev.sh                                                                                                                           │
    │ ├─🗎 f1                                                                                                                               │
    │ ├─🗎 hello.py                                                                                                                         │
    │ ├─🗎 j1.json                                                                                                                          │
    │ ├─🗎 run.sh.bak                                                                                                                       │
    │ └─🗎 stuff.txt                                                                                                                        │
    └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
    ?  Allow sending metadata? [y/N]: y
  
?  >  

⠏ Waiting... (Ctrl+C to stop)

─── Assistant ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
❝  I can see several files in your ~/Sync directory. Let me examine the contents of the potentially executable files (shell scripts and Python files) to check if they contain any dangerous commands.
[ Requirements (3) ]
  [ Read (3) ]
    ❝  Checking the dev.sh shell script for potentially dangerous commands
    🗎  ~/Sync/dev.sh  (/home/francisco/Sync/dev.sh)
    ❝  Checking the hello.py Python script for potentially dangerous code
    🗎  ~/Sync/hello.py  (/home/francisco/Sync/hello.py)
    ❝  Checking the run.sh.bak backup shell script for potentially dangerous commands
    🗎  ~/Sync/run.sh.bak  (/home/francisco/Sync/run.sh.bak)

```
</details>

---

## 🧩 Plugins

Solveig has an extensible plugin system that automatically discovers and loads plugins on startup.

**Plugin Types:**
1. **Hook into requirements**: Use `@before()` or `@after()` decorators to validate or process existing requirements (file/command operations)
2. **Schema extensions**: Create new requirement types that the LLM can request by extending `Requirement` and implementing `_actually_solve()`
3. **Plugin tests**: Add comprehensive test suites in `tests/plugins/test_my_plugin.py`

**Adding a hook plugin:**
1. Create a file in `solveig/plugins/hooks/my_plugin.py` 
2. Use decorators: `@before(requirements=(CommandRequirement,))`, `@after()`, both, or neither
3. Add tests in `tests/plugins/test_my_plugin.py` following the existing patterns
4. Plugins auto-load when Solveig starts - no configuration needed!

Check out `solveig/plugins/hooks/shellcheck.py` and `tests/plugins/test_shellcheck.py` for complete examples.


### Examples:

*click to expand:*

<details>
<summary><b>Block dangerous commands with custom patterns</b></summary>

```python
from solveig.config import SolveigConfig
from solveig.plugins.hooks import before
from solveig.plugins.exceptions import SecurityError
from solveig.schema.requirement import CommandRequirement

@before(requirements=(CommandRequirement,))
def block_dangerous_commands(config: SolveigConfig, requirement: CommandRequirement):
    """Block commands that could be dangerous to system security."""
    dangerous_patterns = [
        "sudo chmod 777",
        "wget http://",  # Block HTTP downloads
        "curl http://",
        "dd if=",        # Block disk operations
    ]
    
    for pattern in dangerous_patterns:
        if pattern in requirement.command:
            raise SecurityError(f"Blocked dangerous command pattern: {pattern}")
```
</details>

<details>
<summary><b>Anonymize all paths before sending to LLM</b></summary>

```python
import re

from solveig.config import SolveigConfig
from solveig.plugins.hooks import after
from solveig.plugins.exceptions import ProcessingError
from solveig.schema.requirement import ReadRequirement, WriteRequirement
from solveig.schema.result import ReadResult, WriteResult

@after(requirements=(ReadRequirement, WriteRequirement))
def anonymize_paths(config: SolveigConfig, requirement: ReadRequirement|WriteRequirement, result: ReadResult|WriteResult):
    """Anonymize file paths in results before sending to LLM."""
    try:
        original_path = result.metadata['path']
    except:
        return
    anonymous_path = re.sub(r"/home/\w+", "/home/jdoe", original_path)
    anonymous_path = re.sub(r"^([A-Z]:\\Users\\)[^\\]+", r"\1JohnDoe", anonymous_path, flags=re.IGNORECASE)
    result.metadata['path'] = anonymous_path
```
</details>

---

## 🤝 Contributing

We use modern Python tooling to maintain code quality and consistency:

### Development Tools

All code is automatically checked on `main` and `develop` branches:
1. **Formatting**: `black .` - Ensures consistent code style
2. **Linting**: `ruff check .` - Catches potential bugs and code quality issues  
3. **Type checking**: `mypy solveig/ scripts/ --ignore-missing-imports` - Validates type hints
4. **Testing**: `pytest` - Runs full test suite with coverage reporting

### Testing Philosophy

Solveig follows **strict testing guidelines** to ensure reliability and safety:

#### Test Coverage Requirements
- **Success and failure paths**: Every feature must test both successful execution and error conditions
- **Mock only when necessary**: Mock only low-level I/O behavior with potential side effects
- **No untested code paths**: All business logic, error handling, and user interactions must be tested

#### Testing Architecture
**Unit Tests (`tests/unit/`)**:
- Mock all I/O and side-effect operations (file system, user interface, external commands)
- Use **minimal mocking**: Mock only the lowest-level behaviors while keeping high-level logic unmocked
- Mock framework provides utility methods for easy test setup (mock filesystem with directory structure)
- Test real object serialization and business logic with actual Pydantic models

**Integration Tests (`tests/integration/`)**:
- Allow real file I/O operations using temporary directories
- Mock only user interactions to avoid interactive prompts
- Test full stack from requirement parsing to actual file operations
- Marked with `@pytest.mark.no_file_mocking` to bypass file system mocks

**Mocking Strategy**:
- **File operations**: Mock `solveig.utils.file` methods for filesystem interactions
- **User interface**: Mock input/output methods while preserving all display logic and formatting
- **External commands**: Mock subprocess calls and command execution
- **Real objects**: Never mock requirement/result objects - test actual Pydantic serialization

#### Running Tests

```bash
# Install with testing dependencies:
pip install -e .[dev]

# Unit tests only
python -m pytest tests/unit/ -v

# Integration tests only  
python -m pytest tests/integration/ -v

# Specific test class
python -m pytest tests/unit/test_main.py::TestInitializeConversation -v

# Run all checks locally (same as CI) 
black . && ruff check . && mypy solveig/ scripts/ --ignore-missing-imports && pytest ./tests/ --cov=solveig --cov=scripts --cov-report=term-missing -vv
```

#### Test Organization
```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
├── mocks/          # Mock implementations
└── plugins/        # Plugin-specific tests
```

---

## 📈 Roadmap

**Next Steps:**
- Enhanced command validation with Semgrep static analysis  
- Second-opinion LLM validation for generated commands
- Improve test coverage
- API integration for Claude/Gemini
