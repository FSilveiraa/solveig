import os
import platform

from .plugins.schema.tree import TreeRequirement, TreeResult
from .utils.file import Metadata

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None  # type: ignore

# TODO: Make conversation examples dynamic rather than hardcoded
from solveig.schema import REQUIREMENTS
from solveig.schema.requirements import (
    CommandRequirement,
    MoveRequirement,
    ReadRequirement,
    TaskListRequirement,
    WriteRequirement,
)
from solveig.schema.results import (
    CommandResult,
    MoveResult,
    ReadResult,
    Task,
    TaskListResult,
    WriteResult,
)

from .config import SolveigConfig
from .schema.message import AssistantMessage, MessageHistory, UserMessage

SYSTEM_PROMPT = """
You are an AI assisting a user with their problems.
First, analyze the conversation and determine if you need to perform any extra operations.
For direct answers, respond immediately with the required information in the task-list comment.
You may also request any of the following operations:
{CAPABILITIES_LIST}
Use `tasks` to plan multi-step operations in a task list or to communicate with user. Adapt your plan to failure or user denial.
Use the `tasks` comment field to provide answers or explanations alongside operational work.
Put system safety first - explain operations, prefer file operations over commands, avoid destructive actions unless necessary.
"""

SYSTEM_PROMPT_OS_INFO = """
You have access to the following information regarding the user's system:
"""

SYSTEM_PROMPT_EXAMPLES = (
    "Use the following conversation example(s) to guide your expected output format"
)
CONVERSATION_EXAMPLES = []

# joke_chat = MessageHistory(
#     system_prompt=""
# )  # we don't want system prompt for a chat history that itself will be used in our system prompt
# CONVERSATION_EXAMPLES.append(joke_chat)
# joke_chat.add_messages(UserMessage(comment="Tell me a joke"))
# joke_chat.add_messages(
#     AssistantMessage(requirements=[
#         TaskListRequirement(comment="Sure! Here's a joke for you. Why do programmers prefer dark mode? Because light attracts bugs.",)
#     ])
# )
#
# script_chat = MessageHistory(system_prompt="")
# # CONVERSATION_EXAMPLES.append(script_chat)
# script_chat.add_messages(UserMessage(comment="What does the script on ~/run.sh do?"))
# file_req1 = ReadRequirement(
#     metadata_only=True,
#     path="~/run.sh",
#     comment="To check what this script does, I need to read the contents of run.sh.",
# )
# script_chat.add_messages(
# AssistantMessage(requirements=[
#         TaskListRequirement(
#             comment="Of course, let's take a look",
#             tasks=[
#                 Task(description="Check scripts", status="in_progress"),
#                 Task(description="Explain script contents to user", status="pending"),
#
#             ]
#         ),
#     ])
# )
# script_chat.add_messages(
#     UserMessage(
#         comment="Ok here you go",
#         results=[
#             ReadResult(
#                 requirement=file_req1,
#                 path=file_req1.path,
#                 metadata=Metadata(
#                     owner_name="user",
#                     group_name="user",
#                     path=PurePath("/home/user/run.sh"),
#                     size=101,
#                     modified_time=int(
#                         datetime.fromisoformat("2025-07-17T02:54:43").timestamp()
#                     ),
#                     is_directory=False,
#                     is_readable=True,
#                     is_writable=True,
#                 ),
#                 accepted=True,
#                 content="""
# #!/usr/bin/env bash
# mkdir -p logs tmp
# touch logs/app.log
# echo "Project initialized." > tmp/init.flag
# """.strip(),
#             )
#         ],
#     )
# )
# script_chat.add_messages(
#     AssistantMessage(requirements=[
#             TaskListRequirement(
#                 comment="""
# This script initializes a project workspace.
# This script creates logs/ and tmp/, makes an empty logs/app.log, and writes “Project initialized.” to tmp/init.flag.
# It’s safe—no deletions or overwrites.
# """.strip()
#             )
#     ])
# )


large_example = MessageHistory(system_prompt="")
CONVERSATION_EXAMPLES.append(large_example)

