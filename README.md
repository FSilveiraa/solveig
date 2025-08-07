
# Solveig

[![PyPI](https://img.shields.io/pypi/v/solveig)](https://pypi.org/project/solveig)
[![CI](https://github.com/FranciscoSilveira/solveig/workflows/CI/badge.svg)](https://github.com/FranciscoSilveira/solveig/actions)
[![codecov](https://codecov.io/gh/FranciscoSilveira/solveig/branch/main/graph/badge.svg)](https://codecov.io/gh/FranciscoSilveira/solveig)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[![asciicast](https://asciinema.org/a/XaPr7wtGuZIMTDAoZZAJBm8K1.svg)](https://asciinema.org/a/XaPr7wtGuZIMTDAoZZAJBm8K1)

**A safe bridge between AI assistants and your computer.**

Solveig lets LLMs read files and run commands with explicit user approval for every operation.

* **Explicit consent** - Review every file or command request before execution
* **Safety validation** - Shellcheck integration prevents dangerous commands
* **Works anywhere** - Any OpenAI-compatible LLM endpoint (OpenRouter, local models)
* **Simple setup** - Modern Python CLI with comprehensive testing

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
<summary><b>Ask for the time in different timezones</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > What time is it?
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I can tell you the current time by checking the system clock. Let me run the date command to get the current time and date.

[ Requirements (1) ]
  Commands:
    date

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (1) ]
  [ Command ]
    comment: "Run the date command to display the current system time and date"
    command: date
    ? Allow running command? [y/N]: y
    [ Output ]
      Tue Jul 22 01:24:40 AM EEST 2025
    ? Allow sending output? [y/N]: y

Reply:
 > Here you go. By the way, what's the conversion to Hong Kong?
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
The system shows 01:24 AM EEST (Eastern European Summer Time). Hong Kong is 5 hours ahead of EEST, so the time in Hong Kong is 06:24 AM HKT.

```
</details>

<details>
<summary><b>Does this file look dangerous?</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > I don't recognize the file ~/run.sh, is it dangerous?
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I need to examine the ~/run.sh file to determine if it's dangerous. Let me check its contents and metadata to see what it does.

[ Requirements (1) ]
  Read:
    ~/run.sh (content)

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (1) ]
  [ Read ]
    comment: "I need to read the contents of ~/run.sh to analyze what commands it contains and determine if it could be harmful"
    path: ~/run.sh (file)
    ? Allow reading file? [y=content+metadata / m=metadata / N=skip]: y
    [ Metadata ]
      {"path": "/home/francisco/run.sh", "size": 1 (...) 01, "mtime": "Thu Jul 17 02:54:43 2025", "is_directory": false, "owner": "francisco", "group": "francisco"}
    [ Content ]
      (Base64)
    ? Allow sending file content and metadata? [y/N]: y

Reply:
 > 
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
The ~/run.sh file appears to be safe. It's a simple initialization script that creates directories for logs and tmp files, creates an empty log file, and sets up a flag file indicating the project has been initialized. The commands are all basic file operations (mkdir, touch, echo) and don't contain any suspicious or dangerous operations.

```
</details>

<details>
<summary><b>Create a Dockerized FastAPI example project</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > Create a Dockerized FastAPI example project in ~/my_app/
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I'll create a Dockerized FastAPI example project in ~/my_app/. This will include the FastAPI application code, requirements, Dockerfile, and docker-compose configuration.

[ Requirements (6) ]

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (6) ]
  [ Write ]
    comment: "Create the main project directory ~/my_app/"
    path: ~/my_app/ (directory)
    ! Warning: this path already exists !
  [ Write ]
    comment: "Create the FastAPI main application file"
    path: ~/my_app/main.py (file)
      [ Content ]
        from fastapi import FastAPI
        from p (...) ydantic import BaseModel
        
         (...) 
        @app.get("/health")
        async def health_check():
            return {"status": "healthy"}
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create requirements.txt with FastAPI dependencies"
    path: ~/my_app/requirements.txt (file)
      [ Content ]
        fastapi==0.104.1
        uvicorn[standard]==0.24.0
        pydantic==2.5.0
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create Dockerfile for containerizing the FastAPI app"
    path: ~/my_app/Dockerfile (file)
      [ Content ]
        FROM python:3.11-slim
        
        WOR (...) KDIR /app
         (...) 
        EXPOSE 8000
        
        CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create docker-compose.yml for easy development"
    path: ~/my_app/docker-compose.yml (file)
      [ Content ]
        version: '3.8'
        
        services:
 (...)          (...) 
        
        # volumes:
        #   postgres_data:
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create .dockerignore file to optimize build context"
    path: ~/my_app/.dockerignore (file)
      [ Content ]
        __pycache__
        *.pyc
        *.pyo
   (...)        (...) 
        README.md
        .env
        .venv
    ? Allow writing file and contents? [y/N]: y

Reply:
 > 

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

### Running tests and checks

```bash
# Install with testing dependencies:
pip install -e .[dev]

# Unit tests only
python -m pytest tests/unit/ -v

# Specific test class
python -m pytest tests/unit/test_main.py::TestInitializeConversation -v

# Run all checks locally (same as CI)
black . && ruff check . && mypy solveig/ scripts/ --ignore-missing-imports && pytest ./tests/ --cov=solveig --cov=scripts --cov-report=term-missing -vv
```

---

## 📈 Roadmap

**Next Steps:**
- Enhanced command validation with Semgrep static analysis  
- Second-opinion LLM validation for generated commands
- Improve test coverage
- API integration for Claude/Gemini
