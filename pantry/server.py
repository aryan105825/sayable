# @exports: ConfigError(RuntimeError)
# @exports: Config(port: int, db_path: str, secret: str, threshold: int, allowed_hosts: tuple[str, ...]) frozen dataclass
# @exports: load_config() -> Config  # the only place PANTRY_PORT, CONFIRM_SECRET, CONFIRM_THRESHOLD, PANTRY_ALLOWED_HOSTS are read; PANTRY_DB via db.default_path()
# @exports: make_token(scope: str, names: list[str] | None, count: int, secret: str, now: float) -> str  # HMAC-SHA256 over scope, normalised names, count, expiry (now + 60 s)
# @exports: verify_token(token: str, scope: str, names: list[str] | None, count: int, secret: str, now: float) -> bool
# @exports: build_server(cfg: Config, host: str = "127.0.0.1") -> FastMCP  # name "sayable-pantry", path /mcp
# @exports: main(argv: list[str] | None = None) -> int
# @imports: pantry/db.py:default_path, connect, add_item, expiring, find_names, count, preview_delete, delete
# @imports: pantry/speech.py:parse_when, say_date, say_number, say_list, plural, capitalize_first
# @env: PANTRY_PORT
# @env: PANTRY_DB
# @env: CONFIRM_SECRET
# @env: CONFIRM_THRESHOLD
# @env: PANTRY_ALLOWED_HOSTS
# @schema: every tool returns CallToolResult(content=[TextContent], structuredContent=dict); failures set isError=True with structuredContent {"error": code}
# @schema: whats_expiring(within_days:int=3) readOnly,idempotent -> {items:[{name,quantity,expires_on,days_left}], count:int}
# @schema: count_item(name:str) readOnly,idempotent -> {name,quantity} | {needs_clarification:true, options:[str]}
# @schema: add_item(name:str, quantity:int=1, expires_on:str|None=None) not readOnly, not destructive -> {id,name,quantity,expires_on}
# @schema: remove_items(scope:"named"|"expired"|"all", names:list[str]|None=None, confirm_token:str|None=None) destructive, not idempotent -> {removed:int} | {needs_confirmation:true, count:int, confirm_token:str}
# @schema: remove_items needs confirmation when affected rows >= CONFIRM_THRESHOLD or scope == "all"; token is single-use and expires after 60 s
# @schema: CLI: python -m pantry.server [--host 127.0.0.1]  # serves http://HOST:PANTRY_PORT/mcp
import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from pantry import db
from pantry.speech import (
    capitalize_first,
    parse_when,
    plural,
    say_date,
    say_list,
    say_number,
)

TOKEN_TTL_S = 60
MIN_SECRET_LEN = 16


class ConfigError(RuntimeError):
    """Invalid or missing environment configuration."""


@dataclass(frozen=True)
class Config:
    port: int
    db_path: str
    secret: str
    threshold: int
    allowed_hosts: tuple[str, ...]


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not an integer. Fix it in .env.") from exc
    if not low <= value <= high:
        raise ConfigError(f"{name}={value} must be between {low} and {high}. Fix it in .env.")
    return value


def load_config() -> Config:
    port = _int_env("PANTRY_PORT", 8801, 1, 65535)
    threshold = _int_env("CONFIRM_THRESHOLD", 3, 1, 1000)
    secret = os.environ.get("CONFIRM_SECRET", "").strip()
    if len(secret) < MIN_SECRET_LEN:
        raise ConfigError(
            f"CONFIRM_SECRET must be set to at least {MIN_SECRET_LEN} characters. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    raw_hosts = os.environ.get("PANTRY_ALLOWED_HOSTS", "").strip()
    if raw_hosts:
        hosts = tuple(h.strip() for h in raw_hosts.split(",") if h.strip())
    else:
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
    if not hosts:
        raise ConfigError("PANTRY_ALLOWED_HOSTS has no usable entries. Use a comma-separated host list.")
    try:
        db_path = db.default_path()
    except RuntimeError as exc:
        raise ConfigError(str(exc)) from exc
    return Config(port=port, db_path=db_path, secret=secret, threshold=threshold, allowed_hosts=hosts)


def _norm_names(names: list[str] | None) -> list[str] | None:
    if names is None:
        return None
    return sorted({n.strip().lower() for n in names if n.strip()})


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()


def make_token(scope: str, names: list[str] | None, count: int, secret: str, now: float) -> str:
    claims = {"s": scope, "n": _norm_names(names), "c": count, "e": int(now) + TOKEN_TTL_S}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_sign(body, secret)}"


def verify_token(
    token: str, scope: str, names: list[str] | None, count: int, secret: str, now: float
) -> bool:
    if not isinstance(token, str) or token.count(".") != 1:
        return False
    body, signature = token.split(".")
    if not body.isascii():
        return False
    if not hmac.compare_digest(signature.encode("utf-8"), _sign(body, secret).encode("ascii")):
        return False
    try:
        claims = json.loads(_unb64(body))
    except (binascii.Error, ValueError):
        return False
    if not isinstance(claims, dict):
        return False
    return (
        claims.get("s") == scope
        and claims.get("n") == _norm_names(names)
        and claims.get("c") == count
        and isinstance(claims.get("e"), int)
        and now <= claims["e"]
    )


def _result(speech: str, structured: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=speech)],
        structuredContent=structured,
    )


def _error(speech: str, code: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=speech)],
        structuredContent={"error": code},
        isError=True,
    )


