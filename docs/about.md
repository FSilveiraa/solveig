# About Solveig

Solveig is an AI agent framework built on the principle that AI assistants are unreliable by nature tools should be both capable and trustworthy.
While other AI assistants operate on an "ask forgiveness" model, Solveig implements a consent-first approach that puts users in complete control.

## Key Features

**Consent Model**: Every operation requires explicit user approval by default.
Solveig shows you exactly what it plans to do, asks permission for file operations and commands,
and supports granular pattern-based configuration for trusted directories.

**Safe by Design**: Prioritizes direct file operations over shell commands. Supports no-commands mode,
directory isolation, and read-only operation for maximum safety. Includes a wide-spanning test suite.

**Plugin Architecture**: Extensible system with Requirements (new AI capabilities) and Hooks (pre/post-processing).
Add new functionality without modifying core code.

**Provider Independence**: Works with any OpenAI-compatible API, plus native support for OpenAI, Claude,
Gemini,and local models.

**Visual Interface**: Styled terminal output with progress tracking, clear task breakdowns, and rich metadata display.

## FAQ

**What is Solveig?**

An AI agentic framework. It's not a model nor is it an agent, it's a tool that enables safe, agentic behavior
from any model or provider on your computer.

**Is Solveig safe to run?**

Solveig goes to great lengths to ensure user safety with clear information displays, sensible defaults,
comprehensive testing and an included Shellcheck plugin. You can disable commands entirely, which ensures
Solveig cannot even ask you to run Shell code. 
However, it's ultimately a connection between an LLM and your computer's files and shell, which carries inherent
risks. You remain responsible for any operations you approve.

**How does Solveig work?**

Solveig creates a conversation loop with a model where it sends the assistant a list of available resources
and a user prompt, and it plans and acts out a series of tasks to solve it. Solveig can create task lists,
request files and commands, analyze results and adapt to failure.

**Why are there 2 types of plugins?**

You can extend Solveig in any of 2 ways:
- By adding a new requirement, representing a new resource the LLM can request.
- By adding a hook that captures the requirement before or after it's been processed for validation or altering.

See the [Plugins](./plugins.md) page for more information

## Market Comparison

Solveig shares a space with several other tools, mature and with better user adoption that you should reasonably
consider as alternatives. I believe Solveig fills in a relevant niche and I intend for the project to both offer
unique feature sets that no other tool does (like plugins), while also striving to make it the best at core shared
features, like a proper user interface and granular consent modules. I still think all of these tools are worth
using and I have tried some of them myself.

| Feature               | Solveig              | Claude Code          | Cursor               | Cline            | Open Interpreter      | Aider     |
|-----------------------|----------------------|----------------------|----------------------|------------------|-----------------------|-----------|
| **Granular Consent**  | ✅ Patterns           | 🆗 CLAUDE.md         | ✅ Autonomy Slider    | ✅                | 🆗 Yes/No + Safe Mode | 🆗 Yes/No |
| **Extensibility**     | ✅ Plugins            | ❌                    | ✅ VS Code plugins    | ✅ MCP            | ❌                     | ❌         |
| **Provider Choice**   | ✅                    | ❌ Claude only        | ✅                    | ✅                | ✅                     | ✅         |
| **Command Execution** | ✅                    | ✅                    | ✅                    | ✅                | ✅                     | ✅         |
| **File API**          | ✅                    | ✅                    | ✅                    | ✅                | ❌                     | ✅         |
| **Agentic Features**  | 🆗 Simple task lists | ✅ Full task planning | ✅ Full task planning | ❌                | ❌                     | ❌         |
| **Standalone Tool**   | ✅ CLI                | ✅ CLI                | ❌ GUI text editor    | ❌ VS Code plugin | ✅ CLI + GUI + library | ✅ CLI     |

