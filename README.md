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
--- User -----------------------------------------------------------------------------------------------------------------------------------

Reply:
 > I need a command to check the current date and time

--- Assistant ------------------------------------------------------------------------------------------------------------------------------

I can help you with that. The command to get the current date and time is `date`. Let me know if you need more details.

[ Requirements (1) ]
  Commands:
    date

--- User -----------------------------------------------------------------------------------------------------------------------------------

[ Requirement Results (1) ]

  [ Command ]
    Run this command to get the current date and time
      command: date
    ? Allow running command? [y/N]: y
    [ Output ]
Thu Jul 17 05:18:30 PM EEST 2025
    ? Allow sending output? [y/N]: y

Reply:
 > Here's the output

--- Assistant ------------------------------------------------------------------------------------------------------------------------------

The current date and time is Thu Jul 17 05:18:30 PM EEST 2025. You can use this command to get the time in different formats.

--- User -----------------------------------------------------------------------------------------------------------------------------------

Reply:
 > Well based on that, what time is it in hong kong?

--- Assistant ------------------------------------------------------------------------------------------------------------------------------

To determine the current time in Hong Kong, I can use the `date` command with the environment set to the Hong Kong timezone.

[ Requirements (1) ]
  Commands:
    TZ=Asia/Hong_Kong date +"\%T %Z"

--- User -----------------------------------------------------------------------------------------------------------------------------------

[ Requirement Results (1) ]

  [ Command ]
    Run this command to display the current time in Hong Kong (timezone Asia/Hong_Kong).
      command: TZ=Asia/Hong_Kong date +"\%T %Z"
    ? Allow running command? [y/N]: y
    [ Output ]
\22:20:31 HKT
    ? Allow sending output? [y/N]: y

Reply:
 > 

--- Assistant ------------------------------------------------------------------------------------------------------------------------------

Based on the output, the current time in Hong Kong is 22:20:31 HKT. This means it's 10:20 PM Hong Kong Time.

```

```
User:
 > How many users are logged in and who owns ~/run.sh?


--------------------------------------------------------------------------------------------------------------------------------------------

Assistant:
First, let's clarify what you mean by 'logged in' users. Do you mean users currently using the system, or users who have a shell login? I'll assume you're asking for users currently logged in.

[ Requirements (2) ]
  Files:
    ~/run.sh (metadata)
  Commands:
    who

  [ Command ]
    I need to run the 'who' command to see how many users are currently logged in. This command displays users logged on to the system.
      command: who
    ? Allow running command? [y/N]: y
    [ Output ]
jdoe seat0        2025-07-01 12:18
jdoe tty2         2025-07-01 12:18
    ? Allow sending output? [y/N]: y

  [ File ]
    To determine the owner of the file ~/run.sh, I need to read its metadata.
      path: ~/run.sh (dir=False)
    ? Read file? [y=contents+metadata / m=metadata / N=skip]: m
    [ Metadata ]
      {"path": "/home/jdoe/run.sh", "size": 101,(...) "mtime": "Thu Jul 17 02:54:43 2025", "is_directory": false, "owner": "jdoe", "group": "jdoe"}
    ? Allow sending file data? [y/N]: y

--------------------------------------------------------------------------------------------------------------------------------------------

User:
 > Here you go!

--------------------------------------------------------------------------------------------------------------------------------------------

Assistant:
Based on the 'who' command output, there are two users logged in: 'jdoe' and another user on seat0. The second user is also named 'jdoe' and is logged in via a seat, which might be a virtual terminal or remote connection. For the file ~/run.sh, the metadata shows it is owned by 'jdoe' and belongs to the 'jdoe' group. The file has a size of 101 bytes and was last modified on Thu Jul 17 02:54:43 2025.

```
