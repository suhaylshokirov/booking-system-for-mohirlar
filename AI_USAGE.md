# How AI was used

This project was built with an AI coding agent (Claude Code, using the models
Claude Opus 5.5 and Claude Sonnet 5.5) as a pair programmer. This file is a running log, one entry per phase,
written as the work happened. Each entry records:

- **Asked** — what I asked the AI to do
- **Produced** — what it produced
- **Verified** — how I checked it (tests, reading the code, manual checks)
- **Changed / rejected** — what I changed or threw away, and why
- **Bugs caught** — mistakes the AI made that I caught

The architecture decisions (PostgreSQL exclusion constraints, sync SQLAlchemy,
computed slots, server-rendered UI, etc.) were mine and are recorded in
[`docs/decisions/`](docs/decisions/); the AI implemented them under the rules
in [`CLAUDE.md`](CLAUDE.md).

---

## P0 — Bootstrap

- **Asked:** from a written brief of the assignment and my architecture
  decisions, set up the repository skeleton, `CLAUDE.md` (working rules for the
  agent), `tasks.md` (phased plan with a requirement-coverage matrix and time
  checkpoints), and skeletons of the README and docs. Study my previous project
  (Theoria) for UI patterns to port later, without copying features.
- **Produced:** the repository skeleton and working rules (P0.1); the Python
  project with pinned dependencies and ruff (P0.2); the app factory, settings,
  injectable clock, single error envelope and `GET /api/v1/health` (P0.3); a
  Dockerfile and Compose stack with Postgres 16 and a healthcheck (P0.4); a
  Postgres test harness with per-test rollback (P0.5); and the CI workflow plus
  environment-variable table (P0.6).
- **Verified:**
  - Tests and lint: `pytest` (23 tests at the end of P0) and `ruff check` /
    `ruff format --check`, run after every task.
  - Docker: ran `docker compose up --build` for real, called the health
    endpoint from the host, confirmed the container runs as a non-root user and
    that both `navbat` and `navbat_test` exist.
  - Harness: checked the safety guard by starting pytest with
    `TEST_DATABASE_URL` equal to `DATABASE_URL` (it refuses). Ran the Alembic
    branch of the schema builder once with a throwaway migration, because no
    real migration exists until P1.
  - CI: the run on GitHub, not just the local run.
- **Changed / rejected:** three departures from the plan, each recorded in the
  `tasks.md` Deviations log with its reason: the minimal database module pulled
  forward from P1.1 (P0.3), the compose `app` service starting uvicorn without
  `alembic upgrade head` (P0.4), and the test schema being built by Alembic only
  once `alembic.ini` exists (P0.5). Each one leaves a note in P1.1 so it is not
  forgotten.
- **Bugs caught:**
  - The plan said the compose `app` should run `alembic upgrade head`, but there
    is no Alembic setup until P1.1; running it as written would have crashed the
    container on start. Found by checking the repo before writing the file.
  - The Compose stack's default host port 5432 is already taken on my machine.
    Found by running it, fixed with a `DB_HOST_PORT` override that is documented.
  - The first version of the harness could not have migrated the *test* database:
    an Alembic `env.py` that reads `DATABASE_URL` would have migrated the
    development database instead. Fixed by passing the test connection to Alembic
    and requiring `env.py` to use it.

---

## P1 — Database

- **Asked:** from the P1 tasks in `tasks.md` and my rules (the database is the
  double-booking guarantee; PostgreSQL only; UTC; snapshots; soft-delete), build
  the schema and prove it: the SQLAlchemy base and Alembic wiring (P1.1), catalog,
  settings and availability models (P1.2), booking and event models (P1.3), the
  exclusion-constraint migration (P1.4), constraint tests (P1.5), a seed script
  (P1.6) and the database docs (P1.7).
- **Produced:** seven tables plus `provider_services`, and three hand-edited
  migrations (`0001` catalog and availability, `0002` bookings and events, `0003`
  the exclusion constraints); 32 constraint tests that insert directly and assert
  the SQLSTATE and constraint name; an idempotent barbershop seed wired into the
  Docker entrypoint; `docs/database.md` with an ER diagram, a constraint table and
  a plain-language explanation of exclusion constraints; ADRs 0001, 0003, 0006
  and 0007.
- **Verified:**
  - Tests and lint after every task: `pytest` (30 tests after P1.3, 70 at the
    end of P1), `ruff check`, `ruff format --check`.
  - Migrations: upgrade, downgrade, upgrade again on a scratch database, and
    `alembic check` reporting no difference between the models and the migrations.
  - Constraints, by hand in `psql` before writing tests: each CHECK, the unique
    index on `lower(email)`, the availability overlap (adjacent windows allowed),
    and `RESTRICT` on deleting a referenced service.
  - The tests can fail: I temporarily changed the constraint to a closed range
    and removed the status filter, and four tests went red; I removed two seed
    guards and the idempotency tests went red. Then restored both.
  - Docker: a real `docker compose up --build` migrated, seeded and served, and a
    restart left the row counts unchanged.
