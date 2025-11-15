from dataclasses import dataclass


@dataclass
class Palette:
    # Info
    name: str

    # UI
    background: str
    group: str
    section: str
    box: str
    input: str

    # Messages
    text: str
    info: str
    warning: str
    error: str


# no_theme = Palette(
#     name="none",
#     background="auto",
#     text="auto",  # light grey
#     prompt="auto",  # powder blue
#     box="auto",  # pink
#     group="auto",  # light blue
#     section="auto",  # powder blue
#     warning="auto",  # orange
#     error="auto",  # orange
# )


terracotta = Palette(
    name="terracotta",
    background="#231D13",  # dark greyish brown
    text="#FFF1DB",  # beige
    input="#CB9D63",  # faded yellow
    box="#CB9D63",  # faded yellow
    info="#CB9D63",
    group="#869F89",  # pale green
    section="#BE5856",  # clay red
    warning="#BC8F8F",  # rosy brown
    error="#BE5856",  # clay red
)


solarized_dark = Palette(
    name="solarized-dark",
    background="#002b36",  # base3
    text="#839496",  # base0
    input="#2aa198",  # cyan
    info="#2aa198",  # cyan
    box="#268bd2",  # blue
    group="#859900",  # green
    section="#D33682",  # magenta
    warning="#B58900",  # yellow
    error="#CB4B16",  # orange
)


solarized_light = Palette(
    name="solarized-light",
    background="#fdf6e3",  # base3
    text="#657b83",  # base00
    input="#268bd2",  # blue
    info="#268bd2",  # blue
    # box="#93a1a1",         # base1 (subtle grey)
    box="#D33682",  # violet
    group="#859900",  # green
    # section="#586e75",     # base01 (muted grey-blue)
    section="#2aa198",  # cyan
    warning="#b58900",  # yellow
    error="#CB4B16",  # orange
)


forest = Palette(
    name="forest",
    background="#13261C",  # algae green
    text="#d4d4aa",  # sage
    input="#87ceeb",  # sky blue
    info="#87ceeb",  # sky blue
    box="#daa520",  # goldenrod
    group="#87AC87",  # light green
    section="#93AFBA",  # sky blue
    warning="#ff7f50",  # coral
    error="#cd5c5c",  # indian red
)


midnight = Palette(
    name="midnight",
    background="#121414",  # dark grey
    text="#e0e0e0",  # light grey
    input="#9FC7F0",  # bright blue
    info="#9FC7F0",  # bright blue
    box="#A46A73",  # low-contrast pink
    group="#675DA6",  # brighter purple
    section="#3B679C",  # sky blue
    warning="#f39800",  # amber
    error="#e94560",  # bright pink
)


# vice = Palette(
#     name="vice",
#     background="#2d1b69",
#     text="#ffffff",  # pure white
#     prompt="#ff10f0",  # electric magenta
#     box="#01cdfe",  # electric blue
#     group="#05ffa1",  # electric mint
#     section="#ff10f0",  # electric magenta
#     warning="#ffff00",  # electric yellow
#     error="#ff073a",  # electric red
# )


DEFAULT_THEME = terracotta
THEMES = {
    theme.name: theme
    for theme in [
        terracotta,
        solarized_dark,
        solarized_light,
        forest,
        midnight,
        # vice,
    ]
}

from pygments.styles import STYLE_MAP

DEFAULT_CODE_THEME = "coffee"
CODE_THEMES = set(STYLE_MAP.keys())
