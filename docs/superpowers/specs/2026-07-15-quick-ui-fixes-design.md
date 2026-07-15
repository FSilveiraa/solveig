# Quick UI Fixes: Tasks Group, Section Tint, Pending Cap

## Status

Piece 1 of 3 in a larger UI-improvement effort:

1. **This spec** — three independent, architecture-agnostic UI fixes.
2. *(Future spec)* Tie UI state (groups, choice prompts) to per-tool-call
   identity (`tool_call_id`) instead of the current unkeyed `_group_stack`/
   singleton state — see
   `ignore/project-logs/2026-07-13-23-54-tool-call-ui-binding.md`.
3. *(Future spec)* "Tools (N)" meta-grouping — merges consecutive collapsed
   tool-call groups into one summary group. Depends on (2) for group identity.

This spec covers only piece 1. None of its three fixes depend on (2) or (3).

## Why this exists

Three small, unrelated UX papercuts in the Textual CLI interface, bundled
into one spec because they're all small and independent:

1. The Tasks tool's group auto-collapses like every other tool once it
   resolves, hiding the task list right when the user most wants to glance
   at it.
2. User and Assistant turns are visually indistinguishable except for a
   thin one-line `SectionHeader` divider — no background differentiation.
3. A group that is still open (tool running, or left open by an
   interruption) has no bottom marker at all — visually identical to a
   group whose content just hasn't scrolled into view yet, not distinguishable
   from "still working."

## Fix 1: Tasks group never auto-collapses

**Current mechanism**: `run_tool_and_hooks()` (`solveig/tools/orchestration.py`)
wraps every tool call in:

```python
async with interface.with_group(instance.title, auto_collapse=config.auto_collapse_tools):
```

`config.auto_collapse_tools` (default `True`) is a single global flag applied
uniformly to every tool, including `TasksTool` (`solveig/tools/core/task.py`).

**Change**: special-case `TasksTool` at the call site:

```python
async with interface.with_group(
    instance.title,
    auto_collapse=config.auto_collapse_tools and not isinstance(instance, TasksTool),
):
```

Hardcoded, no new config surface — matches the explicit ask ("it's ok to
leave this as a hardcoded rule").

## Fix 2: User/Assistant section background tint

**Current mechanism**: `display_section("User"/"Assistant")` →
`ConversationArea.add_section_header()` (`conversation.py`) mounts a
`SectionHeader` — a single-line `Static` divider only, styled with
`theme.section`. Content mounted after it goes directly into
`ConversationArea`'s flat child list; there is no container wrapping "this
turn's content," so there is nothing to paint a background onto today.

**Change**:

- `ConversationArea` gains `self._current_section_container: Vertical | None`.
- `add_section_header(title)`:
  1. Mounts the `SectionHeader` as today.
  2. Mounts a new `Vertical(classes=f"section-{title.lower()}")`
     immediately after it, and stores it as `_current_section_container`.
- Every method that currently mounts content via `self._mount_target` (or
  equivalent) routes into `_current_section_container` when set, so all
  widgets belonging to a turn land inside that turn's container. (Groups
  still nest normally inside it — `_group_stack`/`with_group` behavior is
  unchanged, just now scoped inside a section container instead of directly
  inside `ConversationArea`.)
- Only `section-user` gets a background tint; `section-assistant` stays
  `theme.background` (unstyled/transparent), matching the explicit ask that
  only the User section shifts.

**Color computation**: no new `Palette` fields for this fix — the tint is
*derived* from `theme.background` at CSS-build time using Textual's `Color`
type (`Color.parse(theme.background)`):

```python
bg = Color.parse(theme.background)
user_bg = bg.darken(0.08) if bg.luminosity >= 0.5 else bg.lighten(0.08)
```

- Dark themes (`luminosity < 0.5`, e.g. `terracotta`, `solarized_dark`,
  `midnight`, `nord`) → User section is lightened by 8%.
