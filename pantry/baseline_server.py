# @exports: BaselineConfig(port: int, db_path: str) frozen dataclass
# @exports: load_config() -> BaselineConfig  # the only place BASELINE_PORT and BASELINE_DB are read; raises RuntimeError with a fix hint
# @exports: build_server(cfg: BaselineConfig, host: str = "127.0.0.1") -> FastMCP  # name "baseline-pantry", path /mcp
# @exports: main(argv: list[str] | None = None) -> int
# @imports: pantry/db.py:connect, add_item, delete
# @env: BASELINE_PORT
# @env: BASELINE_DB
# @schema: README disclosure: baseline is a conventional design we wrote, not a claim about any other team.
# @schema: no annotations; errors propagate raw; same SQLite schema as Pantry
# @schema: get_inventory() -> markdown table string
# @schema: get_expiring(days:int=7) -> json.dumps string with ISO timestamps (expires_at, added_at)
# @schema: add_item(name:str, quantity:int, expires_at:str|None=None) -> plain string
# @schema: delete_items(scope:str, names:list[str]|None=None) -> deletes immediately, returns plain string; scope "named"|"expired"|"all"
# @schema: CLI: python -m pantry.baseline_server [--host H]  # serves http://HOST:BASELINE_PORT/mcp
import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from pantry import db


@dataclass(frozen=True)
class BaselineConfig:
    port: int
    db_path: str


def load_config() -> BaselineConfig:
    raw_port = os.environ.get("BASELINE_PORT", "").strip() or "8802"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(f"BASELINE_PORT={raw_port!r} is not an integer. Fix it in .env.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"BASELINE_PORT={port} must be between 1 and 65535. Fix it in .env.")
    db_path = os.environ.get("BASELINE_DB", "").strip()
    if not db_path:
        raise RuntimeError(
            "BASELINE_DB is not set. Copy .env.example to .env and export it "
            "(set -a; source .env; set +a)."
        )
    return BaselineConfig(port=port, db_path=db_path)


def build_server(cfg: BaselineConfig, host: str = "127.0.0.1") -> FastMCP:
    hosts = [f"127.0.0.1:{cfg.port}", f"localhost:{cfg.port}"]
    origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )
    mcp = FastMCP("baseline-pantry", host=host, port=cfg.port, transport_security=security)

    @mcp.tool()
    def get_inventory() -> str:
        """Return all inventory rows as a markdown table."""
        conn = db.connect(cfg.db_path)
        try:
            rows = conn.execute(
                "SELECT id, name, quantity, expires_on, added_at FROM items ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        lines = [
            "| id | name | quantity | expires_on | added_at |",
            "|----|------|----------|------------|----------|",
        ]
        for r in rows:
            lines.append(
                f"| {r['id']} | {r['name']} | {r['quantity']} | {r['expires_on'] or ''} | {r['added_at']} |"
            )
        return "\n".join(lines)

    @mcp.tool()
    def get_expiring(days: int = 7) -> str:
        """Return items expiring within N days as JSON."""
        cutoff = (date.today() + timedelta(days=days)).isoformat()
        conn = db.connect(cfg.db_path)
        try:
            rows = conn.execute(
                "SELECT id, name, quantity, expires_on, added_at FROM items "
                "WHERE expires_on IS NOT NULL AND expires_on <= ? ORDER BY expires_on, id",
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
        payload = [
            {
                "id": r["id"],
                "name": r["name"],
                "quantity": r["quantity"],
                "expires_at": f"{r['expires_on']}T00:00:00+00:00",
                "added_at": r["added_at"],
            }
            for r in rows
        ]
        return json.dumps(payload, indent=2)

    @mcp.tool()
    def add_item(name: str, quantity: int, expires_at: str | None = None) -> str:
        """Insert a row into the inventory table."""
        expiry = date.fromisoformat(expires_at[:10]) if expires_at else None
        conn = db.connect(cfg.db_path)
        try:
            row_id = db.add_item(conn, name, quantity, expiry)
        finally:
            conn.close()
        return f"Inserted row {row_id}: {name} x{quantity} (expires_at={expires_at})"

    @mcp.tool()
    def delete_items(scope: str, names: list[str] | None = None) -> str:
        """Delete rows by scope: named, expired or all."""
        conn = db.connect(cfg.db_path)
        try:
            deleted = db.delete(conn, scope, names, date.today())
        finally:
            conn.close()
        return f"Deleted {deleted} rows (scope={scope})"

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pantry.baseline_server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    ns = parser.parse_args(argv)
    try:
        cfg = load_config()
    except RuntimeError as exc:
        print(f"pantry.baseline_server: configuration error: {exc}", file=sys.stderr)
        return 2
    print(
        f"baseline-pantry serving http://{ns.host}:{cfg.port}/mcp (db={cfg.db_path})",
        file=sys.stderr,
    )
    build_server(cfg, ns.host).run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    sys.exit(main())
