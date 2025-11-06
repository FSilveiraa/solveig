## Market Comparison

Solveig shares a space with several other tools, mostly more mature and with better user adoption, that you should
reasonably consider as alternatives. Here I want to talk about them and specifically how they compare to Solveig.
I might update this page as my project grows or other tools move in relevancy.

I believe Solveig fills in a relevant niche, and I intend for the project to both offer unique feature sets that no
other tool does (like the drop-in plugin system), while also striving to make it the best at core shared features
(proper UI, pattern-based consent configs). I still think all of these tools are worth
using, and some of Solveig's features or UX details have been inspired by using some of them.

*This comparison is the product of several hours of researching and trying these tools.
If I got any claims wrong, please message me or submit a correction as a PR*

| Feature                    | Solveig                                               | Claude Code            | Gemini CLI                 | Qwen Code               | Kolosal CLI             | Aider          | Open Interpreter  |
|----------------------------|-------------------------------------------------------|------------------------|----------------------------|-------------------------|-------------------------|----------------|-------------------|
| **Persistent Context**     | ❌ (In roadmap)                                        | ✅ CLAUDE.md            | ✅ GEMINI.md                | ✅ QWEN.md               | ✅ (inherited)           | ❌              | ❌                 |
| **Granular Permissions**   | ✅ Patterns                                            | ✅ Deny rules + sandbox | 🆗 Yes/no/always + sandbox | 🆗 (inherited)          | 🆗 (inherited)          | 🆗 Yes/No      | 🆗 Yes/No + Safe  |
| **Extensibility**          | ✅ Drop-in Plugins                                     | ✅ MCP + Plugins        | ✅ MCP                      | ✅ MCP                   | ✅ MCP                   | ❌              | ❌                 |
| **Provider Choice**        | ✅ Any OpenAI-compatible (Anthropic+Gemini in Roadmap) | ❌ Claude only          | 🆗 Gemini (workarounds)    | ✅ Any OpenAI-compatible | ✅ Any OpenAI-compatible | ✅              | ✅                 |
| **Command Execution**      | ✅                                                     | ✅                      | ✅                          | ✅                       | ✅                       | ✅              | ✅                 |
| **File API**               | ✅                                                     | ✅                      | ✅                          | ✅                       | ✅                       | ✅              | ❌                 |
| **Task planning**          | 🆗 Simple task lists                                  | ✅ Workflows            | ✅ Workflows                | ✅ Workflows             | ✅ Workflows             | ❌              | ❌                 | 
| **Local Models**           | ✅                                                     | ❌                      | ❌                          | ✅                       | ✅                       | ✅              | ✅                 |
| **Standalone CLI**         | ✅                                                     | ✅                      | ✅                          | ✅                       | ✅                       | ✅              | ✅ + GUI + library |
| **Open Source**            | ✅ GPL 3.0                                             | ❌                      | ✅ Apache 2.0               | ✅ Apache 2.0            | ✅ Apache 2.0            | ✅              | ✅                 |
| **Free Tier**              | ✅ Free software                                       | ❌ Paid API             | ✅ 1000 req/day             | ✅ 2000 req/day          | Free software           | Free software  | Free software     |


There are roughly 3 categories you can divide the general type of tool we call an AI Assistant:

### Enterprise/SOTA CLI Agentic Assistants
The best-in-class tools, usually offering more advanced features like multi-agent reasoning, custom workflows or
proprietary plugin marketplaces, backed by large companies, committed teams and with serious budgets behind them.
You should use these if you want something that will work consistently. Usually paid and vendor-locked, although not always.
Also, it's not obvious from the lack of screenshots, but all of these (plus Kolosal-CLI) look and behave very similarly.

- **[Claude Code](https://claude.com/product/claude-code)** - Widely considered to be the golden standard for a CLI AI assistant.
It's a feature-superset of Solveig, offering all of its capabilities while being a much more mature project
with a richer user interface. It supports state persistence through features like CLAUDE.md that I plan to add.
It has full planning capabilities with task lists, retries and plan adaptation to failure, as well as advanced
agentic features like multi-agents sessions.
Claude Code is vendor-locked to Anthropic's API and has a proprietary license (which prevents a community fork that
would fix the first issue). There is no free tier, but the basic tier offers good value.
I've had trouble locking down Claude to not access certain directories or disabling commands, but apart from that
it's in general as configurable as Solveig.
I used Claude Code extensively in the development of Solveig, and it served as a comparison for usability
and feature set. Several features and visual quirks were heavily inspired from Claude's user interface, like
the "Waiting..." animations.

