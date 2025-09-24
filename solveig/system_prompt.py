import os
import platform
from datetime import datetime
from pathlib import PurePath

from .plugins.schema.tree import TreeRequirement, TreeResult
from .schema.results.task import Task, TaskListResult
from .utils.file import Metadata

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None  # type: ignore

# TODO: Make conversation examples dynamic rather than hardcoded
from solveig.schema import (
    REQUIREMENTS,
    MoveRequirement,
    MoveResult,
    TaskListRequirement,
    WriteRequirement,
    WriteResult,
)
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from solveig.schema.results import CommandResult, ReadResult

from .config import SolveigConfig
from .schema.message import AssistantMessage, MessageHistory, UserMessage

SYSTEM_PROMPT = """
You are an AI assisting a user with whatever issues they may have.
Your goal is to be as helpful to the user as possible, and leverage the resources their computer offers to solve their problems.
Always try to answer the user's question, no matter how redundant it may seem.
You may request any of the following operations that you think are necessary:
{CAPABILITIES_LIST}
Put system safety first - explain all operations, prefer file operations over commands, avoid destructive actions unless absolutely necessary.
Plan ahead using tasks lists. If the user rejects a requirement, update your plan and suggest alternatives.
Output your response strictly following the `AssistantMessage` format described below.
"""

SYSTEM_PROMPT_OS_INFO = """
You have access to the following information regarding the user's system:
"""

SYSTEM_PROMPT_EXAMPLES = (
    "Use the following conversation example(s) to guide your expected output format"
)
CONVERSATION_EXAMPLES = []

joke_chat = MessageHistory(
    system_prompt=""
)  # we don't want system prompt for a chat history that itself will be used in our system prompt
# CONVERSATION_EXAMPLES.append(joke_chat)
joke_chat.add_messages(UserMessage(comment="Tell me a joke"))
joke_chat.add_messages(
    AssistantMessage(
        comment="Sure! Here's a joke for you. Why do programmers prefer dark mode? Because light attracts bugs.",
        requirements=[],
    )
)

script_chat = MessageHistory(system_prompt="")
# CONVERSATION_EXAMPLES.append(script_chat)
script_chat.add_messages(UserMessage(comment="What does the script on ~/run.sh do?"))
file_req1 = ReadRequirement(
    metadata_only=True,
    path="~/run.sh",
    comment="To check what this script does, I need to read the contents of run.sh.",
)
script_chat.add_messages(
    AssistantMessage(comment="Of course, let's take a look", requirements=[file_req1])
)
script_chat.add_messages(
    UserMessage(
        comment="Ok here you go",
        results=[
            ReadResult(
                requirement=file_req1,
                path=file_req1.path,
                metadata=Metadata(
                    owner_name="user",
                    group_name="user",
                    path=PurePath("/home/user/run.sh"),
                    size=101,
                    modified_time=int(
                        datetime.fromisoformat("2025-07-17T02:54:43").timestamp()
                    ),
                    is_directory=False,
                    is_readable=True,
                    is_writable=True,
                ),
                accepted=True,
                content="""
#!/usr/bin/env bash
mkdir -p logs tmp
touch logs/app.log
echo "Project initialized." > tmp/init.flag
""".strip(),
            )
        ],
    )
)
script_chat.add_messages(
    AssistantMessage(
        comment="""
This script initializes a project workspace.
This script creates logs/ and tmp/, makes an empty logs/app.log, and writes “Project initialized.” to tmp/init.flag.
It’s safe—no deletions or overwrites.
""".strip(),
        requirements=[],
    )
)

