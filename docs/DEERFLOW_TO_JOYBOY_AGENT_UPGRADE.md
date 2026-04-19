# DeerFlow To JoyBoy Agent Upgrade Notes

This note summarizes what is worth taking from the local DeerFlow repository for
JoyBoy's terminal, coding, tool, and agent runtime work.

DeerFlow is MIT licensed, so JoyBoy can reuse ideas and small implementation
patterns with attribution. Avoid copying provider credential flows or large
source files directly unless the license notice is preserved and the behavior is
made generic for JoyBoy's public core.

## Short Verdict

JoyBoy is already going in the same direction: a local AI harness with tools,
workspace access, model routing, packs, provider config, and a terminal mode.

DeerFlow is ahead mostly because it has a stricter agent runtime:

- the harness is separated from the app
- tools are composed through one runtime contract
- sandbox access is treated as the default execution boundary
- middleware handles errors, loops, memory, summaries, todos, titles, and token
  usage
- streaming events are documented and tested
- subagents are backend-managed instead of model-polled

The useful target is not to clone DeerFlow. The useful target is to harden
JoyBoy's local workstation identity with the same runtime discipline.

## What DeerFlow Does Better

### 1. Harness Boundary

DeerFlow separates the agent harness from the application layer. The app imports
the harness, but the harness does not import the app.

JoyBoy should move toward:

```text
core/agent_runtime/
  sessions.py
  tools.py
  middleware.py
  streaming.py
  memory.py
  subagents.py
```

Then `web/routes/terminal.py` becomes only an adapter from HTTP/SSE to runtime
events. Add a boundary test so runtime code never imports Flask routes.

### 2. Tool Runtime And Guardrails

DeerFlow's tool setup is centralized: builtins, MCP, ACP, subagents, and
configured tools are assembled in one place.

JoyBoy already has a good start in:

```text
core/backends/terminal_tools.py
core/backends/terminal_brain.py
```

Next steps:

- keep `ToolRegistry` as the source of truth
- move shell/file policy fully out of the agent loop
- add approval-card support for destructive actions instead of only blocking
- add a provider-style guardrail layer for allowlists and future local packs
- keep tool metadata public through `/terminal/tools`

### 3. Sandbox First

DeerFlow treats filesystem and shell execution as sandboxed work. It translates
virtual paths, masks host paths in output, rejects path traversal, and gates
host bash separately.

JoyBoy already protects workspace-relative file paths. The next level is:

- virtual workspace paths in prompts instead of raw local paths
- host-path masking before sending tool output back to the model
- a local sandbox adapter for shell commands
- explicit policy for when host bash is allowed
- per-session workspace roots instead of a global trust assumption

### 4. Loop And Tool-Call Recovery

DeerFlow has middleware for dangling tool calls, tool errors, and loop
detection. This matters because local models can emit malformed tool calls or
repeat the same exploratory command.

JoyBoy already has anti-loop checks in `TerminalBrain`. Keep improving them:

- normalize every tool exception into a tool result
- preserve enough context for the model to self-correct once
- hard-stop repeated identical tool signatures
- prefer final synthesis over another broad `ls`, `glob`, or `pwd`
- add tests for loop warning events

### 5. Streaming Contract

DeerFlow documents its stream modes and keeps separate state for message ids,
streamed ids, and token usage ids. This avoids duplicate events and double
counted usage.

JoyBoy should document the terminal SSE contract:

- `intent`
- `warning`
- `thinking`
- `tool_call`
- `tool_result`
- `loop_warning`
- `content`
- `done`
- `error`

Add contract tests around `web/routes/terminal.py` so frontend cards can rely on
stable event shapes.

### 6. Backend-Managed Subagents

DeerFlow's task tool starts subagents in the backend, polls internally, then
returns a final result. The model does not waste turns checking whether a task
finished.

JoyBoy can adopt a smaller version:

- `subagent.run_task(description, workspace, tools, timeout)`
- max concurrency per terminal session
- server-side polling and cancellation
- events: `task_started`, `task_running`, `task_completed`, `task_failed`
- first subagent type: read-only code explorer
- second subagent type: shell/test runner

This would make "analyse repo + propose patch + run tests" much stronger.

### 7. Skills Through Packs

DeerFlow's `SKILL.md` pattern is strong because it loads workflow knowledge
progressively instead of stuffing every instruction into the base prompt.

JoyBoy already has local packs, so use that instead of adding a new concept:

```json
{
  "skills": [
    "skills/code-review/SKILL.md",
    "skills/frontend-workflow/SKILL.md"
  ]
}
```

Runtime behavior:

- discover pack skills
- inject only the skill index first
- load the full skill only when the model or router selects it
- keep machine-specific skills outside the public core

### 8. Provider And Model Factory

DeerFlow has a model factory that resolves providers and model options from
config. It handles thinking flags, streaming usage, vision support, and provider
specific kwargs.

JoyBoy should eventually replace hardcoded Ollama assumptions with:

```text
core/models/providers/
  base.py
  ollama.py
  openai_compatible.py
  openrouter.py
  local_http.py
```

Keep credentials in environment variables, `.env`, or `~/.joyboy/config.json`.
Do not commit provider tokens or account-specific URLs.

