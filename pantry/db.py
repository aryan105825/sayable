# @exports: default_path() -> str  # reads and validates PANTRY_DB; the only place PANTRY_DB is read
# @exports: connect(path: str | None = None) -> sqlite3.Connection  # row_factory=sqlite3.Row; creates table items; None -> default_path()
# @exports: add_item(conn, name: str, quantity: int, expires_on: date | None) -> int  # new row id; name stored lowercased
# @exports: expiring(conn, within_days: int, today: date) -> list[dict]  # {name, quantity, expires_on, days_left}; includes already-expired; ordered by expires_on, name, id
# @exports: find_names(conn, name: str) -> list[str]  # exact match wins, else substring matches, sorted
# @exports: count(conn, name: str) -> int  # SUM(quantity) for the exact name, 0 if none
# @exports: preview_delete(conn, scope: str, names: list[str] | None, today: date) -> int  # rows that delete() would remove
# @exports: delete(conn, scope: str, names: list[str] | None, today: date) -> int  # rows removed; commits
# @exports: total(conn) -> int  # row count
# @exports: reset_seed(path: str, today: date | None = None) -> int  # replaces all rows with the 12-row TEST FIXTURE; returns 12
# @exports: main(argv: list[str] | None = None) -> int
# @imports: (none)
# @env: PANTRY_DB
# @schema: table items(id INTEGER PRIMARY KEY, name TEXT NOT NULL, quantity INTEGER NOT NULL, expires_on TEXT NULL ISO date, added_at TEXT NOT NULL ISO timestamp)
# @schema: scope is one of "named" (requires names, exact match), "expired" (expires_on < today), "all"; anything else raises ValueError
# @schema: CLI: python -m pantry.db reset [--path P]  (path defaults to PANTRY_DB)
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS items ("
    "id INTEGER PRIMARY KEY, "
    "name TEXT NOT NULL, "
    "quantity INTEGER NOT NULL, "
    "expires_on TEXT, "
    "added_at TEXT NOT NULL)"
)

# TEST FIXTURE: name, quantity, expiry offset in days from "today" (None = no expiry).
SEED_ROWS: tuple[tuple[str, int, int | None], ...] = (
    ("whole milk", 1, 2),
    ("oat milk", 2, 9),
    ("eggs", 12, 5),
    ("butter", 1, 30),
    ("spinach", 1, -1),
    ("yogurt", 4, 1),
    ("chicken breast", 2, 0),
    ("apples", 6, 4),
    ("bread", 1, -2),
    ("cheddar", 1, 21),
    ("rice", 1, None),
    ("tomatoes", 5, 3),
)


def default_path() -> str:
    path = os.environ.get("PANTRY_DB", "").strip()
    if not path:
        raise RuntimeError(
            "PANTRY_DB is not set. Copy .env.example to .env and export it "
            "(set -a; source .env; set +a), or pass an explicit path."
        )
    return path


def connect(path: str | None = None) -> sqlite3.Connection:
    resolved = default_path() if path is None else path
    os.makedirs(os.path.dirname(os.path.abspath(resolved)), exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _clean_name(name: str) -> str:
    cleaned = name.strip().lower()
    if not cleaned:
        raise ValueError("item name must not be empty")
    return cleaned


def _clean_names(names: list[str] | None) -> list[str]:
    if not names:
        return []
    return sorted({n.strip().lower() for n in names if n.strip()})


def add_item(conn: sqlite3.Connection, name: str, quantity: int, expires_on: date | None) -> int:
    if quantity < 1:
        raise ValueError(f"quantity must be at least 1, got {quantity}")
    added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO items(name, quantity, expires_on, added_at) VALUES (?, ?, ?, ?)",
        (_clean_name(name), quantity, None if expires_on is None else expires_on.isoformat(), added_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def expiring(conn: sqlite3.Connection, within_days: int, today: date) -> list[dict]:
    if within_days < 0:
        raise ValueError(f"within_days must be >= 0, got {within_days}")
    cutoff = (today + timedelta(days=within_days)).isoformat()
    rows = conn.execute(
        "SELECT name, quantity, expires_on FROM items "
        "WHERE expires_on IS NOT NULL AND expires_on <= ? "
        "ORDER BY expires_on, name, id",
        (cutoff,),
    ).fetchall()
    return [
        {
            "name": r["name"],
            "quantity": r["quantity"],
            "expires_on": r["expires_on"],
            "days_left": (date.fromisoformat(r["expires_on"]) - today).days,
        }
        for r in rows
    ]


def find_names(conn: sqlite3.Connection, name: str) -> list[str]:
    needle = _clean_name(name)
    exact = conn.execute("SELECT 1 FROM items WHERE name = ? LIMIT 1", (needle,)).fetchone()
    if exact is not None:
        return [needle]
    rows = conn.execute(
        "SELECT DISTINCT name FROM items WHERE instr(name, ?) > 0 ORDER BY name", (needle,)
    ).fetchall()
    return [r["name"] for r in rows]


def count(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS q FROM items WHERE name = ?", (_clean_name(name),)
    ).fetchone()
    return int(row["q"])


def _where(scope: str, names: list[str] | None, today: date) -> tuple[str, list[str]]:
    if scope == "all":
        return "1 = 1", []
    if scope == "expired":
        return "expires_on IS NOT NULL AND expires_on < ?", [today.isoformat()]
    if scope == "named":
        cleaned = _clean_names(names)
        if not cleaned:
            raise ValueError("scope 'named' requires at least one name in 'names'")
        marks = ",".join("?" * len(cleaned))
        return f"name IN ({marks})", cleaned
    raise ValueError(f"unknown scope {scope!r}; expected 'named', 'expired' or 'all'")


def preview_delete(
    conn: sqlite3.Connection, scope: str, names: list[str] | None, today: date
) -> int:
    where, params = _where(scope, names, today)
    row = conn.execute(f"SELECT COUNT(*) AS c FROM items WHERE {where}", params).fetchone()
    return int(row["c"])


def delete(conn: sqlite3.Connection, scope: str, names: list[str] | None, today: date) -> int:
    where, params = _where(scope, names, today)
    cur = conn.execute(f"DELETE FROM items WHERE {where}", params)
    conn.commit()
    return int(cur.rowcount)


def total(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"])


def reset_seed(path: str, today: date | None = None) -> int:
    base = today if today is not None else date.today()
    added_at = f"{base.isoformat()}T00:00:00+00:00"
    conn = connect(path)
    try:
        conn.execute("DELETE FROM items")
        for name, quantity, offset in SEED_ROWS:
            expires_on = None if offset is None else (base + timedelta(days=offset)).isoformat()
            conn.execute(
                "INSERT INTO items(name, quantity, expires_on, added_at) VALUES (?, ?, ?, ?)",
                (name, quantity, expires_on, added_at),
            )
        conn.commit()
        return total(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pantry.db")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset", help="replace all rows with the 12-row test fixture")
    reset.add_argument("--path", default=None, help="SQLite file (defaults to $PANTRY_DB)")
    ns = parser.parse_args(argv)
    path = ns.path if ns.path is not None else default_path()
    rows = reset_seed(path)
    print(f"seeded {rows} fixture rows at {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