task_list_1 = TaskListRequirement(
    comment="Ok, I will first read the contents of ~/Sync, then individual files",
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
    path="/home/user/Sync",
    size=4096,
    is_directory=True,
    is_readable=True,
    is_writable=True,
    modified_time=1758556702,
    encoding=None,
    listing={
        "/home/user/Sync/config.json": Metadata(
            owner_name="user",
            group_name="user",
            path="/home/user/Sync/config.json",
            size=132,
            is_directory=False,
            is_readable=True,
            is_writable=True,
            modified_time=1758556681,
            encoding=None,
            listing=None,
        ),
        "/home/user/Sync/d1": Metadata(
            owner_name="user",
            group_name="user",
            path="/home/user/Sync/d1",
            size=4096,
            is_directory=True,
            is_readable=True,
            is_writable=True,
            modified_time=1758556735,
            encoding=None,
            listing={
                "/home/user/Sync/d1/d2": Metadata(
                    owner_name="user",
                    group_name="user",
                    path="/home/user/Sync/d1/d2",
                    size=4096,
                    is_directory=True,
                    is_readable=True,
                    is_writable=True,
                    modified_time=1758556743,
                    encoding=None,
                    listing={
                        "/home/user/Sync/d1/d2/f1": Metadata(
                            owner_name="user",
                            group_name="user",
                            path="/home/user/Sync/d1/d2/f1",
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
        "/home/user/Sync/init.sh": Metadata(
            owner_name="user",
            group_name="user",
            path="/home/user/Sync/init.sh",
            size=101,
            is_directory=False,
            is_readable=True,
            is_writable=True,
            modified_time=1753389917,
            encoding=None,
            listing=None,
        ),
        "/home/user/Sync/hello.py": Metadata(
            owner_name="user",
            group_name="user",
            path="/home/user/Sync/hello.py",
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
                path="/home/user/Sync/",
                metadata=tree_metadata,
            ),
        ],
    ),
)


task_list_2 = TaskListRequirement(
    comment="It seems there are several files, the most relevant may be some .py and .sh scripts. Let me read these. There is also a .sh.bak file, it does not have execution permissions, but let me also read it.",
    tasks=[
        Task(description="Read the contents of ~/Sync", status="completed"),
        Task(description="Read suspicious files inside ~/Sync", status="in_progress"),
        Task(
            description="Provide a summary of contents, focused on safety and functionality"
        ),
    ],
)
read_hello_py_req = ReadRequirement(
    comment="", path="~/Sync/hello.py", metadata_only=False
)
read_dev_sh_req = ReadRequirement(
    comment="", path="~/Sync/init.sh", metadata_only=False
)
large_example.add_messages(
    AssistantMessage(
        requirements=[
            task_list_2,
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
                path="/home/user/Sync/hello.py",
                accepted=True,
                metadata=Metadata(
                    owner_name="user",
                    group_name="user",
                    path="/home/user/Sync/hello.py",
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
#!/usr/bin/env bash
mkdir -p logs tmp
touch logs/app.log
echo "Project initialized." > tmp/init.flag
                """.strip(),
                path="/home/user/Sync/init.sh",
                accepted=True,
                metadata=Metadata(
                    owner_name="user",
                    group_name="user",
                    path="/home/user/Sync/init.sh",
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
    comment="This directory seems safe - ~/Sync/hello.py is a basic print script, while init.sh initializes a sample project.",
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
    comment="Of course! I'll write and test an improved print script inside /home/user/Sync",
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
#!/bin/python
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
    timeout=10,
)
large_example.add_messages(
    AssistantMessage(
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
                path="/home/user/Sync/hello_new.py",
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

task_list_5 = TaskListRequirement(
    comment="I'll delete the old script and re-name the new one",
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
    timeout=10,
)
large_example.add_messages(
    AssistantMessage(
        requirements=[
            task_list_5,
            script_delete_move_req,
        ],
    ),
    UserMessage(
        comment="I'd rather use a simple move operation for this",
        results=[
            TaskListResult(
                requirement=task_list_5,
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

task_list_6 = TaskListRequirement(
    comment="I apologize, I'll use a move operation instead of a command",
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
        requirements=[
            task_list_6,
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
