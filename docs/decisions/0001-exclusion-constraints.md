# ADR 0001 — PostgreSQL exclusion constraints prevent double booking

**Status:** accepted (P1.7); implemented in `services/booking.py` (P6.2) and
proven under real concurrency (P6.4). The race timeline is in
[`docs/edge-cases.md`](../edge-cases.md#the-headline-race-two-users-book-the-same-slot-at-the-same-moment).

## Context

Two customers can press "Book" for the same slot at the same moment. Any
design that first *checks* whether the slot is free and then *inserts* has a
gap between the two steps, and both requests can pass the check before either
inserts. The result is two bookings for one provider at one time. Double
booking is the one failure this system must never allow.

## Decision

Let the database enforce it. `bookings` has two exclusion constraints:

```sql
no_provider_overlap  EXCLUDE USING gist (provider_id WITH =,
                       tstzrange(start_at, end_at, '[)') WITH &&)
                     WHERE (status IN ('pending', 'confirmed'))
no_customer_overlap  EXCLUDE USING gist (customer_id WITH =,
                       tstzrange(start_at, end_at, '[)') WITH &&)
                     WHERE (status IN ('pending', 'confirmed'))
```

The service layer may pre-check to give a friendly message, but the constraint
is the guarantee. A violation raises SQLSTATE `23P01`, and the service maps the
violated constraint *name* to `409 SLOT_TAKEN` or `409 CUSTOMER_OVERLAP`.

## How the service uses it

`services/booking.create_booking` does three things in order:

1. Validates the request (`booking_rules`); every failure is a 422 with its own code.
2. Pre-checks for an overlapping pending or confirmed booking, provider first
   and then customer, and answers 409 if it finds one. This only makes the
   common, non-racing case friendly.
3. Inserts the booking and its `booking_events` row inside a **savepoint**. If
   Postgres rejects the insert with `23P01`, only the savepoint is rolled
   back, so the request's transaction stays usable, and the constraint name
   (`no_provider_overlap` or `no_customer_overlap`) picks the 409 code. Any
   other integrity error is not ours to translate and is re-raised.

## Alternatives considered

- **Check in Python, then insert.** The gap between the check and the insert is
  the bug. Kept only as a *pre-check* to produce a friendly message.
- **Application-level lock** (a mutex, or a Postgres advisory lock taken by the
  service). A Python mutex protects one process only; the app may run several.
  An advisory lock works across processes but is a convention: every code path
  that writes a booking must remember to take it, and nothing stops one that
  forgets. The constraint protects every writer, including a future script or a
  hand-typed SQL fix.
- **`SELECT … FOR UPDATE`.** Locks rows that exist. The conflicting booking
  does not exist yet when two requests race, so there is nothing to lock. It
  can be made to work by locking the provider's row as a mutex, but that
  serialises every booking for that provider, and again relies on every path
  doing it.
- **Serializable isolation.** Correct, and Postgres detects the conflict, but
  it can also abort unrelated transactions, needs a retry loop around every
  booking (`40001`), and reports the clash as a generic serialization failure,
  not "this slot is taken". Also depends on every writer using that isolation
  level.
- **Stored slot rows with `UNIQUE (provider_id, slot_start)`.** Simple and
  safe for fixed-length slots, but a 45-minute service must claim three
  15-minute rows atomically, changing granularity or hours means regenerating
  rows, and the table must be kept in sync with availability. Slots are
  computed instead (planned ADR 0002), so there is nothing to lock.

## Consequences

- Correct under any concurrency, with any number of app instances, and even for
  code paths that forget to check.
- Needs the `btree_gist` extension and a hand-written migration (autogenerate
  does not see exclusion constraints).
- Only pending and confirmed bookings block time; cancelling or completing a
  booking frees the slot automatically.
- The friendly error depends on constraint *names*. Renaming a constraint is a
  breaking change to the API's error mapping; the constraint tests
  (`tests/integration/test_db_constraints.py`) assert the names.
- The constraint applies to updates too, so a status change that would
  re-activate a booking on a taken slot is rejected the same way.
- Two bookings racing for one slot both start; Postgres makes the second wait
  for the first to commit or roll back, then re-checks. So the loser can wait
  briefly, and if the first rolls back, the second succeeds.

## Evidence

- **Two transactions, step by step:** `docs/edge-cases.md`, "The headline race".
  Both pre-checks pass, the second insert waits on the first, the first
  commits, the second fails with `23P01`.
- **Ten threads, one slot** (`tests/concurrency/test_booking_races.py`,
  `test_n_customers_same_slot_exactly_one_wins`): one 201, nine 409
  `SLOT_TAKEN`, one row.
- **Forced worst case** (`test_all_pass_the_precheck_and_the_constraint_still_stops_them`):
  a barrier holds every thread between the pre-check and the insert, so all
  ten pass the pre-check by construction. Nine are still rejected, and the
  answer is still `SLOT_TAKEN`. This is the test that shows the pre-check
  alone would have failed.
- **Customer side:** `test_same_customer_two_providers_overlapping_one_rejected`
  and `test_double_submit_same_request_creates_one_booking`.
- **Mapping without the pre-check:**
  `tests/integration/test_create_booking.py::test_database_constraint_maps_to_409_when_the_precheck_is_skipped`.
- **The constraints themselves:** `tests/integration/test_db_constraints.py`.

## Known limits

- A request that loses a race can wait for the winner's transaction to
  finish before it is rejected. Transactions here are short (a few statements),
  so the wait is brief.
- A double submit by one customer breaks both constraints at once; which name
  Postgres reports is not something we rely on, so the client should treat
  either 409 as "already booked".
