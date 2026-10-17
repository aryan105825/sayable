# Friction log

### FL-01: PROTO-08 unknown method returns -32602
- Tool / API: mcp 1.29.0 (FastMCP, Streamable HTTP)
- Trying to do: pass the spec check that an unknown JSON-RPC method returns -32601
- Expected: -32601 Method not found
- Actual: HTTP 200 with error code -32602 (observed on both servers)
- Severity: minor
- Workaround: none; reported as a known deviation
- Suggestion: map unknown methods to -32601 in the SDK

### FL-02: Pantry exits when CONFIRM_SECRET is empty
- Trying to do: start `python -m pantry.server` by hand from .env.example
- Actual: "CONFIRM_SECRET must be set to at least 16 characters"; verify.sh hides this by generating a temporary secret
- Severity: slowed us down
- Suggestion: add the secret step to the README Quickstart

### FL-03: Stale server on port 8802
- Actual: "address already in use"; an old baseline server was still running
- Severity: slowed us down
- Workaround: pkill both servers before restarting
- Suggestion: scripts should check ports first and say which process holds them

### FL-04: Linter reported spec score 10 for servers that redirect /mcp to /mcp/
- Tool / API: mcp 1.29.0 official example servers (Starlette), Streamable HTTP
- Trying to do: lint two official example servers with our raw-HTTP protocol checks
- Expected: protocol checks run against the server
- Actual: POST /mcp returned HTTP 307, our checks did not follow it, so PROTO-01 failed and PROTO-02..08 were reported as not testable (spec 10/100) while the normal MCP client worked fine
- Severity: slowed us down (a bug in our linter, found only by running servers we did not write)
- Workaround: the linter now follows same-host redirects on the first initialize request, runs all checks against the final URL, and reports the redirect in PROTO-01
- Suggestion: SDK examples and docs could state the canonical endpoint URL, with or without the trailing slash