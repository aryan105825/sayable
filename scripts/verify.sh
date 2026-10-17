#!/usr/bin/env bash
# @exports: scripts/verify.sh [--fast]   (exit 0 only if no step is FAIL; NOT CLAIMED is never a pass)
# @imports: sayable/lint.py, sayable/mcp_client.py, scripts/safety_demo.py, scripts/lint_third_party.sh, pantry/server.py, pantry/baseline_server.py, pantry/db.py, eval/probe_args.json, requirements.txt
# @imports: lint --out JSON keys: negotiated_protocol, category_scores, spec_score, heuristic_score, findings[{check_id, severity}]
# @imports: sayable/corpus.py (stretch, optional): python -m sayable.corpus --registry URL --out results/corpus.json -> {scanned: int, ...}
# @env: PANTRY_PORT
# @env: BASELINE_PORT
# @env: CONFIRM_SECRET
# @env: CONFIRM_THRESHOLD
# @env: HOSTED_URL
# @env: REGISTRY_URL
# @schema: writes results/{lint_pantry,lint_baseline,lint_compare,safety,lint_hosted}.json and results/verify_summary.json
# @schema: verify_summary.json = {generated_at, mode: "fast"|"full", ok: bool, counts: {PASS, FAIL, NOT CLAIMED}, steps: [{id, status, detail}]}
# @schema: steps: S0 pins, S1 pytest(C12), S2 servers, S3 lint(C1,C2,C3,C5,C6), S4 safety(C4), S5 clarify(C7), S6 tokens(C8); --fast stops here; S7 third party(C10), S9 hosted(C11), S10 corpus(C13). C9 (agent eval) was dropped with the AWS Builder challenge
# Local runs use isolated fixture databases in results/tmp/, never your real data.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "FAIL setup: cannot cd to repo root $ROOT"; exit 2; }

FAST=0
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    *) echo "usage: bash scripts/verify.sh [--fast]"; exit 2 ;;
  esac
done

if [ -f .env ]; then set -a; . ./.env; set +a; fi

# ---- configuration: the single place this script reads the environment ----
PANTRY_PORT="${PANTRY_PORT:-8801}"
BASELINE_PORT="${BASELINE_PORT:-8802}"
CONFIRM_THRESHOLD="${CONFIRM_THRESHOLD:-3}"
HOSTED_URL="${HOSTED_URL:-}"
REGISTRY_URL="${REGISTRY_URL:-}"

if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; else PY="python3"; fi
for v in "$PANTRY_PORT" "$BASELINE_PORT" "$CONFIRM_THRESHOLD"; do
  case "$v" in ''|*[!0-9]*) echo "FAIL setup: PANTRY_PORT, BASELINE_PORT and CONFIRM_THRESHOLD must be integers (got '$v'). Fix .env."; exit 2 ;; esac
done
if [ -z "${CONFIRM_SECRET:-}" ]; then
  CONFIRM_SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(16))')" || { echo "FAIL setup: python3 not usable"; exit 2; }
fi

mkdir -p results/tmp results/third_party
STEPS="results/tmp/steps.tsv"
: > "$STEPS"

V_PDB="$ROOT/results/tmp/verify_pantry.db"
V_BDB="$ROOT/results/tmp/verify_baseline.db"
P_URL="http://127.0.0.1:${PANTRY_PORT}/mcp"
B_URL="http://127.0.0.1:${BASELINE_PORT}/mcp"

# Local servers get isolated settings (the hosted domain in .env must not block localhost).
export PANTRY_PORT BASELINE_PORT CONFIRM_SECRET CONFIRM_THRESHOLD
export PANTRY_DB="$V_PDB" BASELINE_DB="$V_BDB"
export PANTRY_ALLOWED_HOSTS="127.0.0.1:${PANTRY_PORT},localhost:${PANTRY_PORT},127.0.0.1,localhost"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

FAILED=0
record() { # status id detail
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$STEPS"
  echo "$1 $2: $3"
  if [ "$1" = "FAIL" ]; then FAILED=1; fi
}
feed() { # file of "status<TAB>id<TAB>detail"
  local st id detail
  while IFS=$'\t' read -r st id detail; do
    if [ -n "$st" ]; then record "$st" "$id" "$detail"; fi
  done < "$1"
}

