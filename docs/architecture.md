# Architecture

_Skeleton — each section is filled in by the task noted beside it._

## Layers and why
_P0.3._ Routers (`app/api/v1`, `app/web`) → services (`app/services`) → models
(`app/models`) → PostgreSQL. Routers are thin; all business rules live in
services; the database enforces the invariants it can (see
[`database.md`](database.md)).

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
