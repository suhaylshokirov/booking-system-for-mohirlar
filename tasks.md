# tasks.md — Navbat work queue

Work top to bottom, one task per commit (see `CLAUDE.md` §6 Definition of Done
and §7). Task IDs are stable; if a task is split, use suffixes (`P6.2a`).

**Deadline: 2026-10-02 04:16 UTC.** All times below are UTC (Tashkent = UTC+5).

## Time checkpoints

| By (UTC) | Tashkent | Done |
|---|---|---|
| Sep 29, 20:00 | Sep 30, 01:00 | P0–P2 (bootstrap, database, auth) |
| Sep 30, 18:00 | Sep 30, 23:00 | P3–P6 — **the graded core is safe at this point** |
| Oct 1, 12:00 | Oct 1, 17:00 | P7–P9 (lifecycle, customer UI, admin UI) |
| Oct 1, 18:00 | Oct 1, 23:00 | P10 (bonuses) |
| Oct 1, 23:00 | Oct 2, 04:00 | P11 — deployed, docs final |
| Oct 2, 02:00 | Oct 2, 07:00 | **Latest** the owner submits (buffer until 04:16) |

If behind: cut from the bottom of the bonus list first (email → calendar →
cancellation policy → timezone polish → admin dashboard polish), then UI
polish. Never cut tests, docs, or a minimum requirement.

## Requirement coverage

Every assignment item → the tasks that deliver it. The README feature
checklist (P11.4) is verified against this table.

### Minimum requirements

| Requirement | Tasks |
|---|---|
| Create a service (name, description, duration, price) | P1.2, P3.2, P9.2 |
| Create providers / employees | P1.2, P3.3, P9.3 |
| Set availability | P1.2, P4.1–P4.4, P9.4 |
| User can see available time slots | P5.1–P5.3, P8.4 |
| User can book | P6.1–P6.3, P8.4 |
| Booking statuses: Pending, Confirmed, Cancelled, Completed | P1.3, P7.1–P7.3 |
| No double booking | P1.4, P1.5, P6.2, P6.4, P7.6 |
| Backend API | P0.3, P2–P7 (every `api/v1` router) |
| Authentication | P2.1–P2.6, P8.2 |
| Basic validation | P3.2, P3.3, P4.2, P4.3, P6.1 (+ Pydantic schemas throughout) |
| Booking history | P1.3, P7.2, P7.5, P8.5 |

### Expected to show

| Item | Tasks |
|---|---|
| Edge cases discovered and handled (e.g. simultaneous booking) | P6.4, P7.6, `docs/edge-cases.md` updated in every task |
| AI usage explained, code understood, architecture justified | `AI_USAGE.md` per phase, ADRs, phase summaries, P11.5 |

### Bonuses (in priority order)

| # | Bonus | Tasks |
|---|---|---|
| 1 | Tests (treated as mandatory) | every task; P0.5, P0.6 |
| 2 | API documentation (Swagger + examples + guide) | P0.3, examples in every API task, P10.4 |
| 3 | Docker | P0.4 |
| 4 | Admin dashboard | P9.1–P9.6 |
| 5 | Timezone support | P4.1, P10.3 |
| 6 | Cancellation policy | P7.4 |
| 7 | Calendar integration (`.ics`) | P10.1 |
| 8 | Email notification (pluggable notifier, console/outbox) | P10.2 |

### Deliverables

| Deliverable | Tasks |
|---|---|
| Working application | all |
| Public GitHub repo, step-by-step history | every commit; push per phase |
| README with setup instructions | P0.1 (skeleton), P0.6, P11.4 |
| Architecture explanation | `docs/architecture.md`, ADRs — P1.7, P6.6, P7.7, P11.4 |
| Edge cases explanation | `docs/edge-cases.md` — every task, final pass P11.4 |
| Deployed / demo URL | P11.1, P11.2 |

---

## P0 — Bootstrap

### P0.1 — Repository skeleton, CLAUDE.md, tasks.md, doc skeletons
- [x] Status
- Goal: a repo a reviewer can orient in before any code exists.
- Requirement(s) served: deliverables (README, architecture, edge cases), "how AI was used"
- Acceptance criteria: directory tree per `CLAUDE.md` §4; `CLAUDE.md`; this file with coverage matrix and checkpoints; skeletons of `README.md`, `AI_USAGE.md`, `docs/{architecture,database,edge-cases,api}.md`, `docs/decisions/README.md`; `.gitignore`; `.env.example`.
- Tests: none (no code).
- Docs to update: all of the above are the docs.
- Edge cases covered: —

### P0.2 — Python project and tooling
- [x] Status
- Goal: an installable project with pinned dependencies and one lint/format config.
- Requirement(s) served: Backend API (foundation)
- Acceptance criteria: `pyproject.toml` with pinned runtime deps (fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, psycopg[binary], alembic, jinja2, python-multipart, pwdlib[argon2], pyjwt) and a `dev` extra (pytest, httpx, ruff); ruff config (line length, rule set incl. `I`, `B`, `UP`); `pip install -e ".[dev]"` works on Python 3.12; `ruff check .` passes.
- Tests: `pytest` runs (zero tests collected is fine at this point).
- Docs to update: README "Local development"; CLAUDE.md commands if anything changed.
- Edge cases covered: —

### P0.3 — App factory, settings, clock, error envelope, health endpoint
- [x] Status
- Goal: the minimal running app with the cross-cutting pieces every later task depends on.
- Requirement(s) served: Backend API
- Acceptance criteria:
  - `app/core/config.py`: `Settings` via pydantic-settings, every var in `.env.example`; `get_settings()` cached.
  - `app/core/clock.py`: `Clock` protocol, `SystemClock` (UTC, tz-aware), FastAPI dependency `get_clock`; a `FrozenClock` for tests.
  - `app/core/errors.py`: `AppError(code, message, status, details)` base + handlers so **every** error — our own, `RequestValidationError` (422), `HTTPException` (401/404/405…), unhandled (500) — renders `{"error": {"code", "message", "details"}}`.
  - `app/main.py`: `create_app()` factory; OpenAPI title/description/tags; `GET /api/v1/health` → `{"status": "ok", "database": "ok"}` (runs `SELECT 1`; 503 `DATABASE_UNAVAILABLE` if it fails).
- Tests: unit — error envelope for AppError / validation error / unknown route; FrozenClock. Integration — health 200 against the test DB.
- Docs to update: `docs/api.md` error envelope section; `docs/architecture.md` layers.
- Edge cases covered: consistent error shape for framework-level errors (404 route, 405, malformed JSON).

