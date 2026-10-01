# API guide

Swagger UI at `/docs` (and ReDoc at `/redoc`) is the reference. This page is
the guide: how to authenticate, a walkthrough of the booking flow, and the
conventions every endpoint follows. All endpoints are under `/api/v1`.

## Authentication
Two ways to prove who you are; both carry the same signed token.

- **Bearer** (curl, scripts, Swagger): send `Authorization: Bearer <token>`.
- **Cookie** (the browser): login also sets an HttpOnly, `SameSite=Lax`
  `access_token` cookie (`Secure` in production), plus a readable `csrf_token`
  cookie. See CSRF below.

If both are sent the Bearer header wins, and a bad Bearer token is an error, it
is not quietly replaced by the cookie. Tokens last `JWT_EXPIRE_MINUTES`
(default 12 h). The user is reloaded on every request, so deactivating an
account locks it out immediately.

```bash
# 1. Create an account (always a customer; admins come from the create-admin script, see the README)
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

**CSRF (cookie requests only).** A browser attaches cookies to requests that
other websites trigger, so any `POST`, `PUT`, `PATCH` or `DELETE` that is
authenticated **by the cookie** must also send the value of the `csrf_token`
cookie back, in an `X-CSRF-Token` header (or a `csrf_token` form field for plain
HTML forms). Otherwise: `403 CSRF_FAILED`.

- `GET`/`HEAD`/`OPTIONS` never need it.
- **Bearer requests never need it** (curl, scripts, Swagger's Authorize).
- Anonymous requests (registering or logging in with curl, no cookies) never
  need it.
- Login issues a new `csrf_token`; logout clears both cookies.
- Swagger gotcha: after logging in *inside* Swagger the browser holds the
  cookies, so POSTs from the page fail with `CSRF_FAILED` unless you press
  **Authorize** and paste the token, which makes them Bearer requests.

```js
// browser JavaScript
const csrf = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/)?.[1];
fetch("/api/v1/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrf } });
```

**Login rate limit.** Failed logins are counted per (client IP, email) in a
sliding window: `LOGIN_RATE_LIMIT_ATTEMPTS` failures (default 5) within
`LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default 300). After that, further attempts,
**even with the correct password**, get `429 TOO_MANY_ATTEMPTS` with a
`Retry-After` header (and `details.retry_after_seconds`) until the oldest
failure leaves the window. Details:

- The counter is per pair, so someone failing against your email from another
  address cannot lock you out.
- Emails are compared normalised (case, padding), and unknown emails are
  limited the same way as real ones, so the 429 does not reveal who has an account.
- Only wrong credentials count. Blocked attempts do not extend the block.
  Invalid request bodies (422) and deactivated accounts do not count.
- A successful login clears the counter.
- Limits: the counters live in one process's memory, so they reset when the app
  restarts and are not shared between several instances. Rotating IP addresses
  defeats a per-IP limit. Behind a reverse proxy the app must see the real
  client address (uvicorn `--proxy-headers`), or all visitors share one IP.

**Who may call what.** Every endpoint is one of three kinds, and the status
codes are consistent:

| Kind | Anonymous | Logged-in customer | Admin |
|---|---|---|---|
| Public | works | works | works |
| Customer (needs an account) | `401 UNAUTHENTICATED` | works | works |
| Admin | `401 UNAUTHENTICATED` | `403 FORBIDDEN` | works |

An anonymous call to an admin endpoint is a 401 (log in), not a 403. A public
endpoint that adapts to who is looking (for example, showing "your bookings")
treats an expired or invalid session as anonymous instead of failing. Roles are
read from the database on every request, so promoting, demoting or deactivating
someone applies to their existing token immediately.

| Endpoint | Success | Notes |
|---|---|---|
| `POST /auth/register` | 201 user | Email is trimmed and lower-cased; password 8–128 characters; full name 1–100. `409 EMAIL_TAKEN` if the email exists in any letter case. |
| `POST /auth/login` | 200 `{access_token, token_type}` + cookie | Unknown email and wrong password give the same `401 INVALID_CREDENTIALS`. Rate limited: see below. |
| `POST /auth/logout` | 204 | Clears both cookies (needs the CSRF header if sent by cookie). Tokens are stateless, so a Bearer token you copied stays valid until it expires. |
| `GET /auth/me` | 200 user | `401` without valid credentials. |

