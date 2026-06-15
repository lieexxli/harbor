Implement an MCP (Model Context Protocol) server at `/app/server.py`.

The server must communicate over **stdio** (newline-delimited JSON-RPC 2.0 on
stdin/stdout) and expose **exactly** these three tools — no more, no fewer:

| Tool | Inputs | Output |
|------|--------|--------|
| `add` | `a: number, b: number` | their sum |
| `reverse` | `text: string` | the string reversed |
| `count_words` | `text: string` | number of whitespace-delimited words |

Additional protocol requirements:
- The MCP initialization handshake must complete correctly before any tool call.
- Calling a tool that does not exist must return an error to the caller (either
  an MCP tool-call error with `isError: true` or a JSON-RPC error response).
- Each tool's `inputSchema` must be present and describe its parameters.

Refer to the MCP specification: https://spec.modelcontextprotocol.io/
