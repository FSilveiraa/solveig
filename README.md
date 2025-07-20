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

The default configuration should prevent most problems, and to this day I've never seen Solveig generate actually unsafe code.
But understand that a tool that pipes an often-hallucinating text generator into a BASH interpreter is **probably
the most dangerous thing you could run on your computer**, and that it's your responsibility to be aware of the dangers
and to deny any file or command request that you do not understand.

---

## 🎭 Examples

These were obtained a mixture of local runs of [DeepSeek-R1-0528-Qwen3-8B-GGUF](https://huggingface.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF/tree/main),
as well as [Kimi K2](https://openrouter.ai/moonshotai/kimi-k2) on OpenRouter.

*click to expand:*

<details>
<summary><b>Ask for the time in different timezones</b></summary>

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > I need to check the current date and time
(Sending)

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
 (Sending)

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
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
Now I have the local time in EEST and the time in Hong Kong (Asia/Hong_Kong). The local time is July 17, 2025, 18:41:55 in EEST, and the Hong Kong time is July 17, 2025, 23:41:55 in +0800. I hope this helps!

```
</details>

<details>
<summary><b>How many users are logged in and who owns this file?</b></summary>

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

<details>

<summary><b>Create a Dockerized FastAPI project in ~/my_app/</b></summary>

Disclosure: the Files functionality isn't finished and doesn't yet implement writing, so if the LLM asked me to create a file
with some initial contents, that wouldn't be possible. Because of that I added this to the prompt: `(Use only commands)`

```
--- User -----------------------------------------------------------------------------------------------------------------------------------
Reply:
 > Create a Dockerized FastAPI project in ~/my_app/ (Use only commands)
(Sending)

--- Assistant ------------------------------------------------------------------------------------------------------------------------------
I'll create a Dockerized FastAPI project in ~/my_app/ using commands. This will involve creating the directory structure, Python files, Dockerfile, and docker-compose.yml.

[ Requirements (7) ]
  Commands:
    mkdir -p ~/my_app/app
    cat > ~/my_app/app/main.py << 'EOF'
from fastapi import FastAPI

app = FastAPI(title="My FastAPI App", version="1.0.0")

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI!"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
EOF
    cat > ~/my_app/requirements.txt << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
EOF
    cat > ~/my_app/Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF
    cat > ~/my_app/docker-compose.yml << 'EOF'
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app/app
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
EOF
    cat > ~/my_app/.dockerignore << 'EOF'
__pycache__
*.pyc
*.pyo
*.pyd
.Python
env
pip-log.txt
pip-delete-this-directory.txt
.tox
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.log
.git
.mypy_cache
.pytest_cache
.hypothesis
EOF
    cat > ~/my_app/.gitignore << 'EOF'
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/
EOF

--- User -----------------------------------------------------------------------------------------------------------------------------------
[ Requirement Results (7) ]
  [ Command ]
    Create the main project directory
      command: mkdir -p ~/my_app/app
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y
  [ Command ]
    Create the main FastAPI application file
      command: cat > ~/my_app/app/main.py << 'EOF'
from fastapi import FastAPI

app = FastAPI(title="My FastAPI App", version="1.0.0")

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI!"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
EOF
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y
  [ Command ]
    Create requirements.txt with FastAPI dependencies
      command: cat > ~/my_app/requirements.txt << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
EOF
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y
  [ Command ]
    Create Dockerfile for containerization
      command: cat > ~/my_app/Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y
  [ Command ]
    Create docker-compose.yml for easy development
      command: cat > ~/my_app/docker-compose.yml << 'EOF'
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app/app
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
EOF
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y
  [ Command ]
    Create .dockerignore to optimize build context
      command: cat > ~/my_app/.dockerignore << 'EOF'
__pycache__
*.pyc
*.pyo
*.pyd
.Python
env
pip-log.txt
pip-delete-this-directory.txt
.tox
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.log
.git
.mypy_cache
.pytest_cache
.hypothesis
EOF
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y
  [ Command ]
    Create .gitignore for version control
      command: cat > ~/my_app/.gitignore << 'EOF'
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/
EOF
    ? Allow running command? [y/N]: y
    [ Output ]

    ? Allow sending output? [y/N]: y

Reply:
 > 

```

</details>

---

## 🧩 Plugins

Solveig can be extended by adding new communication capabilities.
Just create a `Pydantic` model that extends `schema.requirement.BaseRequirement`,
and likely a response extending `schema.requirement.RequirementResult`.

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
