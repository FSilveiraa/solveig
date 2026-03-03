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
    # Info
    name="terracotta",
    # UI
    background="#231D13",  # dark greyish brown
    group="#869F89",  # pale green
    section="#BE5856",  # clay red
    box="#CB9D63",  # faded yellow
    input="#CB9D63",  # faded yellow
    # Messages
    text="#FFF1DB",  # beige
    info="#CB9D63",  # faded yellow
    warning="#BC8F8F",  # rosy brown
    error="#BE5856",  # clay red
)


solarized_dark = Palette(
    # Info
    name="solarized-dark",
    # UI
    background="#002b36",  # base3
    group="#859900",  # green
    section="#D33682",  # magenta
    box="#268bd2",  # blue
    input="#2aa198",  # cyan
    text="#839496",  # base0
    info="#2aa198",  # cyan
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
    # Info
    name="midnight",
    # UI
    background="#121414",  # dark grey
    group="#675DA6",  # brighter purple
    section="#3B679C",  # sky blue
    box="#A46A73",  # low-contrast pink
    input="#3B679C",  # bright blue
    # Messages
    text="#e0e0e0",  # light grey
    info="#9FC7F0",  # bright blue
    warning="#f39800",  # amber
    error="#e94560",  # bright pink
)


nord = Palette(
    name="nord",
    background="#2E3440",  # polar night - dark blue-grey
    group="#88C0D0",  # frost - light cyan
    section="#5E81AC",  # frost - deep blue
    box="#4C566A",  # polar night - lighter panel
    input="#5E81AC",  # frost - deep blue
    text="#ECEFF4",  # snow storm - near white
    info="#88C0D0",  # frost - light cyan
    warning="#EBCB8B",  # aurora - yellow
    error="#BF616A",  # aurora - red
)

rose = Palette(
    name="rose",
    background="#FAF0F0",  # blush white
    group="#A8547A",  # deep rose
    section="#D4688E",  # medium pink
    box="#E8C4D0",  # light dusty rose panel
    input="#D4688E",  # medium pink
    text="#3D2030",  # dark plum
    info="#A8547A",  # deep rose
    warning="#C87941",  # warm amber
    error="#B02828",  # deep crimson
)

monochrome = Palette(
    name="monochrome",
    background="#111111",  # near black
    group="#888888",  # mid grey
    section="#CCCCCC",  # light grey
    box="#2A2A2A",  # dark panel
    input="#CCCCCC",  # light grey
    text="#E8E8E8",  # off white
    info="#AAAAAA",  # silver
    warning="#DDDDDD",  # bright grey
    error="#FFFFFF",  # pure white
)


DEFAULT_THEME = terracotta
THEMES = {
    theme.name: theme
    for theme in [
        terracotta,
        solarized_dark,
        solarized_light,
        forest,
        midnight,
        nord,
        rose,
        monochrome,
    ]
}

from pygments.styles import STYLE_MAP

DEFAULT_CODE_THEME = "coffee"
CODE_THEMES = set(STYLE_MAP.keys())
