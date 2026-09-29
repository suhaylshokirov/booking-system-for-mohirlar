# ADR 0007 — Price and duration snapshots on bookings

**Status:** accepted (P1.3)

## Context

The admin can edit a service at any time: raise the price, shorten the
duration. A booking made yesterday for "Haircut, 30 min, 60 000 UZS" is an
agreement. If the booking only pointed at the service, editing the service
would silently rewrite the customer's price and, worse, change `end_at`
relative to the duration, breaking the no-overlap guarantee for bookings that
already exist.

## Decision

`bookings` stores `price_amount` and `duration_minutes`, copied from the
service inside the booking transaction. `start_at` and `end_at` are stored too;
`end_at` is `start_at + duration_minutes` at that moment. Nothing later
recomputes them from the service. `service_id` remains as a reference
(what was booked), not as the source of the numbers.

## Alternatives considered

- **Join to `services` for price and duration.** No duplication, but history
  changes when the catalog changes, and the exclusion constraint would depend
  on data outside the row.
- **Versioned services** (a new row per edit, bookings point at a version).
  Correct, but more tables and more admin logic than a small business needs.
- **Copy only the price.** The duration snapshot is what keeps a booking's
  time range meaningful after the service is shortened or lengthened.

## Consequences

- Editing a service affects only future bookings. Admin UI can say so.
- Two extra columns, each with a CHECK (`price_amount >= 0`,
  `duration_minutes > 0`), so a bad snapshot cannot be stored.
- The service layer must copy the values on creation (P6.2). Nothing at the
  database level forces them to equal the service's values at that moment; the
  test for it is at service level.
- Deactivated services still show correctly in history, because the booking
  carries what it needs.
