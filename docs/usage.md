# Usage Guide

## Installation

### PyPI Installation (Recommended)

```bash
# Core installation (OpenAI + local models only)
pip install solveig

# With specific provider support
pip install solveig[anthropic]  # Add Claude support
pip install solveig[google]     # Add Gemini support
pip install solveig[all]        # All providers
```

### Development Installation

```bash
git clone https://github.com/FSilveiraa/solveig.git
cd solveig
pip install -e .[dev]  # Includes all providers for testing
```

## Quick Start

**Note**: Either `--url` or `--api-type` must be specified (via CLI args or config file).

CLI arguments override config file settings. Examples:

```bash
# API type only (uses its default URL)
solveig --api-type local "Your prompt"

# URL only (assumes OpenAI-compatible)  
solveig -u "http://localhost:5001/v1" "Your prompt"

# Config file provides the required settings
solveig "Your prompt"  # Will throw error if ~/.config/solveig.json does not have `url` or `api_type`
```

### User Prompt

You can start solveig with an initial prompt that is immediately sent to the assistant,
otherwise you will be prompted for one:

```bash
# Provided initial prompt using API type
solveig --api-type local "Remove old files from my Downloads directory"

# No initial prompt - solveig will ask you for one
solveig --api-type local
```

### Basic Usage

```bash
# Using a local model with explicit URL and API type
solveig -u "http://localhost:5001/v1" -a "openai" "Tell me about this directory"

# Using OpenRouter with API key
solveig -u "https://openrouter.ai/api/v1" -k "sk-your-api-key" -m "anthropic/claude-3.5-sonnet" "Help me refactor this code"

# Using a config file (must specify url or api_type in config)
solveig -c ~/.config/solveig.json "Which files are taking up the most space?"
```

### Configuration File

Run the `init` script:

```bash
solveig-init
```

Or create a JSON configuration file at `~/.config/solveig.json`:

```json
{
  "api_type": "openai",
  "url": "https://openrouter.ai/api/v1",
  "api_key": "sk-your-api-key",
  "model": "anthropic/claude-3.5-sonnet",
  "temperature": 0.1,
  "verbose": false,
  "auto_allowed_paths": [ "~/Documents/projects/**/*.py" ],
  "auto_execute_commands": [ "^ls\\s*.*$", "^git status$" ]
}
```

## Configuration Options

