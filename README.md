# Solveig

**A CLI bridge that enables safe, extensible agentic behavior from any model on your computer**

![Demo GIF](./docs/demo.gif)

[![PyPI](https://img.shields.io/pypi/v/solveig)](https://pypi.org/project/solveig)
[![CI](https://github.com/FranciscoSilveira/solveig/workflows/CI/badge.svg)](https://github.com/FranciscoSilveira/solveig/actions)
[![codecov](https://codecov.io/gh/FranciscoSilveira/solveig/branch/main/graph/badge.svg)](https://codecov.io/gh/FranciscoSilveira/solveig)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Installation

```bash
pip install solveig
```

## Quick Start

```bash
# Run with a local model
solveig -u "http://localhost:5001/v1" "Create a demo BlackSheep webapp"

# Run from a remote API like OpenRouter
solveig -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free" "Refactor test_database.py to be more concise"
```

---

## Key Features

📂 **Files and Commands** - Rich File API that prioritizes safe filesystem access, while also offering full shell capability  
🛡️ **Granular Permissions** - Safe defaults with explicit user consent. Supports granular configuration using patterns  
🔌 **Plugins** - Extensible requirement system for custom AI capabilities through simple drop-in plugins. Add an AI SQL query runner with 100 lines of Python  
📋 **Clear Interface** - Clear progress tracking and content display that inform user consent and choices  
🌐 **Provider Agnostic** - Works with any OpenAI-compatible API including local models, Claude and Gemini

---

## Documentation

- **[Usage Guide](./docs/usage.md)** - Configuration options, examples, and advanced features
- **[Plugin Development](./docs/plugins.md)** - How to create and configure custom plugins
- **[About & Comparisons](./docs/about.md)** - Detailed features and how Solveig compares to alternatives
- **[Contributing](./docs/contributing.md)** - Development setup, testing, and contribution guidelines

---

<a href="https://vshymanskyy.github.io/StandWithUkraine">
	<img src="https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg">
</a>
