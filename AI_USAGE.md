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

## Summary (for the submission form)

_Written in P11.5._
