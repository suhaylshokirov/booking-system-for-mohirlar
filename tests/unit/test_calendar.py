"""The .ics builder: escaping, folding, field mapping (P10.1). No database."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.models import Booking, BookingStatus
from app.services.booking import BookingLine
from app.services.calendar import CRLF, escape_text, fold_line, render_ics

START = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)


def make_line(status=BookingStatus.PENDING, notes=None, **overrides) -> BookingLine:
    booking = Booking(
        id=7,
        customer_id=1,
        provider_id=1,
        service_id=1,
        start_at=START,
        end_at=START + timedelta(minutes=30),
        status=status,
        price_amount=60_000,
        duration_minutes=30,
        notes=notes,
        updated_at=datetime(2026, 10, 1, 7, 0, 5, tzinfo=UTC),
    )
    return BookingLine(booking, overrides.get("service", "Haircut"), "Jasur")


def unfold(text: str) -> list[str]:
    """Undo folding, as a calendar app would, and split into content lines."""
    return text.replace(CRLF + " ", "").split(CRLF)[:-1]


def test_escape_text_handles_backslash_semicolon_comma_and_newline():
    assert escape_text("a,b;c\\d\ne") == r"a\,b\;c\\d\ne"
    assert escape_text("one\r\ntwo") == "one\\ntwo"


def test_fold_line_leaves_short_lines_alone():
    assert fold_line("SUMMARY:Haircut") == "SUMMARY:Haircut"


def test_fold_line_never_exceeds_75_octets_and_round_trips():
    line = "DESCRIPTION:" + "x" * 200
    folded = fold_line(line)

    assert all(len(part.encode()) <= 75 for part in folded.split(CRLF))
    assert folded.replace(CRLF + " ", "") == line


def test_fold_line_does_not_split_a_multibyte_character():
    line = "SUMMARY:" + "Сочный стрижка ўзбек " * 10
    folded = fold_line(line)

    assert all(len(part.encode()) <= 75 for part in folded.split(CRLF))
    assert folded.replace(CRLF + " ", "") == line


def test_the_file_is_one_event_with_crlf_endings():
    ics = render_ics(make_line(), "Navbat Barbers")

    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    lines = unfold(ics)
    assert lines.count("BEGIN:VEVENT") == 1
    assert "VERSION:2.0" in lines
    assert "UID:booking-7@navbat" in lines
    assert "DTSTAMP:20261001T070005Z" in lines
    assert "DTSTART:20261005T050000Z" in lines
    assert "DTEND:20261005T053000Z" in lines
    assert "SUMMARY:Haircut with Jasur" in lines
    assert "LOCATION:Navbat Barbers" in lines


def test_times_in_another_offset_are_written_as_real_utc():
    line = make_line()
    line.booking.start_at = START.astimezone(timezone(timedelta(hours=5)))

    assert "DTSTART:20261005T050000Z" in unfold(render_ics(line, "B"))


@pytest.mark.parametrize(
    ("status", "ics_status"),
    [
        (BookingStatus.PENDING, "TENTATIVE"),
        (BookingStatus.CONFIRMED, "CONFIRMED"),
        (BookingStatus.COMPLETED, "CONFIRMED"),
        (BookingStatus.CANCELLED, "CANCELLED"),
    ],
)
def test_status_is_mapped(status, ics_status):
    assert f"STATUS:{ics_status}" in unfold(render_ics(make_line(status), "B"))


def test_notes_and_names_are_escaped():
    ics = render_ics(make_line(notes="Short, on the sides; ask Ali\nthanks", service="A,B"), "X; Y")
    lines = unfold(ics)

    assert "SUMMARY:A\\,B with Jasur" in lines
    assert r"LOCATION:X\; Y" in lines
    assert r"DESCRIPTION:A\,B with Jasur\nNote: Short\, on the sides\; ask Ali\nthanks" in lines
