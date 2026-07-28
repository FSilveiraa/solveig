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
A module that owns config editing registers its own subcommands — the runner
knows arg parsing, not config semantics. A tool writes to an interface scoped
to its group; the interface renders. Every interaction is event → reaction →
event, never imperative fetch → check → act. Pick the option that makes the
project *simpler or better*, never the shortest or easiest.

## Commands (via `just`)

```bash
just ci        # format + check (ruff lint, mypy) + test with coverage — the CI gate
just format    # ruff format solveig/ tests/mocks/
just check     # ruff check + mypy (both always run)
just test      # pytest --cov=solveig  (pass extra paths/flags through)
just mock      # interactive TUI against a mock LLM (you type, canned replies)
just demo      # hands-free auto-typed replay of a recorded story/session
just mcp       # start the local mock MCP server for /mcp connect testing
```

Lint/type scope is `solveig/ tests/mocks/` (the rest of `tests/` is deferred
migration debt and intentionally excluded). `mypy` has `warn_unused_ignores` —
a stale `# type: ignore` is an error.

## Architecture — the spine

```
run.py        Entry point. run_async() wires config/interface/conversation, spawns
              main_loop as a background asyncio Task, awaits interface.start() in the
              foreground. main_loop: dequeue a prompt → run_turn_with_retry → the
              reactive transcript renders everything (no predicted display).
agent.py      build_agent() builds a fresh pydantic-ai Agent PER TURN (cheap; the
              Provider lives in a reused ProviderRef) so runtime config changes apply
              next turn. run_turn() drives agent.iter() by hand: optimistic user-prompt
              echo, per-token streaming into a live entry, the autonomy gate, and
              typed-ahead comment interleaving are plain lines in that loop.
              Two Hooks capabilities: build_loop_capability (the "Thinking" animation
              around a NON-streamed request) and build_tool_execution_capability
              (per-tool-call group + plugin hooks + ToolResult→ToolReturn).
conversation.py  The reactive single source of truth. ONE insertion-ordered
              dict[MessageId, ModelMessage] is simultaneously the ordered list handed
              to pydantic-ai and the O(1) id-index — drift is structurally impossible.
              Mutations (append/edit/truncate_from/adopt/load/begin|update|finalize_stream)
              await registered observers. ReactiveTranscript (interface/reactive.py)
              subscribes and reduces conversation display to three hooks:
              mount / rerender / remove.
context.py    SolveigContext = the RunContext deps dataclass — exactly {config,
              interface}. Nothing else; capabilities read ctx.deps live at call time.
api.py        APIType (OPENAI/ANTHROPIC/GEMINI BaseAPI subclasses), ProviderRef,
              ModelInfo, get_provider/get_model. Flattened from the old llm/ package.
```

**Loop ownership:** core drives `agent.iter()`; pydantic-ai stays the engine for
model I/O, tool schemas, and tool execution. Consent lives in the `tool_execute`
hook — deliberately NOT pydantic-ai's `requires_approval`/`DeferredToolRequests`
(Solveig's consent is value-dependent and mid-execution: diffs, previews, 3-way
run/inspect/decline choices). Tool calls are forced sequential
(`Agent.parallel_tool_call_execution_mode("sequential")`) because the consent UI is
single-flight.

**Replay is not a special path.** `Conversation.load()` fires the same
`message_added` events a live turn does; a session file, a `system_prompt/stories`
story, and a live conversation share one blob shape (`parse_conversation_blob`).
`--add-examples` renders a recorded story mechanically, so examples can't drift.

## Design

These are not style preferences — they are the seams the codebase is built on.

- **Component-owned surfaces.** Each module registers its own subcommands. The
  config module owns `/config set`, `/config save`; the MCP module owns
  `/mcp connect`. The subcommand registry knows arg parsing and dispatch — it
  has no idea what a config or an MCP connection is. A component declares its
  surface; the framework binds it.

