# ADR 0006 — Half-open ranges and UTC storage

**Status:** accepted (P1.4; timezone module and DST policy P4.1)

## Context

Two rules about time decide whether bookings behave correctly:

1. Is a booking 10:00–10:30 "in conflict" with one at 10:30–11:00? Real
   appointments are back-to-back all day; treating that as a clash would make
   every second slot unbookable.
2. Which clock is the truth? The business thinks in local wall-clock time
   ("open 09:00–18:00"), servers and databases run in whatever zone they were
   set to, and daylight saving time can make a local time not exist or exist
   twice.

## Decision

- **Ranges are half-open, `[start, end)`.** The start instant belongs to the
  booking, the end instant does not. The exclusion constraints use
  `tstzrange(start_at, end_at, '[)')`, and the slot algorithm uses the same
  rule, so the database and the application can never disagree about an
  overlap.
- **Every instant is stored as `timestamptz` and compared in UTC.** The
  database converts on input and output; nothing stores a naive datetime.
  `Base.type_annotation_map` makes a naive `datetime` column impossible to
  declare by accident, and the API rejects naive datetimes.
- **Availability is local wall-clock time**, stored as `time` / `date` in the
  business's IANA timezone (`business_settings.timezone`). Converting local
  time to UTC instants happens in exactly one module, `app/core/timezones.py`,
  using `zoneinfo`.
- **DST policy (P4.1).** A wall-clock time in a spring-forward gap moves
  *forward to the first instant that exists* (02:30 -> 03:00 when the clocks
  jump 02:00 -> 03:00). An ambiguous fall-back time takes its *first*
  occurrence (`fold=0`).

## Alternatives considered

- **Closed ranges `[start, end]`.** Back-to-back bookings would overlap by one
  instant and the constraint would reject them.
- **Store local time with a zone name.** Ambiguous during the DST fall-back
  hour, and comparing across zones needs conversion in every query.
- **Shift a gap time by the gap length (02:30 -> 03:30), which is what
  `zoneinfo` does by default.** A window ending at 02:30 would then run half an
  hour past the time the barber wrote. Snapping to the jump never extends a
  window.
- **Store availability as UTC.** "Open 09:00" would drift by an hour twice a
  year in any zone that observes DST.

## Consequences

- Back-to-back bookings work, and an appointment that ends exactly when the
  next begins is not a conflict.
- Nothing in the codebase may call `datetime.now()`; time comes from the
  injected clock (see CLAUDE.md rule 5).
- Availability windows are per day and cannot cross midnight.
- Uzbekistan has not observed DST since 2005, but the design does not depend on
  that: other zones are handled by the single conversion module, with a
  documented policy for DST gaps and overlaps, proven day by day for
  `Europe/Berlin` in `tests/unit/test_timezones.py`.
- Around a DST change a window is an hour shorter (gap) or longer (overlap)
  than its wall-clock length, and a window wholly inside a gap is empty.

## Addendum (P10.3, 2026-10-01): showing times

Storing UTC and reading business-local hours leaves one more question: what does a
reader or a client see? Decisions:

- **API:** booking and slot responses carry the UTC instant (the source of truth),
  the same instant on the business's clock *with its offset* (`local_start`), and the
  `timezone` name. A client never does timezone arithmetic. The offset is the one in
  force on that date, so a Berlin booking reads `+02:00` in October and `+01:00` in
  November.
- **Pages:** every time is printed on the business's clock with the zone named, and
  the UTC offset is computed **per instant** (`utc_offset`), or per day at local noon
  for a date (`day_offset`), never per zone. A zone name alone ("Europe/Berlin") does
  not say which side of a clock change a time is on.
- **A device on another clock:** a small script compares the browser's UTC offset with
  the business's and, when they differ, shows a note. It compares offsets, not names,
  so neighbouring zones with the same offset stay quiet. It never decides anything and
  is hidden without JavaScript.
- **Not done:** the availability-conflicts response is UTC-only (a barber's
  warning list), and the note script is checked against `Intl` in Node, not in a browser.