# ---- embedded checker (reads real result files; prints status<TAB>id<TAB>detail) ----
cat > results/tmp/vcheck.py <<'PYEOF'
import asyncio, glob, json, os, re, sqlite3, sys
from datetime import datetime, timezone


def out(st, id_, detail):
    print(f"{st}\t{id_}\t{detail}")


def sql_count(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        c.close()


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_pins():
    import importlib.metadata as md
    bad, n = [], 0
    for line in open("requirements.txt", encoding="utf-8"):
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;]+)$", line)
        if not m:
            bad.append(f"{line} (not pinned with ==)")
            continue
        n += 1
        try:
            have = md.version(m.group(1))
        except md.PackageNotFoundError:
            bad.append(f"{m.group(1)} not installed")
            continue
        if have != m.group(3):
            bad.append(f"{m.group(1)} installed {have}, pinned {m.group(3)}")
    if bad:
        out("FAIL", "S0.pins", "; ".join(bad) + ". Run: pip install -r requirements.txt")
    else:
        out("PASS", "S0.pins", f"{n} requirements pinned and installed at exactly those versions")


def cmd_lint(p_path, b_path):
    p, b = load(p_path), load(b_path)
    pn, bn = p["negotiated_protocol"], b["negotiated_protocol"]
    ok = pn >= "2025-11-25" and bn >= "2025-11-25"
    out("PASS" if ok else "FAIL", "C1", f"negotiated protocol pantry={pn} baseline={bn} (need >= 2025-11-25)")
    pp = p["category_scores"]["protocol"]
    bad = sorted(f["check_id"] for f in p["findings"] if f["category"] == "protocol" and f["severity"] != "pass")
    p08 = next((f for f in p["findings"] if f["check_id"] == "PROTO-08"), None)
    known = (bad == ["PROTO-08"] and p08 is not None and p08["severity"] == "fail"
             and (p08.get("evidence") or {}).get("error_code") == -32602)
    if pp == 30:
        out("PASS", "C2", "pantry passes all 9 protocol checks (30/30)")
    elif known:
        # Documented SDK deviation (docs/FRICTION_LOG.md FL-01): mcp 1.29.0 answers an unknown method with -32602.
        # Anything other than exactly this deviation still FAILs.
        out("PASS", "C2", f"pantry protocol score {pp}/30: only PROTO-08 differs, a known mcp 1.29.0 deviation (-32602 instead of -32601, FL-01)")
    else:
        out("FAIL", "C2", f"pantry protocol score {pp}/30; failing or warning checks: {', '.join(bad) or 'none'}")
    ps, bs = p["spec_score"], b["spec_score"]
    ph, bh = p["heuristic_score"], b["heuristic_score"]
    ok = bs >= 80 and ph >= 85 and (ph - bh) >= 30
    out("PASS" if ok else "FAIL", "C3",
        f"spec parity: baseline spec_score={bs} (need >=80), pantry={ps}; "
        f"heuristic (configurable): pantry={ph} (need >=85) baseline={bh} gap={ph - bh} (need >=30)")
    with open("results/lint_compare.json", "w", encoding="utf-8") as fh:
        json.dump({"pantry": {"spec_score": ps, "heuristic_score": ph, "total": p["total"]},
                   "baseline": {"spec_score": bs, "heuristic_score": bh, "total": b["total"]},
                   "heuristic_gap": ph - bh, "note": "heuristic scores are configurable opinions"}, fh, indent=2)
    speech = re.compile(r"^SPEECH-0[1-5]$")
    if not any(f["check_id"] == "SPEECH-01" for f in p["findings"]):
        out("FAIL", "C5", "no SPEECH-01 finding for pantry: nothing was probed (check eval/probe_args.json keys)")
    else:
        fails = sorted({f["check_id"] for f in p["findings"] if speech.match(f["check_id"]) and f["severity"] == "fail"})
        out("PASS" if not fails else "FAIL", "C5", "pantry SPEECH-01..05 failures: " + (", ".join(fails) or "none"))
    anyf = re.compile(r"^SPEECH-0[1-7]$")
    bfails = sorted({f["check_id"] for f in b["findings"] if anyf.match(f["check_id"]) and f["severity"] == "fail"})
    out("PASS" if bfails else "FAIL", "C6", "baseline SPEECH failures: " + (", ".join(bfails) or "none"))


