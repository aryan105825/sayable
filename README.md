# Sayable

**A voice-readiness linter for MCP servers, plus a voice-first reference server (Pantry).**

Track: Alexa+. Mini challenge: Open Source (the linter is also published as its own repository, `sayable-lint`, MIT).
Not Amazon-certified. Not affiliated with or endorsed by Amazon. "Alexa+" names the hackathon track only.

## Problem

Voice agents consume MCP servers built for screens: markdown tables, ISO timestamps, long dumps, and destructive tools with no confirmation. Nobody can measure "voice-readiness". Sayable measures it over the wire.

## What is in this repo

1. `sayable-lint` (MIT): connects to any Streamable HTTP MCP server (spec 2025-11-25 or later). Runs protocol checks (**spec**) plus latency, speech and design checks (**heuristic**, configurable). Reports `spec_score`, `heuristic_score` and a 0-100 total as JSON and single-file HTML. It calls only the tools you list in a probe file.
2. Pantry: a reference voice-first MCP server on SQLite. Spoken-length replies with `structuredContent`, clarifying questions, and HMAC two-phase confirmation for bulk deletes.
3. A baseline server we wrote (a conventional, screen-first design over the same data) for comparison.

## 2-minute judge path

```bash
xdg-open results/lint_pantry.html
cat results/safety.json
bash scripts/verify.sh --fast
```

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e . pytest
cp .env.example .env   # then set CONFIRM_SECRET to 16+ random characters
pytest -q
bash scripts/verify.sh --fast
```

Linting your own server:

```bash
sayable-lint http://127.0.0.1:8000/mcp --probe-args probe_args.json --out report.json --html report.html --wait
```

## Measured results

Seeded 12-row fixture. All numbers come from `results/verify_summary.json`, `results/lint_compare.json`, `results/safety.json` and `results/third_party/`.

| Metric | Pantry | Baseline | Source |
|---|---|---|---|
| Spec score | 90 | 90 | `results/lint_compare.json` |
| Heuristic score (configurable opinion) | 97 | 66 | `results/lint_compare.json` |
| Total | 95 | 73 | `results/lint_compare.json` |
| Bulk delete, direct SQLite rows | 12 to 12 | 12 to 0 | `results/safety.json` |
| Unit tests | 73 pass | | `results/verify_summary.json` |

### Servers we did not write

Three unmodified example servers from the official MCP Python SDK, tag `v1.29.0`, commit `98b7159`, each started locally and linted over HTTP. Scores are shown as measured. They are demo servers and were not built for voice, so low heuristic scores say nothing about their quality as demos.

| Example server | Spec | Heuristic | Total | Source |
|---|---|---|---|---|
| `simple-streamablehttp` | 77 | 81 | 80 | `results/third_party/simple_streamable.json` |
| `simple-streamablehttp-stateless` | 77 | 81 | 80 | `results/third_party/simple_stateless.json` |
| `everything-server` | 90 | 86 | 87 | `results/third_party/everything.json` |

Notes on these results:
- On the two simple servers, PROTO-04 failed: a request with a foreign `Origin` got HTTP 200. Their code configures permissive CORS (`allow_origins=["*"]`), so this reflects the demo's configuration.
- The heuristic gap comes mostly from missing tool annotations and confirmation parameters (DES-01, DES-02) and, for the simple servers, no `structuredContent` (SPEECH-06).
- Commit hashes are in `results/third_party/commits.txt`.

Known SDK deviation: PROTO-08 differs on every server we tested, ours and the official examples (`mcp` 1.29.0 returns -32602 for unknown methods instead of -32601), so Pantry's protocol score is 27/30. See `docs/FRICTION_LOG.md` FL-01. A hosted endpoint is not part of this submission.

## Spec vs heuristic scores

- **Spec score**: protocol checks PROTO-01..09, derived from the MCP specification.
- **Heuristic score**: latency, speech and design checks. These encode opinions about what works in voice. Thresholds are configurable (`--max-words`, `--latency-ms`) and the scores are labelled heuristic everywhere they appear.

## Disclosures

- The baseline server (`pantry/baseline_server.py`) is a conventional design we wrote. It is not a claim about any other team's work.
- The 12-row Pantry database is a **test fixture** created by `python -m pantry.db reset`. It is not real user data.
- The bulk-delete demo is a direct tool call, not an AI agent. Row counts come from SQLite, not from the server.
- Sayable has been tested against our own client and linter and the official SDK examples. It has not been tested on an Alexa+ device.
- Claims that `verify.sh` marks `NOT CLAIMED` are not made anywhere in this repo.

## Docs

- `ARCHITECTURE.md`: design, scoring formula, check catalogue
- `CLAIMS.md`: claims ledger mapped to verification steps
- `docs/FRICTION_LOG.md`, `docs/FEEDBACK.md`
- `docs/OPEN_SOURCE_SUBMISSION.md`: text for the Open Source challenge fields
- `eval/third_party.specs.example`: template for linting unmodified third-party example servers

## License

MIT. See `LICENSE`.