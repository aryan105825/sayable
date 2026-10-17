#!/usr/bin/env bash
# Re-creates this repo's history as a sequence of logical commits, one per development phase.
# Run from the root of the main "sayable" repo:   bash split_main_history.sh
# Safe by design: your current history is kept on the branch "backup-before-split", and the script
# verifies that the final tree is identical to your working tree before it finishes.
# It does NOT change commit dates. Do not backdate commits.
set -euo pipefail

git rev-parse --git-dir >/dev/null 2>&1 || { echo "ERROR: run this inside the git repo."; exit 1; }
[ -f pantry/server.py ] && [ -f sayable/schemas.py ] || { echo "ERROR: run from the root of the main sayable repo."; exit 1; }
if git show-ref --verify --quiet refs/heads/backup-before-split; then
  echo "ERROR: branch backup-before-split already exists. Rename or delete it first."; exit 1
fi
if git show-ref --verify --quiet refs/heads/staged; then
  echo "ERROR: branch 'staged' already exists. Delete it first: git branch -D staged"; exit 1
fi

# Keep noisy per-run server logs out of the repo.
grep -qxF 'results/third_party/*.server.log' .gitignore || echo 'results/third_party/*.server.log' >> .gitignore

tree_of_working_dir() { # hash of the working tree as git would commit it (respects .gitignore)
  local idx; idx="$(mktemp)"; rm -f "$idx"
  GIT_INDEX_FILE="$idx" git add -A >/dev/null 2>&1
  GIT_INDEX_FILE="$idx" git write-tree
  rm -f "$idx"
}
BEFORE="$(tree_of_working_dir)"

git branch backup-before-split HEAD
git checkout -q --orphan staged
git rm -r -q -f --cached . >/dev/null 2>&1 || true

commit() { # "message" path...
  local msg="$1"; shift
  git add -- "$@"
  git commit -q -m "$msg"
  echo "  committed: $msg"
}

echo "Phase 0: project setup"
commit "chore: project scaffolding, MIT license and pinned dependencies" \
  LICENSE .gitignore pyproject.toml requirements.txt .env.example

echo "Phase 1: linter foundation (Milestone 1)"
commit "feat(linter): finding types and spec/heuristic scoring" \
  sayable/__init__.py sayable/schemas.py
commit "feat(linter): raw-HTTP protocol checks PROTO-01..09 with JSON and SSE parsing" \
  sayable/checks_protocol.py
commit "feat(linter): MCP client with one client per call" \
  sayable/mcp_client.py

echo "Phase 2: Pantry reference server and baseline"
commit "feat(pantry): SQLite layer and speakable formatting" \
  pantry/__init__.py pantry/db.py pantry/speech.py
commit "feat(pantry): voice-first MCP server with HMAC two-phase confirmation" \
  pantry/server.py
commit "feat(pantry): conventional baseline server for comparison" \
  pantry/baseline_server.py

echo "Phase 3: linter heuristics, CLI and reports (Milestone 2)"
commit "feat(linter): speech, latency and design checks" \
  sayable/checks_speech.py sayable/checks_design.py
commit "feat(linter): CLI, JSON and single-file HTML reports, probe-args format" \
  sayable/lint.py sayable/report_html.py eval/probe_args.json
commit "test: unit tests for the linter and Pantry" \
  tests/test_linter.py tests/test_pantry.py
commit "ci: run unit tests and offline verification on every push" \
  .github/workflows/ci.yml

echo "Phase 4: proof (Milestone 3)"
commit "feat(proof): bulk-delete safety demo with direct SQLite counts" \
  scripts/safety_demo.py
commit "feat(proof): lint unmodified third-party example servers locally" \
  scripts/lint_third_party.sh eval/third_party.specs.example eval/third_party.specs
commit "feat(proof): verify.sh one-command verification of every claim" \
  scripts/verify.sh
commit "results: measured scorecards, safety demo and third-party lint output" \
  results

echo "Phase 5: open-source packaging and deployment"
commit "feat(oss): export script and templates for the standalone sayable-lint repo" \
  scripts/export_lint_repo.sh deploy/lint_repo
commit "deploy: Dockerfile and Caddy deploy script for a hosted Pantry (not used in the submission)" \
  deploy/Dockerfile deploy/deploy.sh

echo "Phase 6: documentation"
commit "docs: architecture, scoring formula and check catalogue; claims ledger" \
  ARCHITECTURE.md CLAIMS.md
commit "docs: friction log, product feedback, video script and Open Source submission text" \
  docs
commit "docs: README with measured results and disclosures" \
  README.md

# Anything not listed above still gets committed, so no file is silently dropped.
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
  echo "WARNING: final tree differs from your working tree. Restore with: git checkout -f backup-before-split"; exit 1
fi
echo; git log --oneline
echo; echo "Next: git push --force-with-lease origin main   (rewrites the remote history; this is a solo repo)"
