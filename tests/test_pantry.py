# @exports: (pytest module, no symbols)
# @imports: pantry/db.py, pantry/speech.py, pantry/server.py:make_token, verify_token
# @schema: Pantry reference-server tests. Fixed "today" is Tuesday 2026-10-06; no network, no running servers.
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from pantry import db  # noqa: E402
from pantry.server import make_token, verify_token  # noqa: E402
from pantry.speech import parse_when, plural, say_date, say_list, say_number  # noqa: E402

TODAY = date(2026, 10, 6)  # a Tuesday
SECRET = "s" * 32


# ---------- pantry.speech ----------


def test_parse_when_forms():
    assert parse_when("2026-12-25", TODAY) == date(2026, 12, 25)
    assert parse_when("today", TODAY) == TODAY
    assert parse_when("Tomorrow", TODAY) == date(2026, 10, 7)
    assert parse_when("friday", TODAY) == date(2026, 10, 9)
    assert parse_when("next friday", TODAY) == date(2026, 10, 9)
    assert parse_when("on Friday", TODAY) == date(2026, 10, 9)
    assert parse_when("tuesday", TODAY) == date(2026, 10, 13)
    assert parse_when("in 3 days", TODAY) == date(2026, 10, 9)
    assert parse_when("in one day", TODAY) == date(2026, 10, 7)
    assert parse_when("in two weeks", TODAY) == date(2026, 10, 20)


def test_parse_when_rejects_unknown():
    assert parse_when("", TODAY) is None
    assert parse_when("whenever", TODAY) is None
    assert parse_when("2026-13-45", TODAY) is None
    assert parse_when("in many days", TODAY) is None


def test_say_list():
    assert say_list([]) == "nothing"
    assert say_list(["a"]) == "a"
    assert say_list(["a", "b"]) == "a and b"
    assert say_list(["a", "b", "c"]) == "a, b, and c"
    assert say_list(["a", "b", "c", "d", "e"]) == "a, b, c, and two more"
    assert say_list(["a", "b"], conj="or") == "a or b"
    with pytest.raises(ValueError):
        say_list(["a"], limit=0)


def test_say_number_and_plural():
    assert say_number(0) == "zero"
    assert say_number(12) == "twelve"
    assert say_number(21) == "twenty-one"
    assert say_number(100) == "one hundred"
    assert say_number(345) == "three hundred forty-five"
    assert say_number(1234) == "1,234"
    assert say_number(-3) == "minus three"
    with pytest.raises(TypeError):
        say_number(True)
    assert plural(1, "item") == "item"
    assert plural(2, "item") == "items"


def test_say_date():
    assert say_date(TODAY, TODAY) == "today"
    assert say_date(date(2026, 10, 7), TODAY) == "tomorrow"
    assert say_date(date(2026, 10, 5), TODAY) == "yesterday"
    assert say_date(date(2026, 10, 9), TODAY) == "on Friday"
    assert say_date(date(2026, 10, 3), TODAY) == "three days ago"
    assert say_date(date(2026, 11, 1), TODAY) == "on November 1st"
    assert say_date(date(2027, 1, 12), TODAY) == "on January 12th, 2027"


# ---------- pantry.db ----------


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "pantry.db")
    assert db.reset_seed(path, TODAY) == 12
    connection = db.connect(path)
    yield connection
    connection.close()


def test_seed_and_lookups(conn):
    assert db.total(conn) == 12
    assert db.find_names(conn, "milk") == ["oat milk", "whole milk"]
    assert db.find_names(conn, "eggs") == ["eggs"]
    assert db.find_names(conn, "zzz") == []
    assert db.count(conn, "eggs") == 12
    assert db.count(conn, "zzz") == 0


def test_expiring_includes_expired_and_orders(conn):
    items = db.expiring(conn, 3, TODAY)
    assert [i["name"] for i in items] == [
        "bread", "spinach", "chicken breast", "yogurt", "whole milk", "tomatoes",
    ]
    assert items[0]["days_left"] == -2
    with pytest.raises(ValueError):
        db.expiring(conn, -1, TODAY)


def test_preview_and_delete_scopes(conn):
    assert db.preview_delete(conn, "expired", None, TODAY) == 2
    assert db.preview_delete(conn, "named", ["Eggs"], TODAY) == 1
    assert db.preview_delete(conn, "all", None, TODAY) == 12
    assert db.delete(conn, "named", ["whole milk", "oat milk"], TODAY) == 2
    assert db.total(conn) == 10
    assert db.delete(conn, "all", None, TODAY) == 10
    assert db.total(conn) == 0


def test_db_validation(conn):
    with pytest.raises(ValueError):
        db.preview_delete(conn, "bogus", None, TODAY)
    with pytest.raises(ValueError):
        db.preview_delete(conn, "named", [], TODAY)
    with pytest.raises(ValueError):
        db.add_item(conn, "eggs", 0, None)
    assert db.add_item(conn, "  Kefir ", 2, None) == 13
    assert db.find_names(conn, "kefir") == ["kefir"]


# ---------- confirmation tokens ----------


def test_token_roundtrip_and_expiry():
    token = make_token("all", None, 12, SECRET, 1000.0)
    assert verify_token(token, "all", None, 12, SECRET, 1000.0)
    assert verify_token(token, "all", None, 12, SECRET, 1060.0)
    assert not verify_token(token, "all", None, 12, SECRET, 1061.0)


def test_token_names_are_normalised():
    token = make_token("named", ["B", "a"], 2, SECRET, 1000.0)
    assert verify_token(token, "named", ["a", "b"], 2, SECRET, 1000.0)


def test_token_cannot_be_forged_or_retargeted():
    token = make_token("all", None, 12, SECRET, 1000.0)
    assert not verify_token(token, "all", None, 12, "t" * 32, 1000.0)
    assert not verify_token(token, "all", None, 11, SECRET, 1000.0)
    assert not verify_token(token, "expired", None, 12, SECRET, 1000.0)
    assert not verify_token(token, "named", ["eggs"], 12, SECRET, 1000.0)
    body, signature = token.split(".")
    flipped = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    assert not verify_token(f"{body}.{flipped}", "all", None, 12, SECRET, 1000.0)
    other_body = make_token("all", None, 1, SECRET, 1000.0).split(".")[0]
    assert not verify_token(f"{other_body}.{signature}", "all", None, 12, SECRET, 1000.0)


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c", "é.abcd", "..", "x."])
def test_token_malformed(bad):
    assert not verify_token(bad, "all", None, 12, SECRET, 1000.0)
