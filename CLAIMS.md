# Claims ledger

Every public claim about Sayable maps to one check in `scripts/verify.sh`. The status of each claim is whatever
`results/verify_summary.json` says after a run. Nothing here is typed in by hand.

- `PASS`: the check ran and its measured numbers are in `results/`.
- `FAIL`: the check ran and did not hold. Do not quote the claim.
- `NOT CLAIMED`: the check could not run (missing credentials, URL or stretch code). The README, video and Devpost text must not mention it.

Run `bash scripts/verify.sh --fast` for C1-C8 and C12 (no cloud account, no internet). Run `bash scripts/verify.sh` for the rest.

| ID | Claim | Module | verify.sh step | Evidence file |
|----|-------|--------|----------------|---------------|
| C1 | Both servers negotiate MCP protocol 2025-11-25 or later over Streamable HTTP | `mcp_client`, `checks_protocol` | S3 | `results/lint_pantry.json`, `results/lint_baseline.json` |
| C2 | Pantry passes 8 of 9 protocol checks (27/30). The one difference is PROTO-08: `mcp` 1.29.0 returns JSON-RPC -32602 for an unknown method instead of -32601. The baseline differs identically. `verify.sh` accepts exactly this deviation (and nothing else) and prints it in the step detail; any other protocol failure is a FAIL. | `checks_protocol` | S3 | `results/lint_pantry.json` |
| C3 | **Spec parity:** baseline `spec_score` is at least 80. **Heuristic gap (labelled heuristic, configurable):** Pantry `heuristic_score` is at least 85 and at least 30 above the baseline | all checks | S3 | `results/lint_compare.json` |
| C4 | A bulk delete changes no rows on Pantry without confirmation, while the baseline deletes everything | `remove_items`, `delete_items` | S4 | `results/safety.json` (direct SQLite counts) |
| C5 | Pantry's probed replies pass SPEECH-01..05 (at most 45 words, no markdown, URL or ISO timestamp, not raw JSON, no emoji) | `checks_speech` | S3 | `results/lint_pantry.json` |
| C6 | The baseline fails at least one SPEECH check | `checks_speech` | S3 | `results/lint_baseline.json` |
| C7 | An ambiguous request ("milk") gets a clarifying question with 2 options | `count_item` | S5 | `results/tmp/check_clarify.out` |
| C8 | A confirmation token can't be forged or replayed | `verify_token`, `remove_items` | S6 and `pytest` | `results/tmp/check_tokens.out` |
| C9 | Dropped: the AWS Builder challenge is not entered, so there is no agent eval | - | - | - |
| C10 | NOT CLAIMED: third-party scorecards were not run | - | - | - |
| C11 | NOT CLAIMED: no hosted endpoint in this submission | - | - | - |
| C12 | Unit tests pass | `tests/` | S1 | `results/tmp/pytest.txt` |
| C13 | NOT CLAIMED: stretch goal, not built | - | - | - |

## Wording rules

- The baseline is "a conventional design we wrote, not a claim about any other team."
- Spec scores come from protocol checks. Heuristic scores are our opinions and are configurable. Always label them.
- Agent-eval numbers are quoted as mean ± stdev with n, repeats and model ids. Never write "better than"; write what was measured.
- Third-party scorecards are quoted per server with the commit hash from `commits.txt`.
- Sayable is not Amazon-certified and makes no claim about any voice assistant's certification.
- Keep third-party names, logos and trademarks off screen in the video.

## Before submitting

1. Run `bash scripts/verify.sh` on a fresh Ubuntu VM.
2. Open `results/verify_summary.json` and list every step with status `NOT CLAIMED` or `FAIL`.
3. Remove every mention of a `NOT CLAIMED` claim from the README, video and Devpost text.
4. Copy README numbers from `results/` only.
