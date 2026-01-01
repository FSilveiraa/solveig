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

## Configuration Options

The CLI args are merged with, and take precedence over, the configuration file -
see [Configuration Precedence](#configuration-precedence) for more.

### Config Files

You can pass Solveig a JSON configuration file through the `-c` file or omit for the default location of
`~/.config/solveig.json`:

| CLI Flag       | Description          | Default                  |
|----------------|----------------------|--------------------------|
| `-c, --config` | Config file location | `~/.config/solveig.json` |

```json
{
  "url": "https://openrouter.ai/api/v1",
  "api_type": "openai",
  "api_key": "sk-your-api-key",
  "model": "anthropic/claude-3.5-sonnet",
  "encoder": null,
  "temperature": 0,
  "max_context": -1,
  "add_examples": false,
  "add_os_info": false,
  "exclude_username": false,
  "min_disk_space_left": "1GiB",
  "verbose": false,
  "auto_allowed_paths": [],
  "auto_execute_commands": [],
  "no_commands": false,
  "theme": "terracotta",
  "code_theme": "coffee",
  "wait_between": 0.3,
  "plugins": {
    "shellcheck": {
      "shell": "bash"
    },
    "tree": {}
  }
}
```

### Connection

| Option        | CLI Flag            | Description                                                   | Default            |
|---------------|---------------------|---------------------------------------------------------------|--------------------|
| `url`         | `-u, --url`         | LLM endpoint URL (assumes OpenAI-compatible if no `api_type`) | `""`               |
| `api_type`    | `-a, --api-type`    | API provider (openai, local, anthropic, gemini)               | -                  |
| `api_key`     | `-k, --api-key`     | API key for remote services                                   | `""`               |
| `model`       | `-m, --model`       | Model name/path                                               | `null`             |
| `encoder`     | `-e, --encoder`     | Model encoder for token counting                              | Uses `model` value |
| `temperature` | `-t, --temperature` | Model temperature                                             | `0`                |
| `max_context` | `-s, --max-context` | Maximum context size in tokens                                | `-1` (no limit)    |

### Security and Automation

| Option                  | CLI Flag                  | Description                                     | Default |
|-------------------------|---------------------------|-------------------------------------------------|---------|
| `no_commands`           | `--no-commands`           | Disable command execution entirely              | `false` |
| `auto_allowed_paths`    | `--auto-allowed-paths`    | Glob patterns for auto-approved file operations | `[]`    |
| `auto_execute_commands` | `--auto-execute-commands` | Regex patterns for auto-approved commands       | `[]`    |

### Interface

| Option         | CLI Flag             | Description                                                            | Default      |
|----------------|----------------------|------------------------------------------------------------------------|--------------|
| `verbose`      | `-v, --verbose`      | Enable verbose logging (displays system prompt, messages, etc)         | `false`      |
| `wait_between` | `-w, --wait-between` | Time (seconds) between displaying tools                                | `0.3`        |
| `theme`        | `--theme`            | CLI theme to use (`none` to disable, see [Themes](./themes/themes.md)) | `terracotta` |              |
| `code_theme`   | `--code-theme`       | Code linting theme to use (see [Themes](./themes/themes.md))           | `material`   |              |

### System Prompt and Resources

| Option                | CLI Flag                        | Description                       | Default   |
|-----------------------|---------------------------------|-----------------------------------|-----------|
| `min_disk_space_left` | `-d, --min-disk-space-left`     | Minimum disk space required       | `1GiB`    |
| `add_os_info`         | `--add-os-info, --os`           | Include OS info in system prompt  | `false`   |
| `exclude_username`    | `--exclude-username, --no-user` | Exclude username from OS info     | `false`   |
| `add_examples`        | `--add-examples, --ex`          | Include examples in system prompt | `false`   |

## System Prompt

You can configure the System Prompt using your own template, controlling what is sent to the assistant.
If you write your own System Prompt, remember to include the following tags, otherwise their respective
config flags will not work:
- `{AVAILABLE_TOOLS}` - descriptive list of available operations
- `{SYSTEM_INFO}` - details about the running operating system
- `{EXAMPLES}` - conversation examples

Of course, you can also just hardcode the information on the System Prompt itself.
Keep in mind, `SYSTEM_INFO` and `EXAMPLES` are optional, so don't for example use a header like
`System info:\n{SYSTEM_INFO}` that would be followed by nothing if the  flag isn't used.

Below is the current System Prompt template:

```
You are an AI assistant helping users solve problems through tool use.

Guidelines:
- Use the comment field to explain each operation, use tasks().comment to communicate simple answers
- For multi-step work, start with a task list showing your plan, then execute operations
- Update task status as you progress through the plan
- Prefer file operations over shell commands when possible
- Ask before destructive actions (delete, overwrite)
- If an operation fails, adapt your approach and continue

Available tools:
{AVAILABLE_TOOLS}

{SYSTEM_INFO}

{EXAMPLES}
```

## Security Modes

### No-Commands Mode

Disable command execution entirely for maximum security:

```bash
solveig --api-type local --no-commands "Analyze this codebase structure"
```

In this mode, Solveig can only perform file operations (read, write, copy, move, delete).
For both security and conversation sanity, shell commands are not just blocked, the Assistant isn't
aware of commands as possible resource.

### Auto-Approval Patterns

You can auto-approve certain operations if they match certain patterns for both command regex and file path
glob patterns - keep in mind if these are the final CLI args, you will need to add `--` before the user prompt:

`python -m tests.mocks.run_mock --auto-allowed-paths "~/src/**/*.js" "~/tests/**/*.py" --auto-execute-commands "^git status$" "^git --no-pager diff$" -- "Review my project"`

You can also include this in the config file:

```json
{
  "auto_allowed_paths": [
    "~/src/**/*.js",
    "~/tests/**/*.py"
  ],
  "auto_execute_commands": [
    "^git status$",
    "^git --no-pager diff$"
  ]
}
```

**Warning**: Use with extreme caution. These patterns allow automatic command execution and file operations.

## Model Selection

Solveig itself doesn't force you to specify a model nor does it validate it as a name or path (e.g. "-m gpt-5" vs
"-m openai/gpt-5"), however your backend might. Typically only local backends like Koboldcpp don't enforce it.

