# MCP (Model Context Protocol)

JoyBoy can load external MCP servers and expose their tools to the terminal harness the same way DeerFlow exposes deferred tools:

- MCP servers stay optional
- config stays local and out of git
- tools are loaded lazily and exposed through `tool_search`
- HTTP / SSE servers can use OAuth token injection

## Where JoyBoy stores MCP config

JoyBoy keeps MCP server config in your local settings file:

```text
~/.joyboy/config.json
```

The MCP section uses the same `mcpServers` shape DeerFlow documents, but JoyBoy stores it under the local `mcp_servers` key internally.

## Example servers

JoyBoy ships DeerFlow-style templates for:

- `filesystem`
- `github`
- `postgres`

You can fetch the current config plus templates from:

```text
GET /api/mcp/config
```

And update the local config with:

```text
PUT /api/mcp/config
```

## Example payload

```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "$GITHUB_TOKEN"
      },
      "description": "Expose GitHub via MCP pour repos, issues et PR."
    }
  }
}
```

## OAuth support

For `http` and `sse` transports, JoyBoy supports OAuth token fetch + refresh:

- `client_credentials`
- `refresh_token`

Secrets should stay in environment variables or local provider config, never in git.

## Runtime status

`/api/mcp/config` returns runtime status so the UI can show:

- enabled servers
- loaded MCP tools
- config validation issues
- unresolved environment placeholders

That makes it easier to see why an MCP server is not being promoted into the terminal harness.
