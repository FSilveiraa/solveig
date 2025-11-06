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
future alternatives like web interfaces - see the [Roadmap](https://github.com/FSilveiraa/solveig/discussions/2) for more.

**Industry standards** - Adopts proven patterns from leading agentic AI tools. Several features were inspired
by or functionally copied from other tools, building on what works rather than reinventing solutions - see
[Market Comparison](./comparison.md) for more.


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

Not currently, although it might in the future - check the
[Roadmap](https://github.com/FSilveiraa/solveig/discussions/2).

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
