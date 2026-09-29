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

## Summary (for the submission form)

_Written in P11.5._
