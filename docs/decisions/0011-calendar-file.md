# ADR 0011 — The calendar file (.ics) is built by hand, in UTC, with a stable UID

**Status:** accepted (P10.1, 2026-10-01)

## Context

Bonus 7: let a customer add a booking to any calendar app. The format is RFC 5545
(iCalendar). The question is how to produce it and how a re-download should behave
once the booking has changed.

## Decision

- **No library.** One `VEVENT` is a dozen lines; the tricky parts (text escaping,
  folding lines at 75 bytes without splitting a UTF-8 character, CRLF endings) are
  small, pure functions with unit tests (`services/calendar.py`). CLAUDE.md §7 asks for
  a reason to add a dependency, and there is none.
- **Times in UTC (`...Z`).** Correct in whatever zone the calendar app runs in; the
  app does the local conversion. `LOCATION` is the business name.
- **Stable identity.** `UID` is `booking-{id}@navbat` and never changes. `DTSTAMP` is
  the booking's `updated_at`, so the file is the same on every download and changes
  exactly when the booking does. Downloading again after a confirm or cancel
  therefore **updates** the existing calendar entry instead of adding a second one.
- **Status mapping:** pending is `TENTATIVE`; confirmed and completed are
  `CONFIRMED`; cancelled is `CANCELLED`. A cancelled booking still downloads from the
  API (so a calendar that has it can update); the booking page hides the link.
- **Visibility is the booking's:** the same `get_booking` / `get_own_booking` rules,
  so someone else's booking is a 404, not a 403. The web link uses its own route
  (`/me/bookings/{id}/ics`) because it must work with the cookie login and the
  customer-only page rules.

## Alternatives considered

- **The `icalendar` package.** Handles more of the spec than we use; one more
  dependency to pin and explain.
- **`webcal://` subscription feed.** Needs a per-user secret URL and caching rules;
  far more than "add this one booking".
- **A random UID or the current time as `DTSTAMP` each download.** Simpler, but a
  re-download would create duplicates in the customer's calendar.

## Consequences

- We write only what we emit: no `VTIMEZONE`, no recurrence, no alarms, no
  `SEQUENCE`. Some clients may not reschedule an existing entry without a rising
  `SEQUENCE`; `DTSTAMP` is our only ordering signal. Acceptable for a bonus feature.
- Multi-byte text (Uzbek, Russian notes) is safe because folding is by bytes.
