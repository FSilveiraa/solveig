import os
import platform

from config import SolveigConfig

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None

from schema.requirement import *
from schema.message import *

SYSTEM_PROMPT = """
You are an AI assisting a user with whatever issues they may have with their computer.
Your goal is to be as helpful to the user as possible.

To assist the user, you may request to access either the metadata or the contents for any path (file or directory) you think is necessary.
If you ask to read a directory's content or its metadata, in both cases the user will provide the information equivalent of `ls -la`.
Any time that you require access to a path, always explain why it's necessary.

You may also request to run certain commands and inspect their output if you think it will help you solve user's issue.
Any time you ask the user to execute anything, always explain why you need it, what each flag does, what you expect it to do and what the expected output is.
Put the safety and integrity of user's system above everything else, do not suggest dangerous/destructive commands unless it's absolutely necessary.

Request as few requirements as necessary to obtain what is needed. For example, don't ask for a file and also a command to read that file.
Prioritize asking for files explicitly over running a command to read that file since it's safer for the user.
Use commands only when necessary for access or performance reasons.
If you believe your solution will require multiple steps in sequence, ask only for what is necessary at this moment.
Assume the user will keep interacting with you until their problem is solved.

Output your response strictly following the `LLMessage` format described below.
Important: Your response must always be a JSON object with these fields: `comment` (string) and `requirements` (array of requirement objects, optional).
Do not return a raw list of requirements, or a single requirement. Wrap the array of requirements in an object.
"""

SYSTEM_PROMPT_OS_INFO = """
You have access to the following information regarding the user's system:
"""

SYSTEM_PROMPT_EXAMPLES = "Use the following conversation examples to guide your expected output format"
CONVERSATION_EXAMPLES = []

joke_chat = MessageHistory(system_prompt="") # we don't want system prompt for a chat history that itself will be used in our system prompt
CONVERSATION_EXAMPLES.append(joke_chat)
joke_chat.add_message(UserMessage(comment="Tell me a joke"))
joke_chat.add_message(LLMMessage(comment="Sure! Here's a joke for you. Why do programmers prefer dark mode? Because light attracts bugs.", requirements=[]))

script_chat = MessageHistory(system_prompt="")
CONVERSATION_EXAMPLES.append(script_chat)
script_chat.add_message(UserMessage(comment="What does the script on ~/run.sh do?"))
file_requirement = FileReadRequirement(
    path="~/run.sh",
    comment="To check what this script does, I need to read the contents of run.sh.",
)
script_chat.add_message(LLMMessage(comment="Of course, let's take a look", requirements=[file_requirement]))
script_chat.add_message(UserMessage(comment="Ok here you go", results=[FileReadResult(requirement=file_requirement, content="""
#!/usr/bin/env bash
mkdir -p logs tmp
touch logs/app.log
echo "Project initialized." > tmp/init.flag
""".strip())]))
script_chat.add_message(LLMMessage(comment="""
This script initializes a project workspace.
This script creates logs/ and tmp/, makes an empty logs/app.log, and writes “Project initialized.” to tmp/init.flag.
It’s safe—no deletions or overwrites.
""".strip(), requirements=[]))


def get_basic_os_info(exclude_username=False):
    info = {
        "os_name": platform.system(),           # e.g., 'Linux', 'Windows', 'Darwin'
        "os_release": platform.release(),       # e.g., '6.9.1-arch1-1'
        "os_version": platform.version(),       # detailed kernel version
    }
    # Add username and home path
    if not exclude_username:
        info["username"] = os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USER")
        info["home_dir"] = os.path.expanduser("~")
    # Add distro info if we're in Linux
    if info["os_name"] == "Linux" and distro:
        info["linux_distribution"] = distro.name(pretty=True)  # e.g. 'Manjaro Linux'
    return info


def get_system_prompt(config: SolveigConfig):
    system_prompt = SYSTEM_PROMPT.strip()
    if config.add_os_info:
        os_info = get_basic_os_info(config.exclude_username)
        system_prompt = (f"{system_prompt}\n\n{SYSTEM_PROMPT_OS_INFO.strip()}\n"
                         + "\n ".join(f"{k}: {v}" for k, v in os_info.items())).strip()
    if config.add_examples:
        system_prompt = (f"{system_prompt}\n\n{SYSTEM_PROMPT_EXAMPLES.strip()}\n"
                         + "\n\n".join([history.to_example() for history in CONVERSATION_EXAMPLES]))
    return system_prompt.strip()
