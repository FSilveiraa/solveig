"""
Interface layer for Solveig - handles all user interaction and presentation.


You're expected to use the interface with automatic indenting
```
interface = CLIINterface()
interface.section("User")

# automatically enters and exits indent
with interface.group("Input", count=57):
    prompt = interface.ask_user("Message > ") # What time is it?
    with interface.indent():
        interface.show("Sending this:")
        interface.display_text_box(prompt)
    interface.show(f"Sent!")
interface.show("⋆꙳·❅* ‧ ‧*❆ ₊⋆", level=4)
```
Output:
```

─── User ────────────────────────────────────────────
[ Input (57) ]
  Message > What time is it?
    Sending this:
    ┌───────────────────────────────────────────────┐
    │ What time is it?                              │
    └───────────────────────────────────────────────┘
  Sent!
        ⋆꙳·❅* ‧ ‧*❆ ₊⋆
```
"""


class TEXT_BOX:
    # Basic
    H = "─"
    V = "│"
    # Corners
    TL = "┌"  # top-left
    TR = "┐"  # top-right
    BL = "└"  # bottom-left
    BR = "┘"  # bottom-right
    # Junctions
    VL = "┤"
    VR = "├"
    HB = "┬"
    HT = "┴"
    # Cross
    X = "┼"


from .base import SolveigInterface
from .cli import CLIInterface

__all__ = ["SolveigInterface", "CLIInterface"]