### P0.4 — Docker Compose and Dockerfile
- [x] Status
- Goal: `docker compose up --build` gives a running app + Postgres with no other setup.
- Requirement(s) served: Bonus 3 (Docker), README quick start
- Acceptance criteria: `Dockerfile` (python:3.12-slim, non-root user, deps layer cached); `docker-compose.yml` with `db` (postgres:16, healthcheck, volume, init script creating `navbat_test`) and `app` (depends on healthy db, runs `alembic upgrade head` then uvicorn); `.dockerignore`. Health endpoint answers from the container.
- Tests: manual — `docker compose up --build`, `curl localhost:8000/api/v1/health`; the test DB is reachable for pytest from the host.
- Docs to update: README "Quick start".
- Edge cases covered: app start before DB ready (healthcheck + depends_on condition).

### P0.5 — Test harness against real Postgres
- [x] Status
- Goal: fast, isolated tests on the real engine.
- Requirement(s) served: Bonus 1 (tests)
- Acceptance criteria: `tests/conftest.py` — engine on `TEST_DATABASE_URL`, schema built once per session **by running Alembic migrations** (so the exclusion constraints under test are the real ones); per-test connection + outer transaction + `join_transaction_mode="create_savepoint"` rolled back after each test; `client` fixture (TestClient with DB and clock dependencies overridden); `frozen_clock` fixture; a separate `committing_db` fixture for concurrency tests that truncates tables afterwards. Refuse to run if `TEST_DATABASE_URL` equals `DATABASE_URL`.
- Tests: the P0.3 tests run through these fixtures; a test proving rollback isolation (row inserted in one test is absent in the next).
- Docs to update: README "Running tests"; `docs/architecture.md` testing note.
- Edge cases covered: tests accidentally wiping the dev database (guard).

### P0.6 — CI and README bootstrap
- [x] Status
- Goal: every push is linted and tested; the reviewer sees a green badge.
- Requirement(s) served: Bonus 1, git history quality
- Acceptance criteria: `.github/workflows/ci.yml` — Python 3.12, `postgres:16` service, `pip install -e ".[dev]"`, `ruff check`, `ruff format --check`, `pytest`; badge in README; push P0 and confirm the run is green.
- Tests: CI run itself.
- Docs to update: README badge, env-var table, `AI_USAGE.md` P0 entry.
- Edge cases covered: —

---

## P1 — Database

### P1.1 — SQLAlchemy base, session and Alembic wiring
- [x] Status
- Goal: one engine/session setup used by app, scripts, tests, and migrations.
- Requirement(s) served: Backend API (foundation)
- Acceptance criteria: `app/core/db.py` (engine from settings, `SessionLocal`, `get_db` dependency that commits/rolls back per request); `app/models/base.py` with a naming convention (so constraint names are predictable — the 23P01 mapping depends on them) and `created_at`/`updated_at` mixin (`timestamptz`, server defaults); `alembic.ini` + `migrations/env.py` reading `DATABASE_URL` from settings; `alembic upgrade head` on an empty DB works; the compose `app` command gets `alembic upgrade head &&` in front of uvicorn (P0.4 deviation); `env.py` uses `config.attributes["connection"]` when given (the P0.5 test harness passes the test DB connection that way).
- Tests: migration upgrade → downgrade → upgrade round-trip on the test DB.
- Docs to update: `docs/database.md` conventions section; ADR 0003 (sync SQLAlchemy).
- Edge cases covered: —

### P1.2 — Catalog, settings and availability models
- [x] Status
- Goal: tables for users, business settings, services, providers, provider↔services, availability rules and exceptions.
- Requirement(s) served: create service; create providers; set availability; authentication
- Acceptance criteria:
  - `users`: email unique **case-insensitively** (unique index on `lower(email)`), `role` enum (`customer`, `admin`), `is_active`.
  - `business_settings`: single row enforced (`id = 1` CHECK); name, timezone, currency, slot_granularity_minutes, min_lead_time_minutes, max_booking_horizon_days, cancellation_cutoff_hours.
  - `services`: `CHECK (duration_minutes > 0)`, `CHECK (price >= 0)`, `is_active`; name length limits.
  - `providers`, `provider_services` (composite PK, FKs `ON DELETE RESTRICT`).
  - `availability_rules`: weekday `0..6` CHECK, `CHECK (end_time > start_time)`, **exclusion constraint** rejecting overlapping rules for the same provider + weekday.
  - `availability_exceptions`: provider, date, nullable start/end (both null = day off, both set = custom hours; CHECK enforces that), unique per (provider, date).
- Tests: in P1.5.
- Docs to update: `docs/database.md` table sections.
- Edge cases covered: overlapping availability rules; negative price; zero duration; email case.

### P1.3 — Booking and booking-event models
- [x] Status
- Goal: the booking record with snapshots, and its audit trail.
- Requirement(s) served: user can book; statuses; booking history
- Acceptance criteria: `bookings` — customer_id, provider_id, service_id, `start_at`/`end_at` (`timestamptz`, `CHECK (end_at > start_at)`), `status` enum (`pending`, `confirmed`, `cancelled`, `completed`), `price_amount` + `duration_minutes` snapshots, notes (length-capped), cancelled_by, cancel_reason; indexes for (customer_id, start_at), (provider_id, start_at), (status). `booking_events` — booking_id, from_status (nullable for creation), to_status, actor_id, reason, created_at; index on (booking_id, created_at).
- Tests: in P1.5.
- Docs to update: `docs/database.md`; ADR 0007 (snapshots).
- Edge cases covered: price/duration changed after booking.

### P1.4 — Initial migration with the exclusion constraints
- [x] Status
- Goal: the schema, with every invariant the database can enforce, written explicitly and commented. (P1.2 already created migration `0001` with `btree_gist` and the availability exclusion — see Deviations log — so this task adds the exclusion constraints as migration `0003`; P1.3 already created the booking tables as `0002`.)
- Requirement(s) served: **No double booking**
- Acceptance criteria: autogenerated migration read line by line and edited; `CREATE EXTENSION IF NOT EXISTS btree_gist`; `no_provider_overlap` and `no_customer_overlap` `EXCLUDE USING gist (… WITH =, tstzrange(start_at, end_at, '[)') WITH &&) WHERE (status IN ('pending','confirmed'))`; the availability-rule overlap exclusion; each with a comment explaining it; downgrade drops them cleanly.
- Tests: in P1.5.
- Docs to update: `docs/database.md` "Constraints"; ADR 0001 (draft), ADR 0006 (half-open ranges + UTC).
- Edge cases covered: double booking at the storage layer; back-to-back allowed by `[)`.

### P1.5 — Database constraint tests
- [x] Status
- Goal: prove the database, on its own, refuses invalid data.
- Requirement(s) served: No double booking; basic validation
- Acceptance criteria / Tests (`tests/integration/test_db_constraints.py`, direct inserts bypassing services):
  - overlapping booking for the same provider → `23P01` naming `no_provider_overlap`
  - overlapping booking for the same customer, different provider → `no_customer_overlap`
  - back-to-back (10:00–10:30, 10:30–11:00) → allowed
  - cancelled / completed booking does not block the slot
  - overlapping availability rules → rejected; adjacent rules → allowed
  - `end_at <= start_at`, negative price, zero duration, bad weekday → CHECK violation
  - duplicate email differing only in case → unique violation