- **Changed / rejected:** three departures, all in the `tasks.md` Deviations
  log. Migrations `0001` and `0002` were written in P1.2 and P1.3 instead of one
  migration in P1.4, because the P1.2 acceptance criteria already required an
  exclusion constraint and the round-trip test fails for any model without a
  migration. `hash_password` and `local_to_utc` were created in P1.6 instead of
  P2.1 and P4.1, because the seed needs them and CLAUDE.md allows one home for
  each. I kept `cancelled_by_id` as a foreign key name instead of the task's
  `cancelled_by`, for consistency with the other keys.
- **Bugs caught:**
  - Autogenerate created the `booking_status` enum once per column, which would
    have failed with "type already exists"; it also never dropped the `user_role`
    type on downgrade, so a second upgrade would have failed. Both found by
    reading the generated migration, fixed by hand.
  - Autogenerate named the unique constraint on `(provider_id, date)` as
    `uq_availability_exceptions_provider_id`, hiding half of what it covers.
    Named explicitly.
  - Tests passed on the first run, which I did not trust. The mutation check
    above is why the suite now has proof that it can fail.
  - A first draft of the seed converted time zones inline, which would have put
    a second conversion site in the codebase. Moved into `app/core/timezones.py`.
  - The default database port 5432 on this machine belongs to a different
    Postgres, so test runs failed with a password error until pointed at 5433.
  - I was told two or three tasks were left in P1; four were (P1.4 to P1.7).

---

## P2 — Authentication

- **Asked:** from the P2 tasks in `tasks.md` and my rules (JWT in an HttpOnly
  cookie plus Bearer, CSRF double-submit, roles read from the database, no
  endpoint that creates an admin), build the security helpers (P2.1), register,
  login, logout and `me` (P2.2), the current-user and admin dependencies (P2.3),
  CSRF protection (P2.4), login rate limiting (P2.5) and the create-admin script
  (P2.6).
- **Produced:** password verification and HS256 access tokens whose expiry is
  checked against the injected clock; the four `/auth` endpoints; `get_current_user`,
  `get_optional_user` and `require_admin`; an app-wide CSRF dependency, cookie
  helpers and ADR 0005; an in-memory sliding-window login limiter behind a
  three-method interface; an idempotent `python -m scripts.create_admin`. 130
  new tests, 200 in the suite at the end of the phase (70 at the end of P1).
- **Verified:**
  - Tests and lint after every task: `pytest` on the whole suite,
    `ruff check`, `ruff format --check`.
  - **Mutation checks on every task.** Tests that pass on the first run prove
    little, so after each task the AI broke the code on purpose and I looked for
    the matching test to go red, then restored the file. Examples: `alg=none` and
    `HS384` added to the JWT allow-list (two tests failed); the CSRF check made a
    no-op (10 failed); "any Authorization header skips CSRF" (the `Basic`-header
    test failed); the login limiter without its reset, without the IP in the key,
    counting blocked attempts, counting deactivated accounts, or not normalising
    the email (each caught by its own test); the admin script without promotion,
    reactivation, or with an unconditional re-hash (each caught).
  - The create-admin script run for real against the development database: it
    created an admin, said "nothing changed" on a rerun (any email case), refused a
    5-character password, and fell back to `ADMIN_EMAIL`/`ADMIN_PASSWORD`. The
    test rows were deleted afterwards.
  - The OpenAPI document builds after each task that adds endpoints.
- **Changed / rejected:** three departures, all in the `tasks.md` Deviations log.
  `get_current_user` was built in P2.2 instead of P2.3 because `GET /auth/me`
  needs it. Email shape is checked with a regex instead of pydantic `EmailStr`,
  because `EmailStr` needs the `email-validator` package and `CLAUDE.md` says to
  ask me before adding a dependency (I have not been asked; the swap is small).
  The pre-login CSRF cookie for the login and register forms is delivered as
  tested building blocks, wired into the HTML forms in P8.2 when those exist.
- **Bugs caught:**
  - Two of the AI's first tests for P2.1 were wrong, not the code: one decoded a
    token whose `iat` (1 Oct) is in the future relative to the real date (29 Sep),
    the other put `datetime` objects into a JSON payload. Fixed in the tests.
  - Adding CSRF broke two earlier tests in exactly the expected way: logout by
    cookie now needs the token, and the "Secure cookie in production" test patched
    a function that had moved. Both were updated, not the check loosened.
  - A script that edited `app/main.py` ran before the virtualenv was active, so
    the edit silently did nothing while the following commands succeeded. Found by
    reading `git diff` before running the tests.
  - Two mutation results were informative rather than good: switching PyJWT's own
    expiry check on changed nothing, because our clock-based check already covers
    it; and allowing empty CSRF tokens was caught by the unit test but not the
    integration test, because an empty header is already treated as missing. Both
    are defence in depth, not gaps, and are noted here so nobody "fixes" them.
  - Recurring environment problem: the default Postgres port 5432 on this
    machine belongs to a different database, so every test run needed
    `DATABASE_URL` and `TEST_DATABASE_URL` pointed at 5433.

