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
- **`db.py`**: the engine and a session per request (`get_db`).

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
clients, CSRF double-submit for cookie requests, login rate limiting.

## Why the web UI and the API share services
_P8.1._

## Testing strategy
_P0.5._ Unit (pure logic), integration (API + real Postgres), concurrency
(threads + real commits).

## Trade-offs accepted
_Filled in as they are made._
