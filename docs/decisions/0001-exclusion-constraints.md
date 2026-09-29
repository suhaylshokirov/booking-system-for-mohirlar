# ADR 0001 — PostgreSQL exclusion constraints prevent double booking

**Status:** draft (P1.4). Finalised in P1.7; the race-condition write-up and
the concurrency test results are added in P6.5.

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

To be written in full in P1.7: application-level lock, `SELECT … FOR UPDATE`,
serializable isolation, stored slot rows.

## Consequences

- Correct under any concurrency, with any number of app instances, and even for
  code paths that forget to check.
- Needs the `btree_gist` extension and a hand-written migration (autogenerate
  does not see exclusion constraints).
- Only pending and confirmed bookings block time; cancelling or completing a
  booking frees the slot automatically.
