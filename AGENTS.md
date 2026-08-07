# AGENTS.md — Solveig

Guidance for AI coding agents working in this repository. Start here.

## What this is

Solveig is an autonomous, safety-first AI agent for the terminal, built on
**pydantic-ai** (agent engine), **pydantic-settings** (config), **Textual**
(TUI), and **FastMCP** (MCP). Any OpenAI-compatible LLM. Python ≥ 3.13, fully
async.

Solveig is designed around a single idea: **components declare what they care
about, and the framework reacts.** A config change notifies observers; an
observer wakes up and updates the model info; the stats bar refreshes.
A module that owns config editing registers its own subcommands — the registry
knows arg parsing, not config semantics. A tool writes to an interface scoped
to its group; the interface renders. Every interaction is event → reaction →
event, never imperative fetch → check → act. Pick the option that makes the
project *simpler or better*, never the shortest or easiest.

## Commands (via `just`)

```bash
just ci        # format + check + import + test with coverage — the CI gate
just format    # ruff format
just check     # ruff check + mypy (both always run)
just import    # lint-imports: the import-layering contracts
just test      # pytest --cov=solveig  (pass extra paths/flags through)
just mock      # interactive TUI against a mock LLM (you type, canned replies)
just demo      # hands-free auto-typed replay of a recorded story/session
just mcp       # start the local mock MCP server for /mcp connect testing
```

Lint/type scope is `solveig/ tests/mocks/ tests/conftest.py` (the rest of
`tests/` is deferred migration debt and intentionally excluded). `mypy` has
`warn_unused_ignores` — a stale `# type: ignore` is an error.

## Architecture — the spine

```
run.py        Entry point. run_async() wires config/interface/conversation, spawns
              main_loop as a background asyncio Task, awaits interface.start() in the
              foreground. main_loop: dequeue a prompt → run_turn_with_retry → the
              reactive transcript renders everything (no predicted display).
agent.py      build_agent() builds a fresh pydantic-ai Agent PER TURN (cheap; the
              Provider lives in a reused Client) so runtime config changes apply
              next turn. run_turn() drives agent.iter() by hand: optimistic user-prompt
              echo, per-token streaming into a live entry, the autonomy gate, and
              typed-ahead comment interleaving are plain lines in that loop.
              Two Hooks capabilities: build_loop_capability (the "Thinking" animation
              around a NON-streamed request) and build_tool_execution_capability
              (per-tool-call group + plugin hooks + ToolResult→ToolReturn).
session/conversation.py  The reactive single source of truth. ONE insertion-ordered
              dict[MessageId, ModelMessage] is simultaneously the ordered list handed
              to pydantic-ai and the O(1) id-index — drift is structurally impossible.
              Mutations (append/edit/truncate_from/adopt/load/begin|update|finalize_stream)
              await registered observers.
session/display.py  SessionDisplay — the observer that puts a conversation on
              screen, and the peer of SessionManager (one shows it, one saves it).
              Interface-agnostic: it reduces display to the interface's protocol
              verbs, and redraws a recorded tool call ONLY on conversation_loaded.
context.py    SolveigContext = the RunContext deps dataclass — exactly {config,
              interface}. Nothing else; capabilities read ctx.deps live at call time.
api/          api/types.py: APIType (base class with OpenAI/Anthropic/Gemini
              subclasses), ModelInfo. api/client.py: Client (runtime provider
              holder, reactive to config) + the model subcommands.
todo.py       Layer 0, beside utils/file.FileMetadata: TodoItem/TodoStatus. The todo
              list is Solveig's, not TodoTool's — an agent that works autonomously has
              to say what it intends, what it is doing and what it dropped, and the
              tool is merely the surface the assistant edits it through. Tools and
              frontends both name it; neither owns it. Its vocabulary is the industry's
              (see Conventions), not ours.
user_message_queue.py  UserMessageQueue — asyncio.Queue[str] + a prompt gate on
              put() (routes /commands before insertion) + an on_change doorbell
              (self-registered by the queued-messages display widget).
```

