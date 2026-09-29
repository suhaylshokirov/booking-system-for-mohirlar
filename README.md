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
- **CI:** _badge added in P0.6_

> Status: in development. Progress is tracked task by task in [`tasks.md`](tasks.md).

## Screenshots

_Added in P11.3: customer booking flow, admin dashboard._

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
- [ ] Cancellation policy
- [ ] Calendar integration (`.ics`)
- [ ] Email notification (pluggable notifier)

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
- Postgres is published on host port 5432 so pytest and Alembic can reach it
  from your machine. If that port is already used, run
  `DB_HOST_PORT=5433 docker compose up --build` and point `DATABASE_URL` and
  `TEST_DATABASE_URL` at `localhost:5433`.
- Only the database is needed for local development:
  `docker compose up -d db`.
- Migrations and seed data (`docker compose exec app ...`) arrive with P1.

## Local development

Requires Python 3.12.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"      # pinned runtime deps + pytest, httpx, ruff
ruff check . && ruff format --check .
pytest
```

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

_The environment variables table is added in P0.6._

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
