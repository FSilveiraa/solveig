# About Solveig

**An AI assistant that brings safe agentic behavior from any LLM to your terminal**

[Solveig](https://github.com/FSilveiraa/solveig) can plan tasks, read files, list directory trees, edit your code, run commands and more.

---


## Features and Principles

I built Solveig under the clear knowledge that it arrived late into a space competing with long-existing
and widely-adopted tools.
I've used most of its relevant competitors, some at length and often to build Solveig itself - see
[Market Comparison](./comparison.md) for more on that - and used it to build a basic set of guiding principles
for why and how I want Solveig to exist.

**Exceptional UI** - Solveig is built on [Textual](https://textual.textualize.io/), with hundreds of hours put
into building widgets, themes, stats bars, animations, buttons, multi-choice selection, directory trees and several
other custom elements to create one of the most responsive UIs achieved in a terminal.

**Informed UX** - Solveig's powerful UI provides all the details necessary to ensure informed user choices.
Token usage, model pricing, API URL, file metadata, diff views for file editing, code linting, reasoning details,
queued messages, task lists - all of these are always easily inspectable for safe usage.

**Filesystem Tools** - Solveig prioritizes tool-based file operations over shell execution for fundamental safety,
allowing a tighter use of UI capabilities, more granular user approval controls and a more predictable outcome preview.

**Persistent Shell** - Commands are executed in a shell that persists important metadata like the `cwd`.
The UI makes this information clearly visible at all times so the user is always aware of where a command would run.

**Advanced configurability** - Nearly every aspect of Solveig that can be configurable is.
Extensive customization is achieved through glob patterns, permission rules, briefing files, and filters for
tools and plugins. See [Usage](./usage.md) for more.

**Sub-command framework** - Solveig includes a sub-command parser that allows running tools, managing sessions,
editing config values, changing models and APIs, connecting to MCP servers and more. See [Subcommands](./subcommands.md)
for more.

**Session management** - Sessions are stored by default in `./.solveig/sessions/` and can be reloaded or resumed
to continue long-running conversations.

**Plugin framework and MCP server support** - New capabilities are additive, not core modifications that require code PRs.
Plugins are simple drop-in Python files that anyone can develop, while MCP servers can easily be added and filtered.
All added tools are instantly available to the assistant. See [Plugins](plugins.md) and [MCP](./mcp.md) for more

**FOSS and provider-independent** - Solveig is a free and open-source tool, aiming to work with any
OpenAI-compatible API. I've tested Solveig with a wide range of models and providers, including local LLMs, to
ensure wide compatibility with the evolving landscape of models.

**Industry standards** - Adopts proven patterns from leading agentic AI tools. Several features were inspired
by or functionally copied from other tools, building on what works rather than reinventing solutions. See
[Market Comparison](./comparison.md) for more.


---


## FAQ

**What is Solveig?**

Solveig is an open-source agentic assistant in your command-line, allowing safe AI access to commands, files and other resources.
It's highly configurable and features plugins, MCP support, sub-commands, sessions and more.

**What is Solveig *really*?**

Solveig is an *agentic runtime*. It's not a model nor is it an agent itself, it's a tool that enables safe agentic
behavior from any model or provider on your computer.
Let's define an agent as the complete joining of these features:
* **1. Model:** an LLM capable of parsing a prompt and generating a response, including calling actions
* **2. Resources:** the implemented actions the LLM can call as tools (read a file, get a web page, produce C++ code, etc.)
* **3. User Loop:** a series of rules that guide assistant behavior according to real-time user interaction, with adaptation to denial, failure
* **4. Context:** an ability to maintain a state along a session, usually with some persistent history and context window management

Then Solveig offers points 2-4, and allows you to easily plug-in point 1.

**Is Solveig an *agent framework* like [LangChain](https://www.langchain.com/) or [VoltAgent](https://github.com/VoltAgent/voltagent)?**

No, agent frameworks allow creating specialized agents based of arbitrary criteria - you can make one that
translates natural language to emoji or creates CSS templates.
Solveig is more opinionated and focused on helping users interact with their computers.

**Is Solveig a *coding assistant* like [Claude Code](https://claude.com/product/claude-code) or [Qwen-Code](https://github.com/QwenLM/qwen-code)?**

Yes, although these tools tend to be highly focused on software development and benefit from full access to
a strict single directory tree, usually the project root.
Solveig aims and largely achieves general feature parity with most of these tools, while keeping a broader focus on
general user assistance and with informed usage as a core principle.

See the [Market Comparison](./comparison.md) for more.

**Is Solveig safe to run?**

Solveig goes to great lengths to ensure user safety with clear information displays, sensible defaults,
comprehensive testing and an included Shellcheck plugin. You can disable commands entirely, which ensures
Solveig cannot even ask you to run Shell code. 
However, it's ultimately a connection between an LLM and your computer's files and shell, which carries inherent
risks. You remain responsible for any operations you approve.

**Why are there 2 types of plugins?**

You can extend Solveig in any of 2 ways:
- By adding a new tool, representing a new resource the LLM can request (e.g. fetch a webpage).
- By adding a hook that captures the tool before or after it's been processed for validation or altering
(e.g. clear sensitive info from any file content before sending it to the assistant).

See the [Plugins](./plugins.md) page for more information
