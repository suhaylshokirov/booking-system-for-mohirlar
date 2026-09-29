# Edge cases

Every edge case we know about, how it is handled, where it is enforced, and
the test that proves it. **Where:** DB = PostgreSQL constraint · Service =
`app/services` · API = schema/router · UI = templates/JS.

_Rows marked "planned" are filled in by the task in brackets; the Test column
names a real test once it exists._

## The headline race: two users book the same slot at the same moment

_P6.5: two-transaction timeline showing why check-then-insert fails and how
the exclusion constraint closes it._

## Table

| # | Edge case | Why it's a risk | How it's handled | Where | Test |
|---|---|---|---|---|---|
| 1 | Two users book the same slot simultaneously | Both pass a "is it free?" check before either inserts | Exclusion constraint `no_provider_overlap`; 23P01 → 409 `SLOT_TAKEN` | DB, Service | planned [P6.4] |
| 2 | Double-click / double submit | Same request sent twice | Constraint rejects the 2nd; UI disables the submit button | DB, UI | planned [P6.4, P8.2] |
| 3 | Same customer, overlapping bookings with different providers | Customer can't be in two places | Exclusion constraint `no_customer_overlap` → 409 `CUSTOMER_OVERLAP` | DB, Service | planned [P6.4] |
| 4 | Back-to-back bookings | Must be allowed; closed ranges would wrongly conflict | Half-open `[start, end)` ranges | DB, Service | planned [P1.5, P5.1] |
| 5 | Booking in the past / inside lead time / beyond horizon / misaligned | Invalid appointments | Booking rules with distinct error codes | Service | planned [P6.1] |
| 6 | Service duration doesn't fit before the window ends | Appointment would run past closing | Slot must fit entirely inside a window | Service | planned [P5.1] |
| 7 | Provider doesn't offer the service; inactive service/provider | Booking something that can't happen | Validation → 422 codes | Service | planned [P6.1] |
| 8 | Price or duration changes after booking | Customer's agreed price would change | Snapshot fields on `bookings` | DB, Service | planned [P6.2] |
| 9 | Availability edited/removed while future bookings exist | Silent loss of bookings | Bookings kept; admin sees conflicts | Service, UI | planned [P4.4] |
| 10 | Provider/service deactivated with future bookings | Broken references, lost history | Soft deactivation, never hard delete | DB, Service | planned [P3.2, P3.3] |
| 11 | Overlapping availability rules for the same provider | Ambiguous hours, duplicate slots | Exclusion constraint + service pre-check → 409 | DB, Service | planned [P1.5, P4.2] |
| 12 | Naive datetimes | Ambiguous instant | Rejected by schema (422) | API | planned [P4.1, P6.3] |
| 13 | DST gaps/overlaps in non-Tashkent zones | Nonexistent or repeated local times | Documented policy in the timezone module | Service | planned [P4.1] |
| 14 | Local date boundary vs UTC date | Slots attributed to the wrong day | Day bounds computed in business tz | Service | planned [P4.1] |
| 15 | Invalid status transitions | Corrupt lifecycle | Single state machine | Service | planned [P7.1] |
| 16 | Concurrent confirm + cancel | Both could "win" | Guarded `UPDATE … WHERE status = :expected` | DB, Service | planned [P7.6] |
| 17 | Completing before end time | Premature completion | State machine condition | Service | planned [P7.1] |
| 18 | Cancelling after the cutoff | Last-minute no-shows | Cancellation policy | Service | planned [P7.4] |
| 19 | Customer accessing another's booking (IDOR) | Data leak | 404, not 403 | Service, API | planned [P6.3] |
| 20 | Expired or tampered JWT | Forged identity | Signature + expiry verified | Service | planned [P2.1] |
| 21 | Deactivated user with a valid token | Access after deactivation | User reloaded every request | Service | planned [P2.3] |
| 22 | Email case sensitivity on registration | Duplicate accounts | Normalised + unique index on `lower(email)` | DB, Service | planned [P1.5, P2.2] |
| 23 | Login brute force | Password guessing | Rate limit → 429 | Service | planned [P2.5] |
| 24 | Oversized inputs, negative price, zero duration | Garbage data | Schema limits + CHECK constraints | API, DB | planned [P1.5, P3.2] |