**Loop ownership:** core drives `agent.iter()`; pydantic-ai stays the engine for
model I/O, tool schemas, and tool execution. Consent lives in the `tool_execute`
hook — deliberately NOT pydantic-ai's `requires_approval`/`DeferredToolRequests`
(Solveig's consent is value-dependent and mid-execution: diffs, previews, 3-way
run/inspect/decline choices). Tool calls are forced sequential
(`Agent.parallel_tool_call_execution_mode("sequential")`) because the consent UI is
single-flight.

**Replay is not a special path.** `Conversation.load()` fires `conversation_loaded`
and `SessionDisplay` walks the loaded history through the same interface verbs a
live turn uses; a session file, a `system_prompt/stories` story, and a live
conversation share one parse contract (`parse_conversation_blob`).
`--add-examples` renders a recorded story mechanically, so examples can't drift.

## Design

These are not style preferences — they are the seams the codebase is built on.

- **Component-owned surfaces.** Each module registers its own subcommands. The
  config module owns `/config set`, `/config save`; the MCP module owns
  `/mcp connect`. The subcommand registry knows arg parsing and dispatch — it
  has no idea what a config or an MCP connection is. A component declares its
  surface; the framework binds it.

- **Declarative, not imperative.** Components declare what they care about and
  react to changes. `SessionDisplay` (`session/conversation.py` → observers) is
  the canonical example: one insertion-ordered dict is the single source of
  truth; mutations fire observers; the UI renders the diff. Config changes
  follow the same pattern: `@config.on_change(...)` registers a callback,
  `Client` wakes up and fetches new model info, the stats bar refreshes. Event
  → reaction → event — never fetch → check → act.

- **Constructor injection, not post-init wiring.** If an object needs a
  dependency, it takes it in the constructor — no `setup()`, no `wire_*()`,
  no `__post_init__` that does real work. Objects self-register their
  observers (`@config.on_change` in `Client.__init__`, `queue.prompt_handler`
  in `SubcommandRegistry.__init__`, `queue.on_change` in
  `QueuedMessagesDisplay.on_mount`). The composition root in `run_async`
  constructs objects in dependency order; no closures, no late binding.

- **Signature is the contract.** A subcommand handler declares what it needs in
  its function signature — injected deps matched by type, CLI args parsed via
  `CliSettingsSource`. A tool declares its arguments as pydantic model fields —
  one model is simultaneously the LLM schema, the validator, and the CLI parser.
  No hand-rolled argv parsing, no ambient state reach-throughs.

- **One rule, one home.** Every cross-cutting concern has exactly one named seam —
  `is_tool_enabled`/`is_hook_enabled` (enablement), `run_tool_and_hooks`
  (execution), `open_tool_group` (auto-collapse), `_compose_section` (schema
  composition), `to_tool_return()` (the pydantic-ai crossover). When you add a
  rule, put it on the existing seam — never a second copy.

- **Delegation is complete.** No residue wrappers re-implementing pydantic-ai —
  wrap only where Solveig carries real domain semantics (e.g. `ToolResult.private`).
- **Field behavior lives on the field type.** Parse/display/secrecy go on the
  type (`SecretStr`, `ByteSize`, `list[re.Pattern]`, `Palette`, `APIType`), not
  in name-keyed lookup tables.

## Tools

- **`tools/base.py` — `BaseTool[ToolConfigType]`** is the keystone. One pydantic
  model is at once the LLM schema (via pydantic-ai's single-model-param flattening
  in `as_tool()`), the validator, the `/tool` CLI parser (`from_cli_tokens` →
  `CliSettingsSource`, not hand-rolled argv), the replay renderer
  (`display_header` + `ToolResult.display_content`), and the config-schema
  contributor. `config_model` is **auto-derived** from the `BaseTool[SomeConfig]`
  generic arg — declared once, never repeated. `self.settings(config)` returns the
  tool's config statically typed.
- **`tools/orchestration.py` — the single execution seam.** `run_tool_and_hooks`
  opens the call's collapsible group (`open_tool_group`, the one auto-collapse
  policy), shows the header, runs `@before_tool`/`@after_tool` plugin hooks, runs the body —
  shared by the LLM path AND a user-typed `/tool` subcommand (a hand-typed
  `/command` runs the same shellcheck a model call does). It is also the one
  enable/disable enforcement point (`ToolDisabledError`). `run_untyped_tool` gives
  a plain-function/MCP call the same group + 3-way consent generically.