Email addresses are checked with a simple `name@domain.tld` pattern, not a full
RFC validator (that would need an extra dependency); an address that passes but
does not exist is caught the only way it can be: it never receives mail.

## Business settings
The business's timezone, currency and booking rules live in one row.

| Endpoint | Who | Success | Notes |
|---|---|---|---|
| `GET /settings` | public | 200 settings | `name`, `timezone`, `currency`, `slot_granularity_minutes`, `min_lead_time_minutes`, `max_booking_horizon_days`, `cancellation_cutoff_hours`, `updated_at`. Clients need these to show dates and slots, and none is secret. A database that was migrated but never seeded gets the default row on first read. |
| `PATCH /settings` | admin | 200 settings | Partial: send only the fields to change; an empty body or a `null` is `422 VALIDATION_ERROR`. |

Limits on `PATCH`: `timezone` must be an IANA name (`422 INVALID_TIMEZONE`);
`slot_granularity_minutes` one of 5, 10, 15, 20, 30, 60; `min_lead_time_minutes`
0–10080; `max_booking_horizon_days` 1–365; `cancellation_cutoff_hours` 0–720;
`currency` three capital letters; `name` 1–100 characters after trimming.

Changing the granularity is refused with `409 GRANULARITY_CONFLICT` while any
**active** service has a duration that is not a multiple of the new value
(`details.services` lists them), so no service is left unbookable. Nothing is
half-applied: a refused request changes none of its fields. Existing bookings
are never touched by a settings change.

```bash
curl localhost:8000/api/v1/settings
curl -X PATCH localhost:8000/api/v1/settings -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"max_booking_horizon_days": 30}'
```

## Services
What customers can book. Prices are whole UZS (integers; `10.5` and `"100"`
are rejected), durations are whole minutes.

| Endpoint | Who | Success | Notes |
|---|---|---|---|
| `GET /services` | public | 200 page | Active services, alphabetical. `include_inactive=true` is admin-only: anonymous gets `401`, a customer `403` (refused, not quietly ignored, so nobody mistakes a filtered list for a full one). |
| `GET /services/{id}` | public | 200 service | An inactive service is `404` for everyone but admins. |
| `POST /services` | admin | 201 service | See limits below. |
| `PATCH /services/{id}` | admin | 200 service | Partial. `description: null` clears it; other fields cannot be null; an empty body is `422`. |
| `POST /services/{id}/deactivate` | admin | 200 service | Hides it from customers. No hard delete exists. Repeating it is a no-op. |
| `POST /services/{id}/activate` | admin | 200 service | `422 DURATION_NOT_ALIGNED` if the slot granularity changed while it was inactive and it no longer fits. |

Limits: `name` 1–100 characters and `description` up to 1000, both trimmed (a blank
description becomes `null`); `duration_minutes` 1–480 and a multiple of the
business's `slot_granularity_minutes` (`422 DURATION_NOT_ALIGNED`, with both
numbers in `details`); `price` 0 to 2,147,483,647 (0 is a free service).

Editing or deactivating a service never changes existing bookings: each keeps
the price and duration it was made with.

```bash
curl -X POST localhost:8000/api/v1/services -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "Haircut", "description": "Wash and cut.", "duration_minutes": 30, "price": 60000}'
curl 'localhost:8000/api/v1/services?limit=10&offset=0'
```

## Providers
The staff customers book with. Providers are records the admin manages; they
have no login.

| Endpoint | Who | Success | Notes |
|---|---|---|---|
| `GET /providers` | public | 200 page | Active providers, alphabetical, each with the services they offer. `?service_id=` keeps only providers who offer that service (an unknown or inactive service matches nobody). `include_inactive=true` is admin-only (`401` anonymous, `403` customer). |
| `GET /providers/{id}` | public | 200 provider | Includes `services`. An inactive provider is `404` for everyone but admins. |
| `POST /providers` | admin | 201 provider | `name` 1–100 and `bio` up to 1000 characters, trimmed (a blank bio becomes `null`). The new provider offers nothing until you `PUT` their services. |
| `PATCH /providers/{id}` | admin | 200 provider | Partial. `bio: null` clears it; `name` cannot be null; an empty body is `422`. |
| `POST /providers/{id}/deactivate` | admin | 200 provider | Hides them from customers. No hard delete exists. Repeating it is a no-op. |
| `POST /providers/{id}/activate` | admin | 200 provider | |
| `PUT /providers/{id}/services` | admin | 200 provider | Body `{"service_ids": [1, 2]}` **replaces** the whole set; `[]` means "offers nothing"; repeated ids count once. Any id that is not an existing, active service is `422 UNKNOWN_SERVICE` (`details.service_ids` lists them) and nothing is changed. |

