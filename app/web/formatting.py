"""How numbers and times look on a page. Registered as Jinja filters in `templating.py`.

Formatting only: these never round or decide anything. Money is an integer
amount in the business's currency (CLAUDE.md rule 6), so printing it is just
grouping the digits. Times are stored in UTC and shown on the business's wall
clock; the conversion itself is `app/core/timezones.utc_to_local`, the one
place it happens (rule 4).
"""

from datetime import date, datetime

from app.core.timezones import utc_to_local

# A no-break space groups thousands the way Uzbek and Russian write them
# (60 000), and keeps "60 000 UZS" from wrapping across two lines.
NBSP = " "


def local_time(instant: datetime, timezone: str) -> str:
    """A UTC instant as 24-hour wall-clock time in `timezone`: "10:15"."""
    return utc_to_local(instant, timezone).strftime("%H:%M")


def local_date(instant: datetime, timezone: str) -> str:
    """A UTC instant as its wall-clock date in `timezone`: "Mon 5 Oct 2026"."""
    return day_label(utc_to_local(instant, timezone).date())


def day_label(day: date) -> str:
    """A calendar date: "Mon 5 Oct 2026". The day number is added by hand:
    strftime has no portable way to drop the leading zero ("05")."""
    return f"{day:%a} {day.day} {day:%b %Y}"


def money(amount: int, currency: str) -> str:
    """60000, "UZS" -> "60 000 UZS" (no-break spaces)."""
    return f"{amount:,}".replace(",", NBSP) + NBSP + currency


def duration(minutes: int) -> str:
    """30 -> "30 min", 60 -> "1 h", 75 -> "1 h 15 min" (no-break spaces)."""
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}{NBSP}h")
    if rest or not hours:
        parts.append(f"{rest}{NBSP}min")
    return NBSP.join(parts)