---

## P3 — Catalog

- **Asked:** from the P3 tasks in `tasks.md`, build the business settings
  (P3.1), services CRUD (P3.2), providers CRUD with the services each offers
  (P3.3) and one paging convention for every list (P3.4), under my rules:
  routers stay thin, every rule lives in one service module, services and
  providers are deactivated and never deleted, money is an integer.
- **Produced:** `GET`/`PATCH /settings`; five `/services` endpoints and seven
  `/providers` endpoints; `app/core/pagination.py` (`limit`/`offset`, cap of 100,
  a `paginate` helper that also counts the total) with a generic `Page[T]`
  envelope; an `is_admin` / `IncludeInactive` pair in `app/api/deps.py` shared by
  both routers; shared `admin` and `customer` test fixtures. 113 new tests
  (200 at the end of P2, 332 now), plus API docs and edge-case rows 36–46.
- **Verified:**
  - Tests and lint after every task: `pytest` on the whole suite, `ruff check`,
    `ruff format --check`, and the OpenAPI document building.
  - **Mutation checks, run once at the end of the phase** (not after each task,
    unlike P2): 19 deliberate breakages, each followed by the P3 tests, each
    restored with `git checkout`. Every one was caught, including: timezone check
    removed; inactive services ignored / not ignored by the granularity check;
    the "granularity actually changed" guard removed; the settings `ON CONFLICT`
    removed; `strict=True` dropped from price and duration; the non-admin
    `include_inactive` refusal removed; inactive services or providers leaking
    into public reads; the `UNKNOWN_SERVICE` check removed; the `PUT` delete
    inverted; the page total counting the page instead of all matches; the
    `limit` cap removed.
  - **Not verified by a test:** the row locks (`FOR UPDATE` on the settings row
    and on the provider row). They are what makes a concurrent granularity change
    or a concurrent `PUT /providers/{id}/services` safe, but proving that needs
    real threads and commits, and I did not write those tests (the headline
    concurrency tests are P6.4 and P7.6). Reading the code is the only check so
    far, and `docs/edge-cases.md` row 45 says so.
