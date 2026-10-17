#!/usr/bin/env bash
# @exports: scripts/export_lint_repo.sh [OUT_DIR]   (default: dist/sayable-lint)
# @imports: sayable/, LICENSE, pyproject.toml, eval/probe_args.json, tests/test_linter.py, deploy/lint_repo/{README.md,ci.yml,publish.yml}
# @env: none
# @schema: output tree: OUT_DIR/{sayable/, tests/test_linter.py, .github/workflows/{ci,publish}.yml, LICENSE, pyproject.toml, README.md, CHECKS.md, examples/probe_args.json, .gitignore}
# Copies only the linter, its unit tests and CI. pantry/ and the verification harness stay in the main repo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { echo "FAIL export_lint_repo: $*" >&2; exit 1; }

OUT="${1:-dist/sayable-lint}"
for f in sayable LICENSE pyproject.toml eval/probe_args.json tests/test_linter.py deploy/lint_repo/README.md deploy/lint_repo/ci.yml deploy/lint_repo/publish.yml; do
  [ -e "$f" ] || die "$f is missing. Run from a complete checkout."
done
case "$OUT" in
  /|.|..|"") die "refusing to use '$OUT' as the output directory." ;;
esac

rm -rf "$OUT"
mkdir -p "$OUT/examples"
cp -r sayable "$OUT/sayable"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp LICENSE pyproject.toml "$OUT/"
cp eval/probe_args.json "$OUT/examples/probe_args.json"

cat > "$OUT/.gitignore" <<'EOF'
.venv/
__pycache__/
*.egg-info/
dist/
build/
results/
EOF

cp deploy/lint_repo/README.md "$OUT/README.md"
mkdir -p "$OUT/tests" "$OUT/.github/workflows"
cp tests/test_linter.py "$OUT/tests/test_linter.py"
sed -n '1,/^## Pantry confirmation protocol/p' ARCHITECTURE.md | sed '$d' | sed '1s/.*/# Checks and scoring/' > "$OUT/CHECKS.md"
cp deploy/lint_repo/ci.yml "$OUT/.github/workflows/ci.yml"
cp deploy/lint_repo/publish.yml "$OUT/.github/workflows/publish.yml"

echo "Exported linter to $OUT"
echo "Next: cd $OUT && git init && git add . && git commit -m 'sayable-lint' and push to a public repo."