Customers only ever see **active** services inside a provider; the admin also
sees inactive ones (with `is_active: false`), so a link to a retired service
can be found and removed. Deactivating a provider or changing what they offer
never touches bookings that already exist.

```bash
curl -X POST localhost:8000/api/v1/providers -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"name": "Jasur", "bio": "Classic cuts."}'
curl -X PUT localhost:8000/api/v1/providers/1/services -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"service_ids": [1, 2]}'
curl 'localhost:8000/api/v1/providers?service_id=1'
```

## Availability rules
_P4.2._ The weekly hours each provider works, as **local wall-clock times in the
business timezone** (`GET /settings`). `weekday` is 0 = Monday … 6 = Sunday.
Days off and custom hours are exceptions (below); bookings that stop fitting after a change are reported as conflicts (last part of this section).

| Endpoint | Who | Success | Notes |
|---|---|---|---|
| `GET /providers/{id}/availability/rules` | public | 200 list | Monday first, earliest window first. An inactive provider is `404` for everyone but admins. |
| `POST /providers/{id}/availability/rules` | admin | 201 rule + `details.conflicts` | Body `{"weekday": 0, "start_time": "09:00", "end_time": "18:00"}`. |
| `PATCH /providers/{id}/availability/rules/{rule_id}` | admin | 200 rule + `details.conflicts` | Partial; the result is validated as a whole. A rule id that belongs to another provider is `404`. |
| `DELETE /providers/{id}/availability/rules/{rule_id}` | admin | 200 `{id, details}` | A hard delete (nothing references a rule). Bookings are never touched; `details.conflicts` lists the ones that no longer fit. |

Rules: `start_time`/`end_time` are whole minutes with no offset, `end_time` is
later than `start_time` (a window cannot cross midnight, and `24:00` does not
exist, so the latest closing time on the grid is `23:45` at 15 minutes), and both
are multiples of `slot_granularity_minutes` since midnight. Windows on the same
weekday must not overlap; **touching windows are fine** (12:00 ends, 12:00
starts), so a lunch break is two rules.

```bash
curl -X POST localhost:8000/api/v1/providers/1/availability/rules \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"weekday": 0, "start_time": "09:00", "end_time": "13:00"}'
curl localhost:8000/api/v1/providers/1/availability/rules
```

### Exceptions: days off and custom hours
_P4.3._ An exception for a date **replaces** that date's weekly rules
completely: with no times the provider is closed, with both times they work
only that window (the weekly rules for the date are ignored, not merged).

| Endpoint | Who | Success | Notes |
|---|---|---|---|
| `GET /providers/{id}/availability/exceptions` | admin | 200 list | Earliest date first, past dates included. Admin-only: a `reason` such as "sick leave" is not for customers, who only see the resulting slots. |
| `POST /providers/{id}/availability/exceptions` | admin | 201 exception + `details.conflicts` | Day off: `{"date": "2026-10-12", "reason": "Public holiday"}`. Custom hours: add `start_time` and `end_time`. |
| `PATCH /providers/{id}/availability/exceptions/{exception_id}` | admin | 200 exception + `details.conflicts` | Partial, validated as a whole. Here `null` means something: `{"start_time": null, "end_time": null}` turns the date into a day off; `reason: null` clears it. `date` cannot be null. |
| `DELETE /providers/{id}/availability/exceptions/{exception_id}` | admin | 200 `{id, details}` | The weekly rules apply to that date again. Allowed for past dates too. |

Rules: one exception per provider per date (`409 AVAILABILITY_EXCEPTION_EXISTS`);
the date must be **today or later in the business timezone** (`422 DATE_IN_PAST`,
with `details.today`), so an exception cannot be created or edited once its date
has ended on the business's wall clock. Custom hours follow the same grid and
range rules as weekly rules. `is_day_off` in the response is `true` when both
times are `null`. An exception on a date that already has bookings is allowed and
**never touches those bookings**; see conflicts below.

```bash
curl -X POST localhost:8000/api/v1/providers/1/availability/exceptions \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"date": "2026-10-13", "start_time": "12:00", "end_time": "16:00"}'
```

