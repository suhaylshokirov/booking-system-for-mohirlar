# Navbat — appointment booking

> *Navbat* is Uzbek for "turn" or "queue".

Navbat is an appointment booking system for a small service business such as a
barbershop or clinic. Customers pick a service, see the free time slots of the
staff who offer it, and book one; the owner manages services, providers,
working hours and every booking's lifecycle (Pending → Confirmed → Completed,
or Cancelled). Double booking is prevented by the database itself, not just by
application code.

- **Live demo:** https://navbat-pi.vercel.app (Vercel + Neon Postgres; the first request after idle can take a few seconds)
- **Signing in:** there are no passwords. Choose *Sign up*, enter your own email and type the 6-digit code that arrives (check spam). You get a customer account and can book at once. The barber account belongs to the owner.
- **CI:** [![CI](https://github.com/suhaylshokirov/booking-system-for-mohirlar/actions/workflows/ci.yml/badge.svg)](https://github.com/suhaylshokirov/booking-system-for-mohirlar/actions/workflows/ci.yml)

> Status: in development. Progress is tracked task by task in [`tasks.md`](tasks.md).

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

Mapped one-to-one to the assignment. Each item links to where it's
implemented once it exists.

### Minimum requirements

- [ ] Create a service with name, description, duration, price
- [ ] Create providers / employees
- [ ] Set availability
- [ ] See available time slots
- [ ] Book
- [ ] Booking statuses: Pending, Confirmed, Cancelled, Completed
- [ ] No double booking
- [ ] Backend API
- [ ] Authentication
- [ ] Basic validation
- [ ] Booking history

### Bonuses

- [ ] Tests (unit, integration, concurrency)
- [x] API documentation (Swagger with examples and errors on every endpoint, a curl guide, a runnable walkthrough, a complete error-code table)
- [ ] Docker
- [ ] Barber dashboard (each barber's own bookings, hours and queue)
- [x] Timezone support (business timezone; UTC storage; local time and offset in API and pages)
- [ ] Cancellation policy: customers can cancel a confirmed booking until a cutoff (default 2 hours before it starts, set in business settings); the barber is exempt but must give a reason
- [x] Calendar integration (`.ics`)
- [x] Email notification (pluggable notifier; messages go to a transactional outbox, no SMTP yet: ADR 0009)

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
docker compose logs -f app     # or the terminal running `make dev`
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

_Diagram + summary. Full write-up: [`docs/architecture.md`](docs/architecture.md)._

## Key decisions

See [`docs/decisions/`](docs/decisions/) for the ADRs.

## Edge cases

Top five here; the full table is in [`docs/edge-cases.md`](docs/edge-cases.md).

## How AI was used

See [`AI_USAGE.md`](AI_USAGE.md).

## Known limitations and next steps

_Filled in as they are discovered._

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
