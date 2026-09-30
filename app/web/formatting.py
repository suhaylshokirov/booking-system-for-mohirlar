"""How numbers look on a page. Registered as Jinja filters in `templating.py`.

Formatting only: these never round, convert or decide anything. Money is an
integer amount in the business's currency (CLAUDE.md rule 6), so printing it
is just grouping the digits.
"""

# A no-break space groups thousands the way Uzbek and Russian write them
# (60 000), and keeps "60 000 UZS" from wrapping across two lines.
NBSP = " "


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
