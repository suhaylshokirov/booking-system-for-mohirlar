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
`services/booking.create_booking` (P6.2). The router only authenticates and
calls it; the request's session commits when the handler returns.

```mermaid
sequenceDiagram
    participant C as Customer
    participant R as Router
    participant S as booking.create_booking
    participant DB as PostgreSQL

    C->>R: POST /bookings
    R->>S: create_booking(customer, service, provider, start_at, now)
    S->>DB: load service, provider, settings, availability
    S->>S: booking_rules.validate_booking_start (422 on failure)
    S->>DB: pre-check overlap (provider, then customer)
    alt pre-check finds a clash
        S-->>C: 409 SLOT_TAKEN / CUSTOMER_OVERLAP
    else looks free
        S->>DB: SAVEPOINT; INSERT booking (pending) + booking_events
        alt a concurrent request won the race
            DB-->>S: SQLSTATE 23P01 (constraint name)
            S->>DB: ROLLBACK TO SAVEPOINT
            S-->>C: 409 SLOT_TAKEN (no_provider_overlap) / CUSTOMER_OVERLAP (no_customer_overlap)
        else inserted
            DB-->>S: ok
            S-->>R: booking
            R-->>C: 201 Created (commit)
        end
    end
```

The pre-check is only for a friendly message; the exclusion constraint is the
guarantee, because two requests can pass the pre-check at the same moment.

## Components
_P6.5 / P11.4._ Component diagram.

## Time model
_P4.1._ Three rules (ADR 0006):

- **Storage is UTC.** Every timestamp is `timestamptz`; the API rejects
  datetimes without an offset (`UtcDatetime` in `app/schemas/types.py`, 422) and
  converts any offset it accepts to UTC.
- **Availability is local.** Working hours are `time` / `date` values in the one
  business timezone (`business_settings.timezone`). `app/core/timezones.py` is
  the only place that turns them into instants:
  `local_to_utc`, `local_window_to_utc(day, start, end, tz)`,
  `local_day_bounds_utc(day, tz)` and `utc_to_local`.
- **Ranges are half-open `[start, end)`**, so a day's bounds are
  `[local midnight, next local midnight)` and neighbouring days tile exactly.

A local date is not a UTC date: 02:00 on 5 October in Tashkent is 21:00 UTC on
the 4th, so "bookings on the 5th" is always a query on `local_day_bounds_utc`,
never on `start_at::date`.

**DST policy** (Tashkent has none; this matters for other zones):

| Wall-clock time | Example (`Europe/Berlin`) | Result |
|---|---|---|
| Inside a spring-forward gap | 02:30 on 2026-03-29 does not exist | Moved forward to the first instant that exists: 03:00 CEST (01:00 UTC) |
| Inside a fall-back overlap | 02:30 on 2026-10-25 happens twice | The first occurrence (`fold=0`, summer time: 00:30 UTC) |

A window lying wholly inside a gap collapses to nothing (start == end) and
yields no slots. A window across a gap is an hour shorter than its wall-clock
length, and across an overlap an hour longer. Days are 23 or 25 hours long.

## Slot algorithm
_P5.1._ Slots are computed on request, never stored (ADR 0002). The pure part
lives in `app/services/slots.py` and does no I/O and no clock reads.

1. `build_windows_for_date(rules, exception, date, tz)` gives the provider's
   working windows for one local date as UTC `[start, end)` pairs. An exception
   replaces the weekly rules (day off = no windows; custom hours = one window).
2. `compute_slots(windows, busy, duration, granularity, now, lead_time,
   horizon_end)` steps candidate starts by `granularity` from each window start
   and keeps a candidate iff:
   - `[start, start + duration)` fits entirely inside the window;
   - it overlaps no busy interval (half-open, so back-to-back is fine);
   - `start >= now + lead_time` (inclusive) and `start < horizon_end`.
3. The result is sorted, de-duplicated UTC datetimes.

The grid is advisory. Two customers can be shown the same slot; the exclusion
constraint decides who gets it (ADR 0001). P5.2 loads the inputs; P6.1 reuses
the same rules to validate a requested start, so grid and validator agree.

## Booking lifecycle (state machine)
_P7.1._ `app/services/booking_state.py` is the only place that says which
status changes are legal. `check_transition` is pure (no DB, no clock); P7.2
applies an allowed change with a guarded UPDATE and writes the history event.

```mermaid
stateDiagram-v2
    [*] --> pending: customer books
    pending --> confirmed: admin, before start
    pending --> cancelled: customer before start / admin any time
    confirmed --> cancelled: customer until start - cutoff / admin before start + reason
    confirmed --> completed: admin, after end_at
    cancelled --> [*]
    completed --> [*]
```

| From | To | Who | Condition | Error otherwise |
|---|---|---|---|---|
| pending | confirmed | admin | `now < start_at` | `INVALID_TRANSITION` |
| pending | cancelled | own customer | `now < start_at` | `CANCELLATION_CUTOFF_PASSED` |
| pending | cancelled | admin | none. Clears a *stale pending* booking (start passed): flagged in the admin list, reason defaults to "not confirmed in time" (P7.7) | |
| confirmed | cancelled | own customer | `now <= start_at - cutoff` | `CANCELLATION_CUTOFF_PASSED` |
| confirmed | cancelled | admin | `now < start_at`, non-blank reason | `INVALID_TRANSITION` / `REASON_REQUIRED` |
| confirmed | completed | admin | `now >= end_at` | `TOO_EARLY_TO_COMPLETE` |

