# Solveig

Solveig analyzes your system to answer any questions or solve any issues you may have.

Generate a summary of your day based on your browser history.

Find the latest file changed in a directory tree.

Create a commit message based on your git diff.

Diagnose problems by sharing logs and getting commands you can audit.

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

```
 1001  2025-07-13 21:48:15 vim ~/.bashrc 
 1002  2025-07-13 23:05:30 source ~/.bashrc 
 1003  2025-07-13 23:05:37 history
```

Add the following line to your `~/.bashrc`:

```bash
export HISTTIMEFORMAT="%F %T "
```


## Examples

All of these were obtained using [DeepSeek-R1-0528-Qwen3-8B-GGUF](https://huggingface.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF/tree/main),
I'm kind of impressed at how good an 8B model is at suggesting commands and solving problems

Ask for the time:
```
User:
 > What time is it now?

[ Sending ]
{
  "comment": "What time is it now?",
  "results": null
}

--------------------------------------------------------------------------------------------------------------------------------------------

Assistant:
I can't check the current time because I don't have direct access to your system's clock.

[ Requirements (1) ]
  [ Command ]
    I need to run a command to get the current system time.
      command: date
    ? Allow running command? [y/N]: y
    [ Output ]
      Thu Jul 17 03:26:57 AM EEST 2025
    ? Allow sending output? [y/N]: y

--------------------------------------------------------------------------------------------------------------------------------------------

User:
 > Here you go

[ Sending ]
{
  "comment": "Here you go",
  "results": [
    {
      "success": true,
      "stdout": "Thu Jul 17 03:26:57 AM EEST 2025",
      "stderr": "",
      "command": "date"
    }
  ]
}

--------------------------------------------------------------------------------------------------------------------------------------------

Assistant:
Based on the system time, it's currently July 17, 2025, at 3:26 AM.

```

```
User:
 > How many user are currently logged into my operating system?


--------------------------------------------------------------------------------------------------------------------------------------------

Assistant:
To determine how many users are logged in, I need to run the 'who' command to list all logged-in users.

[ Requirements (1) ]
  [ Command ]
    Run this command to see who's currently logged in.
      command: who
    ? Allow running command? [y/N]: y
    [ Output ]
jdoe seat0        2025-07-01 12:18
jdoe tty2         2025-07-01 12:18
    ? Allow sending output? [y/N]: y

--------------------------------------------------------------------------------------------------------------------------------------------

User:
 > Here!


--------------------------------------------------------------------------------------------------------------------------------------------

Assistant:
Based on the 'who' command output, only one user 'jdoe' is logged in. However, note that this command typically shows users logged into the system, which may include remote users if they are connected via SSH or other methods. To get a more comprehensive view, you can check the number of user sessions using 'loginctl list-sessions' or look at /var/log/wtmp for historical login records. But for now, it seems only one user is currently logged in.

```