- Docs to update: `docs/edge-cases.md` rows with these test names.
- Edge cases covered: as listed.

### P1.6 — Seed script
- [x] Status
- Goal: one command produces a believable demo business.
- Requirement(s) served: working application; demo
- Acceptance criteria: `python -m scripts.seed` is idempotent (safe to rerun); creates business settings (Asia/Tashkent, UZS, 15-min granularity), ~4 services, ~3 providers with differing service sets, weekly availability, one day-off exception, an admin (from env) and a demo customer, a few bookings in varied statuses with events. Runs in the Docker entrypoint when `SEED_DEMO_DATA=true`.
- Tests: integration — running seed twice leaves the same row counts.
- Docs to update: README quick start (demo credentials).
- Edge cases covered: re-running seed.

### P1.7 — Database documentation
- [x] Status
- Goal: `docs/database.md` complete for P1.
- Requirement(s) served: architecture explanation; database design (review focus)
- Acceptance criteria: Mermaid ER diagram; every table's purpose; every constraint and index with **why**; exclusion constraints in plain language; snapshot rationale; ADR 0001 written (context · decision · alternatives: app-level lock, `SELECT … FOR UPDATE`, serializable isolation, stored slot rows · consequences).
- Tests: —
- Docs to update: `docs/database.md`, ADRs 0001, 0006, 0007, `AI_USAGE.md` P1 entry.
- Edge cases covered: —

---

## P2 — Authentication

### P2.1 — Password hashing and JWT primitives
- [x] Status
- Goal: small, fully tested security helpers.
- Requirement(s) served: Authentication
- Acceptance criteria: `app/core/security.py` — `hash_password`/`verify_password` (pwdlib Argon2), `create_access_token(user_id, now)` (HS256, `sub`, `iat`, `exp`), `decode_access_token` raising a domain error on expired/tampered/malformed tokens. Clock injected (no `now()` inside).
- Tests: unit — round-trip; wrong password; expired token (frozen clock); tampered signature; wrong algorithm (`none`) rejected.
- Docs to update: `docs/architecture.md` auth section.
- Edge cases covered: expired / tampered JWT; `alg=none`.

### P2.2 — Register, login, logout, me
- [x] Status
- Goal: customer accounts over the API.
- Requirement(s) served: Authentication; basic validation
- Acceptance criteria: `services/auth.py` + `api/v1/auth.py`. `POST /auth/register` (email normalised: trimmed + lowercased; password 8–128 chars; full_name 1–100) → 201, always role `customer`, 409 `EMAIL_TAKEN`. `POST /auth/login` → sets HttpOnly `SameSite=Lax` cookie (`Secure` in production) **and** returns `{access_token, token_type}` for Bearer use; wrong email and wrong password give the same 401 `INVALID_CREDENTIALS` (no user enumeration). `POST /auth/logout` clears cookies. `GET /auth/me`. OpenAPI examples on each.
- Tests: integration — happy paths; duplicate email in different case; weak password 422; login failure messages identical; me without auth 401.
- Docs to update: `docs/api.md` auth how-to; edge-case rows.
- Edge cases covered: email case sensitivity; user enumeration.

### P2.3 — Current-user dependency and roles
- [x] Status
- Goal: one way to know who is calling, from cookie or Bearer.
- Requirement(s) served: Authentication
- Acceptance criteria: `get_current_user` (Bearer header wins, else cookie; loads the user from DB each request so deactivation takes effect immediately → 401 `ACCOUNT_INACTIVE`), `get_optional_user`, `require_admin` (403 `FORBIDDEN`).
- Tests: integration — Bearer; cookie; deactivated user with a valid token → 401; customer on admin route → 403; anonymous → 401.
- Docs to update: `docs/api.md`; edge-case rows.
- Edge cases covered: deactivated user with a valid token.

### P2.4 — CSRF protection for cookie-authenticated requests
- [x] Status
- Goal: cookie auth can't be abused cross-site.
- Requirement(s) served: Authentication (security)
- Acceptance criteria: double-submit cookie — login sets a non-HttpOnly `csrf_token` cookie; unsafe methods (POST/PUT/PATCH/DELETE) **authenticated by cookie** must send a matching `X-CSRF-Token` header or `csrf_token` form field (constant-time compare) else 403 `CSRF_FAILED`; Bearer-authenticated requests are exempt (not sent automatically by browsers). Login/register forms get a pre-session CSRF cookie too.
- Tests: integration — cookie POST without token 403; with token OK; Bearer without token OK; mismatched token 403.
- Docs to update: `docs/api.md`; ADR 0005 (JWT in HttpOnly cookie + Bearer, CSRF).
- Edge cases covered: CSRF.

### P2.5 — Login rate limiting
- [x] Status
- Goal: slow down password guessing.
- Requirement(s) served: Authentication (security)
- Acceptance criteria: sliding window of **failed** attempts per (client IP, email), in-process store behind a small interface; over the limit → 429 `TOO_MANY_ATTEMPTS` with `Retry-After`; success clears the counter. Limitation (single process, resets on restart) documented.
- Tests: unit on the limiter with a frozen clock; integration — N failures then 429, window expiry restores access.
- Docs to update: `docs/api.md`; edge-case row; README known limitations.
- Edge cases covered: login brute force.

### P2.6 — Create-admin CLI
- [x] Status
- Goal: the first admin exists without an open "become admin" endpoint.
- Requirement(s) served: Authentication
- Acceptance criteria: `python -m scripts.create_admin --email --password` (falls back to `ADMIN_EMAIL`/`ADMIN_PASSWORD`); idempotent (promotes/updates an existing user); refuses weak passwords.
- Tests: integration — creates admin; rerun doesn't duplicate.
- Docs to update: README; CLAUDE.md commands; `AI_USAGE.md` P2 entry; push.
- Edge cases covered: registration can never create an admin.

---

## P3 — Catalog

### P3.1 — Business settings
- [x] Status
- Goal: the single source for timezone, currency and booking policy numbers.
- Requirement(s) served: Set availability (timezone); bonus 5, 6 (foundation)
- Acceptance criteria: `GET /settings` (public subset), `PATCH /settings` (admin). Validation: timezone is a valid IANA name (`zoneinfo`), granularity in {5, 10, 15, 20, 30, 60}, lead time ≥ 0, horizon 1–365 days, cutoff ≥ 0. Changing granularity is rejected if an active service's duration isn't a multiple of it (`GRANULARITY_CONFLICT`).
- Tests: integration — read; admin update; invalid tz 422; customer 403.
- Docs to update: `docs/api.md`; edge-case rows.
- Edge cases covered: invalid timezone; granularity change vs existing durations.

