# Architecture

_Skeleton — each section is filled in by the task noted beside it._

## Layers and why
Routers (`app/api/v1`, `app/web`) → services (`app/services`) → models
(`app/models`) → PostgreSQL. Routers are thin; all business rules live in
services; the database enforces the invariants it can (see
[`database.md`](database.md)).

Cross-cutting pieces live in `app/core/`:

- **`config.py`**: `Settings` (pydantic-settings) reads every variable in
  `.env.example`; production refuses to start with the placeholder JWT secret.
- **`clock.py`**: business code takes `now` from an injected `Clock` rather than
  calling `datetime.now()`, so tests can freeze time at rule boundaries.
- **`errors.py`**: services raise `AppError(code, message, status_code, details)`
  and never build responses. Handlers turn that, validation errors, framework
  `HTTPException`s and unhandled exceptions into the single
  `{"error": {"code", "message", "details"}}` envelope.
- **`db.py`**: the engine and a session per request. Handlers take a
  `DbSession`; the request commits when the handler returns and rolls back if it
  raises (see [`database.md`](database.md) conventions and ADR 0003).

The health endpoint shows the pattern in miniature: the router
(`api/v1/health.py`) only calls `services/health.check_database`, which runs
`SELECT 1` and raises `AppError` on failure.

## Request lifecycle: create a booking
_P6.5._ Mermaid sequence diagram, including the exclusion-constraint path
(SQLSTATE 23P01 → 409 `SLOT_TAKEN`).

## Components
_P6.5 / P11.4._ Component diagram.

## Time model
_P4.1._ UTC storage, one business timezone, half-open `[start, end)` ranges,
DST policy.

## Slot algorithm
_P5.1._

## Booking lifecycle (state machine)
_P7.1._ Mermaid state diagram and transition rules.

## Authentication
_P2.1–P2.5._ JWT in an HttpOnly cookie for the browser, Bearer for API
clients, CSRF double-submit for cookie requests (ADR 0005), login rate limiting.

**Primitives (`app/core/security.py`, P2.1).**

- Passwords: Argon2id via pwdlib. `verify_password` returns `False` (never
  raises) for a stored hash it does not recognise.
- Tokens: HS256 JWT with `sub` (user id as a string), `iat`, `exp`; lifetime is
  `JWT_EXPIRE_MINUTES`. The token holds no role or active flag: those are
  reloaded from the database on every request (P2.3), so deactivating a user
  or changing a role takes effect at once.
- Decoding only accepts `HS256` (an explicit allow-list, which is what rejects
  `alg=none` and algorithm switching) and requires all three claims.
  Expired, tampered, foreign-secret, wrong-algorithm and malformed tokens all
  raise `InvalidTokenError` (401): code `TOKEN_EXPIRED` for expiry,
  `INVALID_TOKEN` for everything else.
- The clock is injected: both token functions take `now`. Expiry is compared
  against it by us rather than by PyJWT, which would use the real time. A token
  is valid while `now < exp`. There is no leeway and no check that `iat` is not
  in the future, since one process issues and verifies every token.

**Cookies and CSRF (`app/api/cookies.py`, `app/api/csrf.py`, P2.4).** Login sets
`access_token` (HttpOnly) and `csrf_token` (readable). `csrf_protect` runs on
every request app-wide: unsafe methods authenticated by the cookie, without a
Bearer header, must echo the CSRF cookie in `X-CSRF-Token` or a form field, else
403 `CSRF_FAILED`. Reasoning and trade-offs are in ADR 0005.

## Why the web UI and the API share services
_P8.1._

## Testing strategy
Three layers: unit (pure logic, no database), integration (API + real
Postgres), concurrency (threads + real commits). PostgreSQL always, because
the double-booking guarantee is a Postgres exclusion constraint that SQLite
cannot express.

The harness (`tests/conftest.py`, `tests/support.py`):

- **Schema once per run.** The test database's schema is dropped and rebuilt by
  running the Alembic migrations, so the tests exercise the real constraints.
- **Rollback per test.** The `db` fixture wraps each test in an outer
  transaction that is rolled back at the end; the session uses
  `join_transaction_mode="create_savepoint"`, so code under test can `commit()`
  and the data still disappears. The `client` fixture (API) shares that session.
- **Real commits for races.** `committing_db` hands out a session factory whose
  sessions commit for real, one connection per thread, and truncates all tables
  afterwards.
- **Frozen time.** `frozen_clock` overrides the injected clock (see Clock above).
- **Safety guard.** pytest refuses to start when `TEST_DATABASE_URL` equals
  `DATABASE_URL`, since the harness resets the test schema.

## Trade-offs accepted
_Filled in as they are made._
