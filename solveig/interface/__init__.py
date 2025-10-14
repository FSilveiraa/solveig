"""
Modern interface layer for Solveig.

Provides clean, async-first interfaces for user interaction:

- TextualCLI: Modern terminal interface using Textual
- SolveigInterface: Protocol for implementing new interface types
- AsyncSolveigInterface: Base class for async interfaces

Example usage:
```python
from solveig.interface import TextualCLI

# Create and start interface
cli = TextualCLI()
cli.set_input_callback(handle_user_input)
await cli.start()

# Display messages
cli.display_text("Hello!")
cli.display_success("Operation completed")
cli.display_error("Something went wrong")

# Get specific input
name = await cli.ask_prompt("What's your name?")
confirm = await cli.ask_yes_no("Continue?")
```
"""

from solveig.interface.base import SolveigInterface
from solveig.interface.cli_textual import TextualInterface
from solveig.interface.themes import Palette, terracotta

__all__ = [
    "SolveigInterface",
    "TextualInterface",
    "Palette",
    "terracotta",
]
