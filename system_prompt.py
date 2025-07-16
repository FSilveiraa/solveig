import os
import platform

from click import command

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
file_req1 = FileReadRequirement(
    path="~/run.sh",
    comment="To check what this script does, I need to read the contents of run.sh.",
)
script_chat.add_message(LLMMessage(comment="Of course, let's take a look", requirements=[ file_req1 ]))
script_chat.add_message(UserMessage(comment="Ok here you go", results=[FileReadResult(requirement=file_req1, content="""
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

multiple_issues_chat = MessageHistory(system_prompt="")
CONVERSATION_EXAMPLES.append(multiple_issues_chat)
multiple_issues_chat.add_message(UserMessage(comment="""
My computer is slow, can you help me find which processes are using my CPU the most and what my disk usage is?
Also summarize the contents of ~/my_app.log, count how many errors occurred and how serious they look
I'm using Linux
"""))
cmd_req_cpu_usage = CommandRequirement(comment="Run this command to list processes sorted by CPU usage", command="ps aux --sort=-%cpu | head -n 10")
cmd_req_disk_usage = CommandRequirement(comment="Run this to see overall disk usage per mounted filesystem", command="df -h")
cmd_req_large_dirs = CommandRequirement(comment="If you also want to see which directories are largest in your home folder", command="du -h --max-depth=1 ~ | sort -hr | head -n 15")
file_req2 = FileReadRequirement(comment="I need to access the log to analyze it", path="~/my_app.log")
multiple_issues_chat.add_message(LLMMessage(
    comment="Sure! Let’s check these step by step.",
    requirements=[ cmd_req_cpu_usage, cmd_req_disk_usage, cmd_req_large_dirs, file_req1 ]
))
multiple_issues_chat.add_message(UserMessage(
    comment="Here you go. I don't think it's necessary to run the 3rd command",
    results=[
        CommandResult(
            requirement=cmd_req_cpu_usage,
            stdout="""
USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
jdoe        8421 95.7  4.2 905312 342816 ?       Rl   09:13  10:44 /opt/firefox/firefox
jdoe        9154 28.9  1.8 732448 146232 ?       Sl   09:26   2:12 /usr/bin/python3 /home/jdoe/projects/scraper.py
root        1203 18.4  0.9 255280  72012 ?       Ssl  07:45   7:03 /usr/lib/Xorg vt1 -displayfd 3
jdoe        9772 11.6  0.5 214560  41288 ?       Sl   09:38   0:58 /usr/lib/code/code
jdoe        9805  8.3  0.4 163820  33728 pts/1    S+   09:39   0:12 htop
jdoe        8810  6.9  0.6 289104  51244 ?       Sl   09:18   0:47 /usr/lib/virtualbox/VirtualBoxVM --startvm UbuntuDev
root        1357  4.7  0.3 180400  28212 ?       Ssl  07:45   4:20 /usr/bin/pipewire
root        1408  3.1  0.2  36864   7900 ?       Ss   07:45   0:21 /usr/sbin/cron -f
jdoe        9924  2.4  0.1 125700  14200 ?       Sl   09:41   0:09 /usr/bin/gnome-terminal-server
jdoe        9501  1.9  0.3 204560  27712 ?       Sl   09:24   0:18 /usr/lib/thunderbird/thunderbird
""",
            success=True
        ),
        CommandResult(
            requirement=cmd_req_disk_usage,
            stdout="""
Filesystem      Size  Used Avail Use% Mounted on
tmpfs           784M  2.0M  782M   1% /run
/dev/sda2        60G   42G   16G  73% /
tmpfs           3.8G  128M  3.7G   4% /dev/shm
tmpfs           5.0M     0  5.0M   0% /run/lock
/dev/sda1       512M  6.1M  506M   2% /boot/efi
/dev/sdb1       200G  150G   50G  75% /mnt/data
tmpfs           784M   48K  784M   1% /run/user/1000
""",
            success=True
        ),
        FileReadResult(
            requirement=file_req2,
            content="""
2025-07-16 09:12:03 INFO  [app] Starting web server on port 8080
2025-07-16 09:12:04 INFO  [db] Connection established to postgres://localhost:5432/mydb
2025-07-16 09:12:05 INFO  [app] GET / 200 12ms
2025-07-16 09:12:07 INFO  [app] GET /api/users 200 24ms
2025-07-16 09:12:08 WARN  [auth] Failed login attempt for user 'admin'
2025-07-16 09:12:09 INFO  [app] POST /api/login 401 18ms
2025-07-16 09:12:11 INFO  [app] GET /dashboard 302 3ms
2025-07-16 09:12:15 ERROR [payment] Timeout while processing transaction #98432
2025-07-16 09:12:16 INFO  [app] GET /api/orders 200 45ms
"""
        )
    ]
))
multiple_issues_chat.add_message(LLMMessage(
    comment="""
I understand. Based on the information you've shared, Firefox is using a lot of your CPU and could be responsible for it being slow.
The file ~/my_app.log shows that someone tried to login as 'admin' around 09:12, but failed. Around the same time there was also a failed payment transaction. 
"""
))


def get_basic_os_info(exclude_username=False):
    info = {
        "os_name": platform.system(),           # e.g., 'Linux', 'Windows', 'Darwin'
        "os_release": platform.release(),       # e.g., '6.9.1-arch1-1'
        "os_version": platform.version(),       # detailed kernel version
    }
    # Add username and home path
    if not exclude_username:
        info["cwd"] = os.getcwd()
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
