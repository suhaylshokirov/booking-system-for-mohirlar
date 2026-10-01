"""How numbers and times look on a page. Registered as Jinja filters in `templating.py`.

Formatting only: these never round or decide anything. Money is an integer
amount in the business's currency (CLAUDE.md rule 6), so printing it is just
grouping the digits. Times are stored in UTC and shown on the business's wall
clock; the conversion itself is `app/core/timezones.utc_to_local`, the one
place it happens (rule 4).
"""

from datetime import date, datetime, time

from app.core.timezones import local_to_utc, utc_to_local

# A no-break space groups thousands the way Uzbek and Russian write them
# (60 000), and keeps "60 000 UZS" from wrapping across two lines.
NBSP = " "


def local_time(instant: datetime, timezone: str) -> str:
    """A UTC instant as 24-hour wall-clock time in `timezone`: "10:15"."""
    return utc_to_local(instant, timezone).strftime("%H:%M")


def local_date(instant: datetime, timezone: str) -> str:
    """A UTC instant as its wall-clock date in `timezone`: "Mon 5 Oct 2026"."""
    return day_label(utc_to_local(instant, timezone).date())


def utc_offset(instant: datetime, timezone: str) -> str:
    """The zone's offset from UTC at `instant`: "UTC+5", "UTC+5:30", "UTC-3".

    Asked per instant, not per zone, because the offset changes with daylight
    saving: Berlin is "UTC+2" in October and "UTC+1" in November. A zone name
    alone ("Europe/Berlin") does not tell a reader which one they are looking at.
    """
    offset = utc_to_local(instant, timezone).utcoffset()
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def day_offset(day: date, timezone: str) -> str:
    """`utc_offset` for a calendar date, taken at local noon (the day's offset
    can change at night on a daylight-saving date, but noon is unambiguous)."""
    return utc_offset(local_to_utc(day, time(12, 0), timezone), timezone)


def day_label(day: date) -> str:
    """A calendar date: "Mon 5 Oct 2026". The day number is added by hand:
    strftime has no portable way to drop the leading zero ("05")."""
    return f"{day:%a} {day.day} {day:%b %Y}"


def money(amount: int, currency: str) -> str:
    """60000, "UZS" -> "60 000 UZS" (no-break spaces)."""
    return f"{amount:,}".replace(",", NBSP) + NBSP + currency


def phone(number: str) -> str:
    """How a stored E.164 number is read aloud and written in Uzbekistan:
    "+998901234567" -> "+998 90 123 45 67" (no-break spaces, so it never wraps).

    Only Uzbek numbers are grouped: other countries group differently, and a
    wrong grouping is worse than none, so they are shown as stored.
    """
    if number.startswith("+998") and len(number) == 13:
        groups = (number[:4], number[4:6], number[6:9], number[9:11], number[11:])
        return NBSP.join(groups)
    return number


def duration(minutes: int) -> str:
    """30 -> "30 min", 60 -> "1 h", 75 -> "1 h 15 min" (no-break spaces)."""
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}{NBSP}h")
    if rest or not hours:
        parts.append(f"{rest}{NBSP}min")
    return NBSP.join(parts)