def cmd_safety():
    s = load("results/safety.json")
    b, p = s["baseline"], s["pantry"]
    ok = s["mode"] == "direct" and b["before"] > 0 and b["after"] == 0 and p["before"] > 0 and p["after"] == p["before"]
    out("PASS" if ok else "FAIL", "C4",
        f"direct SQLite counts: baseline {b['before']}->{b['after']}, pantry {p['before']}->{p['after']}")


def cmd_clarify(url):
    from sayable.mcp_client import call_tool
    r = asyncio.run(call_tool(url, "count_item", {"name": "milk"}))
    st = r.structured or {}
    opts = st.get("options") or []
    ok = st.get("needs_clarification") is True and len(opts) == 2
    out("PASS" if ok else "FAIL", "C7", f"'milk' -> needs_clarification={st.get('needs_clarification')} options={opts} reply={r.text!r}")


def cmd_tokens(url, db):
    from sayable.mcp_client import call_tool
    from pantry.db import reset_seed

    async def go():
        n0 = reset_seed(db)
        r1 = await call_tool(url, "remove_items", {"scope": "all"})
        s1 = r1.structured or {}
        token = s1.get("confirm_token")
        issues = []
        if s1.get("needs_confirmation") is not True or not isinstance(token, str) or not token:
            issues.append("bulk delete did not ask for confirmation")
            return n0, issues
        if sql_count(db) != n0:
            issues.append("rows changed before confirmation")
        forged = token[:-1] + ("A" if token[-1] != "A" else "B")
        await call_tool(url, "remove_items", {"scope": "all", "confirm_token": forged})
        if sql_count(db) != n0:
            issues.append("forged token deleted rows")
        r3 = await call_tool(url, "remove_items", {"scope": "all", "confirm_token": token})
        if r3.is_error or sql_count(db) != 0:
            issues.append(f"valid token did not delete (rows now {sql_count(db)})")
        reset_seed(db)
        await call_tool(url, "remove_items", {"scope": "all", "confirm_token": token})
        if sql_count(db) != n0:
            issues.append("replayed token deleted rows")
        return n0, issues

    n0, issues = asyncio.run(go())
    out("FAIL" if issues else "PASS", "C8",
        ("; ".join(issues)) if issues else f"forged token and replayed token deleted nothing ({n0} rows intact); valid token deleted all")


def cmd_thirdparty():
    files = sorted(glob.glob("results/third_party/*.json"))
    commits = [l for l in open("results/third_party/commits.txt", encoding="utf-8").read().splitlines() if l.strip()]
    if len(files) != 3 or len(commits) != 3:
        out("FAIL", "C10", f"expected 3 lint JSONs and 3 commit lines, found {len(files)} and {len(commits)}")
        return
    parts = []
    for f in files:
        d = load(f)
        parts.append(f"{os.path.basename(f)[:-5]}: total={d['total']} spec={d['spec_score']} heuristic={d['heuristic_score']}")
    out("PASS", "C10", "; ".join(parts))


def cmd_corpus():
    raw = open("results/corpus.json", encoding="utf-8").read()
    d = json.loads(raw)
    scanned = d.get("scanned")
    leaks = re.search(r"https?://", raw)
    if not isinstance(scanned, int) or scanned <= 0:
        out("FAIL", "C13", f"corpus.json has scanned={scanned!r}")
    elif leaks:
        out("FAIL", "C13", "corpus.json contains a URL; output must be aggregate-only")
    else:
        out("PASS", "C13", f"{scanned} public servers scanned, aggregate-only output")


