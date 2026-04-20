# LLM Providers

JoyBoy is local-first. Ollama remains the default local chat and terminal runtime.
Cloud LLM providers are optional and must be configured through environment
variables, `.env`, or the local UI config stored in `~/.joyboy/config.json`.

Never commit API keys.

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
* configured provider model lists are discovered live when possible
* tool-capable cloud models plug into the same terminal tool loop
* provider metadata is exposed to the UI without exposing secrets
* provider-specific behavior stays behind a model client boundary

This lets JoyBoy use cloud LLMs for chat, coding, and terminal work while
keeping image, inpainting, video, packs, and local routing on the existing local
machine stack.
