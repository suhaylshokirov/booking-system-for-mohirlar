# API guide

Swagger UI at `/docs` (and ReDoc at `/redoc`) is the reference. This page is
the guide: how to authenticate, a walkthrough of the booking flow, and the
conventions every endpoint follows. All endpoints are under `/api/v1`.

## Authentication
_P2.2–P2.4._ Cookie (browser, needs CSRF token on unsafe requests) vs
`Authorization: Bearer <token>` (Swagger, curl).

## Walkthrough: book an appointment with curl
_Built up in P5.3, P6.3, P7.3; verified end to end in P10.4._

## Error envelope
Every error has the same shape, whether we raised it, request validation
rejected the input, the route doesn't exist, or something crashed:

```json
{"error": {"code": "SLOT_TAKEN", "message": "That time was just booked by someone else.", "details": {}}}
```

- `code` is stable and machine-readable; clients switch on it.
- `message` is for humans and may be reworded.
- `details` is an object with extra context, `{}` when there is none.
- Malformed JSON, missing fields and wrong types are `422 VALIDATION_ERROR`,
  with one entry per problem in `details.errors`:
  `{"field": "body.email", "message": "...", "type": "string_too_short"}`.
- Unexpected server errors are `500 INTERNAL_ERROR` with a generic message;
  the details are in the server log, never in the response.

## Error codes
_One row per code, added by the task that introduces it._

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Body, query or path failed schema validation; see `details.errors` |
| `BAD_REQUEST` | 400 | Generic framework 400 |
| `UNAUTHENTICATED` | 401 | Generic framework 401 (specific auth codes arrive in P2) |
| `FORBIDDEN` | 403 | Generic framework 403 |
| `NOT_FOUND` | 404 | No such route (or, for our own endpoints, no such resource) |
| `METHOD_NOT_ALLOWED` | 405 | Route exists but not for this HTTP method; `Allow` header lists the valid ones |
| `CONFLICT` | 409 | Generic framework 409 |
| `TOO_MANY_REQUESTS` | 429 | Generic framework 429 |
| `INTERNAL_ERROR` | 500 | Unexpected failure on our side |
| `DATABASE_UNAVAILABLE` | 503 | `GET /health` could not reach the database |

## Health check
`GET /api/v1/health` → `200 {"status": "ok", "database": "ok"}`; it runs
`SELECT 1`, and answers `503 DATABASE_UNAVAILABLE` if the database is down.

## Pagination
_P3.4._ `limit` (default 20, max 100) and `offset`; responses are
`{items, total, limit, offset}`.

## Times and timezones
_P4.1._ All datetimes are ISO 8601 with an offset; naive datetimes are
rejected.
