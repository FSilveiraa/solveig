from dataclasses import asdict, dataclass


@dataclass
class Palette:
    name: str
    background: str
    text: str
    prompt: str
    box: str
    group: str
    section: str
    warning: str
    error: str

    def to_textual_css(self) -> dict:
        """Generate Textual CSS rules from palette colors."""
        palette_dict = asdict(self)
        palette_dict.pop("name")  # Remove name field
        return dict(palette_dict.items())
        # for field_name, color in palette_dict.items():
        #     if color:  # Skip empty colors
        #         css_rules.append(f".{field_name}_message {{ color: {color}; }}")
        #
        # return "\n".join(css_rules)


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
    background="#221A0F",  # dark brown
    text="#FFF1DB",  # beige
    prompt="#CB9D63",  # faded yellow
    box="#CB9D63",  # faded yellow
    group="#869F89",  # pale green
    section="#BE5856",  # clay red
    warning="#BC8F8F",  # rosy brown
    error="#BE5856",  # clay red
)


solarized_dark = Palette(
    name="solarized-dark",
    background="#002b36",  # base3
    text="#839496",  # base0
    prompt="#2aa198",  # cyan
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
    prompt="#268bd2",  # blue
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
    prompt="#87ceeb",  # sky blue
    box="#daa520",  # goldenrod
    group="#87AC87",  # light green
    section="#93AFBA",  # sky blue
    warning="#ff7f50",  # coral
    error="#cd5c5c",  # indian red
)


midnight = Palette(
    name="midnight",
    background="#11111A",  # dark greyish blue
    text="#e0e0e0",  # light grey
    prompt="#4a9eff",  # bright blue
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

DEFAULT_CODE_THEME = "material"
CODE_THEMES = set(STYLE_MAP.keys())
