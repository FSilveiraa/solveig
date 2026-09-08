from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator, field_serializer
from pydantic import ValidationInfo

from pygments.style import Style
from pygments.styles import STYLE_MAP
from rich.syntax import get_style_by_name
from textual.color import Color, ColorParseError
from textual.theme import Theme as TextualTheme


CodeTheme = type[Style]

CODE_THEMES: dict[str, CodeTheme] = {
    code_theme_name: get_style_by_name(code_theme_name) for code_theme_name in STYLE_MAP
}


class TuiTheme(BaseModel):
    """TUI theme, contains colors used for UI elements and a code theme."""

    # Tells Pydantic to make this object immutable
    model_config = ConfigDict(frozen=True)

    if TYPE_CHECKING:
        # HACK: declaration only for mypy. Pydantic generates the real
        # __init__ from the fields above, and its validators accept the
        # written form (hex string, style name) while the attributes
        # hold the parsed instance.
        def __init__(
            self,
            name: str,
            *,
            background: Color | str,
            foreground: Color | str,
            primary: Color | str,
            accent: Color | str,
            warning: Color | str,
            error: Color | str,
            border: Color | str,
            group: Color | str,
            input: Color | str,
            code_theme: type[Style] | str = ...,
        ) -> None: ...

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

    code_theme: CodeTheme = CODE_THEMES["material"]

    def __str__(self) -> str:
        return self.name

    @field_validator("*", mode="before")
    @classmethod
    def _parse_color(cls, value: object, info: ValidationInfo) -> object:
        if (
            info.field_name
            and cls.model_fields[info.field_name].annotation is not Color
        ):
            return value
        if isinstance(value, str):
            try:
                return Color.parse(value)
            except ColorParseError as error:
                raise ValueError(f"Invalid hex colour '{value}'") from error
        return value

    @field_serializer("*")
    def _serialize_color(self, value: Color | str) -> str:
        return value.hex if isinstance(value, Color) else value

    @field_validator("code_theme", mode="before")
    @classmethod
    def _parse_code_theme(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str):
            return CODE_THEMES[value]
        return value

    @field_serializer("code_theme")
    def _serialize_code_theme(self, code_theme: CodeTheme) -> str:
        return code_theme.name

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
        return (
            self.background.lighten(shift)
            if self.is_dark
            else self.background.darken(shift)
        )

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


terracotta = TuiTheme(
    name="terracotta",
    code_theme="coffee",
    background="#231D13",  # dark greyish brown
    foreground="#FFF1DB",  # beige
    primary="#CB9D63",  # faded yellow
    accent="#BE5856",  # clay red
    warning="#BC8F8F",  # rosy brown
    error="#BE5856",  # clay red
    border="#CB9D63",  # faded yellow
    group="#869F89",  # pale green
    input="#4B2828",  # faded red wine
)


solarized_dark = TuiTheme(
    name="solarized-dark",
    code_theme="solarized-dark",
    background="#002b36",  # base3
    foreground="#839496",  # base0
    primary="#2aa198",  # cyan
    accent="#D33682",  # magenta
    warning="#B58900",  # yellow
    error="#CB4B16",  # orange
    border="#268bd2",  # blue
    group="#859900",  # green
    input="#2aa198",  # cyan
)


solarized_light = TuiTheme(
    name="solarized-light",
    code_theme="solarized-light",
    background="#fdf6e3",  # base3
    foreground="#657b83",  # base00
    primary="#268bd2",  # blue
    accent="#2aa198",  # cyan
    warning="#b58900",  # yellow
    error="#CB4B16",  # orange
    border="#D33682",  # violet
    group="#859900",  # green
    input="#268bd2",  # blue
)


forest = TuiTheme(
    name="forest",
    code_theme="gruvbox-dark",
    background="#13261C",  # algae green
    foreground="#d4d4aa",  # sage
    input="#87ceeb",  # sky blue
    primary="#87ceeb",  # sky blue
    border="#daa520",  # goldenrod
    group="#87AC87",  # light green
    accent="#93AFBA",  # sky blue
    warning="#ff7f50",  # coral
    error="#cd5c5c",  # Indian red
)


midnight = TuiTheme(
    name="midnight",
    code_theme="night-owl",
    background="#121414",  # dark grey
    group="#675DA6",  # brighter purple
    accent="#3B679C",  # sky blue
    border="#A46A73",  # low-contrast pink
    input="#3B679C",  # bright blue
    foreground="#e0e0e0",  # light grey
    primary="#9FC7F0",  # bright blue
    warning="#f39800",  # amber
    error="#e94560",  # bright pink
)


nord = TuiTheme(
    name="nord",
    code_theme="nord",
    background="#2E3440",  # polar night - dark blue-grey
    group="#88C0D0",  # frost - light cyan
    accent="#5E81AC",  # frost - deep blue
    border="#8B96AA",  # mid blue grey - lighter panel
    input="#5E81AC",  # frost - deep blue
    foreground="#ECEFF4",  # snow storm - near white
    primary="#88C0D0",  # frost - light cyan
    warning="#EBCB8B",  # aurora - yellow
    error="#BF616A",  # aurora - red
)


rose = TuiTheme(
    name="rose",
    code_theme="xcode",
    background="#FAF0F0",  # blush white
    group="#A8547A",  # deep rose
    accent="#D4688E",  # medium pink
    border="#C4788E",  # deep rose
    input="#D4688E",  # medium pink
    foreground="#3D2030",  # dark plum
    primary="#A8547A",  # deep rose
    warning="#B8620A",  # warm amber
    error="#B02828",  # deep crimson
)


monochrome = TuiTheme(
    name="monochrome",
    # TODO: this is light, find dark-grayscale code theme
    code_theme="friendly_grayscale",
    background="#111111",  # near black
    group="#888888",  # mid grey
    accent="#CCCCCC",  # light grey
    border="#656565",  # mid dark grey
    input="#CCCCCC",  # light grey
    foreground="#E8E8E8",  # off white
    primary="#AAAAAA",  # silver
    warning="#DDDDDD",  # bright grey
    error="#FFFFFF",  # pure white
)


DEFAULT_THEME = terracotta

THEMES = [
    terracotta,
    solarized_dark,
    solarized_light,
    forest,
    midnight,
    nord,
    rose,
    monochrome,
]