### P3.2 — Services CRUD
- [x] Status
- Goal: the admin manages what can be booked.
- Requirement(s) served: **Create a service (name, description, duration, price)**; basic validation
- Acceptance criteria: public `GET /services` (active only, paginated), `GET /services/{id}` (404 if inactive for non-admins); admin `POST`, `PATCH`, `POST /services/{id}/deactivate` and `/activate`; admin list can include inactive. Validation: name 1–100, description ≤ 2000, duration > 0, ≤ 480, multiple of granularity (`DURATION_NOT_ALIGNED`), price integer ≥ 0. No hard delete. Creating, editing the duration of, and *activating* a service read the settings row with `get_business_settings(db, for_update=True)` (see P3.1) so a concurrent granularity change cannot leave it misaligned.
- Tests: integration — each endpoint; validation failures; deactivated service hidden publicly; authz matrix.
- Docs to update: `docs/api.md`; pagination conventions; edge-case rows.
- Edge cases covered: negative price; zero duration; oversized input; deactivating a service with future bookings (bookings kept).

### P3.3 — Providers CRUD and offered services
- [x] Status
- Goal: the admin manages staff and what each offers.
- Requirement(s) served: **Create providers / employees**
- Acceptance criteria: public `GET /providers?service_id=` (active only) and `GET /providers/{id}` (includes offered services); admin `POST`, `PATCH`, deactivate/activate, `PUT /providers/{id}/services` (replace set; unknown/inactive service ids → 422 `UNKNOWN_SERVICE`).
- Tests: integration — CRUD; service filter; replace offered set; authz.
- Docs to update: `docs/api.md`; edge-case rows.
- Edge cases covered: provider deactivated with future bookings.

### P3.4 — Pagination helper
- [x] Status
- Goal: one paging convention for every list.
- Requirement(s) served: Backend API
- Acceptance criteria: `limit` (default 20, max 100) + `offset`; response `{items, total, limit, offset}`; out-of-range `limit` → 422. Used by services/providers now and bookings later.
- Tests: unit/integration — defaults, cap, total.
- Docs to update: `docs/api.md` pagination; `AI_USAGE.md` P3 entry.
- Edge cases covered: unbounded list requests.

---

## P4 — Availability

### P4.1 — Timezone conversion module
- [x] Status
- Goal: the **one** place local wall-clock time becomes UTC.
- Requirement(s) served: Set availability; see slots; bonus 5
- Acceptance criteria: `app/core/timezones.py` — `local_window_to_utc(date, start_time, end_time, tz)`, `utc_to_local(dt, tz)`, `local_day_bounds_utc(date, tz)`. DST policy (documented): a wall-clock time in a spring-forward gap is shifted forward to the first valid instant; an ambiguous fall-back time takes the first occurrence (`fold=0`). Schemas reject naive datetimes (`AwareDatetime`).
- Tests: unit — Tashkent (no DST); `Europe/Berlin` spring-forward and fall-back days; local-date boundary vs UTC date (Tashkent 02:00 local is the previous UTC day).
- Docs to update: `docs/architecture.md` time model; ADR 0006.
- Edge cases covered: DST gap/overlap; date boundary; naive datetimes.

### P4.2 — Weekly availability rules
- [x] Status
- Goal: the admin sets each provider's working hours.
- Requirement(s) served: **Set availability**
- Acceptance criteria: admin `GET/POST /providers/{id}/availability/rules`, `PATCH/DELETE /…/rules/{rule_id}`; also public `GET` of a provider's rules. Validation: weekday 0–6 (Mon=0), times aligned to granularity, `end > start`; overlap with an existing rule → 409 `AVAILABILITY_OVERLAP` (service pre-check + DB exclusion as backstop).
- Tests: integration — create, list, overlap rejected, adjacent allowed, misaligned 422.
- Docs to update: `docs/api.md`; edge-case rows.
- Edge cases covered: overlapping rules; misaligned times.

### P4.3 — Availability exceptions (days off / custom hours)
- [x] Status
- Goal: holidays and one-off schedule changes.
- Requirement(s) served: **Set availability**
- Acceptance criteria: admin CRUD under `/providers/{id}/availability/exceptions`; an exception for a date **replaces** that date's weekly rules — either closed (no times) or one custom window. One per (provider, date) → 409 on duplicate. Past dates rejected.
- Tests: integration — day off, custom hours, duplicate, past date.
- Docs to update: `docs/api.md`; `docs/database.md` exception semantics.
- Edge cases covered: exception on a date with existing bookings.

### P4.4 — Conflicts after availability changes
- [x] Status
- Goal: editing availability never silently drops bookings; the admin sees what no longer fits.
- Requirement(s) served: Set availability; product thinking
- Acceptance criteria: availability edits never modify bookings. `services/availability.find_conflicts(provider_id, now)` lists future active bookings that no longer fit inside availability; exposed as `GET /providers/{id}/availability/conflicts` (admin) and returned as `details.conflicts` (warning, not error) in rule/exception write responses.
- Tests: integration — remove a rule under a booking → conflict listed; booking still exists.
- Docs to update: edge-case row; `AI_USAGE.md` P4 entry; push.
- Edge cases covered: availability edited/removed while future bookings exist.

---

## P5 — Slots

### P5.1 — Pure slot algorithm
- [x] Status
- Goal: compute bookable start times with no I/O, so it is exhaustively testable.
- Requirement(s) served: **User can see available time slots**
- Acceptance criteria: `app/services/slots.py`: `compute_slots(windows_utc, busy_utc, duration, granularity, now, lead_time, horizon_end) -> list[datetime]`, plus `build_windows_for_date(rules, exception, date, tz)`. Candidates step by granularity from each window start; a slot is kept iff `[start, start+duration)` fits entirely inside a window, overlaps no busy interval (half-open), `start >= now + lead_time`, and `start < horizon_end`. Result sorted, deduplicated, UTC-aware.
- Tests (unit, `tests/unit/test_slots.py`): empty day; exact window edges; duration not fitting before window end; back-to-back busy intervals; busy interval touching a slot boundary; lead time cut-off; horizon cut-off; day-off exception; custom-hours exception; two windows (split shift); Tashkent date → UTC; `Europe/Berlin` DST days.
- Docs to update: `docs/architecture.md` slot algorithm; ADR 0002 (computed vs stored slots).
- Edge cases covered: duration doesn't fit; back-to-back; past/lead/horizon; DST.

### P5.2 — Slot query service
- [x] Status
- Goal: load exactly the data the pure function needs.
- Requirement(s) served: see available time slots
- Acceptance criteria: `services/slot_query.get_slots(db, service_id, date, provider_id | None, now)` — validates service/provider active and offered (`PROVIDER_DOES_NOT_OFFER_SERVICE`), loads rules/exception/active bookings for the local day, returns slots **grouped by provider**; with no provider, all active providers offering the service.
- Tests: integration — slots shrink after a booking; cancelled booking frees its slot; "any provider" grouping.
- Docs to update: —
- Edge cases covered: inactive service/provider; provider doesn't offer service.