### Conflicts: what no longer fits
_P4.4._ Editing availability **never modifies, cancels or moves a booking**. Instead
the admin is told which future bookings now fall outside the provider's hours.

| Endpoint | Who | Success | Notes |
|---|---|---|---|
| `GET /providers/{id}/availability/conflicts` | admin | 200 list | Pending and confirmed bookings that have not started yet and are not fully inside a working window of their **local** date (the exception for that date if there is one, else the weekly rules). Earliest first. |

Every rule or exception write (`POST`, `PATCH`, `DELETE`) also returns the same
list as `details.conflicts`. It is a **warning, not an error**: the status is
`2xx` and the change has been applied. A booking that ends exactly at closing time
still fits (half-open ranges). Each item:

```json
{"booking_id": 12, "status": "confirmed", "start_at": "2026-10-05T11:00:00Z",
 "end_at": "2026-10-05T11:30:00Z", "customer_id": 3, "service_id": 1,
 "reason": "day_off"}
```

`reason` is `day_off` (an exception closes that date), `no_hours` (no weekly rule
for that weekday) or `outside_hours` (there are hours that day, but not around the
booking). Note that the deletes return `200` with a body rather than `204`, so the
warning has somewhere to go.

## Walkthrough: book an appointment with curl
_Built up step by step: slots (P5.3), booking (P6.3), cancelling (P7.3); verified end to end in P10.4._

**Step: see free slots** (public, no login). Pick a service id from
`GET /services`, then ask for a date. Omit `provider_id` to get every provider
who offers it, grouped.

```bash
curl 'localhost:8000/api/v1/slots?service_id=1&date=2026-10-05'
curl 'localhost:8000/api/v1/slots?service_id=1&date=2026-10-05&provider_id=1'
```

```json
{
  "date": "2026-10-05",
  "timezone": "Asia/Tashkent",
  "service": {"id": 1, "name": "Haircut", "duration_minutes": 30, "price": 60000},
  "providers": [
    {"provider": {"id": 1, "name": "Jasur"},
     "slots": [{"start_at": "2026-10-05T04:00:00Z", "end_at": "2026-10-05T04:30:00Z",
                "local_start": "2026-10-05T09:00:00+05:00", "local_end": "2026-10-05T09:30:00+05:00"}]},
    {"provider": {"id": 2, "name": "Aziz"}, "slots": []}
  ]
}
```

- `start_at`/`end_at` are UTC instants; `local_start`/`local_end` are the same
  instants on the business's clock, with the UTC offset (04:00Z is
  `09:00+05:00` in Tashkent). `date` and `timezone` say which local day was
  asked for. `end_at` is exclusive. Send `start_at` back when booking.
- `date` must be from today to today + the booking horizon (business settings),
  otherwise `422 DATE_OUT_OF_RANGE` with `details.earliest` / `details.latest`.
- A provider with nothing free is still listed, with `"slots": []`.
- The list is advisory. Someone else may book a slot before you do; the
  booking call then answers `409 SLOT_TAKEN`.

**Step: book it** (login required; Bearer or cookie). Send one of the
`start_at` values from the slots step. It must carry an offset (`Z` or
`+05:00`); a time without one is `422 VALIDATION_ERROR`.

```bash
curl -X POST localhost:8000/api/v1/bookings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"service_id": 1, "provider_id": 1, "start_at": "2026-10-05T04:00:00Z", "notes": "Short back and sides"}'
```

```json
{
  "id": 7, "customer_id": 3, "provider_id": 1, "service_id": 1,
  "start_at": "2026-10-05T04:00:00Z", "end_at": "2026-10-05T04:30:00Z",
  "local_start": "2026-10-05T09:00:00+05:00", "local_end": "2026-10-05T09:30:00+05:00",
  "timezone": "Asia/Tashkent",
  "status": "pending", "price_amount": 60000, "duration_minutes": 30,
  "notes": "Short back and sides", "cancel_reason": null,
  "created_at": "2026-10-01T07:00:00Z"
}
```

- **Times.** Every booking response has the UTC instants (`start_at`, `end_at`,
  the source of truth), the same instants on the business's clock with their
  offset (`local_start`, `local_end`), and the IANA `timezone`. The offset is
  the one in force *on that date*, so a Berlin booking is `+02:00` in October
  and `+01:00` in November; a client never needs timezone arithmetic of its own.
- `201` creates a `pending` booking. Price and duration are copied from the
  service now, so a later edit to the service does not change this booking.