- **Changed / rejected:** two departures, both in the `tasks.md` Deviations log.
  The pagination helper was built in P3.2 rather than P3.4, because the services
  list needed it. The service description limit stays at 1000 characters (the
  column's size) instead of the 2000 in the criteria. Also decided without a log
  entry, because the plan did not cover it: the first `GET /settings` on a
  migrated but unseeded database creates the settings row with defaults, and
  `include_inactive` from a non-admin is refused (401/403) rather than ignored.
- **Bugs caught:**
  - The first `SettingsUpdate` used `# type: ignore` on every field to give
    non-optional types a `None` default. Replaced with `X | None` fields and one
    validator that rejects explicit nulls.
  - The plan said the description could be 2000 characters, but the column
    (from P1) is `varchar(1000)`: it would have been a database error on 1001 to
    2000. Found by reading the model before writing the schema.
  - The migrations never insert the settings row (only the seed does), so a
    freshly migrated database had no settings for `GET /settings` to return.
    Found by reading the migration; fixed by creating the row on first read.
  - A first edit to `app/core/timezones.py` used `python` where only `python3`
    exists outside the virtualenv, so it did nothing while the next command in
    the same script ran. Found from the error message, reapplied.
  - Every new test file passed on its first run, which proves little; that is
    why the mutation checks above were run.
  - Recurring environment problem: the default Postgres port 5432 on this
    machine belongs to a different database, so every test run needed
    `DATABASE_URL` and `TEST_DATABASE_URL` pointed at 5433.

---

## P4 — Availability

- **Asked:** from the P4 tasks in `tasks.md`, build the timezone module with a
  documented DST policy (P4.1), weekly availability rules (P4.2), day-off and
  custom-hours exceptions (P4.3) and conflict reporting when availability
  changes (P4.4), under my rules: local time becomes UTC in one module only,
  the database enforces overlaps, "today" comes from the injected clock, and an
  availability edit never touches a booking.
- **Produced:** `app/core/timezones.py` (`local_window_to_utc`,
  `local_day_bounds_utc`, gap/overlap policy); `UtcDatetime` and `LocalTime`
  schema types; `app/services/availability.py` with rules, exceptions and
  `find_conflicts`; the pure `build_windows_for_date` in `app/services/slots.py`;
  eleven endpoints under `/providers/{id}/availability`. 113 new tests
  (332 at the end of P3, 445 now), ADR 0006 and the time model in
  `docs/architecture.md`, API docs, and edge-case rows 9 and 12-14, 47-55.
- **Verified:**
  - Tests and lint after every task: whole `pytest` suite, `ruff check`,
    `ruff format --check`.
  - **Mutation checks at the end of the phase:** 18 deliberate breakages, each
    followed by the P4 tests and restored afterwards. All were caught: the DST
    gap snap removed; the overlap taking the second occurrence; wrong day end;
    naive datetimes accepted; adjacent rules counted as overlapping; an edited
    rule overlapping itself; autoflush allowed during validation; the grid check
    removed; past dates allowed; the UTC date used for "today"; the overlap check
    ignoring the provider; another provider's rule reachable by id; a booking
    touching closing time flagged; past bookings and cancelled bookings listed;
    the UTC date used for a booking's day; day-off exceptions ignored;
    exceptions ignored altogether.
  - The backstops are proven by blinding the friendly pre-check on purpose
    (`test_database_exclusion_constraint_is_the_backstop`,
    `test_unique_constraint_is_the_backstop`), so the database's own refusal is
    what produces the 409.
  - **Not verified by a test:** the provider-row lock that makes two admins
    writing rules at once queue up. It needs real threads and commits; the
    concurrency tests are P6.4 and P7.6. The constraint backstop covers the
    outcome, the lock only makes the friendly message reliable.
- **Changed / rejected:** four Deviations-log entries. The 23:45 limit on
  closing times (24:00 does not exist on a `time`); an admin-only exceptions list
  and no edits to past exceptions; `DELETE` answering `200` with the conflict
  warning instead of `204`; and `build_windows_for_date` written in P4.4 instead
  of P5.1. I chose to snap a time inside a DST gap forward to the moment the
  clocks jump (02:30 becomes 03:00), not to shift it by the gap length (03:30)
  which is what `zoneinfo` does by default, so a window can never run past the
  time the admin wrote. ADR 0006 records it.
- **Bugs caught:**
  - The first update path changed a rule in memory and then ran the overlap
    query, which autoflushed the half-edited row into the exclusion constraint
    and would have been a 500. Found by reading the flow; fixed with
    `no_autoflush` in the validation step.
  - A test of "today is the business date, not the UTC date" failed with 401
    because advancing the frozen clock 13 hours expired the admin's token. The
    product was right; the test now mints a new token.
  - The Postgres container had stopped overnight and restarting it fought with
    the other database on port 5432. Compose already documents
    `DB_HOST_PORT=5433` for this; the same environment problem as P3.
  - Every new test file except one passed on its first run, so the mutation
    checks above are what show the tests can fail.

## P5 — Slots

- **Asked:** the pure slot algorithm (`compute_slots`), the query service that
  loads its inputs, and the public `GET /slots` endpoint.
- **Produced:** `app/services/slots.py` (`compute_slots`), `app/services/slot_query.py`
  (`get_slots`), `app/api/v1/slots.py` and `app/schemas/slots.py`; ADR 0002;
  27 unit tests for the algorithm, 13 integration tests for the query and 7 for
  the endpoint.
- **Verified how:**
  - Read every boundary in `compute_slots` against the rules: window end
    inclusive for fitting, lead time inclusive, horizon exclusive, busy ranges
    half-open.
  - Mutation checks on `compute_slots`: I changed each comparison by one
    character (window fit, lead time, horizon, both busy-overlap comparisons) and
    removed the sort; every change made the unit tests fail, then I restored the
    file. The busy-interval and DST tests were not mutation-checked separately.
  - Ran the whole suite (485 tests), ruff check and ruff format.
- **Changed / rejected:** the horizon is `now + max_booking_horizon_days` as an
  instant, not the end of a calendar day; P6.1 must reuse it. The date-range
  rule lives in `get_slots` (service layer), not the router. No Deviations-log
  entry was needed.
- **Bugs caught:**
  - One of my own unit tests expected a 60-minute slot at 09:00 to be blocked by
    a booking starting at 10:00; it touches, so it is valid. The algorithm was
    right and the test was fixed.
  - A first draft of a P5.2 test had a nonsense assertion I had to rewrite, and
    the response schema's field named `date` shadowed the `date` type (Pydantic
    refused to build it); fixed with `import datetime as dt`.
  - Integration tests first all errored because another Postgres holds port
    5432 on this machine; ran the project database on 5433 (`DB_HOST_PORT`).

---

## P6 — Booking creation

- **Asked:** the booking validation rules, the `create_booking` service, the
  customer booking endpoints, concurrency tests for the race, and the final
  ADR 0001 write-up.
- **Produced:** `app/services/booking_rules.py` (pure; eight 422 codes),
  `app/services/booking.py` (`create_booking`, `list_my_bookings`,
  `get_booking`), `app/api/v1/bookings.py`, `app/schemas/booking.py`;
  `tests/unit/test_booking_rules.py`, `tests/integration/test_create_booking.py`,
  `tests/integration/test_bookings_api.py`, `tests/concurrency/test_booking_races.py`;
  the create-booking sequence diagram, the race timeline in
  `docs/edge-cases.md`, and ADR 0001 finalised.
- **Verified how:**
  - Read the check order in `validate_booking_start` against the P6.1 list, and
    made `slots.compute_slots` call the same helpers (`earliest_start`,
    `grid_start_fits`, `horizon_end`) so the grid and the validator cannot disagree.
  - The race path is tested without the pre-check
    (`test_database_constraint_maps_to_409_when_the_precheck_is_skipped`) and
    with real threads: ten customers on one slot give one 201, nine 409, one
    row; a second test holds every thread between the pre-check and the insert
    so all ten pass the pre-check by construction. Ran the concurrency file
    three times in a row to check it is not flaky.
  - Ran the whole suite (527 tests), ruff check and ruff format.
