#!/usr/bin/env python3
"""Run Solveig with mock LLM client instead of real API calls."""
import sys

from scripts.run import main_loop
from solveig import SolveigConfig
from solveig.plugins.schema.tree import TreeRequirement
from solveig.schema.requirements import ReadRequirement, WriteRequirement, CommandRequirement, TaskListRequirement
from solveig.schema.message import LLMMessage
from solveig.schema.results.task import Task
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client

# Define your mock responses here
mock_responses = [
    LLMMessage(
        comment="TEST LONG COMMAND",
        requirements=[
            CommandRequirement(
                comment="LONG COMMAND",
                command="python -m \"import sys\nimport os\nprint(\"Done\")"
            )
        ]
    ),

    LLMMessage(
        comment="I'll help you understand what ~/Sync contains",
        requirements=[
            TaskListRequirement(
                comment="I will first read the contents of ~/Sync, then individual files",
                tasks=[
                    Task(description="Read the contents of ~/Sync", status="in_progress"),
                    Task(description="Read suspicious files inside ~/Sync"),
                    Task(description="Provide a summary of contents, focused on safety and functionality"),
                ]
            ),
            TreeRequirement(
                comment="",
                path="~/Sync",
            ),
        ]
    ),
    LLMMessage(
        comment="""
It seems there are several files, the most relevant may be some .py and .sh scripts. Let me read these. There is also a .sh.bak file, it does not have execution permissions, but let me also read it.
""",
        requirements=[
            TaskListRequirement(
                comment="I've identified the most concerning files inside ~/Sync, I'll now read their contents",
                tasks=[
                    Task(description="Read the contents of ~/Sync", status="completed"),
                    Task(description="Read suspicious files inside ~/Sync", status="in_progress"),
                    Task(description="Provide a summary of contents, focused on safety and functionality"),
                ]
            ),
            ReadRequirement(comment="", path="~/Sync/hello.py", metadata_only=False),
            ReadRequirement(comment="", path="~/Sync/dev.sh", metadata_only=False),
            ReadRequirement(comment="", path="~/Sync/run.sh.bak", metadata_only=False),
        ],
    ),
    LLMMessage(
        comment="""
This directory seems safe - ~/Sync/hello.py is a basic print script, while dev.sh and run.sh.bak are both simple project initialization scripts with the same contents. 
""",
        requirements=[
            TaskListRequirement(
                comment="I've analyzed the contents of ~/Sync and everything seems safe",
                tasks=[
                    Task(description="Read the contents of ~/Sync", status="completed"),
                    Task(description="Read suspicious files inside ~/Sync", status="completed"),
                    Task(description="Provide a summary of contents, focused on safety and functionality", status="completed"),
                ]
            )
        ]
    ),
    LLMMessage(
        comment="""
I'll write and test an improved print script.
""",
        requirements=[
            TaskListRequirement(
                comment="Analyze the contents of ~/Sync, then improve print",
                tasks=[
                    Task(description="Read the contents of ~/Sync", status="completed"),
                    Task(description="Read suspicious files inside ~/Sync", status="completed"),
                    Task(description="Provide a summary of contents, focused on safety and functionality", status="completed"),
                    Task(description="Write new print script", status="in_progress"),
                    Task(description="Test new print script", status="pending"),
                ]
            ),
            WriteRequirement(
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
            ),
            CommandRequirement(
                comment="Now execute it to make sure it works correctly",
                command="python ~/Sync/hello_new.py;\npython ~/Sync/hello_new.py 'Solveig'",
            ),
        ]
    ),
]

def cleanup():
    Filesystem.delete("~/Sync/hello_new.py")


if __name__ == "__main__":
    mock_client = create_mock_client(*mock_responses, sleep_seconds=3)
    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()
        main_loop(config=config, user_prompt=prompt, llm_client=mock_client)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)
    finally:
        try:
            cleanup()
        except FileNotFoundError:
            pass
