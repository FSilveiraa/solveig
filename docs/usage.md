# Usage Guide

## Installation

### PyPI Installation (Recommended)

```bash
pip install solveig
```

### Development Installation

```bash
git clone https://github.com/franciscobizi/solveig.git
cd solveig
pip install -r schema.txt
```

## Quick Start

### Basic Usage

```bash
# Using a local model
solveig -u "http://localhost:5001/v1" "Tell me about this directory"

# Using OpenRouter with API key
solveig -u "https://openrouter.ai/api/v1" -k "sk-your-api-key" -m "anthropic/claude-3.5-sonnet" "Help me refactor this code"

# Using a config file
solveig -c ~/.config/solveig.json "What files are taking up the most space?"
```

### Configuration File

Create a configuration file at `~/.config/solveig.json`:

```json
{
  "url": "https://openrouter.ai/api/v1",
  "api_key": "sk-your-api-key",
  "model": "anthropic/claude-3.5-sonnet",
  "temperature": 0.1,
  "verbose": false,
  "auto_allowed_paths": ["~/Documents/projects/**/*.py"],
  "auto_execute_commands": ["^ls\\s*.*$", "^git status$"]
}
```

## Configuration Options

### Connection Settings

| Option | CLI Flag | Description | Default |
|--------|----------|-------------|---------|
| `url` | `-u, --url` | LLM endpoint URL | `http://localhost:5001/v1/` |
| `api_type` | `-a, --api-type` | API provider (openai, local, anthropic, gemini) | `local` |
| `api_key` | `-k, --api-key` | API key for remote services | `null` |
| `model` | `-m, --model` | Model name/path | `null` |
| `encoder` | `-e, --encoder` | Model encoder for token counting | Uses `model` value |
| `temperature` | `-t, --temperature` | Model temperature | `0` |
| `max_context` | `--max-context` | Maximum context length in tokens | `-1` (no limit) |

### Safety & Security

| Option | CLI Flag | Description | Default |
|--------|----------|-------------|---------|
| `allow_commands` | `--no-commands` | Disable command execution entirely | `true` |
| `auto_allowed_paths` | `--auto-allowed-paths` | Glob patterns for auto-approved file operations | `[]` |
| `auto_execute_commands` | `--auto-execute-commands` | Regex patterns for auto-approved commands | `[]` |
| `auto_send` | `--auto-send` | Auto-send results without asking | `false` |

### Interface & Display

| Option | CLI Flag | Description | Default |
|--------|----------|-------------|---------|
| `verbose` | `-v, --verbose` | Enable verbose logging | `false` |
| `add_examples` | `--add-examples, --ex` | Include examples in system prompt | `false` |
| `add_os_info` | `--add-os-info, --os` | Include OS info in system prompt | `false` |
| `exclude_username` | `--exclude-username, --no-user` | Exclude username from OS info | `false` |
| `max_output_lines` | `-l, --max-output-lines` | Max lines of output to display | `6` |
| `max_output_size` | `-s, --max-output-size` | Max characters of output to display | `100` |

### System Resources

| Option | CLI Flag | Description | Default |
|--------|----------|-------------|---------|
| `min_disk_space_left` | `-d, --min-disk-space-left` | Minimum disk space required | `1GiB` |

## Security Modes

### No-Commands Mode

Disable command execution entirely for maximum security:

```bash
solveig --no-commands "Analyze this codebase structure"
```

In this mode, Solveig can only perform file operations (read, write, copy, move, delete) and cannot execute shell commands.

### Auto-Approval Patterns

#### File Operations

Auto-approve file operations matching glob patterns:

```bash
# Auto-approve operations on Python files in projects directory
solveig --auto-allowed-paths "~/Documents/projects/**/*.py" "Refactor this function"

# Multiple patterns
solveig --auto-allowed-paths "~/src/**/*.js" "~/tests/**/*.py" "Update the tests"
```

**Warning**: Use with caution. These patterns bypass user consent for file operations.

#### Command Execution

Auto-approve commands matching regex patterns:

```bash
# Auto-approve safe read-only commands
solveig --auto-execute-commands "^ls\\s*.*$" "^git status$" "^pwd$" "Show me the repository status"
```

**Warning**: Use with extreme caution. These patterns allow automatic command execution.

## API Providers

### Local Models

```bash
# Ollama (default port)
solveig -u "http://localhost:11434/v1" -m "llama3.2" "Your prompt"

# LM Studio
solveig -u "http://localhost:1234/v1" -m "local-model" "Your prompt"

# Custom local server
solveig -u "http://localhost:5001/v1" "Your prompt"
```

### OpenAI

```bash
solveig -a openai -k "sk-your-openai-key" -m "gpt-4" "Your prompt"
```

### Anthropic (Claude)

```bash
solveig -a anthropic -k "sk-ant-your-key" -m "claude-3-5-sonnet-20241022" "Your prompt"
```

### Google Gemini

```bash
solveig -a gemini -k "your-gemini-key" -m "gemini-1.5-pro" "Your prompt"
```

### OpenRouter (Multiple Providers)

```bash
solveig -u "https://openrouter.ai/api/v1" -k "sk-or-your-key" -m "anthropic/claude-3.5-sonnet" "Your prompt"
```

## Advanced Usage

### Configuration Precedence

Configuration is loaded in this order (later values override earlier ones):

1. Default values
2. Configuration file (`~/.config/solveig.json` or specified with `-c`)
3. Command-line arguments

### Environment Variables

While not directly supported, you can use shell environment variables in your commands:

```bash
solveig -k "$OPENAI_API_KEY" -m "gpt-4" "Your prompt"
```

### Plugin Configuration

Configure plugins through the `plugins` section in your config file:

```json
{
  "plugins": {
    "shellcheck": {
      "enabled": true,
      "severity": "warning"
    }
  }
}
```

### Token Counting

Solveig automatically counts tokens for context management. You can specify a different encoder:

```bash
# Use gpt-4 encoder even with a different model
solveig -m "custom-model" -e "gpt-4" "Your prompt"
```

## Safety Guidelines

1. **Review all operations**: Always read what Solveig plans to do before approving
2. **Use no-commands mode**: For maximum safety, disable commands with `--no-commands`
3. **Limit auto-approval**: Be very conservative with `--auto-allowed-paths` and `--auto-execute-commands`
4. **Test configurations**: Try new configurations on non-critical directories first
5. **Regular backups**: Maintain backups of important files when using write operations

## Common Examples

### Code Review

```bash
solveig --add-os-info "Review this Python project for potential issues"
```

### Safe File Analysis

```bash
solveig --no-commands "Analyze the structure of this project and suggest improvements"
```

### Development Workflow

```bash
solveig --auto-allowed-paths "$(pwd)/**/*" --auto-execute-commands "^git status$" "Help me commit these changes with a good message"
```

### Documentation Generation

```bash
solveig --no-commands --auto-allowed-paths "$(pwd)/docs/**/*.md" "Update the documentation to reflect recent changes"
```