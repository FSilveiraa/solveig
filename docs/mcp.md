# MCP Servers

Solveig supports the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), allowing you to connect external tool servers and make their capabilities available to the assistant alongside built-in tools.

---

## Connecting at startup

Add servers to your config file under `mcp_servers`. Each key is a name you choose; each value is a configuration object with at minimum a `url`:

```json
{
  "mcp_servers": {
    "filesystem": {
      "url": "http://localhost:8001/mcp"
    },
    "search": {
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

To connect a single server quickly without editing config, pass `--mcp <url>` on the CLI (can be repeated):

```
solveig --mcp http://localhost:8001/mcp
```

CLI `--mcp` entries are merged into the `mcp_servers` dict keyed by their URL.

---

## Per-server options

| Field | Type | Description |
|---|---|---|
| `url` | string | Server URL. Required. |
| `allowed_tools` | list of strings | Glob patterns for tools to include. Empty (default) accepts all tools. |
| `blocked_tools` | list of strings | Glob patterns for tools to always exclude, applied after `allowed_tools`. |
| `headers` | dict | HTTP headers sent with every request, e.g. `{"Authorization": "Bearer ..."}`. |
| `timeout` | number or null | Connection timeout in seconds. `null` uses the global default. |

### Tool filtering

`allowed_tools` and `blocked_tools` use [fnmatch](https://docs.python.org/3/library/fnmatch.html) glob syntax (case-sensitive) matched against each tool's name as reported by the server.

`allowed_tools` is applied first — if non-empty, only matching tools are kept. `blocked_tools` is then applied to exclude tools from whatever remains.

```json
{
  "mcp_servers": {
    "filesystem": {
      "url": "http://localhost:8001/mcp",
      "allowed_tools": ["read_file", "list_dir*"],
      "blocked_tools": ["delete_*"]
    }
  }
}
```

---

## Transports

**HTTP** — the default. Any `url` starting with `http://` or `https://` uses the streamable HTTP transport.

**stdio** — for local processes. Use a `stdio://` URL where the remainder is the command to run:

```json
{
  "mcp_servers": {
    "local-tools": {
      "url": "stdio://python my_mcp_server.py --flag"
    }
  }
}
```

---

## Runtime management

Servers can be connected and disconnected mid-conversation without restarting. See [Subcommands](./subcommands.md) for the full reference.

```
/mcp connect http://localhost:8003/mcp   — connect to a new server
/mcp disconnect filesystem               — disconnect by server name
/mcp list                                — show connected servers and their tools
```

The server name shown in `/mcp list` and used by `/mcp disconnect` is the name the server reports during the MCP handshake (`serverInfo.name`), not the key from your config file.

All connected servers' tools are immediately available to the assistant. Disconnecting removes them from the active tool set.