- `409 SLOT_TAKEN`: the provider is busy then. `409 CUSTOMER_OVERLAP`: you
  already have a booking at that time, with anyone. Back-to-back is fine.
- The booking rules answer `422` with their own code (see the error table).

`GET /bookings?scope=upcoming|past&status=pending&limit=20&offset=0` lists
your own bookings (paginated). `upcoming` means not over yet, soonest first;
`past` is latest first. `GET /bookings/{id}` reads one; someone else's booking
is `404 BOOKING_NOT_FOUND`, exactly like one that does not exist. Admins can
read any booking by id.

**Step: confirm or cancel.** Status changes are separate calls:

```bash
# admin confirms
curl -X POST localhost:8000/api/v1/bookings/7/confirm -H "Authorization: Bearer $ADMIN_TOKEN"
# the customer (or an admin) cancels; the body is optional
curl -X POST localhost:8000/api/v1/bookings/7/cancel \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason": "Feeling unwell."}'
```

Each returns the updated booking. Who may do what, and when (full table in
`docs/architecture.md`):

| Call | Who | Errors |
|---|---|---|
| `POST /bookings/{id}/confirm` | admin, before it starts | `403 FORBIDDEN` (customer), `409 INVALID_TRANSITION` |
| `POST /bookings/{id}/cancel` | its customer, or an admin | `409 CANCELLATION_CUTOFF_PASSED` (`details.cutoff_at`), `422 REASON_REQUIRED` (admin, confirmed booking), `409 INVALID_TRANSITION` |
| `POST /bookings/{id}/complete` | admin, after it ends | `403 FORBIDDEN`, `409 TOO_EARLY_TO_COMPLETE` |

- Cancellation policy: a customer may cancel a *confirmed* booking until
  `cancellation_cutoff_hours` before it starts (`GET /settings`, so a client can
  say so up front); a *pending* one until it starts. After that,
  `409 CANCELLATION_CUTOFF_PASSED` with `details.cutoff_at`. Admins are exempt
  but must give a reason. Changing the setting applies to existing bookings too.
- Someone else's booking is `404 BOOKING_NOT_FOUND` on every call.
- `409 BOOKING_STATE_CHANGED` means another request changed it at the same
  moment (say, the admin confirmed while the customer cancelled). Reload and
  look again; exactly one of the two wins (ADR 0008).
- Cancelling frees the time straight away for other customers.

**History: `GET /bookings/{id}/history`** returns every status change, oldest
first (not paginated; a booking has a handful):

```json
[
  {"from_status": null, "to_status": "pending", "actor": {"id": 3, "role": "customer", "name": "Ali"}, "reason": null, "created_at": "2026-10-01T07:00:00Z"},
  {"from_status": "pending", "to_status": "confirmed", "actor": {"id": 1, "role": "admin", "name": "Owner"}, "reason": null, "created_at": "2026-10-01T09:12:00Z"}
]
```

`actor` is `null` when the system acted. Same visibility as the booking: someone
else's is `404 BOOKING_NOT_FOUND`; admins can read any.

**Calendar: `GET /bookings/{id}/ics`** downloads the booking as an RFC 5545
file (`Content-Type: text/calendar`, `Content-Disposition: attachment;
filename="booking-7.ics"`) that any calendar app can import:

```bash
curl localhost:8000/api/v1/bookings/7/ics -H "Authorization: Bearer $TOKEN" -o booking-7.ics
```

```text
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Navbat//Booking//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
UID:booking-7@navbat
DTSTAMP:20261001T070005Z
DTSTART:20261005T050000Z
DTEND:20261005T053000Z
SUMMARY:Haircut with Jasur
LOCATION:Navbat Barbers
DESCRIPTION:Haircut with Jasur\nNote: Short\, on the sides
STATUS:TENTATIVE
END:VEVENT
END:VCALENDAR
```

Times are UTC (`Z`); the calendar shows them in the viewer's own zone. Lines
end in CRLF, text is escaped and long lines are folded. `STATUS` is `TENTATIVE`
(pending), `CONFIRMED` (confirmed or completed) or `CANCELLED`; `UID` stays the
same, so importing again updates the entry instead of duplicating it. Same
visibility as the booking: someone else's is `404 BOOKING_NOT_FOUND`, no token
is `401`. In the browser the booking page (`/me/bookings/{id}`) has an "Add to
calendar" link to the same file.