* **[Claude Code](https://claude.com/product/claude-code)** The current golden standard for a CLI AI assistant.
It's a feature-superset of Solveig, offering all of its capabilities while being a much more mature project
with a richer user interface. It supports state persistence through features like CLAUDE.md that I plan to add.
It has full planning capabilities, with task lists, retry mechanisms and fallbacks.
However, it only supports Claude as a model and has no extensibility through plugins. It's also missing some
relevant configurations, like no-command mode or explicitly restricting file access to certain paths.
As far as I can tell, there is no way to fully restrict Claude from even trying to access your root directory.
I used Claude Code extensively in the development of Solveig, and it served as a comparison for usability
and feature set. Several features and visual quirks were heavily inspired from Claude's user interface, like
the "Waiting..." animations.

* **[Cline](https://cline.bot/)** an open-source IDE extension available for VS Code and Jetbrains. It's focused
on assisting developers and supports multiple providers. It has a simple consent model, supports rich browser
interaction for web applications (it can even take screenshots of web pages!), and can have new functionality
added on-the-fly through a [Model Context Protocol](https://github.com/cline/cline?tab=readme-ov-file#add-a-tool-that).
Overall Cline seems like a very powerful and mature tool, but the fact that it relies on an IDE just sets it
fundamentally apart from Solveig.

* **[Cursor](https://cursor.com/)** - An AI-first code editor built as a fork of VS Code rather than a CLI assistant.
It focuses on in-editor AI integration with features like Tab completion, inline code generation and an Agent mode
that can autonomously complete coding tasks. Cursor supports multiple AI providers (OpenAI, Anthropic, Gemini, xAI)
and has a Privacy Mode where code never leaves the user's machine.
It has huge adoption and excels at providing an AI-native IDE experience with features like codebase indexing and
multi-file editing.
It's fundamentally a GUI application rather than a CLI tool, and this makes it more comparable to VS Code with AI
extensions than to command-line assistants like Solveig.
Cursor has a very interesting consent mechanism - users define how in control they want to be through an
"autonomy slider" that changes what the assistant has to ask for permission for. This enables features like
fully-integrated task planning, however it's more about pre-allowing file operations within the project
directory that the editor is working on, and not so much a system-wide permission system.

* **[Open Interpreter](https://github.com/openinterpreter/open-interpreter)** - OI is an interpreter for commands and
code generated by an LLM. It supports Shell commands as well as multiple languages like JS and Python.
It can be run in multiple ways - as a CLI tool, as a library integrated into another project and even as a desktop
app, and is very configurable.
Open Interpreter seems to take user safety seriously, with clear warnings and an experimental Safe Mode.
However, it has no built-in File API meaning it relies on commands for every operation, which is a valid concern.
Its permission model is also a basic Yes/No prompt and it currently has no plugin extensibility.
I'm thinking of adopting some of their functional features, like offering a similar Semgrep shell analysis plugin
[similar to their Safe Mode](https://github.com/OpenInterpreter/open-interpreter/blob/main/docs/SAFE_MODE.md) or
use the same strategy for [token counting with reasonable fallbacks](https://docs.litellm.ai/docs/completion/token_usage#2-cost_per_token).

* **[Aider](https://aider.chat/)** - Possibly the closest tool to what Solveig tries to offer in terms of sheer
functionality. It supports all of its core features, including provider choice, a file API alongside command
execution, and is intensely focused on development assistance. The flow and functionality is very similar to
what Solveig already does, while being a much more mature and project with real testing from user adoption.
I think the very simple interface is honestly the biggest drawback, and the consent model is a basic
Yes/No compared to our granular permissions. Despite that the UI still has some very nice features, like a
very good file diff view with linting that I'm thinking of adopting eventually. 
It has no extensibility through plugins, but Aider itself can be integrated into an IDE through plugins.
One of its most interesting features is having a shorthand command to [scrape a webpage using playwright with a
command](https://aider.chat/docs/install/optional.html#enable-playwright) that the assistant can then interact with.
It's also very configurable - onestly, give Aider a try, it's a very useful tool, people have built businesses with
it.


## Design Principles

These are the core principles I try to follow use when building Solveig:

- **User consent and safety** - Built around sane, secure defaults and the idea that people shouldn't be
afraid of trying out Solveig without first reading documentation.
By default, it requires consent before reading files, executing commands, or making changes, ensuring users
maintain control over their system at every step.
Solveig also maintains a comprehensive test suite with wide coverage.

- **Advanced configurability** - Offers extensive customization through glob patterns, permission rules and
operation-specific controls. Power users can disable or auto-allow commands, auto-approve trusted paths,
or create custom resources through plugins and configuration files.

- **Code restrictions over notes** - The limitations around what is allowed should be explicit and bound
by code, not (only) notes in the system prompt for the assistant. Assume user error is a serious concern
and that it's best if dangerous actions can't be prompted at all.

- **File API over Shell commands** - Filesystem operations through our File API are fundamentally safer
than shell code execution. The system prompt instructs models to prioritize File Requirements, and the
configuration allows excluding commands entirely.

- **Plugin extensibility** - New capabilities should be additive, not require core modifications. Plugins
are simple drop-in files that anyone can develop - an 80-line Python file can add new LLM resources or
interact with existing ones without requiring PRs to project code.

- **Visual transparency** - Informed decisions require information being displayed clearly. The interface
tracks planned tasks and shows resolved file paths and contents with clear visual guidelines so users can
make safe choices. The code interface remains abstract enough to support future alternatives like web
interfaces with media rendering and HTML support.

- **Industry standards** - Solveig adopts proven patterns from leading agentic AI tools. Several features were
inspired by or functionally copied from other tools - see the [Market Comparison](#market-comparison) for details.

- **Dynamic sessions** - Although not yet implemented, assume that the configuration can change along the session,
which influences early design decisions. It's hard to loosen a system that was built rigid by design.


## Roadmap

- **Plugin config from CLI args** - Currently it's only possible to configure plugins from a file configuration.
I'd like to extend this to CLI args, it seems easy to add without breaking anything, and it's just an expected
feature. I also have to find a way to have the plugins have some sort of documentation with configuration. 

- **Code linting and diff view** - Two very common features in this type of tool, allowing the interface to
display content visually formatted according to its type and giving users a clearer idea of exactly what is
being changed. The diff view might be more than just graphical, especially for very large files it might be
valuable to have some sort of localized per-line updated.

- **Better theme support** - The current CLI theming is static and not very well internally organized across
different modules. I'd like to review and expand this module, maybe make it configurable.

- **Web interface** - I've started the work on a web interface for solveig and I'm convinced it offers some real
value - rendering generated HTML and images, allowing deeper visual customization, better visual structuring
with collapsible directory trees, etc. However, this is not expected to be available anytime soon.

- **Session awareness** - I'd like to have some sort of persistence. I think this should involve some kind of
CLAUDE.md approach, although I would also like to consider some sort of progress tracking. I don't want to assume
git is always available for reading.
