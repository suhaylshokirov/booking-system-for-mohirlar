# Navbat — appointment booking

> *Navbat* is Uzbek for "turn" or "queue".

Navbat is an appointment booking system for a small service business such as a
barbershop or clinic. A customer picks a service, sees the free times of the
barbers who offer it, and books one. The barbers run the shop themselves: each
manages their own bookings (Pending → Confirmed → Completed, or Cancelled), weekly
hours and profile, and any barber manages the shared services and settings. There is
no administrator ([ADR 0010](docs/decisions/0010-barbers-replace-the-admin.md)).
Double booking is prevented by the database itself, not just by application code.

- **Live demo:** https://navbat-pi.vercel.app (Vercel + Neon Postgres; the first request after idle can take a few seconds)
- **Signing in:** there are no passwords. Choose *Sign up*, enter your own email and type the 6-digit code that arrives (check spam). You get a customer account and can book at once. The barber account belongs to the owner.
- **CI:** [![CI](https://github.com/suhaylshokirov/booking-system-for-mohirlar/actions/workflows/ci.yml/badge.svg)](https://github.com/suhaylshokirov/booking-system-for-mohirlar/actions/workflows/ci.yml)

> Status: feature-complete. The work was done task by task; the queue, with every
> decision and deviation, is in [`tasks.md`](tasks.md).

## Screenshots

Taken from the seeded app (`docs/screenshots/`). Times are the shop's local time (Asia/Tashkent).

| | |
|---|---|
| **Home: the shop and its services** (`/`) | **Slot picker**: a free time chosen (saffron), sticky *Continue* bar (`/book/{id}`) |
| ![Services](docs/screenshots/services.png) | ![Slot picker with a chosen time](docs/screenshots/slot-picker.png) |
| **My bookings**: a pending booking and a cancelled one (`/me/bookings`) | **Barber: all bookings**, with the actions each status allows (`/barber/bookings`) |
| ![My bookings](docs/screenshots/my-bookings.png) | ![Barber bookings](docs/screenshots/barber-dashboard.png) |

**Dark mode** follows the OS and has a toggle in the header:

![Slot picker in dark mode](docs/screenshots/dark-mode.png)

## Features

Mapped one-to-one to the assignment, each with where it is implemented and the test
that proves it.

### Minimum requirements

- [x] **Create a service** with name, description, duration, price: [`app/services/service_catalog.py`](app/services/service_catalog.py), `POST /api/v1/services`, the barber's *Services* page. Price is an integer in UZS; the duration must fit the slot grid (`tests/integration/test_services.py`).
- [x] **Create providers / employees**: [`app/services/provider_catalog.py`](app/services/provider_catalog.py), [`scripts/create_barber.py`](scripts/create_barber.py); a barber is a login plus the provider record customers book (`tests/integration/test_providers.py`, `test_create_barber.py`).
- [x] **Set availability**: weekly hours and days off, overlapping windows refused by the database: [`app/services/availability.py`](app/services/availability.py) (`tests/integration/test_availability_*.py`).
- [x] **See available time slots**: computed, never stored, by the pure function [`app/services/slots.py`](app/services/slots.py) (`tests/unit/test_slots.py`), served by `GET /api/v1/slots` and the live slot picker.
- [x] **Book**: [`app/services/booking.py`](app/services/booking.py) `create_booking` (`tests/integration/test_create_booking.py`).
- [x] **Booking statuses** Pending, Confirmed, Cancelled, Completed: one state machine, [`app/services/booking_state.py`](app/services/booking_state.py), applied with a guarded `UPDATE` (`tests/unit/test_booking_state.py`, `tests/concurrency/test_transition_races.py`).
- [x] **No double booking**: PostgreSQL exclusion constraints `no_provider_overlap` and `no_customer_overlap` in [`migrations/versions/0003_booking_exclusion_constraints.py`](migrations/versions/0003_booking_exclusion_constraints.py), mapped to `409 SLOT_TAKEN` / `CUSTOMER_OVERLAP`. Ten simultaneous customers on one slot give exactly one booking: `tests/concurrency/test_booking_races.py`.
- [x] **Backend API**: versioned JSON under `/api/v1`, one error envelope, [`docs/api.md`](docs/api.md) and `/docs`.
- [x] **Authentication**: passwordless sign-in with an emailed 6-digit code, JWT in an HttpOnly cookie or as a Bearer token, CSRF double-submit: [`app/services/auth.py`](app/services/auth.py), [ADR 0005](docs/decisions/0005-jwt-cookie-bearer-csrf.md), [ADR 0013](docs/decisions/0013-email-codes-replace-passwords.md).
- [x] **Basic validation**: Pydantic schemas for shape ([`app/schemas/`](app/schemas/)), business rules in one place ([`app/services/booking_rules.py`](app/services/booking_rules.py): past, lead time, horizon, grid, working hours), database CHECKs behind both.
- [x] **Booking history**: every status change writes a `booking_events` row in the same transaction; customers see their own bookings (someone else's is a `404`), barbers see theirs: `GET /api/v1/bookings/{id}/history`, *My bookings*, the barber's *Bookings* page.

### Bonuses

- [x] **Tests**: unit, integration (real PostgreSQL, never SQLite) and concurrency tests with real commits and threads, run in [CI](.github/workflows/ci.yml); see *Running tests*.
- [x] **API documentation**: Swagger at `/docs` with examples and errors on every endpoint, a curl guide, a runnable walkthrough ([`docs/walkthrough.sh`](docs/walkthrough.sh)) and a complete error-code table ([`docs/api.md`](docs/api.md)).
- [x] **Docker**: `docker compose up --build` runs the app and PostgreSQL, migrates and seeds.
- [x] **Barber dashboard**: each barber's own bookings, hours and profile, today's queue and a plain stats row ([`app/web/barber*.py`](app/web/)); it replaces the usual admin dashboard ([ADR 0010](docs/decisions/0010-barbers-replace-the-admin.md)).
- [x] **Timezone support**: the business timezone (default Asia/Tashkent) decides what "10:00" means; storage is UTC `timestamptz`; the API rejects naive datetimes; DST gaps and overlaps are handled in one module, [`app/core/timezones.py`](app/core/timezones.py) (`tests/unit/test_timezones.py`).
- [x] **Cancellation policy**: customers can cancel a confirmed booking until a cutoff (default 2 hours before it starts, set in business settings); a barber is exempt but must give a reason.
- [x] **Calendar integration**: an `.ics` file for each booking ([ADR 0011](docs/decisions/0011-calendar-file.md)).
- [x] **Email**: sign-in codes are emailed over SMTP ([`app/core/mail.py`](app/core/mail.py)). Booking messages (requested, confirmed, cancelled) are written to a transactional outbox and logged but **no worker sends them yet** ([ADR 0009](docs/decisions/0009-transactional-outbox.md)).

## Quick start (Docker)

Requires Docker with the Compose plugin. Nothing else to install or configure.

```bash
docker compose up --build
curl http://localhost:8000/api/v1/health     # {"status":"ok","database":"ok"}
```

- App: <http://localhost:8000> · API reference: <http://localhost:8000/docs>
- Two services: `db` (Postgres 16, with a healthcheck) and `app`. The app
  starts only once the database reports healthy, so a slow Postgres start
  never crashes it.
- The first start creates two databases: `navbat` (the app) and `navbat_test`
  (pytest, so tests never touch app data). Postgres runs the init script only
  on a fresh volume; to recreate the test database run `docker compose down -v`.
- Postgres is published on host port 5433 so pytest and Alembic can reach it
  from your machine. If that port is already used, run
  `DB_HOST_PORT=5434 docker compose up --build` and point `DATABASE_URL` and
  `TEST_DATABASE_URL` at `localhost:5434`.
- Only the database is needed for local development:
  `docker compose up -d db`.
- The `app` container runs `alembic upgrade head` before starting, so a fresh
  database gets its schema automatically, and the demo data (see below) is seeded.

### Demo data

`python -m scripts.seed` fills the database with a demo barbershop: settings
(Asia/Tashkent, UZS, 15-minute slots), four services, three barbers with
different service sets, weekly hours, a demo phone number and a stock photo (one has a day off next week), a login
for each barber, a demo customer and four bookings covering every status. Dates
are relative to today. It is idempotent: run it as often as you like; it never
duplicates rows and never overwrites what you changed in the barber UI (one
exception: a demo barber with no photo or phone gets the demo one again, so a
database seeded before photos existed gets them too). Docker Compose runs it on
start while `SEED_DEMO_DATA=true`. The barbers' portraits and the shop photos on
the home page are free Unsplash stock photos, credited in
[`docs/credits.md`](docs/credits.md).

| Role | Email |
|---|---|
| Barber (Jasur) | `BARBER_EMAIL` (`jasur@navbat.local`) |
| Barber (Bekzod, Dilshod) | `bekzod@navbat.local`, `dilshod@navbat.local` |
| Customer | `demo@navbat.local` |

**There are no passwords.** Signing in asks for your email, sends a 6-digit code to it
and asks you to type the code (ADR 0013). These seeded `.local` addresses cannot receive
mail, so with no mail server configured the app writes each email to its log instead:

```bash
docker compose logs -f app     # or the terminal running uvicorn
# INFO:     [navbat.mail] email to demo@navbat.local: Navbat Barbershop: your sign-in code is 482913
```

Outside production, the sign-in page also has an **Open the barber dashboard (demo)** button that signs in as Jasur
without a code and opens `/barber`; in production it does not exist. To try the API: `POST /api/v1/auth/login`, then
`POST /api/v1/auth/verify` with the code (see [`docs/api.md`](docs/api.md)). Real addresses work the same once
`SMTP_HOST` is set (below).

### Create a barber

There is no administrator: the barbers run the shop (ADR 0010). A barber is a
login together with the provider record customers book, created from the command
line (signing up always creates a customer; there is no endpoint for this):

```bash
python -m scripts.create_barber --email jasur@example.com --name Jasur
# or take the email from BARBER_EMAIL
python -m scripts.create_barber
# inside Docker:
docker compose exec app python -m scripts.create_barber --email ... --name ...
```

There is no password to set: the barber signs in at `/login` with a code emailed to that
address, so use one they can read. It is safe to run again: an existing account with that
email (any letter case) is promoted to barber (and given a provider record if it has
none) and reactivated; nothing is duplicated. The email must pass the same check as
sign-up.

## Local development

Requires Python 3.12.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"      # pinned runtime deps + pytest, httpx, ruff
ruff check . && ruff format --check .
pytest
```

A `Makefile` wraps the common steps; `make help` lists them. The ones you will use:

| Command | What it does |
|---|---|
| `make` | The whole app and Postgres in Docker (same as `docker compose up --build`) |
| `make dev` | Postgres in Docker, migrated and seeded; the app on your machine with auto-reload |
| `make test` | Starts Postgres if needed and runs the whole suite |
| `make lint` / `make format` | `ruff check` and `ruff format --check`, or fix them |
| `make barber EMAIL=you@x.com NAME="Jasur"` | Create a barber |
| `make reset` | Stop the containers and **delete the database** |

### Database migrations

```bash
alembic upgrade head                              # apply all migrations
alembic downgrade -1                              # undo the latest one
alembic revision --autogenerate -m "describe it"  # then READ and edit the file
```

Autogenerate cannot see the exclusion constraints, so every migration is
reviewed by hand. Conventions: [`docs/database.md`](docs/database.md).

### Running tests

Tests run against a real PostgreSQL, never SQLite. Start the database, then run
pytest:

```bash
docker compose up -d db      # also creates the separate navbat_test database
pytest                       # everything
pytest tests/unit            # or one layer: unit · integration · concurrency
```

- The tests use `TEST_DATABASE_URL` (default `.../navbat_test`). At the start of
  each run the harness **drops and recreates that database's schema** and
  rebuilds it with the Alembic migrations, so the constraints under test are the
  real ones.
- pytest **refuses to start** if `TEST_DATABASE_URL` and `DATABASE_URL` name the
  same database, so a mistake cannot wipe your development data.
- Each test runs inside a transaction that is rolled back afterwards. Concurrency
  tests use the `committing_db` fixture instead, which really commits and
  truncates the tables when the test ends.
- If Postgres is on another host port (see Quick start), export both
  `DATABASE_URL` and `TEST_DATABASE_URL` with that port.

### Environment variables

Copy `.env.example` to `.env` to change any of them. Every variable has a
default that works on a fresh checkout, except the two secrets marked below,
which must be replaced in production (and `SMTP_HOST`, which production requires).

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production`. Production turns on Secure cookies and refuses to start with the placeholder `JWT_SECRET`. |
| `DATABASE_URL` | `postgresql+psycopg://navbat:navbat@localhost:5433/navbat` | The app's database (psycopg 3 driver). Inside Docker Compose the host is `db`. |
| `TEST_DATABASE_URL` | `postgresql+psycopg://navbat:navbat@localhost:5433/navbat_test` | The database pytest resets and uses. Must differ from `DATABASE_URL`. |
| `JWT_SECRET` | placeholder | **Secret.** Signs login tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `JWT_EXPIRE_MINUTES` | `720` | Lifetime of a login token. |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | Failed logins allowed per (IP, email) per window. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Length of that window. |
| `SMTP_HOST` | empty | Mail server that sends the sign-in codes. Empty: codes are only logged to the console (development). **Required in production.** |
| `SMTP_PORT` | `587` | Mail server port (`465` with `SMTP_SECURITY=ssl`). |
| `SMTP_USER` / `SMTP_PASSWORD` | empty | **Secret** (the password). Login for the mail server; skipped when the user is empty. |
| `SMTP_FROM` | `Navbat <no-reply@navbat.local>` | The sender shown on the email. |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl`, or `none` (a local test server only). |
| `BARBER_EMAIL` | `jasur@navbat.local` | Email of the first barber (`scripts/create_barber.py`; the seed's first barber and the demo button). |
| `SEED_DEMO_DATA` | `false` (`true` in `docker-compose.yml`) | Run the seed script on container start. Safe to leave on; see below. |

### Deploying to Vercel

The live site runs on Vercel with a Neon Postgres (decision: [ADR 0014](docs/decisions/0014-vercel-and-neon.md)).
The Dockerfile and Compose file are for local use only.

1. `npx vercel link` creates the project; `npx vercel integration add neon` adds the
   database and injects `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED`.
2. In the project's environment (Production) set `APP_ENV=production`, a fresh
   `JWT_SECRET`, `BARBER_EMAIL` (a real address: the first barber signs in by code),
   and the `SMTP_*` settings. Production refuses to start without `SMTP_HOST`.
3. Migrate and seed **once, by hand**, with the unpooled URL (they do not run on deploy):
   `DATABASE_URL=<unpooled url> alembic upgrade head`, then the same with
   `BARBER_EMAIL=<real address> python -m scripts.seed`. A later schema change repeats the `alembic` step before its deploy.
4. `npx vercel deploy --prod` (or push to `main`; the project is connected to GitHub).

## Architecture in brief

```mermaid
flowchart LR
    B[Browser pages<br/>Jinja2 + vanilla JS] --> W[app/web<br/>HTML routers]
    C[API clients] --> A[app/api/v1<br/>JSON routers]
    W --> S[app/services<br/>all business rules]
    A --> S
    S --> M[app/models<br/>SQLAlchemy]
    M --> DB[(PostgreSQL<br/>exclusion constraints)]
    S -.-> K[app/core<br/>clock, timezones, mail, errors]
```

Routers are thin and never touch the database; both entry points call the same
services, so each rule (double-booking protection, validation, status transitions)
lives in exactly one place. Slots are computed from weekly hours and existing bookings,
never stored. Every timestamp is UTC `timestamptz`; "10:00" means the business's local
time, converted in one module. The database, not Python, is the double-booking guarantee:
two `EXCLUDE USING gist` constraints on `tstzrange(start_at, end_at, '[)')`, one per
barber and one per customer, whose violation (SQLSTATE `23P01`) becomes `409 SLOT_TAKEN`
or `CUSTOMER_OVERLAP`. Full write-up, with the booking and state-machine diagrams:
[`docs/architecture.md`](docs/architecture.md); the schema: [`docs/database.md`](docs/database.md).

## Key decisions

Each is a short record with the alternatives that were rejected: [`docs/decisions/`](docs/decisions/).

| ADR | Decision |
|---|---|
| [0001](docs/decisions/0001-exclusion-constraints.md) | PostgreSQL exclusion constraints, not application checks, prevent double booking |
| [0002](docs/decisions/0002-computed-slots.md) | Slots are computed, not stored |
| [0003](docs/decisions/0003-sync-sqlalchemy.md) | Synchronous SQLAlchemy 2.0 |
| [0004](docs/decisions/0004-server-rendered-ui.md) | Server-rendered UI with vanilla JS; every form works without JavaScript |
| [0005](docs/decisions/0005-jwt-cookie-bearer-csrf.md) | JWT in an HttpOnly cookie or a Bearer token, with CSRF double-submit |
| [0006](docs/decisions/0006-half-open-ranges-and-utc.md) | Half-open ranges (back-to-back bookings are fine) and UTC storage |
| [0007](docs/decisions/0007-booking-snapshots.md) | A booking keeps the price and duration it was made with |
| [0008](docs/decisions/0008-guarded-status-updates.md) | Status changes are guarded `UPDATE`s, not row locks |
| [0009](docs/decisions/0009-transactional-outbox.md) | Booking notifications go through a transactional outbox |
| [0010](docs/decisions/0010-barbers-replace-the-admin.md) | Barbers run the shop; there is no administrator |
| [0011](docs/decisions/0011-calendar-file.md) | The `.ics` file is built by hand, in UTC |
| [0012](docs/decisions/0012-photos-in-postgres.md) | A barber's photo is stored in Postgres |
| [0013](docs/decisions/0013-email-codes-replace-passwords.md) | Emailed codes replace passwords |
| [0014](docs/decisions/0014-vercel-and-neon.md) | Deploy on Vercel with a Neon Postgres |

## Edge cases

The full table (105 rows, each with where it is enforced and the test that proves it,
checked by `tests/unit/test_edge_case_docs.py`) is in [`docs/edge-cases.md`](docs/edge-cases.md).
Five that matter most:

1. **Two people book the same slot at the same instant** (#1): both pass the "is it free?"
   check; the exclusion constraint lets exactly one insert commit and the other gets
   `409 SLOT_TAKEN`. Ten simultaneous customers, one winner: `tests/concurrency/test_booking_races.py`.
2. **One customer in two places at once** (#3): a second constraint, per customer, gives `409 CUSTOMER_OVERLAP`.
3. **A barber confirms while the customer cancels** (#16): guarded `UPDATE ... WHERE status = :expected`;
   the loser gets `409 BOOKING_STATE_CHANGED` and only one history row exists.
4. **Daylight-saving gaps and overlaps, and local day versus UTC day** (#13, #14):
   all conversion is in `app/core/timezones.py` and tested around real transitions.
5. **A sign-in code submitted twice at once** (#100): only one verification can consume it
   (`tests/concurrency/test_sign_in_races.py`); wrong tries are capped per code, in the database.

## How AI was used

[`AI_USAGE.md`](AI_USAGE.md) is the running log: for each phase, what was asked, what
the AI produced, how it was verified, what was changed or rejected, and which bugs
were caught. It ends with a summary written for the submission form. In short: AI
drafted code and docs; every rule that matters (double booking, status transitions,
time handling) is covered by tests, including races against a real PostgreSQL with
real commits and threads, and the author reads and can explain every line.

## Known limitations and next steps

- **Login rate limiting is in-process.** Counters live in the app's memory: they
  reset on restart and are not shared across several instances. A per-IP limit
  is also bypassed by rotating addresses. Behind a reverse proxy, run uvicorn
  with `--proxy-headers` so the limiter sees real client addresses. A shared
  store (for example Redis) would drop in behind the same interface. **On Vercel
  every function instance has its own counters**, so this limit is only a
  best-effort extra there; the 5-tries-per-code cap is in the database and holds.
- **Cold starts.** After idle time the first request starts the function and wakes
  Neon's compute, so it can be a few seconds slower.
- **Neon runs PostgreSQL 18; tests and Docker Compose run 16.** The migrations and
  constraints applied unchanged, but CI does not run against 18.
- **Email goes through one Gmail account** (about 500 messages a day). If Gmail
  refuses, sign-in requests fail and nobody can log in.
- **Booking emails are not sent.** Requested, confirmed and cancelled messages are
  stored in the outbox and logged, but no worker delivers them
  ([ADR 0009](docs/decisions/0009-transactional-outbox.md)). Only sign-in codes are emailed.
- **Any barber can change the shared services and settings.** There is no administrator
  ([ADR 0010](docs/decisions/0010-barbers-replace-the-admin.md)); a barber's own bookings,
  hours and profile are private to them.
- **Barber accounts are created from the command line** (`scripts/create_barber.py`);
  signing up always makes a customer.
