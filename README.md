# Solveig

Solveig works as safe bridge between AI assistants and your computer.

You ask questions and it translates the LLM's response into actionable requests that you can audit.

* **Ask anything** - Solveig figures out what info it needs.
* **File & shell context** - Let Solveig peek at file contents and metadata, or run specific commands to help you.
* **Explicit permissions** - You review every file or command request before anything is read, executed or sent.
* **Minimal setup** - Works with any OpenAI‑compatible LLM endpoint - Claude+Gemini coming!
* **Clean interface** - Simple and clear CLI (check out the [examples](#-examples)).

---

## 🚀 Quick start

Assuming you have an OpenAI-compatible API running on http://localhost:5001:

```commandline
pip install -r ./requirements.txt
python ./main.py -u "http://localhost:5001/v1" "Tell me a joke" 
```

---

## ❓ FAQ


### What is Solveig?

Solveig is a terminal‑based AI helper. Instead of just chatting, it can request access to files and command outputs
to actually solve problems on your machine.

### Is Solveig an LLM like ChatGPT?

Solveig isn't an LLM, it's a safe interface between those services and your computer. Solveig *can use* ChatGPT.

### Why use Solveig instead of a plain LLM?

By itself, an LLM can only guess based on what you type.
If you ask ChatGPT a question and it needs something else, it becomes your job to understand those requirements and manually attach them.
Solveig handles all of that for you. It can make your LLM understand what you need,
what resources it has available and how to help you - safely, automatically and without copy-pasting.

### Why use Solveig over other LLM‑to‑shell assistants?

All the software that acts as a layer between your LLM and a shell terminal can't be compared in terms of "what can it do?"
because the answer to all of them is "everything". Instead, Solveig's value comes more from how it prevents itself from doing
dangerous things through an explicit access system to both commands and files. It tries to minimize risk by allowing
direct file access over arbitrary commands, as well as enforcing explicit user consent.

Basically, it's much safer for an LLM to ask you for a file than to ask to run a `cat` command to read that file.

### Is Solveig safe to run?

The default configuration should prevent most problems, and to this day I've never seen Solveig generate actually unsafe code.
But understand that a tool that pipes an often-hallucinating text generator into a BASH interpreter is **probably
the most dangerous thing you could run on your computer**, and that it's your responsibility to be aware of the dangers
and to deny any file or command request that you do not understand.

---

## 🎭 Examples

All of these were obtained using [DeepSeek-R1-0528-Qwen3-8B-GGUF](https://huggingface.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF/tree/main),
I'm impressed with how good an 8B model is at suggesting commands and solving problems

<details>
<summary><b>(expand) Ask for the time in different timezones</b></summary>

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
</details>

<details>
<summary><b>(expand) How many users are logged in and who owns this file?</b></summary>

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
</details>