**Admin: `GET /bookings/all`** lists everyone's bookings, soonest start first,
paginated. Filters: `status`, `provider_id`, `customer_id`, and `date_from` /
`date_to` (calendar days on the business's clock, both inclusive; a booking
matches when it *starts* on one of those days). Customers get `403`.
`GET /bookings` stays "my own bookings" for everyone, admins included.

Each item here also has `stale_pending`: `true` for a booking still `pending`
after its start time. It can no longer be confirmed; cancel it. With no
`reason`, an admin's cancel of such a booking records "not confirmed in time".
There is no background job doing this for you.

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
| `TOO_MANY_ATTEMPTS` | 429 | Login: too many failed attempts for this IP and email; wait `Retry-After` seconds |
| `CSRF_FAILED` | 403 | Cookie-authenticated unsafe request without a matching `X-CSRF-Token` header / `csrf_token` field (Bearer requests are exempt) |
| `ACCOUNT_INACTIVE` | 401 | The account was deactivated (at login only once the password was right; on any request with a token) |
| `EMAIL_TAKEN` | 409 | Registration: that email already has an account |
| `INVALID_TIMEZONE` | 422 | Settings: the timezone is not an IANA name such as `Asia/Tashkent` |
| `GRANULARITY_CONFLICT` | 409 | Settings: an active service's duration is not a multiple of the new slot granularity; `details.services` lists them |
| `DURATION_NOT_ALIGNED` | 422 | A service's duration is not a multiple of the slot granularity; `details` has both numbers |
| `UNKNOWN_SERVICE` | 422 | Setting a provider's services: an id is not an existing, active service; `details.service_ids` lists them |
| `MISALIGNED_TIME` | 422 | Availability: a start or end time is not a multiple of the slot granularity; `details` has `field` and `slot_granularity_minutes` |
| `INVALID_TIME_RANGE` | 422 | Availability: an edit leaves `end_time` at or before `start_time`, or an exception with only one of its two times |
| `DATE_OUT_OF_RANGE` | 422 | Slots: the date is before today or beyond the booking horizon (business timezone); `details.earliest`, `details.latest` |
| `PROVIDER_DOES_NOT_OFFER_SERVICE` | 422 | Slots: the chosen provider does not perform that service; `details` has both ids |
| `SERVICE_INACTIVE` | 422 | Booking: the service is deactivated |
| `PROVIDER_INACTIVE` | 422 | Booking: the provider is deactivated |
| `START_IN_PAST` | 422 | Booking: the start is before now |
| `INSIDE_LEAD_TIME` | 422 | Booking: the start is sooner than the minimum lead time; `details.earliest` |
| `BEYOND_HORIZON` | 422 | Booking: the start is at or past the booking horizon; `details.before` |
| `OUTSIDE_AVAILABILITY` | 422 | Booking: the provider is not working for the whole service at that time (weekly rules and exceptions applied) |
| `NOT_ALIGNED` | 422 | Booking: the start is not on the slot grid measured from the window start |
| `BOOKING_NOT_FOUND` | 404 | No such booking, or it belongs to someone else (admins see any) |
| `SLOT_TAKEN` | 409 | Booking: the provider already has a pending or confirmed booking overlapping that time |
| `CUSTOMER_OVERLAP` | 409 | Booking: you already have a pending or confirmed booking overlapping that time |
| `DATE_IN_PAST` | 422 | Availability exception: the date is before today in the business timezone; `details.today` |
| `AVAILABILITY_EXCEPTION_EXISTS` | 409 | Availability exception: the provider already has one for that date; `details.exception_id` |
| `AVAILABILITY_OVERLAP` | 409 | Availability: the window overlaps another rule of the provider on that weekday; `details.conflicting_rule` |
| `FORBIDDEN` | 403 | Logged in, but the endpoint needs the admin role (or a generic framework 403) |
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
Every list takes `limit` (default 20, 1–100) and `offset` (default 0, ≥ 0), and
returns `{"items": [...], "total": N, "limit": 20, "offset": 0}`. `total` counts
all matching items, not just this page. An out-of-range `limit` or `offset` is
`422 VALIDATION_ERROR`; an `offset` past the end is an empty `items` list.
Lists are always sorted in a fixed order, so pages never overlap.

## Times and timezones
_P4.1._ All datetimes are ISO 8601 with an offset; naive datetimes are
rejected.