**Note**: Anthropic and Google providers require additional packages. Install with `pip install solveig[anthropic]`
or `pip install solveig[google]` respectively.

## Advanced Usage

### Configuration Precedence

Configuration is loaded in this order (later values override earlier ones):

1. Default values
2. Configuration file (`~/.config/solveig.json` or specified with `-c`)
3. Command-line arguments

### Interactive Commands

During a conversation with Solveig, you can use special subcommands that start with `/` to control the session:

| Command       | Description                                                             |
|---------------|-------------------------------------------------------------------------|
| `/help`       | Display help information and list all available subcommands             |
| `/exit`       | Exit the application (alternatively, use Ctrl+C)                        |
| `/log <path>` | Export the current conversation history to a file at the specified path |

These commands are processed directly by Solveig's interface and don't require AI model interaction,
making them fast and reliable for session management.

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

Solveig can manage the session context by keeping track of the token length of each message.
This is done using an encoder that can either be specified explicitly or inferred according to the API type and model,
and by also setting a maximum context size:

```bash
# Use the default encoder for the specified model
# Since no max_context is specified, the context isn't managed and all messages will always be sent
solveig --api-type openai -k "your-key" -m "gpt-4" "Create a backup of my config files before updating them"

# Use a recent GPT encoder with a custom URL and a limit to the context size
solveig -u "https://api.openai.com/v1" -k "your-key" -e "cl200k_base" -m "gpt-5" -s 16384 "Analyze my project for security issues"
```

### Mock Client

It's possible to run Solveig with a mocked LLM client, used mostly for testing and development, that just uses
a pre-defined interaction loop (the one from the example conversations). However, it can be useful for anyone
trying to test Solveig without access to a model. It accepts all normal options, although obviously many of them
won't apply.

```bash
python -m tests.mocks.run_mock -c ~/.config/solveig.json -v --no-commands --theme solarized-dark
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