- **[Gemini CLI](https://github.com/google-gemini/gemini-cli)** - Google's open-source implementation of a Claude Code clone.
It's specifically optimized for Gemini with no official support for 3rd-party models, but Google documents using it
with [LiteLLM](https://www.litellm.ai/) as middleware, which allows running it through other models and providers (including
OpenAI and Anthropic APIs). There are also community forks of the tool focused on adding other providers.
I've tried Gemini CLI, and it looks and behaves a lot like Claude Code, down to using GEMINI.md for persistence.
However, it includes some very obvious UX improvements like always showing the current directory (coming to Solveig
in a merge soon) and an excellent final stats display at the end of a session.
It has a free tier as well, although from my experience Gemini (the model family itself) gets
lost more easily in general tasks than other SOTAs like GPT and Claude Sonnet.

- **[Qwen Code](https://github.com/QwenLM/qwen-code)** - A fork of Gemini CLI, this time by Alibaba, the company behind
the free Qwen models that specifically added the ability to use any OpenAI-compatible API, including local models.
I haven't tried this one, but it looks very interesting and supports features like specific vision capabilities for
image files. It's provider-agnostic, but supposedly (and understandably) optimized for their Qwen model family.
Arguably the most promising of all of these tools, considering the combination of team+budget, current state, license
and vendor-independence.

### General CLI Assistants

Essentially, these are mostly independent projects developed by medium-to-small teams or single developers, trying to
achieve the majority of the features of their SOTA counterparts. They're all open-source and provider-independent.
Some allow different API types, but they all support any OpenAI API including local models. They also all implement
core agentic features as well as some other improvements I think are valuable (linting, sub-commands, persistence,
context window).

**Also, fairly important technicality: none of these, neither Solveig nor any of the command runners further below,
is an actual AI Assistant.
You can find a better discussion behind nomenclature in the [About](./about.md) page, but
essentially these are all agentic runtimes, frameworks that wrap a model with agentic capabilities and a user loop.
When run, these tools behave like agents, but the tools themselves and the fact that they don't include a model nor
are they optimized for a specific one means that they're referred to as AI Assistants for simplicity.*

- **[Aider](https://aider.chat/)** - Probably the most successful and user-adopted tool in this category, and very close
to what Solveig tries to offer in terms of sheer functionality. It supports all of its core features, including
provider choice, a file API alongside command execution, and is intensely focused on development assistance. The
flow and functionality is a basic user-assistant flow, while being a much more mature project with real testing
from user adoption.
The UX is pretty basic, with a user-assistant flow similar to Claude Code, although it doesn't support things like
Task Planning.
The interface is fairly simple and not very appealing, but offers clear separation of information and actually
relevant features that Solveig also adopted like code linting a file edit diff.
The consent model is a basic Yes/No compared to Solveig's granular permissions.
It has no extensibility through plugins, but Aider itself can be integrated into an IDE through plugins.
One of its most interesting and original features is having a shorthand command to [scrape a webpage using
playwright with a command](https://aider.chat/docs/install/optional.html#enable-playwright) that the assistant can then interact with.
It's also very configurable - honestly, give Aider a try, it's a very useful tool, people have built businesses with
it.

- **Kolosal CLI** - Kolosal is a fork of Qwen Code which itself is a fork of Gemini, so it's built on top of a pretty
solid foundation with an overall polished experience. This also means they carried over a lot of serious features
that would be difficult for a smaller team to add to a new project.
The team behind it built some relevant additions on top of it, mainly to do with local model integration, and
also added tool calling for models that don't officially support it.
Seems like a very cool project, although I haven't found an excuse to try it yet (I already have 4 assistants installed,
one of which I wrote).
Go give these folks a view, they forked an already good project and built decent features on top.
**If you want to try a side-project assistant that *just works*, prioritize Kolosal over Solveig.**


### AI Command Executors

These are simpler assistants that fundamentally work as pipes between an LLM and your shell.
Their categorizing feature is the lack of a File API that allows for the assistant to explicitly call operations
on Files, which I believe is a core feature in modern agentic assistants that allows for a clearer consent display
and more informed decisions. However, this almost always is accompanied by lacking other explicitly agentic features
like task planning.

This isn't necessarily criticism. I think there's distinct value in these tools and their simplicity, but this also
sets them apart more as runners for LLM-generated code, and enforces that their dedicated user base will always
require some level of comfort with interpreting and auditing commands in Bash or Python/JS code, since that's the
only way to interact with the system.

- **[Open Interpreter](https://github.com/openinterpreter/open-interpreter)** - OI is an interpreter for commands and
code generated by an LLM. It supports Shell commands as well as multiple languages like JS and Python.
It can be run in multiple ways - as a CLI tool, as a library integrated into another project and even as a desktop
app, and is very configurable.
Open Interpreter seems to take user safety seriously, with clear warnings and an experimental Safe Mode.
It has no built-in File API meaning it relies on commands for every operation, which is a valid safety concern,
but supposedly has features to integrate file access (I haven't explored this in depth).
Its permission model is also a basic Yes/No prompt and it currently has no plugin extensibility.
I'm thinking of adopting some of their functional features, like offering a similar Semgrep shell analysis plugin
[similar to their Safe Mode](https://github.com/OpenInterpreter/open-interpreter/blob/main/docs/SAFE_MODE.md) or
use the same strategy for [token counting with reasonable fallbacks](https://docs.litellm.ai/docs/completion/token_usage#2-cost_per_token).

### Other
These are grouped not because they have anything in common, but because they're fundamentally different tools.

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
I've tried Cursor for about a week and had a good experience, I specifically like how good its project-wide
awareness and how easy it is to keep track of the change history along the current session with the assistant,
specifically useful during huge breaking refactors. Honestly, if you're new to development and AI assistants in
general, try this one, a lot of people that have tried several alternatives swear it's their favorite.
It has a free trial mode and reasonable paid modes.

- **[Cline](https://cline.bot/)** an open-source IDE extension available for VS Code and Jetbrains. It's focused
on assisting developers and supports multiple providers. It has a simple consent model, supports rich browser
interaction for web applications (it can even take screenshots of web pages!), and can have new functionality
added on-the-fly through a [Model Context Protocol](https://github.com/cline/cline?tab=readme-ov-file#add-a-tool-that).
Overall Cline seems like a very powerful and mature tool, but the fact that it relies on an IDE just sets it
fundamentally apart from Solveig.