- **Declarative, not imperative.** Components declare what they care about and
  react to changes. The reactive transcript (`conversation.py` → observers) is
  the canonical example: one insertion-ordered dict is the single source of
  truth; mutations fire observers; the UI renders the diff. Config changes
  follow the same pattern: `SolveigConfig.notify_changed` fires, `ProviderRef`
  wakes up and fetches new model info, the stats bar refreshes. Event →
  reaction → event — never fetch → check → act.

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
  policy), shows the header, runs `@before`/`@after` plugin hooks, runs the body —
  shared by the LLM path AND a user-typed `/tool` subcommand (a hand-typed
  `/command` runs the same shellcheck a model call does). It is also the one
  enable/disable enforcement point (`ToolDisabledError`). `run_untyped_tool` gives
  a plain-function/MCP call the same group + 3-way consent generically.
- **`tools/available.py` — `AVAILABLE_TOOLS`.** A `CombinedToolset([FilteredToolset(
  FunctionToolset), *mcp_toolsets])`. `rebuild(config)` is needed ONLY after a genuine
  membership change (plugin rescan, MCP connect/disconnect) — a `tools.<name>.enabled`
  toggle is decided live per step by the FilteredToolset reading `ctx.deps.config`,
  no rebuild. `tool_classes()` feeds session replay.
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
- **Runtime schema composition:** config never hand-enumerates tools. `_compose_section`
  builds `config.tools` (from `CORE_TOOLS`, at import via a sorter-proof function-local
  import in `config/__init__`), and `config.plugins.tools`/`config.plugins.hooks` (from
  discovered plugins/hooks) in the **two-phase bootstrap** inside
  `parse_config_and_prompt` (parse → `discover_plugins` → compose → reparse). Adding a
  core tool == adding a plugin tool == adding a hook: config is untouched.
- **Enablement:** `is_tool_enabled(name)` spans `tools.*` + `plugins.tools.*`;
  `is_hook_enabled(name)` covers `plugins.hooks.*`. One rule each, consulted by both
  the schema filter and the execution guard.
- **PRESERVE+WARN:** the composed plugin sections use `extra="allow"` — a config block
  for an undiscovered plugin survives in `model_extra`, round-trips `/config save`,
  and gets a load-time warning (never silently dropped). CLI stays strict.