def build_server(cfg: Config, host: str = "127.0.0.1") -> FastMCP:
    origins: list[str] = []
    for allowed in cfg.allowed_hosts:
        origins.extend([f"http://{allowed}", f"https://{allowed}"])
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(cfg.allowed_hosts),
        allowed_origins=origins,
    )
    mcp = FastMCP("sayable-pantry", host=host, port=cfg.port, transport_security=security)

    used_tokens: set[str] = set()
    used_lock = threading.Lock()

    @mcp.tool(
        annotations=ToolAnnotations(
            title="What's expiring",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def whats_expiring(within_days: int = 3) -> CallToolResult:
        """List pantry items expiring within a number of days, soonest first, including items already expired."""
        if not 0 <= within_days <= 365:
            return _error("Please ask about a number of days between zero and 365.", "invalid_days")
        today = date.today()
        conn = db.connect(cfg.db_path)
        try:
            items = db.expiring(conn, within_days, today)
        finally:
            conn.close()
        window = f"{say_number(within_days)} {plural(within_days, 'day')}"
        if not items:
            return _result(f"Nothing is expiring in the next {window}.", {"items": [], "count": 0})
        phrases = [
            f"{item['name']} {say_date(date.fromisoformat(item['expires_on']), today)}"
            for item in items
        ]
        n = len(items)
        speech = (
            f"{capitalize_first(say_number(n))} {plural(n, 'item')} expiring in the next {window}: "
            f"{say_list(phrases)}."
        )
        return _result(speech, {"items": items, "count": n})

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Count an item",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def count_item(name: str) -> CallToolResult:
        """Say how many of one item are in the pantry. Asks which one you mean if the name matches several items."""
        if not name.strip():
            return _error("Tell me which item to count.", "empty_name")
        conn = db.connect(cfg.db_path)
        try:
            matches = db.find_names(conn, name)
            if len(matches) == 1:
                quantity = db.count(conn, matches[0])
        finally:
            conn.close()
        if not matches:
            return _result(
                f"I don't see any {name.strip().lower()} in the pantry.",
                {"name": name.strip().lower(), "quantity": 0},
            )
        if len(matches) > 1:
            return _result(
                f"Did you mean {say_list(matches, limit=3, conj='or')}?",
                {"needs_clarification": True, "options": matches},
            )
        return _result(
            f"You have {say_number(quantity)} {matches[0]}.",
            {"name": matches[0], "quantity": quantity},
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Add an item",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        )
    )
    def add_item(name: str, quantity: int = 1, expires_on: str | None = None) -> CallToolResult:
        """Add an item to the pantry with a quantity and an optional expiry such as tomorrow or Friday."""
        if not name.strip():
            return _error("Tell me which item to add.", "empty_name")
        if quantity < 1:
            return _error("The quantity needs to be at least one.", "invalid_quantity")
        today = date.today()
        expiry: date | None = None
        if expires_on is not None and expires_on.strip():
            expiry = parse_when(expires_on, today)
            if expiry is None:
                return _error(
                    "I couldn't understand that date. Try a day like Friday, or in three days.",
                    "invalid_date",
                )
        conn = db.connect(cfg.db_path)
        try:
            row_id = db.add_item(conn, name, quantity, expiry)
        finally:
            conn.close()
        speech = f"Added {say_number(quantity)} {name.strip().lower()}"
        speech += f", expiring {say_date(expiry, today)}." if expiry is not None else "."
        return _result(
            speech,
            {
                "id": row_id,
                "name": name.strip().lower(),
                "quantity": quantity,
                "expires_on": None if expiry is None else expiry.isoformat(),
            },
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Remove items",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        )
    )
    def remove_items(
        scope: Literal["named", "expired", "all"],
        names: list[str] | None = None,
        confirm_token: str | None = None,
    ) -> CallToolResult:
        """Remove pantry items by name, all expired items, or everything. Large removals first ask for a spoken confirmation."""
        today = date.today()
        conn = db.connect(cfg.db_path)
        try:
            try:
                affected = db.preview_delete(conn, scope, names, today)
            except ValueError as exc:
                return _error(f"I can't remove that. {exc}", "invalid_request")
            if affected == 0:
                return _result("There is nothing to remove for that.", {"removed": 0})
            needs_confirmation = scope == "all" or affected >= cfg.threshold
            if needs_confirmation:
                if confirm_token is None:
                    token = make_token(scope, names, affected, cfg.secret, time.time())
                    return _result(
                        f"That removes {say_number(affected)} {plural(affected, 'item')}. "
                        "Say confirm to go ahead.",
                        {"needs_confirmation": True, "count": affected, "confirm_token": token},
                    )
                with used_lock:
                    already_used = confirm_token in used_tokens
                    if not already_used and verify_token(
                        confirm_token, scope, names, affected, cfg.secret, time.time()
                    ):
                        used_tokens.add(confirm_token)
                        valid = True
                    else:
                        valid = False
                if already_used:
                    return _error(
                        "That confirmation was already used. Ask me again to start over.",
                        "token_used",
                    )
                if not valid:
                    return _error(
                        "That confirmation is not valid or has expired. Ask me again to start over.",
                        "token_invalid",
                    )
            removed = db.delete(conn, scope, names, today)
        finally:
            conn.close()
        return _result(
            f"Done. Removed {say_number(removed)} {plural(removed, 'item')}.",
            {"removed": removed},
        )

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pantry.server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (use 0.0.0.0 inside Docker)")
    ns = parser.parse_args(argv)
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"pantry.server: configuration error: {exc}", file=sys.stderr)
        return 2
    print(
        f"sayable-pantry serving http://{ns.host}:{cfg.port}/mcp (db={cfg.db_path}, "
        f"allowed hosts={','.join(cfg.allowed_hosts)})",
        file=sys.stderr,
    )
    build_server(cfg, ns.host).run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    sys.exit(main())
