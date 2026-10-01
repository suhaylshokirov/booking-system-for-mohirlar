# ADR 0008 — Guarded (optimistic) status updates instead of row locks

**Status:** accepted (P7.2; race test in P7.6)

## Context

A barber confirms a booking at the same moment the customer cancels it. Both
requests read `pending`, both pass the state machine, both write. Without
protection the last write wins silently, and the history claims two changes
that contradict each other.

## Decision

Every status change is one statement:

    UPDATE bookings SET status = :to, ... WHERE id = :id AND status = :expected

`:expected` is the status the state machine just validated against. If the
row count is 0, the status moved under us: raise 409 `BOOKING_STATE_CHANGED`
and write no event. On success, insert the `booking_events` row in the same
transaction, so the status and its history commit or roll back together.

## Alternatives considered

- **`SELECT ... FOR UPDATE`.** Also correct, but holds a lock across the rules
  check, and a second request waits, then re-validates. More moving parts for
  a case that is rare here.
- **A version column.** Same effect as checking the status, plus a column to
  maintain. The status is already the state we care about.
- **Python-side check only.** Two requests both pass it. Not a guarantee.

## Consequences

- The loser gets a clear, retryable 409 instead of a silent overwrite.
- Exactly one event exists per real change.
- Rules are evaluated on the row as read; a race is caught by the guard, not
  by re-running the rules. The row count is the single source of truth.
- Cancelling frees the slot at once, because the exclusion constraints only
  cover `pending`/`confirmed` (ADR 0001).
