# ADR 0001 — PostgreSQL exclusion constraints prevent double booking

**Status:** accepted (P1.7). The two-transaction race timeline and the
concurrency test results are added in P6.5.

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
