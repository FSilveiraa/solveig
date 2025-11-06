[![PyPI](https://img.shields.io/pypi/v/solveig)](https://pypi.org/project/solveig) &nbsp;
[![CI](https://github.com/Fsilveiraa/solveig/workflows/CI/badge.svg)](https://github.com/Fsilveiraa/solveig/actions) &nbsp;
[![codecov](https://codecov.io/gh/Fsilveiraa/solveig/branch/main/graph/badge.svg)](https://codecov.io/gh/Fsilveiraa/solveig) &nbsp;
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/) &nbsp;
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://docs.astral.sh/ruff/)  &nbsp;
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0) &nbsp;

---

# Solveig

**An AI assistant that brings safe agentic behavior from any LLM to your terminal**

[![Demo](https://asciinema.org/a/p5mzDGAoHTUHNEaVeROHpFibx.svg)](https://asciinema.org/a/p5mzDGAoHTUHNEaVeROHpFibx)

#### *You can also see the Demo in video format [here](https://fsilveiraa.github.io/solveig/demo.mp4)*

---

<p align="center">
    <span style="font-size: 1.17em; font-weight: bold;">
        <a href="./docs/about.md">About</a> &nbsp;&nbsp;|&nbsp;&nbsp;
        <a href="./docs/usage.md">Usage</a> &nbsp;&nbsp;|&nbsp;&nbsp;
        <a href="./docs/comparison.md">Comparison</a> &nbsp;&nbsp;|&nbsp;&nbsp;
        <a href="./docs/themes/themes.md">Themes</a> &nbsp;&nbsp;|&nbsp;&nbsp;
        <a href="./docs/plugins.md">Plugins</a> &nbsp;&nbsp;|&nbsp;&nbsp;
        <a href="https://github.com/FSilveiraa/solveig/discussions/2">Roadmap</a> &nbsp;&nbsp;|&nbsp;&nbsp;
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

📋 **Modern CLI** - Clear interface with task planning, file and metadata previews, diff editing,
usage stats, code linting, waiting animations and directory tree displays for informed user decisions.

🌐 **Provider Independence**  - Works with any OpenAI-compatible API, including local models.

---

## Documentation

- **[About](./docs/about.md)** - Detailed features and FAQ
- **[Usage](./docs/usage.md)** - Config files, CLI flags, sub-commands, usage examples and more advanced features
- **[Comparison](./docs/comparison.md)** - Detailed comparison to alternatives in the same market space
- **[Themes](./docs/themes/themes.md)** - Themes explained, visual examples
- **[Plugins](./docs/plugins.md)** - How to use, configure and develop plugins
- **[Roadmap](https://github.com/FSilveiraa/solveig/discussions/2)** - Upcoming features and general progress tracking
- **[Contributing](./docs/contributing.md)** - Development setup, testing, and contribution guidelines

---

<a href="https://vshymanskyy.github.io/StandWithUkraine">
	<img alt="Support Ukraine: https://stand-with-ukraine.pp.ua/" src="https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg">
</a>