Every other (from, to) pair, and any role not listed, is `INVALID_TRANSITION`
(409). The cutoff comes from `business_settings.cancellation_cutoff_hours`.

**Applying a transition (`booking.transition`, P7.2).** Load the booking as the
actor (404 if not theirs), `check_transition`, then
`UPDATE bookings SET status = :to WHERE id = :id AND status = :expected`.
Zero rows updated means someone else changed it first: 409
`BOOKING_STATE_CHANGED`, and no event is written. Otherwise a `booking_events`
row (`from_status`, `to_status`, actor, reason) is inserted in the same
transaction, and a cancel also stores `cancelled_by_id` and `cancel_reason`.
See ADR 0008.

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

**Login rate limiting (`app/core/rate_limit.py`, `services/auth.login`, P2.5).**
A sliding window of failed attempts per (client IP, email), checked before the
password is verified. The store is an in-process dictionary behind a
three-method interface (`retry_after`, `record_failure`, `reset`), so a shared
store could replace it; the trade-off is that it resets on restart and is not
shared between instances. See `docs/api.md` for the exact behaviour.

**In the browser (`app/web/auth.py`, P8.2).** `/login`, `/register` and
`POST /logout` validate with the same schemas and call the same service
functions as `/api/v1/auth`, so the rules and the rate limit are shared; only
the answer differs (a re-rendered form or a 303 redirect instead of JSON).
Details worth knowing:

- Login and register are posted before any login cookie exists, so they use
  the always-on `require_csrf`; `render()` gives every visitor a CSRF cookie on
  their first page, and a successful login issues a fresh one.
- `next` goes through `safe_next_path` (`app/web/redirects.py`): only a path
  on this site, never another host (open-redirect defence).
- A page GET that raises 401 redirects to `/login?next=<that page>`
  (`app/web/errors.py`), so any page that needs an account just takes
  `CurrentUser`.
- A re-rendered form keeps the email but never the password.

## Why the web UI and the API share services
_P8.1. Decision: [ADR 0004](decisions/0004-server-rendered-ui.md)._

The browser UI is server-rendered Jinja2 served by the same FastAPI app.
`app/web/` routers are as thin as `app/api/v1/` ones: they call the same
service functions and hand the result to a template. So a rule (slot
availability, the double-booking check, a status transition) exists once, and
the pages cannot disagree with the API.

| Piece | Where | Job |
|---|---|---|
| Templates | `app/templates/` | `base.html` (layout, header, flash notice, confirm dialog), one file per page, `_partials/` for fragments JS swaps in. Formatting only |
| Rendering | `app/web/templating.py` | `render()` adds the shared context (CSRF token, current user, flash notice) and clears the flash cookie |
| Current user | `app/web/deps.py` | `load_current_user`, attached to every web router in `app/main.py`, so the header always knows who is looking |
| Form wording | `app/web/forms.py` | Turns a schema's validation error into one message per field, in the form's own words |
| Formatting | `app/web/formatting.py` | Jinja filters `money` (`60 000 UZS`, integer amounts, never rounded) and `duration` (`1 h 15 min`) |
| Paging | `app/web/paging.py` | `?page=N` for web lists on top of the services' limit/offset; a page past the end is 404 |
| Error pages | `app/web/errors.py` | Wording for the HTML error page; `app/core/errors.py` calls it for any path outside `/api/` |
| Styles | `app/static/css/app.css` | Every token (light + dark) and shared component. A page stylesheet may add components, never restyle these |
| Behaviour | `app/static/js/app.js` | One IIFE: theme toggle, mobile nav, confirm dialog, submit-once, inline email check, menu closing. Enhancement only |

**Which errors are pages.** `/api/*` always answers with the JSON envelope,
whoever asks. Every other path is a page a person reads, so a 404, a bad link
(422), a CSRF failure (403) or a crash (500) renders `error.html`. Our own
`AppError` messages are shown as written; a 500 never shows the exception.

**Flash notices.** A redirect after a form post ("Booking requested") leaves a
short-lived `flash` cookie holding a *key* into `FLASH_MESSAGES`, never text,
so a tampered cookie cannot put words on the page. The page that shows it
deletes the cookie.

**Without JavaScript.** Every page is complete HTML and every form posts
normally. An inline script in `<head>` adds `html.has-js` before first paint
(and applies the saved theme, to avoid a white flash); CSS shows JS-only
controls (theme and menu toggles) only under that class, so no dead buttons
appear when JS is off.

**Booking in the browser (`app/web/booking.py`, P8.4).** Three steps over the
same services: the picker (`GET /book/{id}`, public) shows `slot_query.get_slots`
as radio tiles grouped by person and part of the day; the confirm step
(`GET /book/{id}/confirm`, signed in) re-checks that the time is still free and
shows the ticket with the cancellation deadline from
`booking_state.cancellation_cutoff_at`; `POST /book/{id}` calls
`booking.create_booking`. A lost race (`SLOT_TAKEN`, `CUSTOMER_OVERLAP`) or a
broken booking rule re-renders the picker for that day with the reason, never an
error page. The live picker asks the same URL with `X-Requested-With` and gets
only `_partials/slot_grid.html`; responses carry `Vary: X-Requested-With`.

**CSRF.** HTML forms are covered by the same app-wide `csrf_protect`
dependency as the API; forms carry the token in a `csrf_token` hidden field.

**Visual language.** Lime means *committed or selected*: the chosen slot, a
Confirmed status, the page you're on, the button that books. Everything else
is ink on paper. Status chips always spell the status and add a shape (ring,
dot, dash), so colour is never the only signal.

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