- **`/config save` persists only `_declared` fields** (explicitly set via file/CLI/
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
- **Hook plugins** (`plugins/hooks/`, e.g. `shellcheck.py` `@before`, `trafilatura.py`
  `@after`) — intercept a tool call for validation/transformation. A hook is a plain
  function; its config type comes from `@before/@after(config_model=…)` or bare
  `ToolConfig`. Hooks target a tool by name and are enabled-by-default.

`discover_plugins(config)` is idempotent and UI-free (folds external `plugins.paths`
into the built-in packages, then scans); `report_plugins` renders the Plugins dialog
list-all-mark-disabled (a disabled plugin is shown, never hidden). Discovery runs in
the config bootstrap (phase 1) and again in `setup_loop` for reporting.

## Interface

- `interface/base.py` — `SolveigInterface` (ABC): the display protocol + the input
  queue + the cancellation registry. `interface/reactive.py` — `ReactiveTranscript`,
  the pure observer base (mount/rerender/remove). `interface/cli/` — the Textual
  materialization (`transcript.py` maps a message part → widget; `app.py` holds the
  static theme-independent CSS).
- **Two surfaces, kept separate:** the reactive transcript (state → view) and the
  transient imperative UI (consent prompts, status bar, animations) — they never tangle.
- The **group-as-interface** trick: `interface.with_group(title)` yields a scoped
  interface whose container is fixed, so a tool body writes only within its own
  collapsible group and stays scope-oblivious. Cancellation uses an innermost-task
  stack (`_request_tasks`) so Esc/Ctrl+C cancels exactly the in-flight cancellable.
- **Native Textual theming:** palettes are registered as Textual `Theme`s; CSS is
  static and theme-independent via `$variables` (no per-widget f-string interpolation).

## Sessions

`sessions/manager.py` — one JSON blob per session file in `config.session.dir`
(default `.solveig/sessions`). `store`/`checkpoint`/`load`/`_fuzzy_find` +
`announce_resumed_session`. Serialization is pydantic-ai's own
`ModelMessagesTypeAdapter` + `to_jsonable_python`; usage comes from the shared
`RunUsage`. Resume replays through the reactive transcript (tool calls via each
`BaseTool.replay()`). Filenames are timestamped. Sessions and
`system_prompt/stories/*.jsonl` story files share one parse contract
(`parse_conversation_blob`), so a stored session doubles as a replayable story/demo.

## MCP

`mcp_servers/client.py` builds a real `pydantic_ai.mcp.MCPToolset` per connection
(refcounted `__aenter__` held for the session), filtered by `allowed_tools`/
`blocked_tools` and prefixed with a model-friendly name. `MCP_CONNECTIONS` (the single
source of truth) lives in `mcp_servers/__init__.py` — a dependency-free holder both
`client.py` and `tools/available.py` import at top level (this is the established
cycle-breaking pattern; do not reintroduce a `connections.py` or import the dict from
`client`). `connect`/`disconnect` trigger `AVAILABLE_TOOLS.rebuild()` (a genuine
membership change). Untyped MCP calls route through `run_untyped_tool`.

## Subcommands

**Push model.** Every subcommand source pushes a template into a module-level list
(`_PENDING` in `subcommand/base.py`) at import time. The `@subcommand` decorator on
a plain function does it; `BaseTool.__pydantic_init_subclass__` does it for tools.
The registry reads the list, inspects each function's signature, separates injected
deps (matched by type) from CLI args (parsed via `CliSettingsSource`), and binds a
handler. No fetch, no iterate, no two-author split in dispatch.

**Built-in commands** are standalone functions in the module that owns the behaviour:

```python
# solveig/config/commands.py
@subcommand("/config save", section="config", detail=True)
async def config_save(
    config: SolveigConfig,          # injected
    interface: SolveigInterface,    # injected
    path: str = "",                 # CLI-parsed
    full: bool = False,             # CLI-parsed → --full / --no-full
) -> None:
    ...
```

Injected types (`SolveigConfig`, `SolveigInterface`, `Conversation`, `ProviderRef`,
`SessionManager`) are provided by the framework. Bool params with defaults become
`--flag/--no-flag`. `*rest` maps to a greedy positional list.

**Tool commands** push the same way — `BaseTool.__pydantic_init_subclass__` pushes a
template with `tool_cls` set; the registry binds a handler that parses via
`from_cli_tokens` → `CliSettingsSource` and orchestrates via `run_tool_and_hooks`.

`subcommand/base.py` — the `_PENDING` list, `_SubcommandTemplate` dataclass,
`@subcommand` decorator, and `Subcommand` runtime dispatch object.
`subcommand/registry.py` — `SubcommandRegistry`: reads `_PENDING`, binds handlers,
dispatches via longest-prefix match, generates `/help`.

## Conventions that matter (do not regress)

- **No compat shims; big-bang cutovers.** Migrations go red mid-flight and green at
  the end. Commit per task even while red.
- **Seam comments explain *why*.** The load-bearing, non-obvious invariants are
  documented at the seam (see `Conversation.adopt`'s object-identity note, the
  `_compose_core_tools` import-order note, `_thinking`'s two-sites rationale). Keep
  them accurate when you change the code — several existing docstrings were allowed
  to go stale and had to be corrected.
- **Highlighted comment prefixes** project-wide: `TODO`/`FIXME`/`NOTE`/`HACK`.
- **Import-cycle law:** tools top-level-import `solveig.config`; config must not
  import tools at module level (hence the function-local import in
  `config/__init__.py`). Respect the two-phase bootstrap ordering.
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

Documented in `CLAUDE.md`; the live set includes `tools/base.py`'s
`CliSettingsSource(cls, …)` (`type: ignore[arg-type]` — typed for `BaseSettings`,
accepts a `BaseModel` at runtime), `interface/cli/queued_messages.py`'s
`queue._queue` peek, `api.py`'s `GoogleProvider(api_key=None)`, the optional-dep
`_trafilatura = None`, and `interface/cli/collapsible_widgets.py`'s framework-private
`CollapsibleTitle` import (marked `# HACK:`, re-verify on Textual upgrades).
`warn_unused_ignores` keeps them honest — remove an ignore the moment it's stale.