### 9. Memory, Todos, And Summaries

DeerFlow has structured memory and todos in runtime state. For coding agents,
this is more useful than a vague chat history.

JoyBoy should add:

- per-conversation runtime todos
- summarization after long terminal loops
- structured memory facts with source and confidence
- debounced async memory writes
- a visible "plan/todos" card in the terminal UI

### 10. Tests As Runtime Contracts

DeerFlow treats tests as architecture locks. JoyBoy should add tests for:

- no Flask imports from `core/agent_runtime`
- workspace path traversal
- destructive shell denial
- stream event shapes
- loop guard behavior
- read-before-write behavior
- cancellation cleanup
- pack skill discovery without loading private files into git

## Recommended JoyBoy Roadmap

### Phase 0: Harden The Current Terminal

Low risk, no big rewrite.

- keep improving `ToolRegistry`
- hide rare tool schemas behind `tool_search`
- middle-truncate shell output so failures keep their tail
- add loop warning tests
- normalize all tool errors
- keep runtime todos visible through context compaction
- document the SSE event contract

### Phase 1: Extract Runtime Interfaces

Move contracts out of the Flask route without changing behavior:

- `AgentSession`
- `RuntimeEvent`
- `ToolResult`
- `ToolPolicy`
- `ModelClient`

`TerminalBrain` can stay as the first implementation.

### Phase 2: Add Skills And Runtime Todos

Use JoyBoy packs as the extension point.

- pack skill manifest support
- progressive `SKILL.md` loading
- todo state in conversation runtime
- terminal UI plan card

### Phase 3: Add Subagents

Start with bounded, practical workers:

- explorer subagent for read-only codebase scans
- verifier subagent for tests and shell commands
- max concurrent tasks
- timeout and cancellation
- backend-managed polling

### Phase 4: Add MCP/ACP Bridges

Only after the runtime boundary is clean.

- local MCP config in `~/.joyboy/config.json`
- lazy MCP loading
- tool metadata surfaced through the registry
- optional ACP adapters for external coding agents

## What Not To Copy Blindly

- DeerFlow's whole LangGraph stack: powerful, but it may be too heavy for
  JoyBoy's local-first desktop harness right now.
- Provider-specific OAuth internals: keep JoyBoy generic and public-safe.
- Branding or frontend skills that are DeerFlow-specific.
- Private endpoint assumptions.

## First Adopted Patch

JoyBoy now has a small `core/agent_runtime` package for DeerFlow-style runtime
primitives that must stay independent from Flask/UI code:

- stable terminal event helpers
- reusable tool loop guard
- middle truncation for long tool output
- workspace host-path masking before output reaches the model/UI
- bounded subagents callable through `delegate_subagent`:
  - `code_explorer` for read-only repo exploration
  - `verifier` for one allowlisted test/build command without shell chaining

## Second Adopted Patch

JoyBoy's terminal now adopts two more DeerFlow-style runtime habits without
pulling in the full LangGraph stack:

- deferred terminal tool discovery through `tool_search`, so web, skills,
  subagents, destructive actions, and planning tools do not spend schema tokens
  on every small turn
- `write_todos` task tracking for complex requests, auto-promoted only when the
  task looks multi-step
- active todo reminders after context compaction, so the model does not forget
  incomplete work just because the original tool call scrolled out
- a capped anti-premature-exit nudge when the model tries to finish while
  todos are still pending
- a DeerFlow-style cap on `delegate_subagent` tool calls per model response, so
  one noisy turn cannot fan out too many backend tasks
- local file-backed runtime memory through `remember_fact` and `list_memory`,
  stored under `~/.joyboy/agent_memory.json` instead of the repository

This is still intentionally smaller than DeerFlow. The next real gaps are a
proper sandbox provider, automatic memory summarization/retrieval middleware,
and a backend-managed general-purpose subagent with cancellation.

The terminal brain is wired to this runtime for loop checks and shell output
hygiene. This mirrors the DeerFlow pattern where the harness owns tool safety
instead of scattering it through routes.

JoyBoy also now has a DeerFlow-style LLM provider catalog and a first cloud
runtime slice for OpenAI-compatible terminal models:

- provider keys stay in environment variables, `.env`, or `~/.joyboy/config.json`
- provider metadata is exposed through `/api/providers/status`
- terminal models can use provider-prefixed ids such as `openai:gpt-4o-mini`,
  `openrouter:provider/model`, `deepseek:deepseek-chat`, or `vllm:Qwen/Qwen3-32B`
- Anthropic, Gemini, and Volcengine keys are cataloged for future native
  adapters without hardcoding provider logic in routes

DeerFlow web note: their default web strength is tool-based browsing/research,
not necessarily a full interactive browser. The repo includes providers for
`web_search` and `web_fetch` through DuckDuckGo, Jina, Tavily, Firecrawl, Exa,
and related extension tooling. A local model can choose and call those tools
when configured, while MCP can add heavier browser automation later.

Files:

- `core/agent_runtime/`
- `core/backends/terminal_tools.py`
- `core/backends/terminal_brain.py`
- `tests/test_agent_runtime.py`
- `tests/test_terminal_tools.py`
