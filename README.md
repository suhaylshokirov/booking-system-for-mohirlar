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

_Completed in P0.4._

## Local development

_Completed in P0.2 / P0.5: virtualenv setup, running tests, environment
variables table._

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
