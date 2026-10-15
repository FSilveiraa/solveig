from __future__ import annotations

from dataclasses import dataclass


# `init=False` ensures the dataclass doesn't auto-generate an __init__.
# Without it, we'd be forced to instantiate with `CliFlags(["-u", "--url"])`
#  instead of `CliFlags("-u", "--url")`
@dataclass(frozen=True, slots=True, init=False)
class CliFlags:
    flags: tuple[str, ...]

    def __init__(self, *flags) -> None:
        # NOTE: Not a real hack, this is the documented way to expose an alternative
        #  constructor with a frozen dataclass. The alternative is using `.of(*flags)`
        object.__setattr__(self, "flags", flags)

    def to_argparse(self) -> list[str]:
        return [
            (f"{'-' if len(flag) == 1 else '--'}{flag.replace('_', '-')}")
            for flag in self.flags
        ]
