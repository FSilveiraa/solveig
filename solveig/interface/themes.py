import dataclasses


@dataclasses.dataclass
class Palette:
    name: str
    text: str
    prompt: str
    box: str
    group: str
    section: str
    warning: str
    error: str


class NoTheme(Palette):
    name = "none"
    text = "reset"  # light grey
    prompt = "reset"  # powder blue
    box = "reset"  # pink
    group = "reset"  # light blue
    section = "reset"  # powder blue
    warning = "reset"  # orange
    error = "reset"  # orange


class Terracotta(Palette):
    # background: #461E52
    name = "terracotta"
    text = "#FFF1DB"  # beige
    prompt = "#DA9842"  # burnt yellow
    box = "#BC8F8F"  # rosy brown
    group = "#869F89"  # pale green
    section = "#DA9842"  # burnt yellow
    warning = "#BE5856"  # clay red
    error = "#BE5856"  # clay red


class Vercetti(Palette):
    # background: #8E7266
    name = "vercetti"
    text = "#EAEAEA"  # light grey
    prompt = "#556CC9"  # powder blue
    box = "#DD517E"  # pink
    group = "#7A98EE"  # light blue
    section = "#556CC9"  # powder blue
    warning = "#E68E35"  # orange
    error = "#E68E35"  # orange


class Solarized(Palette):
    # background: #002b36
    name = "solarized"
    text = "#839496"  # base0
    prompt = "#268bd2"  # blue
    box = "#d33682"  # magenta
    group = "#2aa198"  # cyan
    section = "#268bd2"  # blue
    warning = "#cb4b16"  # orange
    error = "#dc322f"  # red


class Forest(Palette):
    # background: #1e3a2e
    name = "forest"
    text = "#d4d4aa"  # sage
    prompt = "#87ceeb"  # sky blue
    box = "#daa520"  # goldenrod
    group = "#90ee90"  # light green
    section = "#87ceeb"  # sky blue
    warning = "#ff7f50"  # coral
    error = "#cd5c5c"  # indian red


class Midnight(Palette):
    # background: #1a1a2e
    name = "midnight"
    text = "#e94560"  # bright pink
    prompt = "#0f3460"  # deep blue
    box = "#16213e"  # dark blue-grey
    group = "#533483"  # purple
    section = "#0f3460"  # deep blue
    warning = "#f39800"  # amber
    error = "#e94560"  # bright pink


class Vice(Palette):
    # background: #2d1b69
    name = "vice"
    text = "#ffffff"  # pure white
    prompt = "#ff10f0"  # electric magenta
    box = "#01cdfe"  # electric blue
    group = "#05ffa1"  # electric mint
    section = "#ff10f0"  # electric magenta
    warning = "#ffff00"  # electric yellow
    error = "#ff073a"  # electric red


DEFAULT = Terracotta
THEMES = {
    theme.name: theme
    for theme in {NoTheme, Terracotta, Vercetti, Solarized, Forest, Midnight, Vice}
}