- **Not verified:** I did not run the mutation check that drops both exclusion
  constraints to confirm the concurrency tests then fail (the command was
  blocked by the permission system and I did not retry it). The tests are
  designed so that only the constraint can produce nine 409s, but that has
  not been demonstrated.
- **Changed / rejected:** `GET /bookings` lists only the caller's own bookings,
  admins included; the admin view is P7.3. The response has ids and snapshots
  but no service or provider names; they are added when the UI needs them.
  No Deviations-log entry was needed.
- **Bugs caught:**
  - The forced-interleaving concurrency tests first hung on a barrier timeout.
    Cause: `get_business_settings` inserts the settings row with
    `ON CONFLICT DO NOTHING`, and a second transaction's insert waits for the
    first to commit, so a thread holding a barrier deadlocked its neighbours.
    Fixed by committing the settings row in the test fixture; not a
    production bug (only the very first request on an empty database is affected).
  - A test that advanced the frozen clock five days failed because the 12-hour
    test token had expired; the test now mints a new token after advancing.
  - A double submit breaks both constraints at once, so the loser's code
    (`SLOT_TAKEN` or `CUSTOMER_OVERLAP`) is not deterministic; the test accepts
    either and ADR 0001 says so.
  - Integration tests errored again because the database container was
    stopped and port 5432 is held by another Postgres; used `DB_HOST_PORT=5433`.

---

## P7 — Lifecycle and history

- **Asked:** the booking state machine, guarded transitions with history
  events, the confirm/cancel/complete endpoints and admin list, the
  cancellation policy, the history endpoint, the confirm-vs-cancel race test,
  and flagging stale pending bookings.
- **Produced:** `app/services/booking_state.py` (pure transition table and
  `check_transition`), `booking.transition` / `list_all_bookings` /
  `list_history` in `app/services/booking.py`, the transition, admin-list and
  history routes, ADR 0008, the Mermaid state diagram;
  `tests/unit/test_booking_state.py`, `tests/integration/test_transition.py`,
  `tests/integration/test_booking_transitions_api.py`,
  `tests/concurrency/test_transition_races.py`; `is_stale_pending` and the
  `stale_pending` flag on the admin list.
- **Verified how:**
  - The state machine has a parametrised test for every (from, to) pair not in
    the table and for every role, plus the exact boundaries at the cutoff,
    `start_at` and `end_at`.
  - The race: a barrier placed after each request's rules check makes both
    read `pending` before either writes, so only the guarded UPDATE can stop
    the second. **Mutation check done:** with `Booking.status == expected`
    removed, `test_concurrent_confirm_and_cancel_exactly_one_wins` fails
    (`[200, 200]`); with it restored it passes.
  - Stress-ran the concurrency folder 15 times in a row after the fix below:
    15 of 15 green. Full suite 610 tests at the end of the phase, ruff check and format clean.
- **Not verified:** the P6.4 gap "drop both exclusion constraints and see the
  tests fail" is still not demonstrated.
- **Changed / rejected:**
  - The admin list is `GET /bookings/all`, not `GET /bookings` (deviations
    log): that URL already meant "my own bookings" for everyone.
  - A customer cancelling a pending booking has no cutoff, only "before it
    starts"; the cutoff protects confirmed bookings.
  - The state machine also refuses a non-owner customer as a backstop; the
    404 for someone else's booking happens before it, in `get_booking`.
- **Bugs caught:**
  - Stress-running the concurrency tests showed a **P6 bug**: about one run in
    five, two overlapping inserts (one customer, two providers) deadlocked in
    Postgres and the loser got a 500. `create_booking` now maps the deadlock
    (40P01) to 409 `SLOT_TAKEN`; ADR 0001 records it. The earlier
    "ran it three times, not flaky" in the P6 entry was too few runs to see it.
  - The unforced confirm/cancel test first used start times outside the
    provider's working window (422); fixed by using the 04:00 to 07:00 UTC window.
  - Stale pending: no new rule was needed for the cancel itself, because the
    state machine already let an admin cancel any pending booking; the work was
    the flag and the default reason. Checked that confirming a stale one is
    refused (`INVALID_TRANSITION`).
  - Tests initially assumed a `set()` on the frozen clock that does not exist;
    they advance it by the difference instead.

---

## P8 — Customer UI

- **Asked:** the server-rendered customer side: base layout and design system,
  sign in / create account / sign out, the services price board and service
  page, booking with a live slot picker, and "My bookings" with cancel.
- **Produced:** `app/web/` (`auth`, `catalog`, `booking`, `my_bookings`,
  `errors`, `templating`, `formatting`, `paging`), the Jinja templates and
  `_partials/slot_grid.html`, `static/css/*` and `static/js/app.js`;
  service additions the pages needed and the rules already lived in:
  `slot_query.bookable_dates`, `booking_state.cancellation_cutoff_at` and
  `can_cancel`, `booking.get_own_booking`, `booking.describe_bookings`;
  `tests/integration/test_web_*.py` and the matching unit tests.