- Light themes (`luminosity >= 0.5`, e.g. `solarized_light`) → User section
  is darkened by 8%.
- 8% is a starting delta, chosen to be visible without being jarring;
  expected to be tuned after a live visual check (`just mock`).
- This means all 8 existing palettes get a correctly-contrasted User tint
  automatically, with zero manual per-palette values to maintain.

**CSS**: `.section-user { background: <computed hex>; }` added to
`ConversationArea.get_css()`'s generated CSS block, alongside the existing
per-widget `get_css()` assembly pattern.

## Fix 3: "Pending" end cap for open groups

**Current mechanism**: `enter_group()` mounts the `CustomCollapsible` group
widget and pushes it onto `_group_stack` — no footer of any kind.
`exit_group()` is the *only* place a footer is ever mounted:
`Static("┗━━━", classes="group_end")`. Between entry and exit (which, for a
long-running tool, can be a real wall-clock duration the user is looking
at), there is no visual indicator that the group is still open versus
finished-but-not-yet-rendered.

**Change**:

- `enter_group()` additionally mounts a `Static(PENDING_GLYPH, classes="group_pending")`
  immediately after the group widget, and stores a reference to it (e.g. as
  an attribute on the returned `CustomCollapsible`, or a second stack
  parallel to `_group_stack`) so `exit_group()` can locate and remove it.
- `exit_group()` removes the `group_pending` `Static` (if present) *before*
  mounting the real `Static("┗━━━", classes="group_end")` footer — so a
  resolved group ends up with exactly the same footer it has today; only the
  in-between state changes.
- Shown for the *entire* time a group is open, not just on error/cancellation
  — i.e. it's the normal "in progress" state, not an abnormal-exit-only
  indicator.
- Static glyph, no animation — no dependency on the existing waiting-animation
  subsystem.
- New `Palette` field `group_pending: str` (a color token, following the
  existing `group`/`section`/`box` pattern), defaulted per-palette to a
  dimmer/desaturated variant of that theme's `group` color. This gives an
  explicit, first-class override point (edit the palette, no code change)
  rather than a computed color, since the user explicitly wants to hand-tune
  this one.
- Glyph value: kept as a single named constant (not inlined at each call
  site) so it's a one-line swap to compare candidates live. Starting
  candidate: `"┗╌╌╌"` (dashed variant of the real closed cap — guaranteed to
  render in any monospace terminal font). The user's two suggested
  Unicode "Legacy Computing" glyphs (𜹯 U+1FA6F, 🭡 U+1FB61) are visually
  closer to the intended "dissipating" look but have inconsistent font
  coverage outside Nerd Fonts/specialized terminal fonts — worth comparing
  live via `just mock` before committing to one, flagged here as a known
  rendering-support tradeoff rather than a blocker.

## Testing strategy

- Unit/integration tests in `tests/unit/interface/` (or wherever
  `ConversationArea`/`with_group` tests currently live) covering:
  - `TasksTool` group is mounted with `collapsed=False` regardless of
    `config.auto_collapse_tools`; a non-Tasks tool still respects the flag.
  - `add_section_header` mounts a `Vertical` with the expected CSS class,
    and subsequent `_add_element`/mount calls land inside it.
  - `enter_group` mounts a `group_pending` `Static`; `exit_group` removes it
    and mounts `group_end` in its place; the pending marker never survives
    into a resolved group's rendered children.
- Manual visual check via `just mock` for all three (task list staying
  visible, section tint contrast in at least one light and one dark theme,
  pending-cap glyph legibility) before considering this spec done — this is
  UI-only work and the interface layer is excluded from coverage
  measurement per project convention.

## Out of scope (explicitly deferred)

- Per-tool-call identity / `tool_call_id`-keyed group state (future spec,
  piece 2).
- "Tools (N)" meta-grouping of collapsed tool calls (future spec, piece 3,
  depends on piece 2).
- Animating the pending cap.
- Any change to `auto_collapse_tools` as a config option beyond the
  `TasksTool` hardcoded exception.