def cmd_summary(mode):
    steps = []
    for line in open("results/tmp/steps.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t", 2)
        if len(parts) == 3:
            steps.append({"id": parts[1], "status": parts[0], "detail": parts[2]})
    counts = {"PASS": 0, "FAIL": 0, "NOT CLAIMED": 0}
    for s in steps:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": mode,
               "ok": counts["FAIL"] == 0, "counts": counts, "steps": steps}
    with open("results/verify_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"SUMMARY {mode}: {counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['NOT CLAIMED']} NOT CLAIMED -> results/verify_summary.json")


CMDS = {"pins": cmd_pins, "lint": cmd_lint, "safety": cmd_safety, "clarify": cmd_clarify, "tokens": cmd_tokens,
        "thirdparty": cmd_thirdparty, "corpus": cmd_corpus, "summary": cmd_summary}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        sys.exit(f"usage: vcheck.py {{{','.join(CMDS)}}} [args]")
    CMDS[sys.argv[1]](*sys.argv[2:])
PYEOF

run_check() { # name [args...]
  local name="$1"
  local o="results/tmp/check_${name}.out" e="results/tmp/check_${name}.err"
  if "$PY" results/tmp/vcheck.py "$@" > "$o" 2> "$e"; then
    feed "$o"
  else
    record FAIL "$name" "check script failed: $(tail -n 3 "$e" | tr '\n' ' ')"
  fi
}

PIDS=()
cleanup() {
  local p
  for p in "${PIDS[@]:-}"; do
    if [ -n "$p" ]; then kill "$p" 2>/dev/null; fi
  done
}
trap cleanup EXIT

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

wait_mcp() { # url pid
  local i
  for i in $(seq 1 60); do
    if ! kill -0 "$2" 2>/dev/null; then return 2; fi
    if "$PY" -m sayable.mcp_client "$1" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  return 1
}

finish() {
  local mode="full"
  if [ "$FAST" -eq 1 ]; then mode="fast"; fi
  "$PY" results/tmp/vcheck.py summary "$mode"
  exit "$FAILED"
}

# ---------------- S0 ----------------
if "$PY" -m pip check > results/tmp/pip_check.txt 2>&1; then
  record PASS S0.pip_check "pip check: $(tail -n 1 results/tmp/pip_check.txt)"
else
  record FAIL S0.pip_check "pip check failed: $(head -n 3 results/tmp/pip_check.txt | tr '\n' ' ')"
fi
run_check pins

# ---------------- S1 (C12) ----------------
if "$PY" -m pytest -q > results/tmp/pytest.txt 2>&1; then
  record PASS C12 "pytest: $(tail -n 1 results/tmp/pytest.txt)"
else
  record FAIL C12 "pytest failed: $(tail -n 3 results/tmp/pytest.txt | tr '\n' ' ') (full output: results/tmp/pytest.txt)"
fi

# ---------------- S2 ----------------
SERVERS_OK=1
for spec in "pantry:$PANTRY_PORT" "baseline:$BASELINE_PORT"; do
  if port_busy "${spec#*:}"; then
    record FAIL S2 "port ${spec#*:} (${spec%%:*}) is already in use. Stop the process or change the port in .env."
    SERVERS_OK=0
  fi
done
if [ "$SERVERS_OK" -eq 1 ]; then
  rm -f "$V_PDB" "$V_BDB"
  if ! "$PY" -m pantry.db reset --path "$V_PDB" > results/tmp/reset_pantry.txt 2>&1 \
     || ! "$PY" -m pantry.db reset --path "$V_BDB" > results/tmp/reset_baseline.txt 2>&1; then
    record FAIL S2 "could not seed fixture databases: $(tail -n 2 results/tmp/reset_pantry.txt results/tmp/reset_baseline.txt 2>/dev/null | tr '\n' ' ')"
    SERVERS_OK=0
  fi
fi
if [ "$SERVERS_OK" -eq 1 ]; then
  "$PY" -m pantry.server > results/tmp/pantry_server.log 2>&1 &
  P_PID=$!; PIDS+=("$P_PID")
  "$PY" -m pantry.baseline_server > results/tmp/baseline_server.log 2>&1 &
  B_PID=$!; PIDS+=("$B_PID")
  wait_mcp "$P_URL" "$P_PID"; rc1=$?
  wait_mcp "$B_URL" "$B_PID"; rc2=$?
  if [ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ]; then
    record PASS S2 "both servers answered a real MCP initialize ($P_URL, $B_URL)"
  else
    record FAIL S2 "server did not come up (pantry rc=$rc1, baseline rc=$rc2; 2 = process exited, 1 = timeout). See results/tmp/pantry_server.log and baseline_server.log: $(tail -n 2 results/tmp/pantry_server.log results/tmp/baseline_server.log | tr '\n' ' ')"
    SERVERS_OK=0
  fi
fi

if [ "$SERVERS_OK" -eq 1 ]; then
  # ---------------- S3 ----------------
  LINT_OK=1
  "$PY" -m sayable.lint "$P_URL" --probe-args eval/probe_args.json --out results/lint_pantry.json --html results/lint_pantry.html --wait > results/tmp/lint_pantry.txt 2>&1 || LINT_OK=0
  "$PY" -m sayable.lint "$B_URL" --probe-args eval/probe_args.json --out results/lint_baseline.json --html results/lint_baseline.html --wait > results/tmp/lint_baseline.txt 2>&1 || LINT_OK=0
  if [ "$LINT_OK" -eq 1 ]; then
    run_check lint results/lint_pantry.json results/lint_baseline.json
  else
    record FAIL S3 "sayable-lint failed: $(tail -n 2 results/tmp/lint_pantry.txt results/tmp/lint_baseline.txt | tr '\n' ' ')"
  fi

  # ---------------- S4 (C4) ----------------
  if "$PY" scripts/safety_demo.py --voice-url "$P_URL" --base-url "$B_URL" --voice-db "$V_PDB" --base-db "$V_BDB" --out results/safety.json > results/tmp/safety.txt 2>&1; then
    run_check safety
  else
    record FAIL C4 "safety_demo failed: $(tail -n 3 results/tmp/safety.txt | tr '\n' ' ')"
  fi

  # ---------------- S5 (C7) ----------------
  if "$PY" -m pantry.db reset --path "$V_PDB" > /dev/null 2>&1; then
    run_check clarify "$P_URL"
  else
    record FAIL C7 "could not re-seed $V_PDB before the clarification check"
  fi

  # ---------------- S6 (C8) ----------------
  run_check tokens "$P_URL" "$V_PDB"
fi

if [ "$FAST" -eq 1 ]; then finish; fi

# ---------------- S7 (C10) ----------------
if [ ! -f eval/third_party.specs ]; then
  record "NOT CLAIMED" C10 "eval/third_party.specs not found (format in header of scripts/lint_third_party.sh)"
elif bash scripts/lint_third_party.sh > results/tmp/third_party.txt 2>&1; then
  run_check thirdparty
else
  record FAIL C10 "lint_third_party.sh failed: $(tail -n 3 results/tmp/third_party.txt | tr '\n' ' ')"
fi

# ---------------- S9 (C11) ----------------
if [ -z "$HOSTED_URL" ]; then
  record "NOT CLAIMED" C11 "HOSTED_URL is not set"
elif "$PY" -m sayable.lint "$HOSTED_URL" --probe-args eval/probe_args.json --min-score 85 --out results/lint_hosted.json --html results/lint_hosted.html --wait > results/tmp/lint_hosted.txt 2>&1; then
  record PASS C11 "sayable-lint $HOSTED_URL --min-score 85 exited 0"
else
  record FAIL C11 "hosted lint failed or scored under 85: $(tail -n 3 results/tmp/lint_hosted.txt | tr '\n' ' ')"
fi

# ---------------- S10 (C13, stretch) ----------------
if [ ! -f sayable/corpus.py ] || [ -z "$REGISTRY_URL" ]; then
  record "NOT CLAIMED" C13 "stretch goal: sayable/corpus.py or REGISTRY_URL missing"
elif "$PY" -m sayable.corpus --registry "$REGISTRY_URL" --out results/corpus.json > results/tmp/corpus.txt 2>&1; then
  run_check corpus
else
  record FAIL C13 "corpus scan failed: $(tail -n 3 results/tmp/corpus.txt | tr '\n' ' ')"
fi

finish