The CLI args are merged with, and take precedence over, the configuration file -
see [Configuration Precedence](#configuration-precedence) for more.

### CLI-only args

| CLI Flag       | Description          | Default                  |
|----------------|----------------------|--------------------------|
| `-c, --config` | Config file location | `~/.config/solveig.json` |


### Connection

| Option        | CLI Flag            | Description                                                      | Default            |
|---------------|---------------------|------------------------------------------------------------------|--------------------|
| `url`         | `-u, --url`         | LLM endpoint URL (assumes OpenAI-compatible if no `api_type`)    | `""`               |
| `api_type`    | `-a, --api-type`    | API provider (openai, local, anthropic, gemini)                  | -                  |
| `api_key`     | `-k, --api-key`     | API key for remote services                                      | `""`               |
| `model`       | `-m, --model`       | Model name/path                                                  | `null`             |
| `encoder`     | `-e, --encoder`     | Model encoder for token counting                                 | Uses `model` value |
| `temperature` | `-t, --temperature` | Model temperature                                                | `0`                |
| `max_context` | `-s, --max-context` | Maximum context length in tokens                                 | `-1` (no limit)    |

### Security

| Option                  | CLI Flag                  | Description                                     | Default |
|-------------------------|---------------------------|-------------------------------------------------|---------|
| `no_commands`           | `--no-commands`           | Disable command execution entirely              | `false` |
| `auto_allowed_paths`    | `--auto-allowed-paths`    | Glob patterns for auto-approved file operations | `[]`    |
| `auto_execute_commands` | `--auto-execute-commands` | Regex patterns for auto-approved commands       | `[]`    |
| `auto_send`             | `--auto-send`             | Auto-send results without asking                | `false` |

### Interface

| Option             | CLI Flag                        | Description                                                            | Default      |
|--------------------|---------------------------------|------------------------------------------------------------------------|--------------|
| `verbose`          | `-v, --verbose`                 | Enable verbose logging                                                 | `false`      |
| `add_examples`     | `--add-examples, --ex`          | Include examples in system prompt                                      | `false`      |
| `add_os_info`      | `--add-os-info, --os`           | Include OS info in system prompt                                       | `false`      |
| `exclude_username` | `--exclude-username, --no-user` | Exclude username from OS info                                          | `false`      |
| `max_output_lines` | `-l, --max-output-lines`        | Max lines of output to display in a text box                           | `20`         |
| `wait_before_user` | `-w, --wait-before-user`        | Time (seconds) between assistant and user response                     | `1.0`        |
| `theme`            | `--theme`                       | CLI theme to use (`none` to disable, see [Themes](./themes/themes.md)) | `terracotta` |

### System Resources

| Option                | CLI Flag                    | Description                 | Default  |
|-----------------------|-----------------------------|-----------------------------|----------|
| `min_disk_space_left` | `-d, --min-disk-space-left` | Minimum disk space required | `1GiB`   |

## Security Modes

### No-Commands Mode

Disable command execution entirely for maximum security:

```bash
solveig --api-type local --no-commands "Analyze this codebase structure"
```

In this mode, Solveig can only perform file operations (read, write, copy, move, delete).
It's not just that it can't execute shell commands, the Assistant isn't aware of commands as possible resource.

### Auto-Approval Patterns

#### File Operations

Auto-approve file operations matching glob patterns:

```bash
# Auto-approve operations on Python files in projects directory
solveig --api-type local --auto-allowed-paths "~/Documents/projects/**/*.py" "Refactor this function"

# Multiple patterns
solveig --api-type local --auto-allowed-paths "~/src/**/*.js" "~/tests/**/*.py" "Update the tests"
```

**Warning**: Use with caution. These patterns bypass user consent for file operations.

#### Command Execution

Auto-approve commands matching regex patterns:

```bash
# Auto-approve safe read-only commands
solveig --api-type local --auto-execute-commands "^ls\\s*.*$" "^git status$" "^pwd$" "Show me the repository status"
```

**Warning**: Use with extreme caution. These patterns allow automatic command execution.


## API Providers

Solveig itself doesn't force you to specify a model nor does it validate it as a name or path
(e.g. "gpt-5" vs "openai/gpt-5"), however your backend might.
Typically only local backends like Koboldcpp don't enforce it.

**Note**: Anthropic and Google providers require additional packages. Install with `pip install solveig[anthropic]`
or `pip install solveig[google]` respectively.

### Local Models

```bash
# Using api-type (recommended - uses default URL)
solveig --api-type local "Your prompt"

# Koboldcpp with explicit URL
solveig -u "http://localhost:5001/v1" "Your prompt"

# Ollama (default port)
solveig -u "http://localhost:11434/v1" -m "llama3.2" "Your prompt"

# LM Studio  
solveig -u "http://localhost:1234/v1" -m "local-model" "Your prompt"
```

### OpenAI

```bash
solveig -a openai -k "your-openai-key" -m "openai/gpt-5" "Your prompt"
```

### Anthropic (Claude)

```bash
solveig --api-type anthropic -k "your-anthropic-key" -m "claude-3-5-sonnet-20241022" "Your prompt"
```

### Google Gemini

```bash
solveig --api-type gemini -k "your-gemini-key" -m "gemini-1.5-pro" "Your prompt"
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

### Examples

Solveig includes a lengthy example conversation that can optionally be included in the system prompt, to
help the LLM understand a typical usage flow that includes practically every feature of solveig.
It's generated at runtime from actual schema objects so that it always matches the current output format.
From my testing it can be useful at helping the LLM understand what is expected, but be aware that it adds
a significant token overhead (currently 2934 with examples vs 352 without).

```bash
# Add example conversation to system prompt
solveig --api-type local --add-examples "Review my config module"
```


### Plugin Configuration

Configure plugins through the `plugins` section in your config file:

```json
{
  "plugins": {
    "shellcheck": {
      "shell": "bash",
      "ignore_codes": ["SC2076", "SC2016"]
    }
  }
}
```

### Context Tokens

Solveig can manage the session context by keeping track of the token length of each message. This is done according using an encoder that to the API type and model, and
you can specify a different encoder and/or a maximum context size:

```bash
# Use the default encoder for the specified model
# Since no max_context is specified, the context isn't managed and all messages will always be sent
solveig --api-type openai -k "your-key" -m "gpt-4" "Create a backup of my config files before updating them"

# Use a recent GPT encoder with a custom URL and a limit to the context size
solveig -u "https://api.openai.com/v1" -k "your-key" -e "cl200k_base" -m "gpt-5" -s 16384 "Analyze my project for security issues"
```

### Mock Client

It's possible to run Solveig with a mocked LLM client, used mostly for testing and development, that just uses
a pre-defined interaction loop (the one from the example conversations). However it can be useful for anyone
trying to test Solveig without access to a model. It accepts all normal options, although obviously many of them
won't apply.

```bash
python -m tests.mocks.run_with_mock_client -c ~/.config/solveig.json -v --no-commands --theme vercetti
```

## Safety Guidelines

1. **Review all operations**: Always read what Solveig plans to do before approving
2. **Use no-commands mode**: For maximum safety, disable commands with `--no-commands`
3. **Limit auto-approval**: Be very conservative with `--auto-allowed-paths` and `--auto-execute-commands`, especially if you're not familiar with glob or regex patterns
4. **Test configurations**: Try new configurations on non-critical directories first
5. **Regular backups**: Maintain backups of important files when using write operations

## Common Examples

### Code Review

```bash
solveig --api-type anthropic -k "your-key" --add-os-info "Review this Python project for potential issues"
```

### Safe File Analysis

```bash
solveig -u "http://localhost:5001/v1" --no-commands "Analyze the structure of this project and suggest improvements"
```

### Development Workflow

```bash
solveig --api-type local --auto-allowed-paths "$(pwd)/**/*" --auto-execute-commands "^git status$" "Help me commit these changes with a good message"
```

### Documentation Generation

```bash
solveig --api-type openai -k "your-key" --no-commands --auto-allowed-paths "$(pwd)/docs/**/*.md" "Update the documentation to reflect recent changes"
```