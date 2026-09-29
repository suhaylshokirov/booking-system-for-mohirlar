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
| 1 | Two users book the same slot simultaneously | Both pass a "is it free?" check before either inserts | Exclusion constraint `no_provider_overlap`; 23P01 → 409 `SLOT_TAKEN` | DB, Service | DB half proven in `tests/integration/test_db_constraints.py` (`test_overlapping_booking_for_same_provider_is_rejected`); concurrent test planned [P6.4] |
| 2 | Double-click / double submit | Same request sent twice | Constraint rejects the 2nd; UI disables the submit button | DB, UI | planned [P6.4, P8.2] |
| 3 | Same customer, overlapping bookings with different providers | Customer can't be in two places | Exclusion constraint `no_customer_overlap` → 409 `CUSTOMER_OVERLAP` | DB, Service | DB half proven in `tests/integration/test_db_constraints.py` (`test_overlapping_booking_for_same_customer_with_other_provider_is_rejected`); concurrent test planned [P6.4] |
| 4 | Back-to-back bookings | Must be allowed; closed ranges would wrongly conflict | Half-open `[start, end)` ranges | DB, Service | `tests/integration/test_db_constraints.py` (`test_back_to_back_bookings_are_allowed`); slot algorithm still planned [P5.1] |
| 5 | Booking in the past / inside lead time / beyond horizon / misaligned | Invalid appointments | Booking rules with distinct error codes | Service | planned [P6.1] |
| 6 | Service duration doesn't fit before the window ends | Appointment would run past closing | Slot must fit entirely inside a window | Service | planned [P5.1] |
| 7 | Provider doesn't offer the service; inactive service/provider | Booking something that can't happen | Validation → 422 codes | Service | planned [P6.1] |
| 8 | Price or duration changes after booking | Customer's agreed price would change | Snapshot fields on `bookings` | DB, Service | DB half proven in `tests/integration/test_db_constraints.py` (`test_booking_keeps_its_snapshot_when_the_service_changes`); copy on create planned [P6.2] |
| 9 | Availability edited/removed while future bookings exist | Silent loss of bookings | Bookings kept; admin sees conflicts | Service, UI | planned [P4.4] |
| 10 | Provider/service deactivated with future bookings | Broken references, lost history | Soft deactivation, never hard delete | DB, Service | DB half proven in `tests/integration/test_db_constraints.py` (`test_referenced_service_cannot_be_hard_deleted`); service logic planned [P3.2, P3.3] |
| 11 | Overlapping availability rules for the same provider | Ambiguous hours, duplicate slots | Exclusion constraint + service pre-check → 409 | DB, Service | `tests/integration/test_db_constraints.py` (`test_overlapping_availability_rules_are_rejected`, `test_adjacent_availability_rules_are_allowed`); service pre-check planned [P4.2] |
| 12 | Naive datetimes | Ambiguous instant | Rejected by schema (422) | API | planned [P4.1, P6.3] |
| 13 | DST gaps/overlaps in non-Tashkent zones | Nonexistent or repeated local times | Documented policy in the timezone module | Service | planned [P4.1] |
| 14 | Local date boundary vs UTC date | Slots attributed to the wrong day | Day bounds computed in business tz | Service | planned [P4.1] |
| 15 | Invalid status transitions | Corrupt lifecycle | Single state machine | Service | planned [P7.1] |
| 16 | Concurrent confirm + cancel | Both could "win" | Guarded `UPDATE … WHERE status = :expected` | DB, Service | planned [P7.6] |
| 17 | Completing before end time | Premature completion | State machine condition | Service | planned [P7.1] |
| 18 | Cancelling after the cutoff | Last-minute no-shows | Cancellation policy | Service | planned [P7.4] |
| 19 | Customer accessing another's booking (IDOR) | Data leak | 404, not 403 | Service, API | planned [P6.3] |
| 20 | Expired or tampered JWT | Forged identity | Signature + expiry verified; only HS256 accepted, so `alg=none` and algorithm switching fail | Service | `tests/unit/test_security.py` (`test_token_is_valid_until_the_instant_it_expires`, `test_tampered_payload_is_rejected`, `test_alg_none_token_is_rejected`) |
| 21 | Deactivated user with a valid token | Access after deactivation | User reloaded every request | Service | `tests/integration/test_auth.py` (`test_a_valid_token_stops_working_once_the_user_is_deactivated`); `tests/integration/test_current_user.py` (`test_deactivated_user_with_a_valid_token_is_401`, `test_deactivated_admin_is_locked_out`, `test_role_changes_apply_to_tokens_already_issued`) |
| 22 | Email case sensitivity on registration | Duplicate accounts | Normalised (trim + lower-case) + unique index on `lower(email)`; losing a simultaneous-registration race is still a clean 409 | DB, Service | `tests/integration/test_db_constraints.py` (`test_duplicate_email_differing_only_in_case_is_rejected`); `tests/integration/test_auth.py` (`test_registering_the_same_email_in_another_case_is_a_conflict`, `test_losing_the_registration_race_is_still_a_clean_409`) |
| 23 | Login brute force | Password guessing | Rate limit → 429 | Service | planned [P2.5] |
| 24 | Oversized inputs, negative price, zero duration | Garbage data | Schema limits + CHECK constraints | API, DB | `tests/integration/test_db_constraints.py` (`test_negative_service_price_is_rejected`, `test_zero_or_negative_service_duration_is_rejected`); schema limits planned [P3.2] |
| 25 | Framework-level errors (unknown route, wrong method, malformed JSON, crash) | Clients would need a second error parser, and a crash could leak SQL or paths | One handler set renders every error as the envelope; 500s are generic | API | `tests/unit/test_errors.py` (`test_unknown_route_is_404_envelope`, `test_wrong_method_is_405_envelope_and_keeps_allow_header`, `test_malformed_json_is_422_in_the_same_envelope`, `test_unexpected_exception_is_500_and_does_not_leak_internals`) |
| 26 | Database down while the app is up | App looks healthy to the load balancer but every booking fails | `/health` runs `SELECT 1` → 503 `DATABASE_UNAVAILABLE` | Service, API | `tests/integration/test_health.py::test_health_is_503_database_unavailable_when_database_is_down` |
| 27 | A cancelled or completed booking blocks its old slot | Slot stays unbookable forever | Exclusion constraints only cover `pending`/`confirmed` | DB | `tests/integration/test_db_constraints.py` (`test_cancelled_or_completed_booking_does_not_block_the_slot`, `test_cancelling_a_booking_frees_its_slot`) |
| 28 | Booking ends before it starts / weekday 9 / availability window ends before it starts | Nonsense time ranges | CHECK constraints | DB | `tests/integration/test_db_constraints.py` (`test_booking_ending_at_or_before_its_start_is_rejected`, `test_weekday_outside_0_to_6_is_rejected`, `test_availability_rule_ending_at_or_before_its_start_is_rejected`) |
| 29 | Availability exception with only one time set, or two exceptions for one date | Ambiguous day: off or open? | CHECK + unique constraint | DB | `tests/integration/test_db_constraints.py` (`test_exception_needs_both_times_or_neither`, `test_second_exception_for_the_same_provider_and_date_is_rejected`) |
| 30 | Cancellation details on a booking that is not cancelled | Falsified history | CHECK constraint | DB | `tests/integration/test_db_constraints.py` (`test_cancellation_details_on_a_live_booking_are_rejected`) |
| 31 | A second business-settings row | Two sources of truth for booking rules | `CHECK (id = 1)` + primary key | DB | `tests/integration/test_db_constraints.py` (`test_second_business_settings_row_is_rejected`) |
| 32 | User enumeration through login | Attacker learns which emails have accounts | Same 401 `INVALID_CREDENTIALS` for unknown email and wrong password; a password hash is computed either way so timing matches | Service | `tests/integration/test_auth.py` (`test_unknown_email_and_wrong_password_give_identical_responses`, `test_unknown_email_still_pays_for_a_password_check`) |
