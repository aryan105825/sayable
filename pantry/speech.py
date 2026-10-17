# @exports: parse_when(text: str, today: date) -> date | None  # ISO, today, tomorrow, weekday names (next occurrence after today), "in N days/weeks" (digits or number words); None if not understood
# @exports: say_date(d: date, today: date) -> str  # "today", "tomorrow", "yesterday", "on Friday", "two days ago", "on March 5th"
# @exports: say_number(n: int) -> str  # words for 0..999, negatives prefixed "minus", larger numbers as "1,234"
# @exports: say_list(items: list[str], limit: int = 3, conj: str = "and") -> str  # "a, b, and c" / "a, b, c, and two more" / "nothing"
# @exports: plural(n: int, singular: str) -> str  # singular when n == 1 else singular + "s"
# @exports: capitalize_first(text: str) -> str
# @imports: (none)
# @env: (none)
# @schema: pure functions, no I/O; all output is plain words with no markdown
from __future__ import annotations

import re
from datetime import date, timedelta

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_NUMBER_WORDS = {word: i for i, word in enumerate(_ONES)}
_NUMBER_WORDS.update({"a": 1, "an": 1, "twenty": 20})


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def parse_when(text: str, today: date) -> date | None:
    t = text.strip().lower()
    if not t:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        try:
            return date.fromisoformat(t)
        except ValueError:
            return None
    if t == "today":
        return today
    if t == "tomorrow":
        return today + timedelta(days=1)
    relative = re.fullmatch(r"in (\w+) (day|days|week|weeks)", t)
    if relative:
        n = _to_int(relative.group(1))
        if n is None:
            return None
        unit_days = 7 if relative.group(2).startswith("week") else 1
        return today + timedelta(days=n * unit_days)
    weekday = re.sub(r"^(?:on\s+)?(?:this\s+|next\s+|coming\s+)?", "", t)
    if weekday in _WEEKDAYS:
        delta = (_WEEKDAYS[weekday] - today.weekday()) % 7
        return today + timedelta(days=delta if delta else 7)
    return None


def say_number(n: int) -> str:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"say_number expects an int, got {type(n).__name__}")
    if n < 0:
        return "minus " + say_number(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = f"{_ONES[hundreds]} hundred"
        return head if rest == 0 else f"{head} {say_number(rest)}"
    return f"{n:,}"


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def say_date(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if 2 <= delta <= 6:
        return f"on {_DAY_NAMES[d.weekday()]}"
    if -6 <= delta <= -2:
        return f"{say_number(-delta)} days ago"
    spoken = f"on {_MONTH_NAMES[d.month - 1]} {_ordinal(d.day)}"
    if d.year != today.year:
        spoken += f", {d.year}"
    return spoken


def say_list(items: list[str], limit: int = 3, conj: str = "and") -> str:
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    values = [str(i) for i in items]
    if not values:
        return "nothing"
    shown = values[:limit]
    extra = len(values) - len(shown)
    parts = shown + ([f"{say_number(extra)} more"] if extra > 0 else [])
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} {conj} {parts[1]}"
    return ", ".join(parts[:-1]) + f", {conj} {parts[-1]}"


def plural(n: int, singular: str) -> str:
    return singular if n == 1 else singular + "s"


def capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:]
