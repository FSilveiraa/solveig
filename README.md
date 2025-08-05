
# Solveig

Solveig works as safe bridge between AI assistants and your computer.

You ask questions and it translates the LLM's response into actionable requests that you can audit.

* **Ask anything** - Solveig figures out what info it needs.
* **File & shell context** - Let Solveig peek at file contents and metadata, or run specific commands to help you.
* **Explicit permissions** - You review every file or command request before anything is read, executed or sent.
* **Minimal setup** - Works with any OpenAI‑compatible LLM endpoint - Claude+Gemini coming!
* **Clean interface** - Simple and clear CLI (check out the [examples](#-examples)).

---

<a href="https://vshymanskyy.github.io/StandWithUkraine">
	<img src="https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg">

---

## 🚀 Quick start
Install:
```commandline
pip install -r ./requirements.txt
```

Local model:
```commandline
python ./main.py -u "http://localhost:5001/v1" "Tell me a joke"
```

OpenRouter:
```commandline
python ./main.py -u "https://openrouter.ai/api/v1" -k "<API_KEY>" -m "moonshotai/kimi-k2:free" "Summarize my day"
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

Solveig takes several steps to prevent unsafe commands or file access on your machine.
For example, the Shellcheck plugin will confirm whether a command is correct bash, and I'm working on adding
other means of security like a "second opinion" LLM or Semgrep's AppSec, as well as a proper test suite.

To this day I've never seen Solveig ask to run actually unsafe code, but understand that a tool that pipes
an often-hallucinating text generator into a BASH interpreter is **probably the most dangerous thing you
could run on your computer**, and that it's your responsibility to be aware of the dangers and to deny any
file or command request that you do not understand.

---

## 🎭 Examples

These were obtained with [Kimi K2](https://openrouter.ai/moonshotai/kimi-k2) on OpenRouter.

*click to expand:*

<details>
<summary><b>Ask for the time in different timezones</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > What time is it?
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I can tell you the current time by checking the system clock. Let me run the date command to get the current time and date.

[ Requirements (1) ]
  Commands:
    date

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (1) ]
  [ Command ]
    comment: "Run the date command to display the current system time and date"
    command: date
    ? Allow running command? [y/N]: y
    [ Output ]
      Tue Jul 22 01:24:40 AM EEST 2025
    ? Allow sending output? [y/N]: y

Reply:
 > Here you go. By the way, what's the conversion to Hong Kong?
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
The system shows 01:24 AM EEST (Eastern European Summer Time). Hong Kong is 5 hours ahead of EEST, so the time in Hong Kong is 06:24 AM HKT.

```
</details>

<details>
<summary><b>Does this file look dangerous?</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > I don't recognize the file ~/run.sh, is it dangerous?
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I need to examine the ~/run.sh file to determine if it's dangerous. Let me check its contents and metadata to see what it does.

[ Requirements (1) ]
  Read:
    ~/run.sh (content)

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (1) ]
  [ Read ]
    comment: "I need to read the contents of ~/run.sh to analyze what commands it contains and determine if it could be harmful"
    path: ~/run.sh (file)
    ? Allow reading file? [y=content+metadata / m=metadata / N=skip]: y
    [ Metadata ]
      {"path": "/home/francisco/run.sh", "size": 1 (...) 01, "mtime": "Thu Jul 17 02:54:43 2025", "is_directory": false, "owner": "francisco", "group": "francisco"}
    [ Content ]
      (Base64)
    ? Allow sending file content and metadata? [y/N]: y

Reply:
 > 
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
The ~/run.sh file appears to be safe. It's a simple initialization script that creates directories for logs and tmp files, creates an empty log file, and sets up a flag file indicating the project has been initialized. The commands are all basic file operations (mkdir, touch, echo) and don't contain any suspicious or dangerous operations.

```
</details>

<details>
<summary><b>Create a Dockerized FastAPI example project</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > Create a Dockerized FastAPI example project in ~/my_app/
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I'll create a Dockerized FastAPI example project in ~/my_app/. This will include the FastAPI application code, requirements, Dockerfile, and docker-compose configuration.

[ Requirements (6) ]

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (6) ]
  [ Write ]
    comment: "Create the main project directory ~/my_app/"
    path: ~/my_app/ (directory)
    ! Warning: this path already exists !
  [ Write ]
    comment: "Create the FastAPI main application file"
    path: ~/my_app/main.py (file)
      [ Content ]
        from fastapi import FastAPI
        from p (...) ydantic import BaseModel
        
         (...) 
        @app.get("/health")
        async def health_check():
            return {"status": "healthy"}
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create requirements.txt with FastAPI dependencies"
    path: ~/my_app/requirements.txt (file)
      [ Content ]
        fastapi==0.104.1
        uvicorn[standard]==0.24.0
        pydantic==2.5.0
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create Dockerfile for containerizing the FastAPI app"
    path: ~/my_app/Dockerfile (file)
      [ Content ]
        FROM python:3.11-slim
        
        WOR (...) KDIR /app
         (...) 
        EXPOSE 8000
        
        CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create docker-compose.yml for easy development"
    path: ~/my_app/docker-compose.yml (file)
      [ Content ]
        version: '3.8'
        
        services:
 (...)          (...) 
        
        # volumes:
        #   postgres_data:
    ? Allow writing file and contents? [y/N]: y
  [ Write ]
    comment: "Create .dockerignore file to optimize build context"
    path: ~/my_app/.dockerignore (file)
      [ Content ]
        __pycache__
        *.pyc
        *.pyo
   (...)        (...) 
        README.md
        .env
        .venv
    ? Allow writing file and contents? [y/N]: y

Reply:
 > 

```

</details>

---

## 🧩 Plugins

Solveig can be extended by adding new communication capabilities or by interacting
with existing messages. A plugin can work in one of two ways:

* You can add a new message that describes a functionality available for the LLM. You can do this by creating a
`Pydantic` model that extends `schema.requirement.Requirement` and returns a response extending
`schema.requirement.RequirementResult`. **This functionality is not implemented yet since it requires figuring out
a way to re-generate the schema sent to the LLM on runtime, after all plugins are registered**
* You can interact with an existing requirement message, either before or after it starts being resolved, by using
the `@before/after(requirements=None)` hooks. Check out the existing `Shellcheck` plugin or the examples below


### Examples:

<details>
<summary><b>Anonymize all paths before sending to LLM</b></summary>

```python
import re

from config import SolveigConfig
from plugins.hooks import after
from schema.requirement import ReadRequirement, WriteRequirement, ReadResult, WriteResult

@after(requirements=(ReadRequirement, WriteRequirement))
def anonymize_paths(config: SolveigConfig, requirement: ReadRequirement|WriteRequirement, result: ReadResult|WriteResult):
    anonymous_path = result.real_path
    anonymous_path = re.sub(r"/home/\w+?", "/home/jdoe/", anonymous_path)
    anonymous_path = re.sub(r"^([A-Z]:\\Users\\)[^\\]+", r"\1JohnDoe", anonymous_path, flags=re.IGNORECASE)
    result.real_path = anonymous_path
```
</details>

---

## 📆 Coming next

My main priority is improving the File API and allow writing access with optional initial content.
This is useful for requests that mostly involve writing static text to large trees, like asking it to set up
an example NodeJS project.

Besides that, I want to focus on strengthening Solveig's CLI capabilities, making it safer to audit and run commands.
This is by automatically (and optionally) validating the commands Solveig generates for syntax errors, vulnerabilities and other concerns,
using two optional complementing approaches:

* [Semgrep](https://github.com/semgrep/semgrep) - a static code analyzer that can identify vulnerabilities
(I'm also exploring their Semgrep AppSec Platform)
* Double-check - requesting another LLM to validate the generated commands (either the main one or a secondary model focused on code safety)

I'm also interested on adding other APIs like Gemini and Claude, but it's not a priority because there are countless
platforms that normalize the API format (like OpenRouter) and local models don't benefit from it.
