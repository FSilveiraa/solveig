# About Solveig

Solveig is an agentic runtime that can run as an assistant in your computer,
built on the principle that AI assistants are unreliable by nature
and implementing a consent model that puts users in complete control.


---


## Features and Principles

**User consent and safety** - Every operation requires explicit user approval by default. Solveig shows you
exactly what it plans to do, asks permission for any action, and supports granular pattern-based configuration
for auto-trusted operations. Built around secure defaults so users can try Solveig safely without
having to be aware of documentation quirks.

**File API over Shell commands** - Solveig prioritizes direct file operations over shell execution for
fundamental safety, and the configuration allows disabling commands entirely. Code restrictions enforce
what's allowed rather than relying solely on assistant notes.

**Advanced configurability** - Extensive customization through glob patterns, permission rules, and
operation-specific controls. Besides typical LLM configurations like Temperature and Context Size, power
users can disable commands, auto-approve trusted paths and commands - see [Usage](./usage.md) for more.

**Plugin extensibility** - New capabilities are additive, not core modifications that require code PRs.
Plugins are simple drop-in Python files that anyone can develop without requiring project PRs - see
[Plugins](plugins.md) for more

**Provider independence** - Works with any OpenAI-compatible API, plus native support for OpenAI, Claude,
Gemini, and local models. Solveig is a free and open-source tool with no artificial limitations.

