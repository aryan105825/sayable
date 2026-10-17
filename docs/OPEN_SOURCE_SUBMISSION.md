# Open Source mini challenge: submission text

- **Contribution / repo URL:** https://github.com/aryan105825/sayable-lint
- **Main project repo URL:** https://github.com/aryan105825/sayable
- **GitHub username:** aryan105825
- **License:** MIT (`LICENSE` in both repos)

## What I did
Published `sayable-lint`, a new open-source command-line linter that scores any Streamable HTTP MCP server (spec 2025-11-25 or later) for voice-readiness. It was written during the hackathon window alongside the Alexa+ track project (a voice-first MCP reference server called Pantry).

## How it works
It connects to a server over HTTP and runs nine raw-protocol checks (version header, Origin handling, 202 on notifications, session handling, tools/list schema validity, unknown-method errors, OAuth discovery on 401). It then runs latency, speech and design checks: reply length, markdown or ISO timestamps in speakable text, structured output, tool annotations and confirmation parameters. It calls only the tools you list in a probe file. It reports a `spec_score` and a separate, configurable `heuristic_score`, as JSON and a single-file HTML report, and exits non-zero under `--min-score` so it can gate CI.

## Why it matters
Voice agents consume MCP servers built for screens, and nobody can measure whether a server is safe and speakable for voice. The linter gives server authors a number, an itemised list of what to fix and a CI gate. Spec conformance and opinionated heuristics are kept apart so people can trust the first and tune the second.