#!/usr/bin/env bash
# Re-creates the standalone sayable-lint repo's history as logical commits.
# Run from the root of the sayable-lint repo:   bash split_lint_history.sh
# Your current history is kept on "backup-before-split". The final tree is verified. Dates are NOT changed.
set -euo pipefail

git rev-parse --git-dir >/dev/null 2>&1 || { echo "ERROR: run this inside the git repo."; exit 1; }
[ -f sayable/lint.py ] && [ ! -d pantry ] || { echo "ERROR: run from the root of the sayable-lint repo."; exit 1; }
git show-ref --verify --quiet refs/heads/backup-before-split && { echo "ERROR: branch backup-before-split already exists."; exit 1; }
git show-ref --verify --quiet refs/heads/staged && { echo "ERROR: branch 'staged' already exists: git branch -D staged"; exit 1; }

tree_of_working_dir() {
  local idx; idx="$(mktemp)"; rm -f "$idx"
  GIT_INDEX_FILE="$idx" git add -A >/dev/null 2>&1
  GIT_INDEX_FILE="$idx" git write-tree
  rm -f "$idx"
}
BEFORE="$(tree_of_working_dir)"

git branch backup-before-split HEAD
git checkout -q --orphan staged
git rm -r -q -f --cached . >/dev/null 2>&1 || true

commit() {
  local msg="$1"; shift
  git add -- "$@"
  git commit -q -m "$msg"
  echo "  committed: $msg"
}

commit "chore: MIT license, packaging metadata and gitignore" \
  LICENSE .gitignore pyproject.toml
commit "feat: finding types and spec/heuristic scoring" \
  sayable/__init__.py sayable/schemas.py
commit "feat: raw-HTTP protocol checks PROTO-01..09 with JSON and SSE parsing" \
  sayable/checks_protocol.py
commit "feat: MCP client with one client per call" \
  sayable/mcp_client.py
commit "feat: speech, latency and design checks" \
  sayable/checks_speech.py sayable/checks_design.py
commit "feat: CLI, JSON and single-file HTML reports, example probe file" \
  sayable/lint.py sayable/report_html.py examples/probe_args.json
commit "test: unit tests for scoring, checks, parsing and reports" \
  tests/test_linter.py
commit "ci: test matrix for Python 3.10-3.12 and optional PyPI publish workflow" \
  .github
commit "docs: README and check catalogue" \
  README.md CHECKS.md

git add -A
if ! git diff --cached --quiet; then
  git commit -q -m "chore: remaining files"
  echo "  committed: chore: remaining files"
fi

git branch -M main
AFTER="$(git rev-parse HEAD^{tree})"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "OK: final tree is identical to your working tree."
else
  echo "WARNING: final tree differs. Restore with: git checkout -f backup-before-split"; exit 1
fi
echo; git log --oneline
echo; echo "Next: git push --force-with-lease origin main"
