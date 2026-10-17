# Video script (under 3:00, English, public on YouTube or Vimeo)

Lead with the safety moment. Judges may stop at 3:00. Use no third-party logos, product names on screen, or music.

1. 0:00-0:30 `python scripts/safety_demo.py`. Two servers, one request ("remove everything"). Baseline rows 12 to 0. Pantry rows 12 to 12 and it says "That removes twelve items. Say confirm to go ahead." Counts come from direct SQLite, not from the server. Say it is a direct tool call, not an AI agent.
2. 0:30-1:00 The "milk" question: `count_item` returns a clarifying question with two options. Then `remove_items` with the confirm token: first call asks, second call with the token deletes. Show a replayed token deleting nothing.
3. 1:00-1:50 `sayable-lint` on both servers and the HTML report. Say the two scores are separate: spec score (protocol) and heuristic score (our configurable opinions). Baseline is a design we wrote, not a claim about anyone else.
4. 1:50-2:25 The linter on three servers we did not write (from `results/third_party/`), with the commit hashes. Say the scores are shown as measured.
5. 2:25-2:50 `bash scripts/verify.sh --fast` green. Mention the one known SDK deviation (PROTO-08, FL-01) in a sentence. Show `pip install sayable-lint` from the standalone MIT repo and the repo URL.
