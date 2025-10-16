# Solveig

**An AI assistant that enables secure and extensible agentic behavior from any LLM in your terminal**

[![Demo GIF](https://asciinema.org/a/eAGrytKnT5Wh6NlzuFnRtTINo.svg)](https://asciinema.org/a/eAGrytKnT5Wh6NlzuFnRtTINo)

[![PyPI](https://img.shields.io/pypi/v/solveig)](https://pypi.org/project/solveig)
[![CI](https://github.com/Fsilveiraa/solveig/workflows/CI/badge.svg)](https://github.com/Fsilveiraa/solveig/actions)
[![codecov](https://codecov.io/gh/Fsilveiraa/solveig/branch/main/graph/badge.svg)](https://codecov.io/gh/Fsilveiraa/solveig)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

<p align="center">
    <span style="font-size: 1.17em; font-weight: bold;">
        <a href="./docs/about.md#features-and-principles">Features</a> &nbsp;|&nbsp;
        <a href="./docs/about.md#faq">FAQ</a> &nbsp;|&nbsp;
        <a href="./docs/usage.md">Usage</a> &nbsp;|&nbsp;
        <a href="./docs/plugins.md">Plugins</a> &nbsp;|&nbsp;
        <a href="./docs/themes/themes.md">Themes</a> &nbsp;|&nbsp;
        <a href="https://github.com/FSilveiraa/solveig/discussions/2">Roadmap</a> &nbsp;|&nbsp;
        <a href="./docs/contributing.md">Contributing</a>
    </span>
</p>

---

## Quick Start

### Installation

```bash
# Core installation (OpenAI + local models)
pip install solveig

# With support for Claude and Gemini APIs
pip install solveig[all]
```

### Running

```bash
# Run with a local model
solveig -u "http://localhost:5001/v1" "Create a demo BlackSheep webapp"

# Run from a remote API like OpenRouter
solveig -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free"
```

---

## Features

🤖 **AI Terminal Assistant** - Automate file management, code analysis, project setup, and system tasks using
natural language in your terminal.

🛡️ **Safe by Design** - Granular consent controls with pattern-based permissions and file operations
prioritized over shell commands.

🔌 **Plugin Architecture** - Extend capabilities through drop-in Python plugins. Add SQL queries, web scraping,
or custom workflows with 100 lines of Python.

📋 **Modern CLI** - Clear interface with plan tracking, task listing, file and metadata previews, diff view,
code linting, waiting animations and rich tree displays for informed user decisions.

🌐 **Provider Independence** - Works with OpenAI, Claude, Gemini, local models, or any OpenAI-compatible API.

---

## Documentation

- **[About & Comparisons](./docs/about.md)** - Detailed features, FAQ and how Solveig compares to alternatives
- **[Usage Guide](./docs/usage.md)** - Configuration options, examples, and advanced features
- **[Themes](./docs/themes/themes.md)** - Themes explained, visual examples
- **[Plugin Development](./docs/plugins.md)** - How to create and configure custom plugins
- **[Roadmap](https://github.com/FSilveiraa/solveig/discussions/2)** - Upcoming features
- **[Contributing](./docs/contributing.md)** - Development setup, testing, and contribution guidelines

---

<a href="https://vshymanskyy.github.io/StandWithUkraine">
	<img src="https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg">
</a>
