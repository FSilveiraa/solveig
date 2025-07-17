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
I'm impressed with how good an 8B model is at suggesting commands and solving problems

Ask for the time:
```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > I need to check the current date and time

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
To check the current date and time, I can use the date command. Let me see what it outputs.

[ Requirements (1) ]
  Commands:
    date

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (1) ]
  [ Command ]
    Run this to show the current date and time.
      command: date
    ? Allow running command? [y/N]: y
    [ Output ]
      Thu Jul 17 06:41:30 PM EEST 2025
    ? Allow sending output? [y/N]: y

Reply:
 > Can you also tell me the time in Hong Kong?

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
The output from the date command shows the local time in EEST timezone. To get the time in Hong Kong, which is in the Asia/Hong_Kong timezone, I need to use the date command with the appropriate timezone set.

[ Requirements (1) ]
  Commands:
    TZ=Asia/Hong_Kong date +'%Y-%m-%d %H:%M:%S %z'

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (1) ]
  [ Command ]
    Run this command to display the current time in Hong Kong (Asia/Hong_Kong timezone).
      command: TZ=Asia/Hong_Kong date +'%Y-%m-%d %H:%M:%S %z'
    ? Allow running command? [y/N]: y
    [ Output ]
      2025-07-17 23:41:55 +0800
    ? Allow sending output? [y/N]: y

Reply:
 > 

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
Now I have the local time in EEST and the time in Hong Kong (Asia/Hong_Kong). The local time is July 17, 2025, 18:41:55 in EEST, and the Hong Kong time is July 17, 2025, 23:41:55 in +0800. I hope this helps!

```

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > How many users are logged in and who owns ~/run.sh?

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
To determine how many users are logged in, I can check the output of the 'who' command. It will list all currently logged-in users and their details. Additionally, I need to know the owner of the file ~/run.sh, which can be found in the file's metadata.

[ Requirements (2) ]
  Files:
    ~/run.sh (metadata)
  Commands:
    who

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (2) ]
  [ Command ]
    Run this command to check how many users are logged in. The 'who' command lists all logged-in users, and we can count them from the output.
      command: who
    ? Allow running command? [y/N]: y
    [ Output ]
      jdoe seat0        2025-07-01 12:18
      jdoe tty2         2025-07-01 12:18
    ? Allow sending output? [y/N]: y
  [ File ]
    Run this to get the metadata of the file to find out who owns it.
      path: ~/run.sh (dir=False)
    ? Read file? [y=contents+metadata / m=metadata / N=skip]: m
    [ Metadata ]
    {"path": "/home/jdoe/run.sh", "size": 101 (...) , "mtime": "Thu Jul 17 02:54:43 2025", "is_directory": false, "owner": "jdoe", "group": "jdoe"}
    ? Allow sending file data? [y/N]: y

Reply:
 > Here you go!

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
Based on the 'who' command output, there are two users logged in: 'jdoe' on seat0 and 'jdoe' on tty2. The file ~/run.sh is owned by 'jdoe'.

```
