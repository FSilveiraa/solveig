from dataclasses import asdict, dataclass

from prompt_toolkit.styles import Style


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

    def to_prompt_toolkit_style(self):
        style_dict = {k: ("" if v == "reset" else v) for k, v in asdict(self).items()}
        style_dict.pop("name")
        style_dict[""] = "" if self.text == "reset" else self.text
        return Style.from_dict(style_dict)


no_theme = Palette(
    name="none",
    background="",
    text="",  # light grey
    prompt="",  # powder blue
    box="",  # pink
    group="",  # light blue
    section="",  # powder blue
    warning="",  # orange
    error="",  # orange
)


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
    background="#002b36",
    text="#839496",  # base0
    prompt="#2aa198",  # cyan
    box="#268bd2",  # blue
    group="#859900",  # green #
    section="#D33682",  # magenta
    warning="#B58900",  # yellow
    error="#dc322f",  # red (more visible than orange)
)


solarized_light = Palette(
    name="solarized-light",
    background="#FDF6E3",  # base3
    text="#586E75",  # base01
    prompt="#2aa198",  # cyan
    box="#268bd2",  # blue
    group="#859900",  # green
    section="#D33682",  # magenta
    warning="#B58900",  # yellow
    error="#cb4b16",  # orange
)


forest = Palette(
    name="forest",
    background="#152B21",  # algae green
    text="#d4d4aa",  # sage
    prompt="#87ceeb",  # sky blue
    box="#daa520",  # goldenrod
    group="#90ee90",  # light green
    section="#87ceeb",  # sky blue
    warning="#ff7f50",  # coral
    error="#cd5c5c",  # indian red
)


midnight = Palette(
    name="midnight",
    background="#1a1a2e",
    text="#e94560",  # bright pink
    prompt="#0f3460",  # deep blue
    box="#16213e",  # dark blue-grey
    group="#533483",  # purple
    section="#0f3460",  # deep blue
    warning="#f39800",  # amber
    error="#e94560",  # bright pink
)


vice = Palette(
    name="vice",
    background="#2d1b69",
    text="#ffffff",  # pure white
    prompt="#ff10f0",  # electric magenta
    box="#01cdfe",  # electric blue
    group="#05ffa1",  # electric mint
    section="#ff10f0",  # electric magenta
    warning="#ffff00",  # electric yellow
    error="#ff073a",  # electric red
)


DEFAULT = terracotta
THEMES = {
    theme.name: theme
    for theme in [
        no_theme,
        terracotta,
        solarized_dark,
        solarized_light,
        forest,
        midnight,
        vice,
    ]
}
