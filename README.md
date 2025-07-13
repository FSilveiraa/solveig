# Solveig

Solveig analyzes your shell and git history to generate 
This tool analyzes your shell history, git activity and other sources of data
to generate daily summaries, commit message suggestions and whatever else using an LLM.

Understand that this tool exposes a lot of your information to an AI, which can have potentially
disastrous privacy consequences.
Solveig will try to anonymize your data, but you're responsible for selecting data sources
for Solveig and using AI services you trust.
We suggest using a local model for sensitive data, and if you're starting out with a 3rd party
LLM service then try out Solveig on a "dummy" system like a VM.

## Setup

Solveig parses your raw session data - your shell commands, your current git repo history,
whatever else you wish to give it - and parses it into blocks that fit into a time range.
So that when you ask "summarize my day" Solveig can look at your data for the previous ~18h.
In order to do that, you need to perform some changes to your system. All of these can be done by executing
the `setup.sh` script.

### Enabling Bash History Timestamps

This will make your bash history use timestamps:

```commandline
 1001  2025-07-13 21:48:15 vim ~/.bashrc 
 1002  2025-07-13 23:05:30 source ~/.bashrc 
 1003  2025-07-13 23:05:37 history
```

Add the following line to your `~/.bashrc`:

```bash
export HISTTIMEFORMAT="%F %T "
```