**Visual transparency** - Styled terminal output with progress tracking, clear task breakdowns, and rich metadata
display. Informed decisions require clear information display. The interface remains abstract enough to support
future alternatives like web interfaces - see the [Roadmap](./about.md#roadmap) for more.

**Industry standards** - Adopts proven patterns from leading agentic AI tools. Several features were inspired
by or functionally copied from other tools, building on what works rather than reinventing solutions - see
[Market Comparison](./about.md#market-comparison) for more.


---


## FAQ

**What is Solveig?**

Solveig is a tool that allows running an AI assistant in your command-line, with safe access to commands, files
and other capabilities according to the guidelines you configure.

**What is Solveig *really*?**

Solveig is an Agentic Runtime or Agentic Scaffolding. It's not a model nor is it an agent itself, it's a tool that
enables safe, agentic behavior from any model or provider on your computer.
Let's define an agent as the complete joining of these features:
* **1. Model:** an LLM capable of parsing a prompt and generating a response, including calling actions
* **2. Resources:** the implemented actions the LLM can call (read a file, get a web page, produce C++ code, etc.)
* **3. User Loop:** a series of rules that guide assistant behavior according to real-time user interaction, with adaptation to denial, failure
* **4. Context:** an ability to maintain a state along a session, usually with some persistent history across sessions

Then Solveig offers points 2-4, and allows you to easily plug-in point 1.

**Is Solveig an agent framework like [LangChain](https://www.langchain.com/) or [VoltAgent](https://github.com/VoltAgent/voltagent)?**

Sort of. Agent frameworks allow creating specialized agents based of arbitrary criteria - you can make one that
translates natural language to emoji or creates CSS templates.
Solveig is more opinionated and focused on helping users interact with their computers. It has a well-defined (even if
general) scope meant to be used as an assistant for end-users - you don't use Solveig to *create* agents, you use
Solveig *as* an agent.

**Is Solveig safe to run?**

Solveig goes to great lengths to ensure user safety with clear information displays, sensible defaults,
comprehensive testing and an included Shellcheck plugin. You can disable commands entirely, which ensures
Solveig cannot even ask you to run Shell code. 
However, it's ultimately a connection between an LLM and your computer's files and shell, which carries inherent
risks. You remain responsible for any operations you approve.

**Does Solveig support multi-agent workflows?**

Not currently, although it might in the future - check the [Roadmap](./about.md#roadmap).

**How does Solveig work?**

Solveig creates a conversation loop between a user and the assistant, presenting the assistant with a user prompt
and a list of available resources it can invoke to solve it. The assistant plans and acts out a series of tasks to
solve it. Solveig can create task lists, request files and commands, analyze results and adapt to failure.

**Why are there 2 types of plugins?**

You can extend Solveig in any of 2 ways:
- By adding a new requirement, representing a new resource the LLM can request (e.g. fetch a webpage).
- By adding a hook that captures the requirement before or after it's been processed for validation or altering
(e.g. clear sensitive info from any file content before sending it to the assistant).

See the [Plugins](./plugins.md) page for more information


---


## Market Comparison

Solveig shares a space with several other tools, mature and with better user adoption that you should reasonably
consider as alternatives. I believe Solveig fills in a relevant niche and I intend for the project to both offer
unique feature sets that no other tool does (like plugins), while also striving to make it the best at core shared
features, like a proper user interface and granular consent modules. I still think all of these tools are worth
using and I have tried some of them myself.

| Feature               | Solveig                  | Claude Code            | Cursor                 | Cline            | Open Interpreter      | Aider     |
|-----------------------|--------------------------|------------------------|------------------------|------------------|-----------------------|-----------|
| **Granular Consent**  | ✅ Patterns               | 🆗 CLAUDE.md           | ✅ Autonomy Slider      | ✅                | 🆗 Yes/No + Safe Mode | 🆗 Yes/No |
| **Extensibility**     | ✅ Plugins                | ❌                      | ✅ VS Code plugins      | ✅ MCP            | ❌                     | ❌         |
| **Provider Choice**   | ✅                        | ❌ Claude only          | ✅                      | ✅                | ✅                     | ✅         |
| **Command Execution** | ✅                        | ✅                      | ✅                      | ✅                | ✅                     | ✅         |
| **File API**          | ✅                        | ✅                      | ✅                      | ✅                | ❌                     | ✅         |
| **Agentic Features**  | 🆗 Simple task lists     | ✅ Full task planning   | ✅ Full task planning   | ❌                | ❌                     | ❌         |
| **Standalone Tool**   | ✅ CLI                    | ✅ CLI                  | ❌ GUI text editor      | ❌ VS Code plugin | ✅ CLI + GUI + library | ✅ CLI     |

- **[Claude Code](https://claude.com/product/claude-code)** The current golden standard for a CLI AI assistant.
It's a feature-superset of Solveig, offering all of its capabilities while being a much more mature project
with a richer user interface. It supports state persistence through features like CLAUDE.md that I plan to add.
It has full planning capabilities, with task lists, retry mechanisms and fallbacks.
However, it only supports Claude as a model and has no extensibility through plugins. It's also missing some
relevant configurations, like no-command mode or explicitly restricting file access to certain paths.
As far as I can tell, there is no way to fully restrict Claude from even trying to access your root directory.
I used Claude Code extensively in the development of Solveig, and it served as a comparison for usability
and feature set. Several features and visual quirks were heavily inspired from Claude's user interface, like
the "Waiting..." animations.

- **[Cline](https://cline.bot/)** an open-source IDE extension available for VS Code and Jetbrains. It's focused
on assisting developers and supports multiple providers. It has a simple consent model, supports rich browser
interaction for web applications (it can even take screenshots of web pages!), and can have new functionality
added on-the-fly through a [Model Context Protocol](https://github.com/cline/cline?tab=readme-ov-file#add-a-tool-that).
Overall Cline seems like a very powerful and mature tool, but the fact that it relies on an IDE just sets it
fundamentally apart from Solveig.

- **[Cursor](https://cursor.com/)** - An AI-first code editor built as a fork of VS Code rather than a CLI assistant.
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

- **[Open Interpreter](https://github.com/openinterpreter/open-interpreter)** - OI is an interpreter for commands and
code generated by an LLM. It supports Shell commands as well as multiple languages like JS and Python.
It can be run in multiple ways - as a CLI tool, as a library integrated into another project and even as a desktop
app, and is very configurable.
Open Interpreter seems to take user safety seriously, with clear warnings and an experimental Safe Mode.
However, it has no built-in File API meaning it relies on commands for every operation, which is a valid concern.
Its permission model is also a basic Yes/No prompt and it currently has no plugin extensibility.
I'm thinking of adopting some of their functional features, like offering a similar Semgrep shell analysis plugin
[similar to their Safe Mode](https://github.com/OpenInterpreter/open-interpreter/blob/main/docs/SAFE_MODE.md) or
use the same strategy for [token counting with reasonable fallbacks](https://docs.litellm.ai/docs/completion/token_usage#2-cost_per_token).

- **[Aider](https://aider.chat/)** - Possibly the closest tool to what Solveig tries to offer in terms of sheer
functionality. It supports all of its core features, including provider choice, a file API alongside command
execution, and is intensely focused on development assistance. The flow and functionality is very similar to
what Solveig already does, while being a much more mature and project with real testing from user adoption.
I think the very simple interface is honestly the biggest drawback, and the consent model is a basic
Yes/No compared to our granular permissions. Despite that the UI still has some very nice features, like a
very good file diff view with linting that I'm thinking of adopting eventually. 
It has no extensibility through plugins, but Aider itself can be integrated into an IDE through plugins.
One of its most interesting features is having a shorthand command to [scrape a webpage using playwright with a
command](https://aider.chat/docs/install/optional.html#enable-playwright) that the assistant can then interact with.
It's also very configurable - honestly, give Aider a try, it's a very useful tool, people have built businesses with
it.


---


## Roadmap

- ~~**Proper theme support**~~ - ✅ Added

- **Plugin config from CLI args** - Currently it's only possible to configure plugins from a file configuration.
I'd like to extend this to CLI args, it seems easy to add without breaking anything, and it's just an expected
feature. I also have to find a way to have the plugins have some sort of documentation with configuration. 

- **Code linting and diff view** - Two very common features in this type of tool, allowing the interface to
display content visually formatted according to its type and giving users a clearer idea of exactly what is
being changed. The diff view might be more than just graphical, especially for very large files it might be
valuable to have some sort of localized per-line updated.

- **Web interface** - I've started the work on a web interface for solveig and I'm convinced it offers some real
value - rendering generated HTML and images, allowing deeper visual customization, better visual structuring
with collapsible directory trees, etc. However, this is not expected to be available anytime soon.

- **Session awareness** - I'd like to have some sort of persistence. I think this should involve some kind of
CLAUDE.md approach, although I would also like to consider some sort of progress tracking. I don't want to assume
git is always available for reading.

- **Overall optimization** - The initial focus on Solveig's design was on security, not efficiency. This is
mostly forgivable as network and assistant overhead impact runtime several orders of magnitude more than, for
example, init'ing the token encoder once per message. Still, I'd like to clean up any unnecessary inefficiencies.

- **Multi-agent support** - As Solveig grows and abstracts more complex behavior into plugins, it might be
valuable to integrate some simple multi-agent capability into Solveig, where the system prompt and available
actions are constrained to a sub-set - e.g. if we can determine with some certainty that a request is only for
file operations, then we should not present the possibility to run a command. Future plugins with complex
functionality (like a `git` plugin) would especially benefit from this. But given the current capabilities,
I don't see a big advantage.

- **Workflows** - I should at least consider how this could be integrated. A very easy solution is to
have some plugins return task lists - for example, the `create_django_webapp` requirement would return the
tasks "1. write app.py", "create static/ dir" and "run app". In this way this is already "supported",
although it's more of a guideline for the LLM instead of static rule that enforces behavior.
