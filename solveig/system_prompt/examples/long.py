"""Longer example conversation shown in the system prompt when `--ex` is set.

Tool calls themselves are native function-calling now, so there's nothing to
demonstrate about their shape here - this example is purely about the
assistant's comment style and use of `update_tasks` to narrate a task plan.
"""

EXAMPLE = """user: Hey I don't recognize the contents of ~/Sync, can you take a look to see if it looks suspicious?
assistant: Ok, I will first read the contents of ~/Sync, then individual files
  [calls update_tasks with: Read the contents of ~/Sync (ongoing), Read suspicious files inside ~/Sync (pending), Provide a summary of contents, focused on safety and functionality (pending)]
  [calls read on ~/Sync]
user: Here you go
assistant: It seems there are several files, the most relevant may be some .py and .sh scripts. Let me read these.
  [calls update_tasks with: Read the contents of ~/Sync (completed), Read suspicious files inside ~/Sync (ongoing), Provide a summary of contents (pending)]
  [calls read on ~/Sync/hello.py and ~/Sync/init.sh]
assistant: This directory seems safe - ~/Sync/hello.py is a basic print script, while init.sh initializes a sample project.
  [calls update_tasks with all three tasks marked completed]
user: Thanks! Can you improve that print script to accept CLI args with a default?
assistant: Of course! I'll write and test an improved print script inside ~/Sync
  [calls write on ~/Sync/hello_new.py, then command to run it]
user: Cool, it works! Thanks, can you clean up the old file now?
assistant: I'll delete the old script and re-name the new one
  [calls command to rm the old file and mv the new one into place]
user: I'd rather use a simple move operation for this
assistant: I apologize, I'll use a move operation instead of a command
  [calls move from ~/Sync/hello_new.py to ~/Sync/hello.py]
user: Great, thanks!"""
