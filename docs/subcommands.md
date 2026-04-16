# Subcommands

Subcommands are typed directly in the chat input, prefixed with `/`. They are processed before the message is sent to the assistant, so they never consume context tokens.

---

## Basic

| Command | Description |
|---|---|
| `/help` | Print all available subcommands |
| `/exit` | Exit Solveig (Ctrl+C also works) |
| `/store [name]` | Shorthand for `/session store` |
| `/resume [name or path]` | Shorthand for `/session resume` |

---

## Config

| Command | Description |
|---|---|
| `/config` | List all editable fields with their current values |
| `/config list` | Same as above |
| `/config get <field>` | Show the current value and description for a field |
| `/config set <field> [value]` | Set a field. Prompts interactively if value is omitted. Also accepts `field=value` syntax. |

Fields that are not exposed here (e.g. `model_info`) are runtime-only and cannot be changed via `/config`.

---

## Model

| Command | Description |
|---|---|
| `/model` | Show current model name, context length, and pricing |
| `/model info` | Same as above |
| `/model set [name]` | Change the active model. Prompts if name is omitted. |
| `/model refresh` | Re-fetch model info from the API |
| `/model list` | List all models available from the current API endpoint |

---

## Session

| Command | Description |
|---|---|
| `/session` | List stored sessions |
| `/session list` | Same as above |
| `/session store [name]` | Save the current conversation. Uses a timestamp if name is omitted. |
| `/session delete <name or path>` | Delete a session by name or path (fuzzy name match) |
| `/session resume [name or path]` | Load and replay a session. Resumes the latest if name is omitted. |

`/sessions` (plural) is accepted as an alias for all of the above.

---

## MCP

See [MCP](./mcp.md) for full documentation on connecting to MCP servers.

| Command | Description |
|---|---|
| `/mcp` | List currently connected MCP servers and their tools |
| `/mcp list` | Same as above |
| `/mcp connect <url>` | Connect to an MCP server at runtime |
| `/mcp disconnect <name>` | Disconnect from a named MCP server |

---

## Tool subcommands

Each built-in tool registers a subcommand so you can invoke it directly without involving the assistant. Results are added to the message queue as if the assistant had run the tool.

| Command | Description |
|---|---|
| `/read <path>` | Read a file or directory |
| `/write <path>` | Write a file |
| `/edit <path> <old> <new>` | Perform a search-and-replace edit |
| `/copy <src> <dst>` | Copy a file or directory |
| `/move <src> <dst>` | Move a file or directory |
| `/delete <path>` | Delete a file or directory |
| `/command <cmd>` | Run a shell command |
| `/http <url>` | Make an HTTP request |

Plugin tools register their own subcommands in the same section. For example, the built-in tree plugin adds `/tree <path>`.
