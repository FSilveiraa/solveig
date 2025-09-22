# Solveig

**AI agent framework with human oversight and extensible plugin architecture**

![Demo GIF](./docs/demo.gif)

Solveig is a safety-first AI agent that combines powerful file operations, command execution, and plugin extensibility with granular permission controls. Unlike other AI tools, Solveig puts you in control with transparent task tracking and configurable safety boundaries.

## Installation

```bash
pip install solveig
```

## Quick Start

```bash
# Run with a local model
solveig -u "http://localhost:5001/v1" "Tell me a joke"

# Run from a remote API like OpenRouter
solveig -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free" "Summarize my day"

# Use with OpenAI
solveig -k "<OPENAI_API_KEY>" "Help me organize my project files"
```

## Key Features

📂 **Files and Commands** - Rich File API that prioritizes safe filesystem access, while also offering full shell capability  
🛡️ **Granular Permissions** - Safe defaults with explicit user consent. Supports granular configuration using patterns  
🔌 **Plugins** - Extensible requirement system for custom AI capabilities through simple drop-in plugins. Add an AI SQL query runner with 100 lines of Python  
📋 **Clear Interface** - Clear progress tracking and content display that inform user consent and choices  
🌐 **Provider Agnostic** - Works with any OpenAI-compatible API including local models, Claude and Gemini

## Documentation

- **[Usage Guide](./docs/usage.md)** - Configuration options, examples, and advanced features
- **[Plugin Development](./docs/plugins.md)** - How to create and configure custom plugins
- **[About & Comparisons](./docs/about.md)** - Detailed features and how Solveig compares to alternatives
- **[Contributing](./docs/contributing.md)** - Development setup, testing, and contribution guidelines

## License

[Your License Here]

---

*Built with safety, extensibility, and developer experience in mind.*