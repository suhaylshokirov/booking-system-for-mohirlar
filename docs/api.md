# API guide

Swagger UI at `/docs` (and ReDoc at `/redoc`) is the reference. This page is
the guide: how to authenticate, a walkthrough of the booking flow, and the
conventions every endpoint follows. All endpoints are under `/api/v1`.

## Authentication
Two ways to prove who you are; both carry the same signed token.

- **Bearer** (curl, scripts, Swagger): send `Authorization: Bearer <token>`.
- **Cookie** (the browser): login also sets an HttpOnly, `SameSite=Lax`
  `access_token` cookie (`Secure` in production). _Cookie requests will need a
  CSRF token on unsafe methods: added in P2.4._

If both are sent the Bearer header wins, and a bad Bearer token is an error, it
is not quietly replaced by the cookie. Tokens last `JWT_EXPIRE_MINUTES`
(default 12 h). The user is reloaded on every request, so deactivating an
account locks it out immediately.

```bash
# 1. Create an account (always a customer; admins come from the create-admin CLI)
curl -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email": "aziza@example.com", "password": "a long passphrase", "full_name": "Aziza Karimova"}'

# 2. Log in and keep the token
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email": "aziza@example.com", "password": "a long passphrase"}' | jq -r .access_token)

# 3. Use it
curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
```

In Swagger (`/docs`): call `POST /auth/login`, copy `access_token`, press
**Authorize** and paste it.

| Endpoint | Success | Notes |
|---|---|---|
| `POST /auth/register` | 201 user | Email is trimmed and lower-cased; password 8–128 characters; full name 1–100. `409 EMAIL_TAKEN` if the email exists in any letter case. |
| `POST /auth/login` | 200 `{access_token, token_type}` + cookie | Unknown email and wrong password give the same `401 INVALID_CREDENTIALS`. |
| `POST /auth/logout` | 204 | Clears the cookie. Tokens are stateless, so a Bearer token you copied stays valid until it expires. |
| `GET /auth/me` | 200 user | `401` without valid credentials. |

Email addresses are checked with a simple `name@domain.tld` pattern, not a full
RFC validator (that would need an extra dependency); an address that passes but
does not exist is caught the only way it can be: it never receives mail.

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
| `UNAUTHENTICATED` | 401 | No credentials sent (or a generic framework 401) |
| `INVALID_CREDENTIALS` | 401 | Login: unknown email or wrong password (deliberately indistinguishable) |
| `INVALID_TOKEN` | 401 | Token is malformed, tampered with, wrongly signed, or names a user that no longer exists |
| `TOKEN_EXPIRED` | 401 | Token is past its expiry; log in again |
| `ACCOUNT_INACTIVE` | 401 | The account was deactivated (at login only once the password was right; on any request with a token) |
| `EMAIL_TAKEN` | 409 | Registration: that email already has an account |
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