### P5.3 — Slots endpoint
- [x] Status
- Goal: public API for the booking UI.
- Requirement(s) served: see available time slots; backend API
- Acceptance criteria: `GET /slots?service_id=&date=YYYY-MM-DD&provider_id=` → `{date, timezone, service, providers: [{provider, slots: [{start_at, end_at}]}]}`; date outside `[today, today+horizon]` → 422 `DATE_OUT_OF_RANGE`; examples in OpenAPI.
- Tests: integration — happy path, filters, invalid date, unknown service 404.
- Docs to update: `docs/api.md` curl walkthrough (slots step); `AI_USAGE.md` P5 entry; push.
- Edge cases covered: date out of range.

---

## P6 — Booking creation

### P6.1 — Booking validation rules
- [x] Status
- Goal: every reason a requested slot is invalid, with its own error code, in one module.
- Requirement(s) served: **User can book**; basic validation
- Acceptance criteria: `services/booking_rules.py` (pure, reused by `slots.py` so the grid and the validator can't disagree): `START_IN_PAST`, `INSIDE_LEAD_TIME`, `BEYOND_HORIZON`, `NOT_ALIGNED`, `SERVICE_INACTIVE`, `PROVIDER_INACTIVE`, `PROVIDER_DOES_NOT_OFFER_SERVICE`, `OUTSIDE_AVAILABILITY` (incl. exceptions).
- Tests: unit — one test per code, plus boundaries (exactly at lead time; exactly at window end).
- Docs to update: `docs/api.md` error table; edge-case rows.
- Edge cases covered: past / lead / horizon / misaligned / not offered / inactive / outside availability.

### P6.2 — Create booking (service)
- [x] Status
- Goal: create a pending booking whose uniqueness is guaranteed by Postgres.
- Requirement(s) served: **User can book**; **No double booking**; booking history
- Acceptance criteria: `services/booking.create_booking(db, customer, service_id, provider_id, start_at, notes, now)`: validates (P6.1); computes `end_at` from the service duration; snapshots price and duration; friendly pre-check for overlap; inserts booking + `booking_events` (None → pending) in one transaction; catches `IntegrityError` with SQLSTATE `23P01` and maps by constraint name → `SlotTaken` / `CustomerOverlap` (409). Docstring explains why the pre-check alone is a race.
- Tests: integration — happy path creates event; overlap → 409 `SLOT_TAKEN`; customer overlap → 409 `CUSTOMER_OVERLAP`; snapshot survives a later price change.
- Docs to update: `docs/architecture.md` sequence diagram (incl. constraint path).
- Edge cases covered: price/duration changed after booking.

### P6.3 — Booking endpoints (customer)
- [x] Status
- Goal: book and see your own bookings over the API.
- Requirement(s) served: User can book; booking history; backend API
- Acceptance criteria: `POST /bookings` → 201; `GET /bookings?scope=upcoming|past&status=` (own, paginated); `GET /bookings/{id}` — another customer's booking → **404** `BOOKING_NOT_FOUND`. Admin sees any booking.
- Tests: integration — create/list/detail; IDOR → 404; anonymous → 401; naive datetime → 422.
- Docs to update: `docs/api.md` walkthrough (book step); edge-case rows.
- Edge cases covered: IDOR; naive datetime.

### P6.4 — Concurrency tests (headline)
- [x] Status
- Goal: prove the race condition is closed under real parallelism.
- Requirement(s) served: **No double booking**; "edge cases I discover myself"
- Acceptance criteria / Tests (`tests/concurrency/`, real commits, separate sessions, `threading.Barrier`):
  - `test_n_customers_same_slot_exactly_one_wins` — 10 threads → exactly one 201, nine 409 `SLOT_TAKEN`, one row in DB.
  - `test_same_customer_two_providers_overlapping_one_rejected`.
  - `test_double_submit_same_request_creates_one_booking`.
- Docs to update: `docs/edge-cases.md` (headline section with the timeline of the race).
- Edge cases covered: simultaneous booking; double submit; same customer overlap.

### P6.5 — ADR 0001 and race-condition write-up
- [x] Status
- Goal: the reviewer understands *why* check-then-insert is broken and the constraint isn't.
- Requirement(s) served: architecture explanation; edge cases explanation
- Acceptance criteria: ADR 0001 final; `docs/edge-cases.md` race section with a two-transaction timeline; `docs/architecture.md` "create booking" Mermaid sequence diagram including the 23P01 → 409 path.
- Tests: —
- Docs to update: as above; `AI_USAGE.md` P6 entry; push.
- Edge cases covered: —

---

## P7 — Lifecycle and history

### P7.1 — State machine (pure)
- [x] Status
- Goal: the only definition of legal status transitions.
- Requirement(s) served: **Booking statuses**
- Acceptance criteria: `services/booking_state.py` — a transition table encoding: pending→confirmed (admin, start in future); pending→cancelled (own customer before start, or admin); confirmed→cancelled (own customer before `start − cutoff`; admin before start, reason required); confirmed→completed (admin, after `end_at`); cancelled/completed terminal. `check_transition(booking, to, actor, now, settings)` raises `InvalidTransition` / `CancellationCutoffPassed` / `ReasonRequired` / `TooEarlyToComplete`.
- Tests: unit — every allowed transition and every forbidden (from, to, role) combination, parametrised; boundary at cutoff and at `end_at`.
- Docs to update: `docs/architecture.md` state diagram (Mermaid).
- Edge cases covered: invalid transitions; completing before end; cancelling after cutoff.

### P7.2 — Guarded transitions with events
- [x] Status
- Goal: concurrent transitions can't both succeed; every change is recorded.
- Requirement(s) served: statuses; **booking history**
- Acceptance criteria: `services/booking.transition(...)` — check rules, then `UPDATE bookings SET status=:to … WHERE id=:id AND status=:expected`; rowcount 0 → 409 `BOOKING_STATE_CHANGED`; insert `booking_events` in the same transaction.
- Tests: integration — stale expected status → 409 and no event written.
- Docs to update: `docs/architecture.md`; ADR 0008 (optimistic guarded update vs row locks).
- Edge cases covered: concurrent confirm + cancel.

### P7.3 — Transition endpoints and admin booking list
- [x] Status
- Goal: customers cancel, admins run the day.
- Requirement(s) served: statuses; backend API
- Acceptance criteria: `POST /bookings/{id}/cancel` (customer own / admin, `reason`), `POST /bookings/{id}/confirm`, `POST /bookings/{id}/complete` (admin); `GET /bookings` for admin with filters `status, provider_id, customer_id, date_from, date_to`, paginated.
- Tests: integration — authz matrix per endpoint; filters.
- Docs to update: `docs/api.md` walkthrough (confirm/cancel).
- Edge cases covered: customer cancelling another's booking → 404.

### P7.4 — Cancellation policy
- [x] Status
- Goal: customers can't cancel a confirmed booking at the last minute.
- Requirement(s) served: Bonus 6
- Acceptance criteria: cutoff read from `business_settings.cancellation_cutoff_hours`; error `CANCELLATION_CUTOFF_PASSED` with `details.cutoff_at`; admins exempt (with reason). Public settings expose the policy so the UI can explain it.
- Tests: integration — just before / just after cutoff with frozen clock.
- Docs to update: README feature list; edge-case row.
- Edge cases covered: cancelling after the cutoff.

### P7.5 — Booking history endpoint
- [x] Status
- Goal: the audit trail is visible.
- Requirement(s) served: **Booking history**
- Acceptance criteria: `GET /bookings/{id}/history` → ordered events `{from_status, to_status, actor {id, role, name}, reason, created_at}`; same visibility rule as the booking (IDOR → 404).
- Tests: integration — create → confirm → cancel produces three events in order.
- Docs to update: `docs/api.md`.
- Edge cases covered: —

### P7.6 — Concurrency: confirm vs cancel
- [x] Status
- Goal: prove the guarded update.
- Requirement(s) served: No double booking / status integrity
- Acceptance criteria / Tests: `test_concurrent_confirm_and_cancel_exactly_one_wins` — barrier-released admin confirm vs customer cancel; exactly one succeeds, the other gets 409; history has exactly one transition after creation. Also: a cancelled slot is immediately bookable by another customer.
- Docs to update: `docs/edge-cases.md`; `AI_USAGE.md` P7 entry; push.
- Edge cases covered: concurrent confirm + cancel.

### P7.7 — Stale pending bookings
- [x] Status
- Goal: a pending booking whose time has passed doesn't linger as "pending" forever.
- Requirement(s) served: statuses; product thinking
- Acceptance criteria: decision recorded (see Open questions): admin can cancel expired pendings (reason "not confirmed in time"); the admin list flags them. No background scheduler.
- Tests: integration — flagged in admin list; cancel allowed.
- Docs to update: edge-case row.
- Edge cases covered: pending booking never confirmed.

---

## P8 — Customer UI

### P8.1 — Web foundation: base template, CSS and JS port
- [x] Status
- Goal: Theoria's design system, re-pointed at booking semantics.
- Requirement(s) served: working application (UI)
- Acceptance criteria: Jinja2 environment + `app/web/` router mounted at `/`; `base.html` (inline pre-paint theme script, `has-js` class, skip link, header with new Navbat mark, nav toggle, theme toggle, flash notices, footer, confirm `<dialog>`); `static/css/app.css` porting tokens (light + `--dark-*` swap under `[data-theme="dark"]` and `prefers-color-scheme`), type roles (Archivo expanded/condensed, Instrument Sans, Spline Sans Mono), page skeleton (`.sheet-head` → `.sheet-section` → `.section-head`), and components `.btn`, `.chip`, `.segmented`, `.field`, `.stats/.stat`, `.table-wrap`, `.notice`, `.empty`, `.menu`, `.pagination`, dialog; new `.slot-grid/.slot` and `.status-chip--{pending,confirmed,completed,cancelled}`; `static/js/app.js` single IIFE with `initThemeToggle`, `initNavToggle`, `initConfirmDialog`. 404/500 pages. Web errors render HTML, not JSON.
- Tests: integration — `/` renders; unknown page → HTML 404; static files served.
- Docs to update: `docs/architecture.md` UI section; ADR 0004 (server-rendered + vanilla JS).
- Edge cases covered: no-JS rendering.

### P8.2 — Web auth pages
- [x] Status
- Goal: sign up / sign in / sign out in the browser.
- Requirement(s) served: Authentication
- Acceptance criteria: `/login`, `/register`, `POST /logout` using `services/auth`; cookie + CSRF hidden field; errors re-render the form with field messages; `next` redirect restricted to same-site paths; submit-button disable (`initSubmitState`) and inline email validation ported.
- Tests: integration — register → logged in; bad login shows error; CSRF missing → 403; open-redirect `next=https://evil` ignored.
- Docs to update: edge-case row (open redirect).
- Edge cases covered: double submit; open redirect.

### P8.3 — Services list and service detail
- [x] Status
- Goal: the customer picks what to book.
- Requirement(s) served: see slots (entry point)
- Acceptance criteria: `/` lists active services (name, duration, price in mono, description); `/services/{id}` shows detail + providers offering it + "Book" CTA; empty state explains what to do.
- Tests: integration — only active services shown.
- Docs to update: —
- Edge cases covered: inactive service URL → 404.

### P8.4 — Booking flow with live slot picker
- [x] Status
- Goal: pick provider (or any) + date → pick a slot → confirm.
- Requirement(s) served: **See available time slots**; **User can book**
- Acceptance criteria: `/book/{service_id}` GET form (provider segmented/select incl. "Any", date input, prev/next day links) — `initLiveFilter` port (`X-Requested-With`, server returns `_partials/slot_grid.html`, swap `innerHTML`, debounce, `AbortController`, full-submit fallback). Slots are radio tiles (neutral; selected = lime). Confirm step shows service, provider, local time + timezone, price, cancellation policy; POST creates the booking via `services/booking`; a 409 re-renders the grid with "That time was just taken — pick another" notice. Works fully without JS.
- Tests: integration — partial response on XHR header; full page otherwise; booking POST success redirect; taken slot shows notice.
- Docs to update: README screenshots list; edge-case row (UI side of SLOT_TAKEN).
- Edge cases covered: slot taken between viewing and booking; double submit.

### P8.5 — My bookings
- [ ] Status
- Goal: customers see and manage their bookings.
- Requirement(s) served: **Booking history**; statuses
- Acceptance criteria: `/me/bookings` with Upcoming / Past segmented tabs, table with status chips (text always), time in business tz (mono); `/me/bookings/{id}` detail with the event timeline and Cancel (confirm dialog, "No" focused first; hidden with explanation after cutoff).
- Tests: integration — own bookings only; cancel via form; other's booking → 404 page.
- Docs to update: `AI_USAGE.md` P8 entry; push.
- Edge cases covered: IDOR in UI.

---

## P9 — Admin UI

### P9.1 — Admin dashboard
- [ ] Status
- Goal: the owner's day at a glance.
- Requirement(s) served: Bonus 4
- Acceptance criteria: `/admin` (admin-only; others → 404/redirect to login): `.stats` — today's bookings, pending count, this week's utilization (booked minutes ÷ available minutes); pending bookings list with Confirm / Cancel (reason) actions; expired pendings flagged.
- Tests: integration — stats computed correctly on seeded fixtures; non-admin blocked.
- Docs to update: `docs/architecture.md` (utilization definition).
- Edge cases covered: —

### P9.2 — Services admin pages
- [ ] Status
- Goal: CRUD in the browser.
- Requirement(s) served: Create a service
- Acceptance criteria: list (incl. inactive), create/edit forms with server-side errors, activate/deactivate.
- Tests: integration — create via form; validation error re-renders.
- Docs to update: —
- Edge cases covered: —

### P9.3 — Providers admin pages
- [ ] Status
- Goal: manage staff and offered services.
- Requirement(s) served: Create providers
- Acceptance criteria: list, create/edit, offered-services checkboxes, activate/deactivate.
- Tests: integration — create, set services.
- Docs to update: —
- Edge cases covered: —

### P9.4 — Availability editor
- [ ] Status
- Goal: set weekly hours and exceptions per provider; see conflicts.
- Requirement(s) served: **Set availability**
- Acceptance criteria: per-provider page: weekly rules table grouped by weekday with add/remove; exceptions list with add (day off / custom hours); conflict notice listing affected bookings (P4.4).
- Tests: integration — add rule; overlap error shown; conflict notice appears.
- Docs to update: —
- Edge cases covered: overlapping rules (UI message).

### P9.5 — All bookings management
- [ ] Status
- Goal: find and act on any booking.
- Requirement(s) served: statuses; booking history
- Acceptance criteria: `/admin/bookings` table with live filters (status, provider, date range, customer email), pagination, row actions (confirm / complete / cancel with reason), detail page with history.
- Tests: integration — filters; actions obey the state machine (complete before end → error notice).
- Docs to update: —
- Edge cases covered: —

### P9.6 — Business settings page
- [ ] Status
- Goal: edit timezone, granularity, lead time, horizon, cutoff.
- Requirement(s) served: bonus 5, 6
- Acceptance criteria: form using `services/settings`; validation messages.
- Tests: integration — update; invalid tz rejected.
- Docs to update: `AI_USAGE.md` P9 entry; push.
- Edge cases covered: —

---

## P10 — Bonuses

### P10.1 — Calendar file (.ics)
- [ ] Status
- Goal: add a booking to any calendar.
- Requirement(s) served: Bonus 7
- Acceptance criteria: `GET /bookings/{id}/ics` → `text/calendar` RFC 5545 VEVENT (UID, DTSTAMP, DTSTART/DTEND in UTC `Z`, SUMMARY, LOCATION = business name, STATUS mapped; CRLF line endings; text escaping), same visibility rules; "Add to calendar" link in UI. No new dependency.
- Tests: integration — content type, required fields, escaping of commas/semicolons; IDOR → 404.
- Docs to update: `docs/api.md`; README checklist.
- Edge cases covered: special characters in notes/names.

### P10.2 — Notifier (console + outbox)
- [ ] Status
- Goal: notification hook points without an SMTP dependency.
- Requirement(s) served: Bonus 8
- Acceptance criteria: `services/notifications.py` — `Notifier` protocol; `ConsoleNotifier` (logs) and `OutboxNotifier` (writes an `outbox_messages` row in the **same transaction** as the booking change, so a rolled-back booking never "sends"); triggered on create, confirm, cancel. Migration for `outbox_messages`.
- Tests: integration — events create outbox rows; rolled-back booking creates none.
- Docs to update: `docs/architecture.md`; ADR 0009 (outbox); README checklist.
- Edge cases covered: notification for a booking that failed.

### P10.3 — Timezone display polish
- [ ] Status
- Goal: times are never ambiguous.
- Requirement(s) served: Bonus 5
- Acceptance criteria: every displayed time shows the business tz abbreviation/offset; API responses include both UTC `start_at` and `local_start` + `timezone`; UI note when the viewer's browser tz differs from the business tz.
- Tests: integration — response fields; Berlin-configured business renders correct local times.
- Docs to update: `docs/api.md`.
- Edge cases covered: viewer in a different timezone.

### P10.4 — API documentation pass
- [ ] Status
- Goal: Swagger that teaches, plus a guide.
- Requirement(s) served: Bonus 2
- Acceptance criteria: every endpoint has summary, description, request/response examples, and documented error responses; `docs/api.md` curl walkthrough runs end to end against a fresh `docker compose up`; complete error-code table.
- Tests: a test asserting every route in the OpenAPI schema has a summary and at least one error response documented.
- Docs to update: `docs/api.md`; `AI_USAGE.md` P10 entry; push.
- Edge cases covered: —

---

## P11 — Ship

### P11.1 — Deploy
- [ ] Status
- Goal: a live demo URL.
- Requirement(s) served: Deployed / demo URL
- Acceptance criteria: Render (or Railway) web service from the Dockerfile + managed Postgres 16 (with `btree_gist` available); `APP_ENV=production` (Secure cookies), secrets set in the dashboard only; migrations on start; **free-tier expiry checked and noted** (must outlive the review window).
- Tests: smoke — health, login, book a slot on the live URL.
- Docs to update: README demo URL; known limitations (cold starts).
- Edge cases covered: —

### P11.2 — Demo data on the live instance
- [ ] Status
- Goal: a reviewer can log in and see a realistic week.
- Requirement(s) served: working application
- Acceptance criteria: seed run on deploy; demo admin + customer credentials in README (demo-only passwords).
- Tests: manual login with both.
- Docs to update: README.
- Edge cases covered: —

### P11.3 — Screenshots
- [ ] Status
- Goal: README shows the product in five seconds.
- Requirement(s) served: README
- Acceptance criteria: `docs/screenshots/` — services list, slot picker with a selected slot, my bookings, admin dashboard, dark mode.
- Tests: —
- Docs to update: README §2.
- Edge cases covered: —

### P11.4 — Final documentation pass
- [ ] Status
- Goal: every doc is true and complete.
- Requirement(s) served: README; architecture; edge cases
- Acceptance criteria: README sections 1–10 complete; feature checklist verified one-to-one against the Requirement coverage table, each linking to code; every `docs/edge-cases.md` row links to an existing test (`pytest --collect-only` check); architecture/database docs match the final schema; ADR index complete.
- Tests: full suite green in CI.
- Docs to update: all.
- Edge cases covered: —

### P11.5 — AI usage summary and submission draft
- [ ] Status
- Goal: honest, specific answers ready for the form.
- Requirement(s) served: AI usage explanation
- Acceptance criteria: `AI_USAGE.md` summary section; `docs/submission.md` with drafts for: product description (≥100 chars), architecture, AI tools used, where AI helped and what was verified/changed (≥120 chars).
- Tests: —
- Docs to update: as above.
- Edge cases covered: —

### P11.6 — Clean-clone verification
- [ ] Status
- Goal: what the reviewer runs, works.
- Requirement(s) served: working application; README setup
- Acceptance criteria: fresh clone → follow README quick start verbatim → app up, seeded, tests pass; tag `v1.0.0`; final push. The owner submits.
- Tests: full suite; manual walkthrough.
- Docs to update: fix anything the walkthrough exposes.
- Edge cases covered: —

---

## Open questions

Decisions assumed in this plan that the owner may want to change:

1. **Stale pending bookings** (P7.7): assumed admin cancels them manually, flagged in the list; no background job.
2. **Customer cancelling a pending booking**: assumed allowed any time *before start* (the prompt's table has no condition; cancelling a past booking makes no sense).
3. **Availability exceptions**: assumed one per (provider, date), either closed or a single custom window.
4. **Rate limiter**: in-process memory (fine for one instance; documented limitation).

## Deviations log

Record every departure from `CLAUDE.md` or this plan: date · task · what changed · why.

| Date (UTC) | Task | Deviation | Reason |
|---|---|---|---|
| 2026-09-29 | P0.1 | Repo root is `booking-system-for-mohirlar/` (not `navbat/`) | Folder and public GitHub remote already existed under this name; the product is still called Navbat |
| 2026-09-29 | P0.3 | Minimal `app/core/db.py` (engine, `SessionLocal`, `get_db` without commit/rollback) pulled forward from P1.1 | The health endpoint needs a session for `SELECT 1`; P1.1 still owns the commit/rollback policy, naming convention and Alembic wiring |
| 2026-09-29 | P0.4 | The `app` service runs only `uvicorn`, not `alembic upgrade head && uvicorn` | `alembic.ini` and `migrations/env.py` do not exist until P1.1. P1.1 must add the `alembic upgrade head &&` step to the compose `command` |
| 2026-09-29 | P0.5 | `build_schema` migrates with Alembic only if `alembic.ini` exists; until P1.1 the test schema is empty | The migrations do not exist yet. Verified once with a throwaway migration. P1.1's `migrations/env.py` must use `config.attributes["connection"]` when present, so the harness migrates the test database and not `DATABASE_URL` |
| 2026-09-29 | P1.1 | Handlers take `db: DbSession` (an alias for `Depends(get_db, scope="function")`), not `Depends(get_db)` | The default scope runs the commit *after* the response is sent, so a failed commit would leave the client with a success response. Proven by `test_failed_commit_is_an_error_not_a_success_response`. Tests still override `get_db` |
| 2026-09-29 | P1.2 | Migration `0001` (catalog, settings, availability tables, `btree_gist`, `no_availability_rule_overlap`) is written in P1.2, not P1.4. P1.3 adds migration `0002` (`bookings`, `booking_events`, `booking_status` enum, indexes) for the same reason, and P1.4 becomes migration `0003` with just the two booking exclusion constraints | P1.2's acceptance criteria require the availability exclusion constraint, which only a migration can create, and `test_real_migrations_upgrade_downgrade_upgrade` fails whenever a model has no migration, so the suite could not stay green otherwise |
| 2026-09-29 | P1.6 | `app/core/security.py` (only `hash_password`) and `app/core/timezones.py` (only `local_to_utc`, `utc_to_local`) are created in P1.6 instead of P2.1 / P4.1; `SEED_DEMO_DATA` setting added | The seed must hash the admin and demo passwords and turn local booking times into UTC, and CLAUDE.md rules 1 and 4 keep each of those in exactly one module, so the seed cannot do it inline. P2.1 and P4.1 extend the same files (verification, JWT; windows, day bounds, DST policy) rather than replace them |
| 2026-09-29 | P2.2 | `get_current_user` (Bearer wins, else cookie, user reloaded, `ACCOUNT_INACTIVE`) is built in P2.2 in `app/api/deps.py`, not P2.3 | `GET /auth/me` and its "401 without auth" test need a real current-user dependency, and a throwaway version would be rewritten in P2.3. P2.3 still owns `get_optional_user`, `require_admin` and their tests |
| 2026-09-29 | P2.2 | Email shape is checked with a regex, not pydantic `EmailStr` | `EmailStr` needs the `email-validator` package, and CLAUDE.md §7 requires the owner's approval for a dependency outside §3. Can be swapped in later without changing the API |
| 2026-09-29 | P2.4 | The pre-session CSRF cookie for login/register forms is delivered as tested building blocks (`ensure_csrf_cookie`, always-on `require_csrf`), not wired into HTML forms | The forms do not exist until P8.2, which must call them (its tests already include "CSRF missing → 403"). Until then only the JSON API exists, where anonymous calls have no cookie to abuse |
| 2026-09-29 | P3.2 | The pagination helper (`app/core/pagination.py`: `PageParams`, `PageParamsDep`, `paginate`; `app/schemas/pagination.py`: `Page[T]`) is built in P3.2, not P3.4. P3.4 keeps its own tests and docs pass | `GET /services` must be paginated (P3.2's criteria) and a throwaway version would be rewritten. `docs/api.md` Pagination is already written |
| 2026-09-29 | P3.2 | Service `description` is limited to 1000 characters, not the 2000 in the criteria | The `services.description` column is `varchar(1000)` (P1.2). A longer text would be a database error, and a service blurb does not need more. Widening it would be a migration for no requirement |
| 2026-09-30 | P4.2 | Availability-rule times cannot end at 24:00, so with a 15-minute grid the latest closing time is 23:45 (the "ends at 23:59" hint in the model docstring is not usable, since 23:59 is off the grid) | The criteria require times aligned to the granularity and a window never crosses midnight; `time` has no 24:00. Closing at midnight is not needed for a barbershop |
| 2026-09-30 | P4.3 | `GET /providers/{id}/availability/exceptions` is admin-only, and an exception whose date has passed cannot be edited (only deleted) | The criteria say "admin CRUD" without a public read; a reason such as "sick leave" is not for customers, who see only the resulting slots |
| 2026-09-30 | P4.4 | `DELETE` of a rule or exception returns `200 {id, details}` instead of `204`; every write response gains `details.conflicts` | The criteria want the conflict warning "in rule/exception write responses", and removing a rule is the write that most often strands bookings, so it needs a body to carry the warning. `docs/api.md` and the P4.2/P4.3 delete tests updated |
| 2026-09-30 | P4.4 | `build_windows_for_date` (pure, in `app/services/slots.py`) is written in P4.4, not P5.1. P5.1 adds `compute_slots` beside it and keeps its own tests | Deciding whether a booking still fits the hours needs exactly "rules + exception + date + tz -> UTC windows", and a second copy would break the one-place rule for the exception-replaces-rules logic |
| 2026-09-30 | P7.3 | The admin booking list is `GET /bookings/all`, not `GET /bookings` | `GET /bookings` is already "my own bookings" for everyone (P6.3, tested and documented, including for admins, who can also book). Making it role-dependent would change the meaning of one URL by who calls it; a separate path keeps each endpoint's contract fixed |
| 2026-09-30 | P8.2 | A 401 on a web page GET redirects to `/login?next=…` (in `app/web/errors.py`), built now rather than in P8.5; the page renderer also receives the error code, so `CSRF_FAILED` gets wording for people | Every signed-in page (P8.5, P9) needs "send them to log in and back", and the login page's `next` handling is what makes it safe; one place instead of a check per route |
| 2026-09-30 | P8.4 | "Any" shows every person's free times, grouped by person, rather than one merged list auto-assigned to someone; after booking, the redirect goes to `/me/bookings/{id}`, which P8.5 builds | Grouping reuses `get_slots` as it is and keeps "who gets an any-booking" from becoming a new business rule under deadline; the customer still sees everything free that day. The booking page is the next task in the same phase |
