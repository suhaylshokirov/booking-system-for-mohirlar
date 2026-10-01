"""A booking as an iCalendar (RFC 5545) file, so it can be added to any calendar.

`render_ics` is pure: it only formats what it is given. `booking_ics` looks up
the names a calendar entry needs and calls it. Who may see the booking is
decided by the caller (`booking.get_booking` / `get_own_booking`), not here.

Choices worth knowing:

* Times are written in UTC (`...Z`), so the file is correct in whatever zone
  the calendar app runs in; the app converts to the viewer's zone itself.
* `UID` is stable per booking and `DTSTAMP` is the booking's last change, so
  downloading the file again after a cancel updates the same calendar entry
  instead of adding a second one.
* Status maps pending -> TENTATIVE, confirmed/completed -> CONFIRMED,
  cancelled -> CANCELLED.
* Lines end in CRLF, text is escaped, and long lines are folded at 75 octets
  without splitting a multi-byte character (names and notes may be Uzbek or
  Russian).
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.services.booking import BookingLine, describe_bookings
from app.services.business_settings import get_business_settings

CRLF = "\r\n"
_MAX_LINE_OCTETS = 75

_STATUS = {
    BookingStatus.PENDING: "TENTATIVE",
    BookingStatus.CONFIRMED: "CONFIRMED",
    BookingStatus.COMPLETED: "CONFIRMED",
    BookingStatus.CANCELLED: "CANCELLED",
}


def escape_text(value: str) -> str:
    """Escape a TEXT value (RFC 5545 3.3.11).

    Backslash first, or the backslashes added for the other characters would be
    doubled. A bare carriage return is dropped; a line break becomes `\\n`.
    """
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line: str) -> str:
    """Wrap a content line at 75 octets: CRLF plus one space continues it (3.1).

    Counted in UTF-8 bytes, not characters, and never inside one character.
    """
    parts: list[str] = []
    current = ""
    limit = _MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            parts.append(current)
            current = char
            limit = _MAX_LINE_OCTETS - 1  # the leading space of a continuation
        else:
            current += char
    parts.append(current)
    return (CRLF + " ").join(parts)


def _utc(moment: datetime) -> str:
    # The driver may hand back another offset; a "Z" time must really be UTC.
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_ics(line: BookingLine, business_name: str) -> str:
    """The booking as a one-event `VCALENDAR`, CRLF-terminated.

    `line.booking` times must be timezone-aware UTC (the database column is).
    """
    booking = line.booking
    description = [f"{line.service_name} with {line.provider_name}"]
    if booking.notes:
        description.append(f"Note: {booking.notes}")
    if booking.status == BookingStatus.CANCELLED:
        description.append("This booking was cancelled.")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Navbat//Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:booking-{booking.id}@navbat",
        f"DTSTAMP:{_utc(booking.updated_at)}",
        f"DTSTART:{_utc(booking.start_at)}",
        f"DTEND:{_utc(booking.end_at)}",
        f"SUMMARY:{escape_text(f'{line.service_name} with {line.provider_name}')}",
        f"LOCATION:{escape_text(business_name)}",
        f"DESCRIPTION:{escape_text(chr(10).join(description))}",
        f"STATUS:{_STATUS[booking.status]}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "".join(fold_line(text) + CRLF for text in lines)


def booking_ics(db: Session, booking: Booking) -> str:
    """The calendar file for `booking`, which the caller has already authorised."""
    (line,) = describe_bookings(db, [booking])
    return render_ics(line, get_business_settings(db).name)
