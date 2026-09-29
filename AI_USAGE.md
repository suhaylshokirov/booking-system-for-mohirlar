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

## Summary (for the submission form)

_Written in P11.5._