multiple_issues_chat = MessageHistory(system_prompt="")
# CONVERSATION_EXAMPLES.append(multiple_issues_chat)
multiple_issues_chat.add_messages(
    UserMessage(
        comment="""
My computer is slow, can you help me find which processes are using my CPU the most and what my disk usage is?
Also summarize the contents of ~/my_app.log, count how many errors occurred and how serious they look
I'm using Linux
"""
    )
)
cmd_req_cpu_usage = CommandRequirement(
    comment="Run this command to list processes sorted by CPU usage",
    command="ps aux --sort=-%cpu | head -n 10",
)
cmd_req_disk_usage = CommandRequirement(
    comment="Run this to see overall disk usage per mounted filesystem", command="df -h"
)
file_req_large_dirs = ReadRequirement(
    comment="If you also want to see which directories are largest in your home folder",
    path="~",
    metadata_only=True,
)
file_req_log = ReadRequirement(
    comment="I need to access the log to analyze it",
    path="~/Documents/my_app.log",
    metadata_only=False,
)
multiple_issues_chat.add_messages(
    AssistantMessage(
        comment="Sure! Let’s check these step by step.",
        requirements=[
            cmd_req_cpu_usage,
            cmd_req_disk_usage,
            file_req_large_dirs,
            file_req_log,
        ],
    )
)
multiple_issues_chat.add_messages(
    UserMessage(
        comment="Here you go. I don't think it's necessary to get the metadata for my home folder, but you can have the rest",
        results=[
            CommandResult(
                requirement=cmd_req_cpu_usage,
                command=cmd_req_cpu_usage.command,
                accepted=True,
                stdout="""
USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
jdoe        8421 95.7  4.2 905312 342816 ?       Rl   09:13  10:44 /opt/firefox/firefox
jdoe        9154 28.9  1.8 732448 146232 ?       Sl   09:26   2:12 /usr/bin/python3 /home/jdoe/projects/scraper.py
root        1203 18.4  0.9 255280  72012 ?       Ssl  07:45   7:03 /usr/lib/Xorg vt1 -displayfd 3
(...)
""",
                success=True,
            ),
            CommandResult(
                requirement=cmd_req_disk_usage,
                command=cmd_req_disk_usage.command,
                accepted=True,
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
                success=True,
            ),
            ReadResult(
                requirement=file_req_large_dirs,
                path=file_req_large_dirs.path,
                accepted=False,
            ),
            ReadResult(
                requirement=file_req_log,
                path=file_req_log.path,
                accepted=True,
                metadata=Metadata(
                    owner_name="user",
                    group_name="user",
                    path=PurePath("/home/user/Documents/my_app.log"),
                    size=11180,
                    modified_time=int(
                        datetime.fromisoformat("2025-07-16T12:59:44").timestamp()
                    ),
                    is_directory=False,
                    is_readable=True,
                    is_writable=True,
                ),
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
""",
            ),
        ],
    )
)
multiple_issues_chat.add_messages(
    AssistantMessage(
        comment="""
I understand. Based on the information you've shared, Firefox is using a lot of your CPU and could be responsible for it being slow.
The file ~/my_app.log shows that someone tried to login as 'admin' around 09:12, but failed. Around the same time there was also a failed payment transaction.
"""
    )
)


large_example = MessageHistory(system_prompt="")
CONVERSATION_EXAMPLES.append(large_example)

task_list_1 = TaskListRequirement(
    comment="I will first read the contents of ~/Sync, then individual files",
    tasks=[
        Task(description="Read the contents of ~/Sync", status="in_progress"),
        Task(description="Read suspicious files inside ~/Sync"),
        Task(
            description="Provide a summary of contents, focused on safety and functionality"
        ),
    ],
)
tree_req = TreeRequirement(
    comment="I'll analyze the tree structure of ~/Sync",
    path="~/Sync",
)
tree_metadata = Metadata(
    owner_name="user",
    group_name="user",
    path=PurePath("/home/user/Sync"),
    size=4096,
    is_directory=True,
    is_readable=True,
    is_writable=True,
    modified_time=1758556702,
    encoding=None,
    listing={
        PurePath("/home/user/Sync/config.json"): Metadata(
            owner_name="user",
            group_name="user",
            path=PurePath("/home/user/Sync/config.json"),
            size=132,
            is_directory=False,
            is_readable=True,
            is_writable=True,
            modified_time=1758556681,
            encoding=None,
            listing=None,
        ),
        PurePath("/home/user/Sync/d1"): Metadata(
            owner_name="user",
            group_name="user",
            path=PurePath("/home/user/Sync/d1"),
            size=4096,
            is_directory=True,
            is_readable=True,
            is_writable=True,
            modified_time=1758556735,
            encoding=None,
            listing={
                PurePath("/home/user/Sync/d1/d2"): Metadata(
                    owner_name="user",
                    group_name="user",
                    path=PurePath("/home/user/Sync/d1/d2"),
                    size=4096,
                    is_directory=True,
                    is_readable=True,
                    is_writable=True,
                    modified_time=1758556743,
                    encoding=None,
                    listing={
                        PurePath("/home/user/Sync/d1/d2/f1"): Metadata(
                            owner_name="user",
                            group_name="user",
                            path=PurePath("/home/user/Sync/d1/d2/f1"),
                            size=446,
                            is_directory=False,
                            is_readable=True,
                            is_writable=True,
                            modified_time=1758556767,
                            encoding=None,
                            listing=None,
                        )
                    },
                )
            },
        ),
        PurePath("/home/user/Sync/dev.sh"): Metadata(
            owner_name="user",
            group_name="user",
            path=PurePath("/home/user/Sync/dev.sh"),
            size=101,
            is_directory=False,
            is_readable=True,
            is_writable=True,
            modified_time=1753389917,
            encoding=None,
            listing=None,
        ),
        PurePath("/home/user/Sync/hello.py"): Metadata(
            owner_name="user",
            group_name="user",
            path=PurePath("/home/user/Sync/hello.py"),
            size=45,
            is_directory=False,
            is_readable=True,
            is_writable=True,
            modified_time=1753134710,
            encoding=None,
            listing=None,
        ),
    },
)


large_example.add_messages(
    UserMessage(
        comment="Hey I don't recognize the contents of ~/Sync, can you take a look to see if it looks suspicious?",
    ),
    AssistantMessage(
        comment="I'll help you understand what ~/Sync contains",
        requirements=[
            task_list_1,
            tree_req,
        ],
    ),
    UserMessage(
        comment="Here you go",
        results=[
            TaskListResult(
                requirement=task_list_1,
                accepted=True,
                tasks=task_list_1.tasks,
            ),
            TreeResult(
                requirement=tree_req,
                accepted=True,
                path=PurePath("/home/user/Sync/"),
                metadata=tree_metadata,
            ),
        ],
    ),
)


task_list_2 = TaskListRequirement(
    comment="I've identified the most concerning files inside ~/Sync, I'll now read their contents",
    tasks=[
        Task(description="Read the contents of ~/Sync", status="completed"),
        Task(
            description="Read suspicious files inside ~/Sync",
            status="completed",
        ),
        Task(
            description="Provide a summary of contents, focused on safety and functionality",
            status="in_progress",
        ),
    ],
)
read_hello_py_req = ReadRequirement(
    comment="", path="~/Sync/hello.py", metadata_only=False
)
read_dev_sh_req = ReadRequirement(comment="", path="~/Sync/dev.sh", metadata_only=False)
large_example.add_messages(
    AssistantMessage(
        comment="""
It seems there are several files, the most relevant may be some .py and .sh scripts. Let me read these. There is also a .sh.bak file, it does not have execution permissions, but let me also read it.
        """,
        requirements=[
            task_list_1,
            read_hello_py_req,
            read_dev_sh_req,
        ],
    ),
    UserMessage(
        results=[
            TaskListResult(
                requirement=task_list_2, accepted=True, tasks=task_list_2.tasks
            ),
            ReadResult(
                requirement=read_hello_py_req,
                path=PurePath("/home/user/Sync/hello.py"),
                accepted=True,
                metadata=Metadata(
                    owner_name="user",
                    group_name="user",
                    path=PurePath("/home/user/Sync/hello.py"),
                    size=45,
                    is_directory=False,
                    is_readable=True,
                    is_writable=True,
                    modified_time=1756916648,
                    encoding=None,
                    listing=None,
                ),
            ),
            ReadResult(
                requirement=read_dev_sh_req,
                content="""
#!/bin/python
print("Hello, world!")
                """.strip(),
                path=PurePath("/home/user/Sync/dev.sh"),
                accepted=True,
                metadata=Metadata(
                    owner_name="user",
                    group_name="user",
                    path=PurePath("/home/user/Sync/dev.sh"),
                    size=101,
                    is_directory=False,
                    is_readable=True,
                    is_writable=True,
                    modified_time=1753389917,
                    encoding=None,
                    listing=None,
                ),
            ),
        ]
    ),
)

task_list_3 = TaskListRequirement(
    comment="I've analyzed the contents of ~/Sync and everything seems safe",
    tasks=[
        Task(description="Read the contents of ~/Sync", status="completed"),
        Task(
            description="Read suspicious files inside ~/Sync",
            status="completed",
        ),
        Task(
            description="Provide a summary of contents, focused on safety and functionality",
            status="completed",
        ),
    ],
)
large_example.add_messages(
    AssistantMessage(
        comment="""
This directory seems safe - ~/Sync/hello.py is a basic print script, while dev.sh and run.sh.bak are both simple project initialization scripts with the same contents.
        """,
        requirements=[
            task_list_3,
        ],
    ),
    UserMessage(
        comment="Thanks! Can you improve that print script to accept CLI args with a default?",
        results=[
            TaskListResult(
                requirement=task_list_1, accepted=True, tasks=task_list_3.tasks
            )
        ],
    ),
)

task_list_4 = TaskListRequirement(
    comment="Improve print utilities in project inside /home/user/Sync",
    tasks=[
        Task(
            description="Analyze and explain the contents of /home/user/Sync",
            status="completed",
        ),
        Task(description="Write new print script", status="in_progress"),
        Task(description="Test new print script", status="pending"),
    ],
)
write_script_req = WriteRequirement(
    comment="Write a better print script",
    path="~/Sync/hello_new.py",
    content="""
import sys

def run():
    try:
        name = sys.argv[1]
    except IndexError:
        name = "world"
    print(f"Hello, {name}!")

if __name__ == "__main__":
    run()
    """.strip(),
    is_directory=False,
)
script_command_req = CommandRequirement(
    comment="Now execute it to make sure it works correctly",
    command="python ~/Sync/hello_new.py;\npython ~/Sync/hello_new.py 'Solveig'",
)
large_example.add_messages(
    AssistantMessage(
        comment="I'll write and test an improved print script.",
        requirements=[
            task_list_4,
            write_script_req,
            script_command_req,
        ],
    ),
    UserMessage(
        comment="Cool, it works! Thanks, can you clean up the old file now?",
        results=[
            TaskListResult(
                requirement=task_list_4,
                accepted=True,
                tasks=task_list_4.tasks,
            ),
            WriteResult(
                requirement=write_script_req,
                path=PurePath("/home/user/Sync/hello_new.py"),
                accepted=True,
            ),
            CommandResult(
                requirement=script_command_req,
                accepted=True,
                command=script_command_req.command,
                stdout="""
Hello, world!
Hello, Solveig!
                """.strip(),
            ),
        ],
    ),
)

task_list_4 = TaskListRequirement(
    comment="Improve project in /home/user/Sync/ and delete old files",
    tasks=[
        Task(
            description="Analyze and explain the contents of /home/user/Sync/",
            status="completed",
        ),
        Task(description="Write and test new print script", status="completed"),
        Task(description="Delete old print script", status="in_progress"),
        Task(description="Re-name the new print script", status="in_progress"),
    ],
)
script_delete_move_req = CommandRequirement(
    comment="Delete a script from /home/user/Sync/ and re-name the old one",
    command="rm /home/user/Sync/hello.py; mv /home/user/Sync/hello_new.py /home/user/Sync/hello.py",
)
large_example.add_messages(
    AssistantMessage(
        comment="Of course! I'll delete the old script and re-name the new one",
        requirements=[
            task_list_4,
            script_delete_move_req,
        ],
    ),
    UserMessage(
        comment="I'd rather use a simple move operation for this",
        results=[
            TaskListResult(
                requirement=task_list_4,
                accepted=True,
                tasks=task_list_4.tasks,
            ),
            CommandResult(
                requirement=script_delete_move_req,
                accepted=False,
                command=script_command_req.command,
            ),
        ],
    ),
)

task_list_5 = TaskListRequirement(
    comment="Improve project in /home/user/Sync/ and delete old files",
    tasks=[
        Task(description="Write and test new print script", status="completed"),
        Task(description="Re-name new print script with command", status="failed"),
        Task(
            description="Over-write old print script with improved one",
            status="in_progress",
        ),
    ],
)
script_move_req = MoveRequirement(
    comment="Over-write old print script with improved one",
    source_path="~/Sync/hello_new.py",
    destination_path="~/Sync/hello.py",
)
large_example.add_messages(
    AssistantMessage(
        comment="I apologize, I'll use a move requirement instead",
        requirements=[
            task_list_5,
            script_move_req,
        ],
    ),
    UserMessage(
        comment="Great, thanks!",
        results=[
            TaskListResult(
                requirement=task_list_5,
                accepted=True,
                tasks=task_list_5.tasks,
            ),
            MoveResult(
                requirement=script_move_req,
                accepted=True,
                source_path=script_move_req.source_path,
                destination_path=script_move_req.destination_path,
            ),
        ],
    ),
)


def get_basic_os_info(exclude_username=False):
    info = {
        "os_name": platform.system(),  # e.g., 'Linux', 'Windows', 'Darwin'
        "os_release": platform.release(),  # e.g., '6.9.1-arch1-1'
        "os_version": platform.version(),  # detailed kernel version
    }
    # Add username and home path
    if not exclude_username:
        info["cwd"] = os.getcwd()
        info["username"] = (
            os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USER")
        )
        info["home_dir"] = os.path.expanduser("~")
    # Add distro info if we're in Linux
    if info["os_name"] == "Linux" and distro:
        info["linux_distribution"] = distro.name(pretty=True)  # e.g. 'Manjaro Linux'
    return info


def get_available_capabilities(config: SolveigConfig) -> str:
    """Generate capabilities list from currently filtered requirements."""
    # Get ALL active requirements from the unified registry (core + plugins)
    active_requirements = list(REQUIREMENTS.registered.values())
    return "\n".join(
        f"- {req_class.get_description()}"
        for req_class in active_requirements
        if req_class != CommandRequirement or not config.no_commands
    )


def get_system_prompt(config: SolveigConfig):
    # Generate dynamic capabilities list
    capabilities_list = get_available_capabilities(config)
    system_prompt = SYSTEM_PROMPT.strip().replace(
        "{CAPABILITIES_LIST}", capabilities_list
    )

    if config.add_os_info:
        os_info = get_basic_os_info(config.exclude_username)
        system_prompt = (
            f"{system_prompt}\n\n{SYSTEM_PROMPT_OS_INFO.strip()}\n"
            + "\n ".join(f"{k}: {v}" for k, v in os_info.items())
        ).strip()
    if config.add_examples:
        system_prompt = (
            f"{system_prompt}\n\n{SYSTEM_PROMPT_EXAMPLES.strip()}\n"
            + "\n\n".join([history.to_example() for history in CONVERSATION_EXAMPLES])
        )
    return system_prompt.strip()
