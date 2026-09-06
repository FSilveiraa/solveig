from dataclasses import dataclass

from pygments.styles import STYLE_MAP
from textual.color import Color
from textual.theme import Theme as TextualTheme


@dataclass(frozen=True)
class Palette:
    # Info
    name: str

    # Textual properties
    background: Color
    foreground: Color
    primary: Color
    accent: Color
    warning: Color
    error: Color

    # Custom roles
    border: Color
    group: Color
    input: Color

    @property
    def is_dark(self) -> bool:
        """Whether this is a dark theme."""
        return self.background.brightness < 0.5

    @property
    def group_pending(self) -> Color:
        """
        Derives a pending group's tail color from blending the group
        border's color with the background.
        """
        return self.group.blend(self.background, 0.5)

    @property
    def background_user(self) -> Color:
        """
        Derives the background color for user comments from the background.
        """
        shift = 0.08
        return self.background.lighten(shift) if self.is_dark else self.background.darken(shift)

    def to_textual_theme(self) -> TextualTheme:
        """A registered Textual `Theme` mirroring a `Palette`. The standard slots
        (background/foreground/primary/warning/error) fill Textual's own chrome, and
        every Solveig-specific colour is exposed as a CSS variable under its own name
        so widget CSS can reference `$section`/`$box`/`$group`/`$input`/
        `$group-pending`/`$user-turn-bg` (with `$background`/`$foreground`/`$primary`/
        `$warning`/`$error` coming from the slots). Switching themes at runtime is
        then just `app.theme = palette.name` - Textual re-resolves every `$var`."""
        return TextualTheme(
            name=self.name,
            primary=self.primary.hex,
            secondary=self.accent.hex,
            accent=self.accent.hex,
            foreground=self.foreground.hex,
            background=self.background.hex,
            success=self.primary.hex,
            warning=self.warning.hex,
            error=self.error.hex,
            surface=self.background.hex,
            panel=self.background.hex,
            dark=self.is_dark,
            variables={
                "border": self.border.hex,
                "group": self.group.hex,
                "input": self.input.hex,
                "group-pending": self.group_pending.hex,
                "background-user": self.background_user.hex,
            },
        )


terracotta = Palette(
    name="terracotta",
    background=Color.parse("#231D13"),  # dark greyish brown
    foreground=Color.parse("#FFF1DB"),  # beige
    primary=Color.parse("#CB9D63"),  # faded yellow
    accent=Color.parse("#BE5856"),  # clay red
    warning=Color.parse("#BC8F8F"),  # rosy brown
    error=Color.parse("#BE5856"),  # clay red
    border=Color.parse("#CB9D63"),  # faded yellow
    group=Color.parse("#869F89"),  # pale green
    input=Color.parse("#4B2828"),  # faded red wine
)


solarized_dark = Palette(
    name="solarized-dark",
    background=Color.parse("#002b36"),  # base3
    foreground=Color.parse("#839496"),  # base0
    primary=Color.parse("#2aa198"),  # cyan
    accent=Color.parse("#D33682"),  # magenta
    warning=Color.parse("#B58900"),  # yellow
    error=Color.parse("#CB4B16"),  # orange
    border=Color.parse("#268bd2"),  # blue
    group=Color.parse("#859900"),  # green
    input=Color.parse("#2aa198"),  # cyan
)


solarized_light = Palette(
    name="solarized-light",
    background=Color.parse("#fdf6e3"),  # base3
    foreground=Color.parse("#657b83"),  # base00
    primary=Color.parse("#268bd2"),  # blue
    accent=Color.parse("#2aa198"),  # cyan
    warning=Color.parse("#b58900"),  # yellow
    error=Color.parse("#CB4B16"),  # orange
    border=Color.parse("#D33682"),  # violet
    group=Color.parse("#859900"),  # green
    input=Color.parse("#268bd2"),  # blue
)


forest = Palette(
    name="forest",
    background=Color.parse("#13261C"),  # algae green
    foreground=Color.parse("#d4d4aa"),  # sage
    input=Color.parse("#87ceeb"),  # sky blue
    primary=Color.parse("#87ceeb"),  # sky blue
    border=Color.parse("#daa520"),  # goldenrod
    group=Color.parse("#87AC87"),  # light green
    accent=Color.parse("#93AFBA"),  # sky blue
    warning=Color.parse("#ff7f50"),  # coral
    error=Color.parse("#cd5c5c"),  # Indian red
)


midnight = Palette(
    # Info
    name="midnight",
    # UI
    background=Color.parse("#121414"),  # dark grey
    group=Color.parse("#675DA6"),  # brighter purple
    accent=Color.parse("#3B679C"),  # sky blue
    border=Color.parse("#A46A73"),  # low-contrast pink
    input=Color.parse("#3B679C"),  # bright blue
    # Messages
    foreground=Color.parse("#e0e0e0"),  # light grey
    primary=Color.parse("#9FC7F0"),  # bright blue
    warning=Color.parse("#f39800"),  # amber
    error=Color.parse("#e94560"),  # bright pink
)


nord = Palette(
    name="nord",
    background=Color.parse("#2E3440"),  # polar night - dark blue-grey
    group=Color.parse("#88C0D0"),  # frost - light cyan
    accent=Color.parse("#5E81AC"),  # frost - deep blue
    border=Color.parse("#8B96AA"),  # mid blue grey - lighter panel
    input=Color.parse("#5E81AC"),  # frost - deep blue
    foreground=Color.parse("#ECEFF4"),  # snow storm - near white
    primary=Color.parse("#88C0D0"),  # frost - light cyan
    warning=Color.parse("#EBCB8B"),  # aurora - yellow
    error=Color.parse("#BF616A"),  # aurora - red
)

rose = Palette(
    name="rose",
    background=Color.parse("#FAF0F0"),  # blush white
    group=Color.parse("#A8547A"),  # deep rose
    accent=Color.parse("#D4688E"),  # medium pink
    border=Color.parse("#C4788E"),  # deep rose
    input=Color.parse("#D4688E"),  # medium pink
    foreground=Color.parse("#3D2030"),  # dark plum
    primary=Color.parse("#A8547A"),  # deep rose
    warning=Color.parse("#B8620A"),  # warm amber
    error=Color.parse("#B02828"),  # deep crimson
)

monochrome = Palette(
    name="monochrome",
    background=Color.parse("#111111"),  # near black
    group=Color.parse("#888888"),  # mid grey
    accent=Color.parse("#CCCCCC"),  # light grey
    border=Color.parse("#656565"),  # mid dark grey
    input=Color.parse("#CCCCCC"),  # light grey
    foreground=Color.parse("#E8E8E8"),  # off white
    primary=Color.parse("#AAAAAA"),  # silver
    warning=Color.parse("#DDDDDD"),  # bright grey
    error=Color.parse("#FFFFFF"),  # pure white
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


DEFAULT_CODE_THEME = "coffee"
CODE_THEMES = set(STYLE_MAP.keys())