- **Verified how:**
  - Every page is tested through the real app against real Postgres with the
    frozen clock: what is shown, the status codes, and that nothing changed
    when a request was refused.
  - The Cancel button asks `can_cancel`, which calls `check_transition`, so the
    button cannot disagree with the rule; tests cover the cutoff exactly and
    one second after it, and pressing Cancel after the cutoff (409, nothing changes).
  - **Mutation check done (P8.5):** with the ownership check removed from
    `get_own_booking`, `test_an_admin_does_not_get_a_customer_page_for_someone_else_s_booking`
    fails; restored, it passes.
  - Full suite 762 tests, ruff check and format clean.
- **Not verified:** the pages were checked by tests and by reading the HTML,
  not by eye in a browser, and the live picker and confirm dialog (JavaScript)
  have no automated test; the no-JavaScript path is what the tests cover.
- **Changed / rejected:**
  - Lime is used only for committed or selected things (rule 12); the ported
    Theoria buttons and stat ticks that were lime became ink.
  - A customer's page for a booking is not shown to an admin who is not its
    owner (`get_own_booking`), although the API lets admins read any: the
    customer page's Cancel button would not be theirs to press.
  - A cancelled future booking stays under Upcoming with its "Cancelled" chip,
    because the service's `upcoming` means "not over yet"; it was not split out.
- **Bugs caught:**
  - A registration name of only spaces passed validation (the length was
    checked before trimming); found while building the header, which greets
    the user by first name. Fixed in `5336427`.
  - After losing a race, `transition` raised 409 but left the booking object in
    the session showing the old status, so the re-rendered page would have
    shown the wrong status. `transition` now refreshes it before raising, and
    `test_stale_expected_status_is_409_and_writes_no_event` asserts it.
  - The first run of the P8.5 tests failed for two of my own mistakes: the
    login cookie in the test expired once the frozen clock moved past the
    booking, and `dict()` on a SQLAlchemy result does not build a mapping
    (`.all()` first).

## P8 — UI redesign ("tile and ticket")

- **Asked:** the owner found the Theoria-inspired look empty and too basic
  and asked for a complete redesign, with a free hand on the direction.
- **Produced:** a new design system in `app/static/css/app.css` and new page
  CSS; every customer template reworked around a `masthead` block in
  `base.html`. Cobalt glazed band with a girih lattice (Tashkent tilework),
  the booking drawn as a *navbat*
  queue ticket, saffron as the one "committed or selected" colour, a
  barber-pole stripe for loading. The home page gained a "house rules" ticket
  built from real business settings and a JS-only shop clock.
- **Verified how:**
  - Screenshotted every page (home, service, login, picker, confirm, my
    bookings, booking page, 404) at 1360 px and 390 px, light and dark, with a
    headless browser against the seeded app, and checked each by eye.
  - Scripted the JavaScript paths in the browser: the live picker swaps the
    grid when the person changes, the chosen time is echoed in the Continue
    bar, the stub opens the booking, the cancel dialog opens with "No"
    first, the theme toggle updates `theme-color`; no console errors.
  - Measured horizontal overflow at 390 px on every page (none).
  - Full suite 762 tests, ruff check and format clean. Class names the tests
    assert were kept; only the token test changed (`--lime` → `--saffron`).
- **Changed / rejected:**
  - The fonts were first changed too (a slab display face, Onest, and a
    dot-matrix face for ticket times; the first dot-matrix face, Doto, drew
    its colon as a cross, "22‡06"). After review the owner asked to keep
    Theoria's type, so Archivo (expanded titles, condensed labels),
    Instrument Sans and Spline Sans Mono stay, at the redesign's sizes.
- **Bugs caught (in AI output, by the screenshots):**
  - `.masthead a` out-ranked `.btn--light`, so buttons on the band had white
    text on a white pill (invisible "Choose a service" / "Book a time").
  - The ticket's print animation clipped its own shadow into a grey box, and
    its `transform` wiped the hero ticket's tilt; now `translate` + a wider clip.
  - `.field input { width: 100% }` also sized the hidden radios of the "With"
    list, making the booking page 436 px wide on a 390 px phone.
  - `syncThemeColor` read `--paper` with `getPropertyValue`, which returns
    the unresolved `light-dark(...)` text; it now reads the resolved colour.

---

## P9 — Admin UI

- **Asked:** one task at a time, the admin pages over the existing services:
  dashboard (P9.1), services (P9.2), providers (P9.3), availability editor
  (P9.4), all-bookings management (P9.5), business settings (P9.6).
- **Produced:** `app/web/admin*.py` routers, `services/dashboard.py`, the
  `admin/` templates, `css/admin.css`, and a `customer_email` filter on
  `list_all_bookings`. Every page is thin: it parses the form, calls the same
  service function the JSON API calls, and turns a refusal into a message
  beside the field (or a notice). Customers get the 404 page on `/admin*`.
