# Navbat — appointment booking

> *Navbat* is Uzbek for "turn" or "queue".

Navbat is an appointment booking system for a small service business such as a
barbershop or clinic. Customers pick a service, see the free time slots of the
staff who offer it, and book one; the owner manages services, providers,
working hours and every booking's lifecycle (Pending → Confirmed → Completed,
or Cancelled). Double booking is prevented by the database itself, not just by
application code.

- **Live demo:** _TBD (P11)_
- **Demo credentials:** _TBD (P11)_ — admin and customer
- **CI:** [![CI](https://github.com/suhaylshokirov/booking-system-for-mohirlar/actions/workflows/ci.yml/badge.svg)](https://github.com/suhaylshokirov/booking-system-for-mohirlar/actions/workflows/ci.yml)

> Status: in development. Progress is tracked task by task in [`tasks.md`](tasks.md).

## Screenshots

_Captured in P11.3._ Planned shots, in the order a customer meets them:

1. The home page: the shop on its glazed band, the house-rules ticket and the services (`/`)
2. A service's page with its staff (`/services/{id}`)
3. The slot picker with a time chosen: saffron tile, sticky Continue bar (`/book/{id}`)
4. "That time was just taken — pick another" after losing a race
5. The confirm ticket with the cancellation policy (`/book/{id}/confirm`)
6. The admin dashboard

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
- [ ] API documentation (Swagger + guide)
- [ ] Docker
- [ ] Admin dashboard
- [ ] Timezone support
- [ ] Cancellation policy: customers can cancel a confirmed booking until a cutoff (default 2 hours before it starts, set in business settings); admins are exempt but must give a reason
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
different service sets and weekly hours (one has a day off next week), the
admin, a demo customer and four bookings covering every status. Dates are
relative to today. It is idempotent: run it as often as you like; it never
duplicates rows and never overwrites what you changed in the admin UI. Docker
Compose runs it on start while `SEED_DEMO_DATA=true`.

| Role | Email | Password |
|---|---|---|
| Admin | `ADMIN_EMAIL` (`admin@navbat.local`) | `ADMIN_PASSWORD` (default `change-me-admin-password`) |
| Customer | `demo@navbat.local` | `demo-customer-password` |

Outside production, the sign-in page also has an **Open the admin panel (demo)** button that signs in as that admin and opens `/admin`; in production it does not exist. The demo passwords are public on purpose and are not secrets. Log in
with either through `POST /api/v1/auth/login` (see [`docs/api.md`](docs/api.md)).

### Create the first admin

There is no endpoint that makes an admin (registration always creates a
customer). Create one from the command line:

```bash
python -m scripts.create_admin --email owner@example.com --password 'a long passphrase'
# or take both from ADMIN_EMAIL / ADMIN_PASSWORD (preferred on a shared machine:
# command-line arguments are visible in `ps` and shell history)
python -m scripts.create_admin
# inside Docker:
docker compose exec app python -m scripts.create_admin --email ... --password ...
```

It is safe to run again: an existing account with that email (any letter case)
is promoted to admin, reactivated and given that password; nothing is
duplicated. The email and password must pass the same rules as registration,
and in production the placeholder password from `.env.example` is refused.

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
which must be replaced in production.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production`. Production turns on Secure cookies and refuses to start with the placeholder `JWT_SECRET`. |
| `DATABASE_URL` | `postgresql+psycopg://navbat:navbat@localhost:5433/navbat` | The app's database (psycopg 3 driver). Inside Docker Compose the host is `db`. |
| `TEST_DATABASE_URL` | `postgresql+psycopg://navbat:navbat@localhost:5433/navbat_test` | The database pytest resets and uses. Must differ from `DATABASE_URL`. |
| `JWT_SECRET` | placeholder | **Secret.** Signs login tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `JWT_EXPIRE_MINUTES` | `720` | Lifetime of a login token. |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | Failed logins allowed per (IP, email) per window. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Length of that window. |
| `ADMIN_EMAIL` | `admin@navbat.local` | Email of the first admin (`scripts/create_admin.py`, seed). |
| `ADMIN_PASSWORD` | placeholder | **Secret.** Password of the first admin. |
| `SEED_DEMO_DATA` | `false` (`true` in `docker-compose.yml`) | Run the seed script on container start. Safe to leave on; see below. |

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
  store (for example Redis) would drop in behind the same interface.
