from solveig.plugins.tools.tree import TreeResult, TreeTool
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserComment,
)
from solveig.schema.message.assistant import Task
from solveig.schema.message.user import UserMessage
from solveig.schema.result import (
    CommandResult,
    MoveResult,
    ReadResult,
    WriteResult,
)
from solveig.schema.tool import (
    CommandTool,
    MoveTool,
    ReadTool,
    WriteTool,
)
from solveig.utils.file import Metadata

EXAMPLE = MessageHistory(system_prompt="")

tasks_1 = [
    Task(description="Read the contents of ~/Sync", status="ongoing"),
    Task(description="Read suspicious files inside ~/Sync"),
    Task(
        description="Provide a summary of contents, focused on safety and functionality"
    ),
]
tree_req = TreeTool(
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


EXAMPLE.add_messages(
    UserMessage(
        responses=[
            UserComment(
                comment="Hey I don't recognize the contents of ~/Sync, can you take a look to see if it looks suspicious?"
            )
        ]
    ),
    AssistantMessage(
        comment="Ok, I will first read the contents of ~/Sync, then individual files",
        tasks=tasks_1,
        tools=[
            tree_req,
        ],
    ),
    UserMessage(
        responses=[
            UserComment(comment="Here you go"),
            TreeResult(
                tool=tree_req,
                accepted=True,
                path="/home/user/Sync/",
                metadata=tree_metadata,
            ),
        ],
    ),
)


tasks_2 = [
    Task(description="Read the contents of ~/Sync", status="completed"),
    Task(description="Read suspicious files inside ~/Sync", status="ongoing"),
    Task(
        description="Provide a summary of contents, focused on safety and functionality"
    ),
]
read_hello_py_req = ReadTool(comment="", path="~/Sync/hello.py", metadata_only=False)
read_dev_sh_req = ReadTool(comment="", path="~/Sync/init.sh", metadata_only=False)
EXAMPLE.add_messages(
    AssistantMessage(
        comment="It seems there are several files, the most relevant may be some .py and .sh scripts. Let me read these. There is also a .sh.bak file, it does not have execution permissions, but let me also read it.",
        tasks=tasks_2,
        tools=[
            read_hello_py_req,
            read_dev_sh_req,
        ],
    ),
    UserMessage(
        responses=[
            ReadResult(
                tool=read_hello_py_req,
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
                tool=read_dev_sh_req,
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

tasks_3 = [
    Task(description="Read the contents of ~/Sync", status="completed"),
    Task(
        description="Read suspicious files inside ~/Sync",
        status="completed",
    ),
    Task(
        description="Provide a summary of contents, focused on safety and functionality",
        status="completed",
    ),
]
EXAMPLE.add_messages(
    AssistantMessage(
        comment="This directory seems safe - ~/Sync/hello.py is a basic print script, while init.sh initializes a sample project.",
        tasks=tasks_3,
    ),
    UserMessage(
        responses=[
            UserComment(
                comment="Thanks! Can you improve that print script to accept CLI args with a default?"
            )
        ]
    ),
)

tasks_4 = [
    Task(
        description="Analyze and explain the contents of /home/user/Sync",
        status="completed",
    ),
    Task(description="Write new print script", status="ongoing"),
    Task(description="Test new print script", status="pending"),
]
write_script_req = WriteTool(
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
script_command_req = CommandTool(
    comment="Now execute it to make sure it works correctly",
    command="python ~/Sync/hello_new.py;\npython ~/Sync/hello_new.py 'Solveig'",
    timeout=10,
)
EXAMPLE.add_messages(
    AssistantMessage(
        comment="Of course! I'll write and test an improved print script inside /home/user/Sync",
        tasks=tasks_4,
        tools=[
            write_script_req,
            script_command_req,
        ],
    ),
    UserMessage(
        responses=[
            UserComment(
                comment="Cool, it works! Thanks, can you clean up the old file now?"
            ),
            WriteResult(
                tool=write_script_req,
                path="/home/user/Sync/hello_new.py",
                accepted=True,
            ),
            CommandResult(
                tool=script_command_req,
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

tasks_5 = [
    Task(
        description="Analyze and explain the contents of /home/user/Sync/",
        status="completed",
    ),
    Task(description="Write and test new print script", status="completed"),
    Task(description="Delete old print script", status="ongoing"),
    Task(description="Re-name the new print script", status="ongoing"),
]
script_delete_move_req = CommandTool(
    comment="Delete a script from /home/user/Sync/ and re-name the old one",
    command="rm /home/user/Sync/hello.py; mv /home/user/Sync/hello_new.py /home/user/Sync/hello.py",
    timeout=10,
)
EXAMPLE.add_messages(
    AssistantMessage(
        comment="I'll delete the old script and re-name the new one",
        tasks=tasks_5,
        tools=[
            script_delete_move_req,
        ],
    ),
    UserMessage(
        responses=[
            UserComment(comment="I'd rather use a simple move operation for this"),
            CommandResult(
                tool=script_delete_move_req,
                accepted=False,
                command=script_command_req.command,
            ),
        ],
    ),
)

tasks_6 = [
    Task(description="Write and test new print script", status="completed"),
    Task(description="Re-name new print script with command", status="failed"),
    Task(
        description="Over-write old print script with improved one",
        status="ongoing",
    ),
]
script_move_req = MoveTool(
    comment="Over-write old print script with improved one",
    source_path="~/Sync/hello_new.py",
    destination_path="~/Sync/hello.py",
)
EXAMPLE.add_messages(
    AssistantMessage(
        comment="I apologize, I'll use a move operation instead of a command",
        tasks=tasks_6,
        tools=[
            script_move_req,
        ],
    ),
    UserMessage(
        responses=[
            UserComment(comment="Great, thanks!"),
            MoveResult(
                tool=script_move_req,
                accepted=True,
                source_path=script_move_req.source_path,
                destination_path=script_move_req.destination_path,
            ),
        ],
    ),
)