- **Verified how:** an integration test file per task (access for visitor,
  customer and admin; the happy path; each refusal showing its message and
  changing nothing); the full suite, 842 tests at the end; ruff check and
  format. The pages were **not** looked at in a browser this phase, so layout
  and the live filter's JavaScript are unchecked by eye.
- **Changed / rejected:**
  - The pending-queue actions first lived in `admin.py`; in P9.5 they moved
    to `admin_bookings.py` (same URLs) so one place owns every booking action.
  - "Live filters" reuse the existing `initLiveFilter` (table fragment on
    `X-Requested-With`) instead of new JavaScript.
- **Bugs caught (in AI output, by tests):**
  - The provider form's "undo if the services are refused" used
    `db.rollback()`, which also wiped the test's fixtures; replaced with a
    savepoint, which is also the right scope in production.
  - The shared `field` macro drew `value` only when truthy, so a saved `0`
    (lead time, cutoff) showed as an empty box; it now tests for none/empty.
  - A first dashboard test expected 17% utilization; one 30-minute booking in
    360 available minutes is 8%. The test was wrong, not the code.

---

## P10 — Bonuses

- **Asked:** one task at a time: the calendar file (P10.1), a notifier with an
  outbox (P10.2), timezone display polish (P10.3), the API documentation pass
  (P10.4). Before P10.4 I changed the
  product: **remove the admin and let the barbers manage client requests**
  (P10.5, ADR 0010). The AI asked me four design questions before touching code
  (how barbers log in, who manages shared setup, how accounts are created, what
  a barber may see) and I chose: a `barber` role tied to one provider, any
  barber manages services and settings, accounts by script and seed only, a
  barber sees only the bookings made with them.
- **Produced:**
  - P10.1 `services/calendar.py` (pure RFC 5545 builder), two download routes,
    an "Add to calendar" link; ADR 0011. Commit `94fe5b0`.
  - P10.2 `services/notifications.py` (`Notifier` protocol, console and outbox
    notifiers), `outbox_messages` and migration `0004`, hooks in
    `create_booking` and `transition`; ADR 0009. Commit `aabf9ab`.
  - P10.3 `local_start` / `local_end` / `timezone` in booking and slot
    responses, a per-instant UTC offset beside every time on the pages, and a
    device-timezone note; ADR 0006 addendum. Commit `78c0e50`.
  - P10.4 `app/core/error_catalog.py` (one list of error codes), `app/core/openapi.py`
    (finishing the Swagger document), examples and descriptions on every endpoint,
    `tests/unit/test_openapi_docs.py` (about 190 checks), `docs/walkthrough.sh`, and the
    docs/api.md updates.
  - P10.5 the barber role: migration `0005`, `require_barber` and
    `require_own_provider`, scoped bookings, dashboard, hours and profile,
    `/admin` renamed to `/barber`, `create_barber`, a seed login per barber;
    ADR 0010, edge cases 87-90. Commit `46cfa32`.
- **Verified how:** a test file or test group per task (including a Berlin
  business across the 25 October clock change, a rolled-back booking leaving no
  notification, and "another barber's booking is a 404" through the API and the
  web); the whole suite after each task (866, 881, 897, 906, then 1101 tests, most of
  the increase being the per-endpoint documentation checks);
  `alembic check` for model/migration drift; a test that migration `0005`
  converts an existing admin; for P10.5 also a real server against the
  migrated and seeded dev database, signing in as a barber and fetching every
  barber page. For P10.4 the guide's flow was **run**, not just read: the walkthrough
  script against a fresh `docker compose up` (a separate project and ports, so my dev
  database was untouched) ended with `WALKTHROUGH OK`. The device-timezone script was checked against real `Intl` in
  Node, **not** in a browser, and the new CSS was not looked at by eye.
- **Changed / rejected:**
  - The AI considered an environment switch for the notifiers and kept a plain
    module list (tests swap it) because nothing needs the switch.
  - For P10.5 the AI offered a "lead barber" flag and per-barber services; both
    rejected as an admin by another name and as model growth for no requirement.
  - Barbers' own pages dropped the provider id from the address entirely rather
    than checking it, so there is nothing to tamper with.
  - Not built, on purpose: a notification to the barber, a delivery worker for
    the outbox, a browser test for the timezone note, the walkthrough in CI.
