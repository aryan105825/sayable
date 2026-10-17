# @exports: main(argv: list[str] | None = None) -> int
# @imports: pantry/db.py:reset_seed(path: str, today: date | None = None) -> int
# @imports: pantry/db.py:default_path() -> str
# @imports: sayable/mcp_client.py:call_tool(url: str, name: str, args: dict, timeout_s: float = 10.0) -> ProbeResult
# @env: PANTRY_PORT
# @env: BASELINE_PORT
# @env: BASELINE_DB
# @schema: CLI: python scripts/safety_demo.py [--voice-url U] [--base-url U] [--voice-db P] [--base-db P] [--out results/safety.json]
# @schema: output JSON: {generated_at, mode: "direct", baseline: Side, pantry: Side}
# @schema: Side{url, db, seeded, before, after, tool_calls: [{tool, args}], reply: str, structured: dict|None}
# Row counts come from a direct SQLite `SELECT COUNT(*) FROM items`, never from the server.
# Run from the repo root: python scripts/safety_demo.py
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pantry.db import default_path, reset_seed  # noqa: E402
from sayable.mcp_client import call_tool  # noqa: E402


def _env_config() -> dict:
    """The only place this script reads environment variables."""
    out = {}
    for var, default in (("PANTRY_PORT", "8801"), ("BASELINE_PORT", "8802")):
        raw = os.environ.get(var, default).strip()
        if not raw.isdigit():
            raise SystemExit(f"ERROR: {var}={raw!r} is not a port number. Fix it in .env.")
        out[var] = int(raw)
    out["BASELINE_DB"] = os.environ.get("BASELINE_DB", "data/baseline.db").strip()
    return out


def sql_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()


async def _side(url: str, db: str, tool: str) -> dict:
    seeded = reset_seed(db)
    before = sql_count(db)
    if before <= 0 or before != seeded:
        raise SystemExit(f"ERROR: seeding {db} gave {before} rows (reset_seed reported {seeded}). Check the DB path.")
    args = {"scope": "all"}
    pr = await call_tool(url, tool, args)
    if pr.is_error:
        raise SystemExit(f"ERROR: {tool} on {url} returned an error: {pr.text!r}")
    calls = [{"tool": tool, "args": args}]
    reply = pr.text
    structured = pr.structured
    after = sql_count(db)
    return {
        "url": url,
        "db": db,
        "seeded": seeded,
        "before": before,
        "after": after,
        "tool_calls": calls,
        "reply": reply,
        "structured": structured,
    }


def main(argv: list[str] | None = None) -> int:
    cfg = _env_config()
    p = argparse.ArgumentParser(description="Bulk-delete safety proof: same request, two servers, direct SQLite counts.")
    p.add_argument("--voice-url", default=f"http://127.0.0.1:{cfg['PANTRY_PORT']}/mcp")
    p.add_argument("--base-url", default=f"http://127.0.0.1:{cfg['BASELINE_PORT']}/mcp")
    p.add_argument("--voice-db", default=default_path())
    p.add_argument("--base-db", default=cfg["BASELINE_DB"])
    p.add_argument("--out", default="results/safety.json")
    a = p.parse_args(argv)

    async def go():
        base = await _side(a.base_url, a.base_db, "delete_items")
        voice = await _side(a.voice_url, a.voice_db, "remove_items")
        return base, voice

    base, voice = asyncio.run(go())
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "direct",
        "baseline": base,
        "pantry": voice,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"baseline: {base['before']} -> {base['after']} rows   reply: {base['reply']!r}")
    print(f"pantry:   {voice['before']} -> {voice['after']} rows   reply: {voice['reply']!r}")
    print(f"wrote {a.out}")
    if voice["after"] != voice["before"]:
        print("SAFETY FAILURE: Pantry changed rows without a confirmed request.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
