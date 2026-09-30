# ADR 0002 — Slots are computed, not stored

**Status:** accepted (P5.1)

## Context

Customers pick from free start times. Those times depend on the provider's
weekly hours, date exceptions, the service duration, the lead time and horizon
in business settings, and the bookings that already exist. We could either
materialise a row per slot or derive the list when someone asks.

## Decision

Slots are **computed on request** by a pure function
(`compute_slots` in `app/services/slots.py`) from windows and busy intervals.
No slot table exists. The only stored fact is the booking itself, and the
database constraint on bookings is what guarantees no double booking.

## Alternatives considered

- **A `slots` table generated ahead of time.** Every change to hours, an
  exception, a service duration, granularity or lead time would have to
  regenerate or patch rows, and stale rows would offer times that are no longer
  valid. Different services need different durations on the same grid, so one
  row per slot does not even fit. A "booked" flag on a slot row would also be a
  second source of truth beside the booking.
- **Caching computed slots.** Adds invalidation for little gain: one provider-day
  is a handful of rows and a few dozen loop iterations.

## Consequences

- Editing availability or settings takes effect immediately, with nothing to
  migrate or regenerate.
- The function is pure, so it is tested exhaustively without a database
  (`tests/unit/test_slots.py`).
- A displayed slot can be taken a moment later. That is expected: the exclusion
  constraint rejects the loser with 409 `SLOT_TAKEN` (ADR 0001).
- Each request costs a few small queries; fine at this scale.
