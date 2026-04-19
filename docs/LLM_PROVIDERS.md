# LLM Providers

JoyBoy is local-first. Ollama remains the default chat and terminal runtime.
Cloud LLM providers are optional and must be configured through environment
variables, `.env`, or the local UI config stored in `~/.joyboy/config.json`.

Never commit API keys.

## Provider Syntax

Terminal cloud models use a provider-prefixed model id:

```text
openai:gpt-4o-mini
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

Terminal mode now supports three runtime families:

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
* tool-capable cloud models plug into the same terminal tool loop
* provider metadata is exposed to the UI without exposing secrets
* provider-specific behavior stays behind a model client boundary

This lets JoyBoy use cloud LLMs for coding and terminal work while keeping image,
inpainting, video, packs, and local routing on the existing local machine stack.