- **Bugs caught:**
  - The full-suite run after P10.2 failed a concurrency test that is not about
    the change. Reproducing it on the previous commit (4 failures in 25 runs)
    showed it was an old flaky test: a deadlock-aborted insert is mapped to
    `SLOT_TAKEN` by design, but the test only accepted `CUSTOMER_OVERLAP`.
    Fixed separately in `0dac484` and logged in the Deviations log.
  - P10.1: my first edit script ran with a `python` that does not exist, so
    nothing was applied; I noticed because lint was unchanged. Then escaped
    semicolons in test strings were malformed (ruff flagged them, a `sed` fix
    made them worse, raw strings fixed them). `DTSTAMP` formatted a datetime
    without converting it to UTC first, which is wrong if the driver returns
    another offset; fixed with `astimezone(UTC)`.
  - P10.2: I put the calendar paragraph under "Authentication" in
    `architecture.md`; moved to its own section in the next commit.
  - P10.3: a template conditional (`if start is defined else ...`) was clumsy and
    replaced with one explicit expression per file.
  - P10.5: a word-level rename (`admin` to `barber`) also rewrote prose it should
    not have ("the the barber wrote", "visited the barber"), found by reading the
    diff. The new CHECK would have failed on any database that already had an
    admin; the migration now creates a provider per admin first, and a test
    proves it. Tests that expected 404 for another provider's hours now expect
    403 on purpose (that is a public provider, not a private booking).
  - P10.4: the new docs test found that five booking-transition codes had never been
    in the error table, so the "complete" table was not complete. FastAPI's generated
    422 documented `{"detail": [...]}`, which this API never sends. I wrote in an
    endpoint docstring that `/auth/me` returns `provider_id` when it did not; running
    the walkthrough exposed that a barber had no way to learn their provider id, so the
    field was added (and tested) rather than the claim removed. The walkthrough's first
    run booked with one barber and then signed in as another, correctly seeing nothing:
    the script was wrong, the API was right.

## P10 — Owner requests: phone numbers, photos, the home page

- **Asked:** add photos and phone numbers to the barbers, and photos of the
  barbershop to the home page, using the frontend-design skill. The AI asked
  two questions first, because image uploads were listed as out of scope
  (CLAUDE.md §8): how a photo gets in (I chose upload, stored in Postgres, over
  pasting a link) and where the phone is shown (I chose the staff cards and the
  customer's own booking). My pending, uncommitted lattice-removal UI change was
  committed on its own first (`0c40b20`) so it did not mix with this work.
- **Produced:**
  - P10.6 phone numbers: `PhoneNumber` (E.164, country code required),
    `ck_providers_phone_e164` and migration `0006`, the profile field, `tel:`
    links on staff cards and on a live booking, grouped display for `+998`.
    Commit `1ceb8fc`.
  - P10.7 photos: `services/provider_photo.py` (type from the file's first
    bytes, 2 MB cap), migration `0007` with three CHECKs, `GET`/`PUT`/`DELETE
    /providers/{id}/photo`, `photo_url` with a version, the profile upload with
    preview and remove, the `.arch` component (every photo framed as an iwan
    arch), seed portraits; ADR 0012. Commit `e2d735d`.
  - P10.8 the home page: five shop photos rising out of the band, and a
    "Barbers" section with a booking link per service.
  - Photos are Unsplash stock (free licence), picked by the AI after looking at
    about 25 candidates, cropped by Unsplash's image service, credited in
    `docs/credits.md`.
- **Verified how:** tests per task (phone spellings and refusals, the CHECKs,
  SVG and mislabelled files refused, exactly 2 MB accepted and one byte more
  refused, a refused photo undoing the whole profile save, photo bytes not loaded
  when listing, the home page's links and images); the whole suite after each
  commit; `alembic check` (no drift); and, because tests cannot judge a shape, the
  pages were run against a separate scratch database and screenshotted in
  headless Chromium at 1280 px and 390 px, light and dark.
- **Changed / rejected:**
  - Rejected: a link to a hosted image (breaks, depends on a third party), files
    on disk (lost on redeploy without a volume), resizing with Pillow (a new
    dependency for a few thumbnails).
  - `photo_url` was first written in the service layer; moved to the schema
    module because building a URL is presentation, not a business rule.
  - The shop photos are static files, not a gallery a barber manages (still out
    of scope); recorded in the Deviations log.
- **Bugs caught:**
  - The first arch screenshot showed a step where the crown met the sides: the
    crown SVG had `preserveAspectRatio="none"`, which removes its aspect ratio,
    so the browser stretched it to the full height. Only the screenshot showed it.
  - On a photo with a white background (Jasur's) the arch vanished into the white
    card; a thin cobalt rim was added. A CSS-drawn phone handset read as a pill
    and was replaced by an icon.
  - A constraint test used a phone spelling longer than the column, so it hit
    "value too long" before the CHECK it meant to test; the value was changed.
  - The OpenAPI docs test assumed every request body is JSON; it now requires a
    multipart upload to describe its fields instead.
  - The first photo credits linked `unsplash.com/photos/<id>` addresses that do not
    exist in that form; replaced with the image addresses actually downloaded.
- **Owner's review, and what changed:**
  - The shop photos were first framed as pointed arches too (an arcade). I did
    not like the framing on the shop pictures; they are now plain rounded
    rectangles in the same row. The arch stays on barber portraits only.
  - My running app showed initials, not photos: its database had been seeded
    before photos existed, and the AI had made the seed add a photo only when it
    creates a barber. It had flagged this in its summary rather than fixing it.
    The seed now fills a missing photo and phone for the demo barbers on every
    run, never replacing ones a barber set (tested).

---

## Summary (for the submission form)

_Written in P11.5._
