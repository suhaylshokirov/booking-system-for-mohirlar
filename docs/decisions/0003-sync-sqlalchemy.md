# ADR 0003 — Sync SQLAlchemy 2.0 instead of async

**Status:** accepted (P1.1)

## Context

FastAPI supports both `async def` handlers with an async database driver and
plain `def` handlers with a synchronous one. The app is a small booking system:
a request does a handful of short queries, and its hard problem is correctness
under concurrency (two people booking the same slot), not raw throughput. The
code has to be readable and explainable line by line, and tested against a real
PostgreSQL with transactions that roll back after each test.

## Decision

Use **synchronous SQLAlchemy 2.0** (typed `Mapped[]` models, `Session`) with the
psycopg 3 driver. Route handlers and services are plain `def`; FastAPI runs them
in its thread pool.

## Alternatives considered

- **Async SQLAlchemy (`AsyncSession`, asyncpg or psycopg async).** Better at
  holding thousands of idle connections, which this app will never have. Costs:
  `async`/`await` through every service, lazy-loading pitfalls
  (`MissingGreenlet`), a harder-to-read transaction model, and a more
  complicated test harness. None of that buys anything here.
- **A different ORM or raw SQL.** SQLAlchemy 2.0 gives typed models, Alembic
  migrations and access to PostgreSQL-specific features (exclusion constraints,
  `tstzrange`) without hiding the SQL.

## Consequences

- Simple mental model: one request = one session = one transaction (see
  `app/core/db.py`).
- Concurrency tests can use ordinary threads with one session per thread and
  real commits, which is exactly what the double-booking proof needs (P6.4).
- Blocking work in a handler occupies a worker thread. Acceptable at this scale;
  if it ever mattered, the layering (routers → services → models) would allow
  moving to async one service at a time.
- Objects are read after the request's commit (`expire_on_commit=False`), so
  services must return fully loaded data rather than rely on lazy loading.
