#!/usr/bin/env bash
# @exports: scripts/lint_third_party.sh [--out-dir DIR] [SPEC ...]
# @imports: sayable/lint.py:main (python -m sayable.lint URL --probe-args FILE --out P --html P --wait)
# @imports: eval/probe_args.json (keyed by each server's own serverInfo.name)
# @env: none (PORT is set only for the launched example server)
# @schema: SPEC = label|port|repo_dir|launch_command   (label: [a-z0-9_-]+; repo_dir: a CLEAN git checkout; command runs inside repo_dir with $PORT set and must serve Streamable HTTP at http://127.0.0.1:PORT/mcp)
# @schema: with no SPEC args, specs are read from eval/third_party.specs (one per line, blank lines and # comments ignored)
# @schema: writes DIR/<label>.json, DIR/<label>.html, DIR/<label>.server.log, DIR/<label>.lint.txt and DIR/commits.txt (label<TAB>origin url<TAB>commit sha)
# Only servers started locally on 127.0.0.1 are linted. No remote host is ever contacted.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "FAIL lint_third_party: cannot cd to $ROOT" >&2; exit 2; }

die() { echo "FAIL lint_third_party: $*" >&2; exit 2; }

if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; else PY="python3"; fi

OUT="results/third_party"
SPECS_FILE="eval/third_party.specs"
SPECS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir) [ $# -ge 2 ] || die "--out-dir needs a value"; OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) SPECS+=("$1"); shift ;;
  esac
done

if [ ${#SPECS[@]} -eq 0 ]; then
  [ -f "$SPECS_FILE" ] || die "no SPEC arguments and $SPECS_FILE does not exist. Create it with lines like: label|port|repo_dir|command (see header of this script)."
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    SPECS+=("$line")
  done < "$SPECS_FILE"
fi
[ ${#SPECS[@]} -ge 1 ] || die "no server specs found in $SPECS_FILE."

mkdir -p "$OUT" || die "cannot create $OUT"
rm -f "$OUT"/*.json "$OUT"/*.html "$OUT"/commits.txt

PID=""
stop_server() {
  if [ -n "$PID" ]; then
    kill -- "-$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
    PID=""
  fi
}
trap stop_server EXIT

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

for spec in "${SPECS[@]}"; do
  IFS='|' read -r label port repo cmd <<< "$spec"
  [[ "$label" =~ ^[a-z0-9_-]+$ ]] || die "bad label '$label' in spec '$spec' (use [a-z0-9_-])."
  [[ "$port" =~ ^[0-9]+$ ]] || die "bad port '$port' in spec '$spec'."
  [ -n "$cmd" ] || die "missing launch command in spec '$spec'."
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || die "$repo is not a git checkout (needed to record the commit hash)."
  if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then
    die "$repo has local modifications. The claim is 'unmodified', so run: git -C $repo checkout -- ."
  fi
  if port_busy "$port"; then die "port $port is already in use. Stop that process or change the port in spec '$label'."; fi

  commit="$(git -C "$repo" rev-parse HEAD)"
  remote="$(git -C "$repo" remote get-url origin 2>/dev/null || echo no-origin)"
  printf '%s\t%s\t%s\n' "$label" "$remote" "$commit" >> "$OUT/commits.txt"

  echo "== $label: starting on 127.0.0.1:$port (commit ${commit:0:12})"
  setsid bash -c 'cd "$1" && PORT="$2" exec bash -c "$3"' _ "$repo" "$port" "$cmd" > "$OUT/$label.server.log" 2>&1 &
  PID=$!

  "$PY" -m sayable.lint "http://127.0.0.1:$port/mcp" \
    --probe-args eval/probe_args.json \
    --out "$OUT/$label.json" --html "$OUT/$label.html" --wait > "$OUT/$label.lint.txt" 2>&1
  rc=$?
  cat "$OUT/$label.lint.txt"
  if [ "$rc" -ne 0 ]; then
    echo "--- last server log lines ($OUT/$label.server.log) ---" >&2
    tail -n 15 "$OUT/$label.server.log" >&2
    stop_server
    die "sayable-lint exited $rc for '$label'. Check the launch command, the port, and that the server serves /mcp."
  fi
  stop_server
  echo "OK $label -> $OUT/$label.json"
done

echo "Linted ${#SPECS[@]} server(s). Commits recorded in $OUT/commits.txt"
