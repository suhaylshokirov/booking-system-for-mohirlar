# ADR 0010 — Barbers run the shop; there is no administrator

**Status:** accepted (2026-10-01, at the owner's request; supersedes the "providers
are records managed by the admin" decision in CLAUDE.md §8)

## Context

The first design had an administrator who managed everything: services, providers,
everyone's hours, every booking. Providers (barbers) were records with no login.
That does not match how a small barbershop works: the barbers are the ones who
take, confirm and cancel client requests and who know their own hours. An
administrator who manages other people's calendars is a role nobody in the shop
has, and it made the barbers passive.

## Decision

- The `admin` role becomes `barber`. A barber is a user linked to **exactly one
  provider** (`users.provider_id`). The database enforces it: a CHECK says
  `role = 'barber'` exactly when `provider_id` is set, and a unique constraint gives
  each provider at most one login. There is no other staff role.
- **Bookings:** a barber sees, confirms, cancels and completes the bookings made with
  *their* provider only. Another barber's booking is the same 404 as a missing one
  (the customer IDOR rule, rule 11). `check_transition` also checks that the actor is
  the booking's barber, as a backstop to the lookup.
- **Own hours and profile:** each barber edits their own working hours, days off,
  name, bio, offered services and visibility. In the JSON API the provider id in the
  path must be the caller's own (`require_own_provider`, 403 otherwise). In the web
  UI the provider comes from the login and is not in the address at all
  (`/barber/hours`, `/barber/profile`).
- **Shared setup:** services and the business settings (name, timezone, cutoff, lead
  time, horizon) can be edited by any barber, like the owner-barbers of a small shop.
- **Onboarding:** `python -m scripts.create_barber` creates a barber and their
  provider together; the seed creates three. There is no endpoint and no UI for it
  (registration still only creates customers). `POST /providers` is gone.
- Renames that follow: `/admin/*` pages are `/barber/*`; `GET /bookings/all` is
  `GET /bookings/clients` and is scoped to the caller; `ADMIN_EMAIL`/`ADMIN_PASSWORD`
  are `BARBER_EMAIL`/`BARBER_PASSWORD`.
- Migration `0005` carries an existing admin over: the role is renamed in place and
  each admin gets a provider of their own, so the CHECK holds for old data.

## Alternatives considered

- **Keep an admin and let barbers also log in.** Two kinds of staff and a permission
  matrix between them, which is exactly the complexity the owner wanted gone.
- **A separate `barbers` table, with providers pointing at it.** The provider already
  is the barber's public record; a second table would only duplicate it.
- **A "lead barber" flag for shared setup.** Reintroduces an admin by another name.
- **Per-barber services and settings.** Prices and the timezone are shop-wide facts;
  making them per barber would multiply the model and the tests for no requirement.

## Consequences

- Any barber can change shop-wide prices and rules. Acceptable for a small shop and
  stated here, not hidden; tightening it later is one dependency (`require_barber`)
  plus a flag.
- A barber cannot see or help with a colleague's clients, even to cover for them.
  Deactivating a barber hides them from customers but their bookings remain theirs.
- A barber who is also a customer (they can still book) is just a customer on that
  booking: the cutoff applies to them and they cannot confirm it.
- No one can create the first barber from the browser; the deployment runs
  `create_barber` (or the seed) once, as it did for the admin.
- The booking list for a barber has no provider filter (it is always their own).
