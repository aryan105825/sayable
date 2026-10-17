# Product feedback

Project: Sayable (Alexa+ track, Open Source mini challenge). Tools used are listed below. Nothing here is estimated; where we did not use something, we say so.

## 1. MCP Python SDK (`mcp` 1.29.0, FastMCP) and Streamable HTTP transport

**Used for:** both reference servers (Pantry and the baseline) and the linter's own client (`sayable/mcp_client.py`). The linter's protocol checks also talk to servers over raw HTTP to see what the SDK hides.

**What worked well**
- FastMCP made a spec-conformant Streamable HTTP server short to write. `@mcp.tool` with `ToolAnnotations` and `CallToolResult(content=..., structuredContent=...)` gave us spoken text plus structured data from one return value.
- Protocol negotiation just worked: both servers negotiate 2025-11-25, and the tool listing, 202 on notifications, 400 on a bad `MCP-Protocol-Version`, 403 on a bad `Origin`, and 405/SSE on GET were all correct without extra code (checks PROTO-01 to PROTO-07 and PROTO-09 pass).
- DNS-rebinding protection (`TransportSecuritySettings` with allowed hosts and origins) is built in and enabled by explicit configuration. That is the right default for servers a voice assistant will call.
- Responses can arrive as JSON or as an SSE body. Handling both in a client was manageable once we parsed by content type.

**What needs work**
- An unknown JSON-RPC method returns `-32602` (invalid params) instead of the standard `-32601` (method not found), over HTTP 200. We saw it on both servers, and it is the only protocol check that differs (friction log FL-01). Any client or conformance tool that follows JSON-RPC will treat the server as non-conformant.
- Examples for configuring the Host/Origin allow-list for a real hostname (as opposed to localhost) were thin. A short worked example in the docs would save time.
- Using the client library across tasks hit cancel-scope constraints, so the linter opens and closes one client per call inside a single task. A documented pattern for "many short calls" would help.

**Onboarding:** The quickstart and the examples got a first server running. The parts the quickstart does not cover were transport security for non-local hosts, error codes, and client task handling; we found those by reading the installed SDK source and testing over raw HTTP.

**Would we build with it again?** Yes.

## 2. MCP specification (revision 2025-11-25)

**Used for:** the source of truth for the linter's spec checks (version header, session handling, Origin validation, notification responses, OAuth protected-resource discovery on 401).

**Worked well:** the transport section is precise enough to turn into black-box checks, which is why a protocol linter is possible at all.

**Needs work:** guidance on what "voice-ready" output looks like is missing. The spec says tools may return text and structured content, but nothing about reply length, speakability or confirmation for destructive tools. We encoded our opinions as heuristics, clearly separated from the spec checks. Authors building for voice assistants would benefit from official guidance on this.

**Would we build with it again?** Yes.

## 3. Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)

**Used for:** Pantry marks every tool explicitly; the linter's DES-01 and DES-02 check for it.

**Worked well:** annotations are exactly the signal a voice client needs to decide when to ask "are you sure?".

**Needs work:** they are advisory hints, and nothing in the protocol makes a client confirm a destructive call. Our baseline server deletes all rows on one call because the protocol allows it. We built two-phase HMAC confirmation inside the server because we could not rely on the client to do it. A standard confirmation pattern (or a client-side requirement for destructive tools) would be a real safety improvement for voice.

**Would we build with it again?** Yes.

## 4. Alexa+ as a target platform

**Used for:** this project targets the Alexa+ track by building an MCP server on the required spec and transport. We tested against our own client and linter. We did not test against an Alexa+ device or the Alexa+ MCP integration itself, so we make no compatibility claim, and Sayable is not Amazon-certified.

**What we would want:** a public conformance checklist or test harness for MCP servers that Alexa+ will call, covering reply length, structured content, latency budgets and confirmation of destructive actions. That is what Sayable tries to be, and an official version would be better than ours.

## 5. SQLite, Docker/Caddy, GitHub Actions

Used as ordinary infrastructure. SQLite served as a real store for the reference server and for direct row-count proof in the safety demo. We prepared a Docker and Caddy deployment script but did not deploy a hosted endpoint in this submission. GitHub Actions runs tests and the offline verification script on each push. No feedback beyond "worked as expected".

## Feature requests

| Request | Why it matters | Urgency |
|---|---|---|
| Return `-32601` for unknown methods in the Python SDK | Standard JSON-RPC behaviour; every conformance check trips on it | Important |
| A documented confirmation pattern for destructive MCP tools | Voice has no screen to catch a mistake; today every server invents its own | Critical for voice |
| Official voice-readiness guidance and a conformance harness for servers used by voice assistants | Server authors cannot tell if their server is safe and speakable for voice | Important |
| A worked example of Host/Origin allow-lists for a real hostname behind a TLS proxy | Most first deployments hit this | Nice-to-have |
| A client-library pattern for many short calls without cancel-scope errors | Linters and test tools make many calls | Nice-to-have |

Friction log entries are in `docs/FRICTION_LOG.md`.
