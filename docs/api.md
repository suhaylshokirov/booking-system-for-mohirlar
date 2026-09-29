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
_P0.3._ Every error has the same shape:

```json
{"error": {"code": "SLOT_TAKEN", "message": "That time was just booked by someone else.", "details": {}}}
```

## Error codes
_One row per code, added by the task that introduces it._

| Code | HTTP | Meaning |
|---|---|---|

## Pagination
_P3.4._ `limit` (default 20, max 100) and `offset`; responses are
`{items, total, limit, offset}`.

## Times and timezones
_P4.1._ All datetimes are ISO 8601 with an offset; naive datetimes are
rejected.
