# Thorne

This tool analyzes your shell and git activity to generate summaries and commit message suggestions using an LLM.

## Setup

To enable detailed shell history parsing, this tool requires that your Bash history includes timestamps.

### Enabling Bash History Timestamps

Add the following line to your `~/.bashrc`:

```bash
export HISTTIMEFORMAT="%F %T "
```
