# LLM Providers

JoyBoy is local-first. Ollama remains the default local chat and terminal runtime.
Cloud LLM providers are optional and must be configured through environment
variables, `.env`, or the local UI config stored in `~/.joyboy/config.json`.

Never commit API keys.

## Access Modes

Each provider has one active access mode. JoyBoy treats these modes as mutually
exclusive so switching to a subscription/CLI path never silently falls back to
the stored API key.

Supported in the public core today:

* `api_key`: uses the provider key from env, `.env`, or the local UI config.
* `codex_cli`: uses Codex CLI account auth from `CODEX_AUTH_PATH`,
  `CODEX_HOME/auth.json`, or `~/.codex/auth.json`, then calls the ChatGPT Codex
  Responses endpoint. JoyBoy does not send `OPENAI_API_KEY` while this mode is
  selected.
* `claude_cli`: uses Claude Code OAuth from `CLAUDE_CODE_OAUTH_TOKEN`,
  `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`,
  `CLAUDE_CODE_CREDENTIALS_PATH`, or `~/.claude/.credentials.json`. JoyBoy uses
  Bearer OAuth headers and does not send `ANTHROPIC_API_KEY` while this mode is
  selected.

This split is deliberate. OpenAI's ChatGPT/Codex subscription path and API
Platform billing are separate systems, and other vendors make similar
distinctions between their app/CLI subscription usage and direct API usage.
Provider credentials stay in the same local config file, but the active mode
decides which one is eligible at runtime.

Gemini stays API-key based in the public core. DeerFlow's Gemini examples also
use `GEMINI_API_KEY` or an OpenAI-compatible gateway, not a Gemini subscription
CLI bridge, so JoyBoy does not expose a fake Gemini CLI mode.

## Provider Syntax

Cloud models use a provider-prefixed model id in chat and terminal mode:

```text
openai:gpt-5.4-mini
openai:gpt-5.4
openai:gpt-5.4-nano
openrouter:provider/model-name
anthropic:claude-sonnet-4-5
gemini:gemini-2.5-pro
deepseek:deepseek-chat
moonshot:kimi-k2.5
novita:deepseek/deepseek-v3.2
minimax:MiniMax-M2.5
volcengine:doubao-seed-1-8-251228
glm:glm-5.1
vllm:Qwen/Qwen3-32B
```

Plain Ollama model ids still work as before:

```text
qwen3.5:2b
qwen3.5:4b
```

The prefix guard is important: `qwen3.5:2b` is treated as an Ollama model, not
as a cloud provider.

OpenAI model ids are public in the OpenAI model docs and account availability can
also be checked with `GET /v1/models`. JoyBoy uses live model discovery for
configured providers when the API exposes a model-list endpoint, filters out
non-chat families like embeddings/image/audio, and falls back to the curated
shortlist when discovery fails.

## Supported Keys

The Settings > Models provider panel can store these keys locally:

```text
HF_TOKEN
CIVITAI_API_KEY
OPENAI_API_KEY
OPENROUTER_API_KEY
ANTHROPIC_API_KEY
GEMINI_API_KEY
DEEPSEEK_API_KEY
MOONSHOT_API_KEY
NOVITA_API_KEY
MINIMAX_API_KEY
VOLCENGINE_API_KEY
ZHIPU_API_KEY
VLLM_API_KEY
```

`VLLM_BASE_URL` can be set in the process environment or `.env` when the vLLM
server is not available at `http://localhost:8000/v1`.
`GLM_BASE_URL` can override the default Zhipu endpoint
`https://open.bigmodel.cn/api/paas/v4`.

## Runtime Status

Chat and terminal mode can use these provider families when their keys are
configured:

* OpenAI
* OpenRouter
* Anthropic Claude via the Messages API
* Google Gemini via the Generative Language API
* DeepSeek
* Moonshot/Kimi
* Novita
* MiniMax
* Volcengine/Doubao
* Zhipu/GLM
* vLLM

OpenAI-compatible providers share the same `/chat/completions` adapter.
Anthropic and Gemini use small native adapters that translate JoyBoy's internal
tool loop into each provider's tool-call format, then normalize the response
back to the same `message/tool_calls` shape used by Ollama.

## DeerFlow Pattern Adopted

The design mirrors the useful DeerFlow idea:

* provider config is data, not scattered conditionals
* API keys are resolved from env/local config at call time
* Codex CLI auth is read from the same account file DeerFlow uses
* Claude Code OAuth accepts the same env/file handoff DeerFlow documents
* configured provider model lists are discovered live when possible
* tool-capable cloud models plug into the same terminal tool loop
* provider metadata is exposed to the UI without exposing secrets
* provider-specific behavior stays behind a model client boundary

This lets JoyBoy use cloud LLMs for chat, coding, and terminal work while
keeping image, inpainting, video, packs, and local routing on the existing local
machine stack.