- **`tools/available.py` — `build_toolset(config)`.** Returns a plain
  `CombinedToolset([FilteredToolset(FunctionToolset), *mcp_toolsets])`, derived fresh
  per turn (`build_agent()` builds a new Agent each turn anyway), so a membership
  change — plugin rescan, MCP connect/disconnect — is picked up on its own and
  nothing has to announce it. There is no cached singleton and nothing to rebuild.
  A `tools.<name>.enabled` toggle is decided live per step by the FilteredToolset
  reading `ctx.deps.config`. `tool_classes()` feeds session replay.
- **`tools/result.py` — `ToolResult`.** The one contract a tool returns:
  `content` (Any, the real output), `metadata` (unconditionally assistant-visible if
  non-empty), `issues` (chronological warnings/errors), `private` (never reaches the
  model; becomes `ToolReturn.metadata`). `to_tool_return()` is the single crossover
  into pydantic-ai's message layer.

## Config — nested pydantic-settings

`SolveigConfig(BaseSettings)` (`config/config.py`) with nested sub-models in
`config/models.py`: `api`, `system_prompt`, `tools`, `plugins`, `mcp`, `session`,
`interface`, plus top-level `briefing`/`min_disk_space_left`/`auto_allowed_paths`/
`ignore_paths`/`disable_autonomy`.

- **Sources & precedence:** CLI > env (`SOLVEIG_API__KEY`) > config files. Files are
  `./.solveig/config.{json,yaml,yml,toml}` (local) layered over `~/.solveig/config.*`
  (global), deep-merged by anyconfig (`config/sources.py`). Legacy flat keys are a
  **hard break** with an explicit old→new map.
- **Runtime schema composition:** config never hand-enumerates tools.
  `_compose_section` (`config/config.py`) builds each section; `bootstrap.py` is what
  feeds it, because config must not import the tool or plugin packages back —
  `compose_core_tools()` from `CORE_TOOLS`, and `compose_plugin_sections()` for
  `config.plugins.tools`/`config.plugins.hooks`, the latter subscribed to plugin
  discovery's `ON_SCANNED` so the schema is a REACTION to the plugin set changing,
  not a step a caller must remember. The **two-phase bootstrap** in
  `parse_config_and_prompt` is parse → `discover_plugins` → compose → reparse.
  Adding a core tool == adding a plugin tool == adding a hook: config is untouched.
- **Enablement:** `is_tool_enabled(name)` spans `tools.*` + `plugins.tools.*`;
  `is_hook_enabled(name)` covers `plugins.hooks.*`. One rule each, consulted by both
  the schema filter and the execution guard.
- **PRESERVE+WARN:** the composed plugin sections use `extra="allow"` — a config block
  for an undiscovered plugin survives in `model_extra`, round-trips `/config save`,
  and gets a load-time warning (never silently dropped). CLI stays strict.
- **`/config save` persists only `_declared_fields`** (explicitly set via file/CLI/
  `/config set`), tracked as dotted paths; `declared_config()` copies those leaves out
  of `model_dump`. Pass `--full`/`--all` to dump the complete config including defaults
  (export/onboarding). `plugins.paths` UNIONs local+global. `model_info` is a `PrivateAttr`
  (API-reported, never user-set). Field-intrinsic types carry behavior: `api.key` is
  `SecretStr`, `min_disk_space_left` is `ByteSize`, `command.auto_execute` is
  `list[re.Pattern]` (compiled at the field).
- **Config I/O bypasses `Filesystem`** (uses `os` + anyconfig directly) — a deliberate,
  documented exception; every other file op (tools, sessions) goes through
  `utils/file.py`.

### Known config gaps (carry-over, Task 10)

- **CLI phase-1 gap:** `--plugins.tools.<x>.<f>` / `--plugins.hooks.<x>.<f>` startup
  flags fail — the strict phase-1 `CliSettingsSource` parses argv before the plugin
  schema is composed. Env / file / `/config set` all work; core `--tools.*` works.
- Bool flags are `--flag/--no-flag` (`cli_implicit_flags`), not `--flag false`.
- `--mcp` → `--mcp-server` (repeatable); `--resume` requires a value (no bare ⇒ latest).
  There is no `--no-commands` sugar — use `--no-tools.command.enabled`.

## Plugins

Dual architecture in `solveig/plugins/`:

- **Tool plugins** (`plugins/tools/`, e.g. `tree.py`) — new capabilities, declared as
  `BaseTool` subclasses or via `@tool(config_model=…)`.
- **Hook plugins** (`plugins/hooks/`, e.g. `shellcheck.py` `@before_tool`,
  `trafilatura.py` `@after_tool`) — intercept a tool call for validation/transformation.
  A hook is a plain function; its config type comes from
  `@before_tool/@after_tool(config_model=…)` or bare `ToolConfig`. Hooks target a tool
  by name and are enabled-by-default.

`discover_plugins(config)` is idempotent and UI-free (folds external `plugins.paths`
into the built-in packages, then scans); `report_plugins` renders the Plugins dialog
list-all-mark-disabled (a disabled plugin is shown, never hidden). Discovery runs in
the config bootstrap (phase 1) and again in `_display_setup` for reporting.

## Interface

- `interface/base/interface.py` — `SolveigInterface` (ABC): the display protocol +
  the user-message queue (the interface's output channel for typed input) + the
  cancellation registry. `interface/base/widgets.py` — the four `@runtime_checkable`
  box handles a display verb hands back (`TextBox`, `DiffBox`, `TreeBox`,
  `EditableMessage`); a missing method fails rather than no-ops. The observer that
  decides *what* to show is `session/display.py`, not the interface.
- `interface/cli/` — the Textual materialization. `interface.py` holds a
  three-class split: `TerminalDisplay` (everything that renders into a container of
  an app it does NOT own — deliberately constructor-free), `TerminalInterface` (the
  root: owns the app, status, stats, prompts, lifecycle) and `GroupInterface` (a
  scoped display fixed to one collapsible group). `message_display.py` maps a
  message part → widget; `app.py` holds the static theme-independent CSS.
- **Display verbs take domain values, never formatted text.** `display_todos` takes
  `list[TodoItem]`, `display_file_metadata` takes a `FileMetadata`, `display_tree`
  takes the metadata. The caller decides WHAT to show and WHEN; the frontend decides
  the glyphs, the separators, the ordering marks and how much of a path to show. A
  tool that emits `f"→ 🔵 {i}. {text}"` has already made every decision a non-terminal
  frontend needed to make differently — a web UI wanting to animate the in-progress
  todo has no way to disagree with a string. When a value cannot be read
  (`metadata=None`), that is a real state to render, not a caller being lazy.
- **Two surfaces, kept separate:** the reactive transcript (state → view) and the
  transient imperative UI (consent prompts, status bar, animations) — they never tangle.
- The **group-as-interface** trick: `interface.with_group(title)` yields a scoped
  interface whose container is fixed, so a tool body writes only within its own
  collapsible group and stays scope-oblivious. Cancellation uses an innermost-task
  stack (`_request_tasks`) so Esc/Ctrl+C cancels exactly the in-flight cancellable.
- **Native Textual theming:** palettes are registered as Textual `Theme`s; CSS is
  static and theme-independent via `$variables` (no per-widget f-string interpolation).

## Sessions

`session/manager.py` — one append-only JSONL file per session in
`config.session.dir` (default `.solveig/sessions`): one message per line, plus a
trailing `session_meta` line with the token totals. `SessionManager` is itself a
`ConversationObserver`, so nothing has to remember to save: a finished message
appends (O(new content)), and only the rare destructive events (an edit, a rewind)
rewrite the file. `store`/`append`/`append_usage`/`write_checkpoint`/`load`/
`resolve` (name → path, absolute first then fuzzy) + `announce_resumed_session`.
Serialization is pydantic-ai's own `ModelMessagesTypeAdapter` +
`to_jsonable_python`; usage comes from the shared `RunUsage`. Resume replays
through `SessionDisplay` (tool calls via each `BaseTool.replay()`). Filenames are
timestamped. Sessions and `system_prompt/stories/*.jsonl` story files share one
parse contract (`parse_conversation_blob` — it reads both the JSONL log and the
single-object blob a story uses), so a stored session doubles as a replayable
story/demo.

## MCP

`mcp_servers/client.py` builds a real `pydantic_ai.mcp.MCPToolset` per connection
(refcounted `__aenter__` held for the session), filtered by `allowed_tools`/
`blocked_tools` and prefixed with a model-friendly name. `MCP_CONNECTIONS` (the single
source of truth) lives in `mcp_servers/__init__.py` — a dependency-free holder both
`client.py` and `tools/available.py` import at top level (this is the established
cycle-breaking pattern; do not reintroduce a `connections.py` or import the dict from
`client`). `connect`/`disconnect` just mutate that dict — `build_toolset()` reads it
on the next turn, so there is nothing to notify. Untyped MCP calls route through
`run_untyped_tool`.

## Subcommands

**One store per source; the decorator you import decides which.** A declaration
writes a finished `Subcommand` straight into a `SubcommandStore` at import time —
no inbox, no later pass. `declaring_into(store)` builds the `@subcommand`
decorator, so the DESTINATION is settled by which module the author imported from,
never by an argument they could forget: core code imports `subcommand` from
`solveig.subcommands`, a plugin imports it from `solveig.plugins`. `Subcommand.from_handler`
inspects the signature, separating injected deps (matched by type) from CLI args
(parsed via `CliSettingsSource`).

**Position is precedence.** `SUBCOMMANDS` is a `SubcommandStores` over
`BUILTIN_SUBCOMMANDS`, `CORE_TOOL_SUBCOMMANDS`, `PLUGIN_SUBCOMMANDS`, in that order.
It holds a `ChainMap` *view* — references, not a merge — so a store replaced by a
plugin reload is visible immediately with nothing to invalidate. One collision rule
for every arrival: a trigger already claimed by ANOTHER store is refused with a
warning rather than shadowed (losing a plugin's command beats a plugin quietly
taking over `/config`); re-declaring into the same store just overwrites.

**Built-in commands** are standalone functions in the module that owns the behaviour:

```python
# solveig/config/commands.py
@subcommand("/config save", section="config", detail=True)
async def config_save(
    config: SolveigConfig,          # injected
    interface: SolveigInterface,     # injected
    path: str = "",                  # CLI-parsed
    full: bool = False,              # CLI-parsed → --full / --no-full
) -> None:
    ...
```

Injected types (`SolveigConfig`, `SolveigInterface`, `Conversation`, `Client`,
`SessionManager`) are resolved by the registry from its constructor arguments —
no `deps` dict parameter, no `interface=` kwarg on dispatch. Bool params with
defaults become `--flag/--no-flag`. `*rest` maps to a greedy positional list.

A parameter whose type is neither CLI-expressible nor injectable is a **declaration
error**: `_resolve_dep` raises `UnknownDependency`, the registry warns at construction
naming the command and the parameter, and dispatch reports it instead of handing the
handler a `None`.

**Tool commands** declare the same way — a `BaseTool` subclass registers into
`CORE_TOOL_SUBCOMMANDS`; the handler parses via `from_cli_tokens` → `CliSettingsSource`
and orchestrates via `run_tool_and_hooks`, so a hand-typed `/command` runs the same
hooks a model call does.

The registry also owns the **prompt gate**: it self-registers as the queue's
`prompt_handler` in its constructor. `/commands` typed as user input are dispatched
before insertion; prompts pass through unchanged.

`subcommands/base.py` — the `Subcommand` dataclass (`from_handler`), `SubcommandStore`
/ `SubcommandStores`, the module-level stores, and `declaring_into`.
`subcommands/registry.py` — `SubcommandRegistry`: binds handlers, dispatches via
longest-prefix match, generates `/help`, self-registers as the queue's prompt gate.

## Conventions that matter (do not regress)

- **Work inline, not through sub-agents.** Do the work in the main conversation
  unless explicitly asked otherwise. Delegating hides the reasoning behind a
  summary; the point of working together is being able to stop and question a
  decision while it is made, not after it has landed.

- **Assistant-facing names follow industry consensus.** Tool names, argument names
  and enum values are prompt surface: a model is measurably better at a tool whose
  vocabulary matches what it has seen across other agent CLIs, so diverging costs
  accuracy and buys nothing but our preference. Read the real schemas — Claude
  Code, gemini-cli, Hermes, openclaw — before naming, then adopt the term
  project-wide, with no internal synonym kept "because we prefer it": a
  translation layer between our word and the model's word is exactly the
  duplication this codebase keeps deleting. Applies only where a consensus
  exists; Solveig's own concepts (consent, groups, `issues`/`private`) get the
  clearest name we can invent.

- **`PathLike` for typing, `anyio.Path` for implementation.** Accept broadly, build
  concretely: a parameter types as `str | PathLike`, and code that actually touches a
  path constructs an `anyio.Path`. `pathlib.Path` is not the base here — the project
  is fully async, and a stdlib `Path` in a signature invites blocking calls. There is
  pre-`anyio` `pathlib` usage still in the tree; convert it when you touch it.

- **No compat shims; big-bang cutovers.** Migrations go red mid-flight and green at
  the end. Commit per task even while red.
- **No `setup()`/`wire_*()` post-init methods.** If an object needs a dependency,
  pass it in the constructor. No post-construction wiring, no closures that close
  over objects created later. Objects self-register their observers in `__init__`
  or `on_mount`.
- **Seam comments explain *why*.** The load-bearing, non-obvious invariants are
  documented at the seam (see `Conversation.adopt`'s object-identity note,
  `compose_plugin_sections`'s why-it-lives-in-bootstrap note, `_thinking`'s
  two-sites rationale). A seam comment says why the code is CORRECT — it never
  narrates how it got that way. Keep them accurate when you change the code.
- **Highlighted comment prefixes** project-wide (PyCharm highlights all four).
  Each means a different thing and they are not interchangeable:
  - `NOTE:` — something a developer needs to know and could not have guessed.
    The shape is correct; the reason it is correct is non-obvious. Never a
    complaint. Most seam comments in this project are NOTEs whether or not
    they carry the prefix.
  - `HACK:` — works, but we are not pleased with it and intend to replace it
    properly. Say what would be better and what blocks it. A `HACK:` is a debt
    we have acknowledged, not an excuse we have accepted.
  - `TODO:` — a genuine next step. We know what to do and simply have not done
    it. If you do not know what should happen, it is a `NOTE:`, not a `TODO:`.
  - `FIXME:` — known-broken behaviour under some condition. Name the condition.

  Prefer fixing over annotating: a problem raised and acknowledged gets fixed
  now, not banked (see "Never bank an improper shape" in the philosophy above).
  An annotation is the floor, not the goal.
- **Import-cycle law:** tools top-level-import `solveig.config`; config must not
  import tools or plugins at all — `bootstrap.py` sits above both and does the
  feeding. Respect the two-phase bootstrap ordering.
- **Every module appears in the layers.** `[tool.importlinter]` carries one
  `exhaustive` layers contract per package, so a module that is not placed in a
  layer fails `just import` instead of sitting silently unchecked. A new module
  is placed when it is created, not when something breaks — and it is placed at
  the layer its imports actually justify, never at whichever layer makes the
  contract pass.
- **Pinned external invariants** get a dedicated regression test, e.g.
  `test_pydantic_ai_preserves_message_history_object_identity` (adopt-by-identity).
  Any new pydantic-ai behavior the code depends on should be pinned the same way.

## Testing

Pyramid: `tests/unit` (mocked), `tests/integration` (real subprocess/file markers),
`tests/end_to_end`. "Mock by default"; `tests/mocks/` has the headless
`RecordingTranscript`, mock interface/client, and the `just mock`/`just demo` harness.
UI (`solveig/interface/cli/*`) is excluded from coverage.

## Commits

- **No PII, no local-only paths** (never reference `ignore/` or the user by name) —
  that directory is gitignored and unreadable to anyone else. Describe the change.
- **No `Co-Authored-By` trailer.**
- First line: a single self-contained summary. Add a body (one bullet per
  path/class/concept) only when something non-obvious changed.

## Known justified type hacks

The live set includes `tools/base.py`'s and `subcommands/base.py`'s
`CliSettingsSource(cls, …)` (`type: ignore[arg-type]` — typed for `BaseSettings`,
accepts a `BaseModel` at runtime), `user_message_queue.py`'s `self._queue` peek
(asyncio.Queue exposes no public read; confined to the class that owns the queue),
`api/types.py`'s `GoogleProvider(api_key=None)`, the optional-dep
`_trafilatura = None`, and `interface/cli/collapsible_widgets.py`'s framework-private
`CollapsibleTitle` import (marked `# HACK:`, re-verify on Textual upgrades).
`warn_unused_ignores` keeps them honest — remove an ignore the moment it's stale.
