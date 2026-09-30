# CLAUDE.md — Navbat (booking system)

Working instructions for any AI agent (and human) contributing to this repo.
Read this file fully before touching code. `tasks.md` is the work queue.

---

## 1. What this is

**Navbat** (Uzbek: "turn / queue") is an appointment booking system for a small
service business such as a barbershop or clinic. A customer picks a service,
sees free time slots, and books one; the business owner (admin) manages
services, providers (staff), availability, and bookings.

It is **Task 3 of the Mohirlar internship assignment**. It will be graded on:
database design, business logic and validation, race conditions and edge
cases, API architecture, product thinking, **step-by-step git history**,
**documentation quality**, and **how AI was used and verified**.

**Hard deadline: 2026-10-02 04:16 UTC (09:16 Tashkent).** The owner submits
the form personally, once. An agent never submits anything.

The owner must be able to explain every line to a reviewer. Therefore:
plain, readable code over clever code; comments explain *why*, not *what*;
after every phase, summarise what to review in plain language (see §9).

## 2. Order of authority

When anything conflicts, the higher item wins:

1. **Assignment requirements** — the minimum requirements, deliverables and
   bonuses listed in `tasks.md` → "Requirement coverage". Never trade one away
   for polish.
2. **Architecture decisions** — this file, `docs/architecture.md`, and the ADRs
   in `docs/decisions/`.
3. **The UI design system** in `app/static/css/app.css` ("tile and ticket":
   cobalt glaze, saffron for committed, the booking as a queue ticket). It
   replaced the Theoria-inspired look on 2026-09-30. Nice to have. Drop
   anything that costs time without serving a requirement.

## 3. Stack and commands

Python 3.12 · FastAPI · Pydantic v2 · PostgreSQL 16 · SQLAlchemy 2.0 (sync,
typed `Mapped[]`) · psycopg 3 · Alembic · Jinja2 + vanilla JS · pwdlib[argon2]
· PyJWT · pytest · ruff · Docker Compose · GitHub Actions.

Dependencies are few and pinned in `pyproject.toml`. Adding one needs a reason
written in the commit body.

| Purpose | Command |
|---|---|
| Run everything (app + db) | `docker compose up --build` |
| App URL / API reference | http://localhost:8000 · http://localhost:8000/docs |
| Local venv setup | `python3.12 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"` |
| Run the app locally | `uvicorn app.main:app --reload` |
| Start only Postgres | `docker compose up -d db` |
| Migrate | `alembic upgrade head` |
| New migration | `alembic revision --autogenerate -m "..."` — then **read and edit it**; autogenerate misses exclusion constraints |
| Seed demo data | `python -m scripts.seed` |
| Create the first admin | `python -m scripts.create_admin --email ... --password ...` (or `ADMIN_EMAIL`/`ADMIN_PASSWORD`) |
| Tests (all) | `pytest` |
| Tests (one layer) | `pytest tests/unit` · `pytest tests/integration` · `pytest tests/concurrency` |
| Lint + format | `ruff check . && ruff format .` |

The commands become available as the P0 tasks land; if one doesn't work yet,
check `tasks.md`.

## 4. Project structure

| Path | Purpose |
|---|---|
| `app/main.py` | App factory: routers, exception handlers, static/templates mount |
| `app/core/` | Settings (pydantic-settings), DB engine/session, security (hashing, JWT, CSRF), error types + envelope, injectable clock, timezone conversion |
| `app/models/` | SQLAlchemy models — table shape only |
| `app/schemas/` | Pydantic request/response models — input shape validation |
| `app/services/` | **All business logic.** `slots.py` is pure (no DB); `booking.py` creates and transitions bookings; one module per area |
| `app/api/v1/` | JSON routers — thin |
| `app/web/` | HTML routers — thin, call the same services |
| `app/templates/` | Jinja2: `base.html`, pages, `_partials/` (fragments the live slot picker swaps in) |
| `app/static/` | `css/app.css` (owns all tokens and shared components), page CSS, `js/app.js` |
| `migrations/` | Alembic migrations, hand-reviewed; home of the exclusion constraints |
| `tests/unit/` | Pure logic: slot algorithm, state machine, validators, time conversion |
| `tests/integration/` | API + real Postgres |
| `tests/concurrency/` | Race-condition tests with real commits and threads |
| `scripts/` | `seed.py`, `create_admin.py` |
| `docs/` | `architecture.md`, `database.md`, `edge-cases.md`, `api.md`, `decisions/` (ADRs), `submission.md` |
| `AI_USAGE.md` | Running log of how AI was used and verified (required by the submission form) |

## 5. Non-negotiable rules

1. **Layering.** Routers (`api/`, `web/`) never touch the database or contain
   business rules. Templates contain no business logic (formatting only).
   Both entry points call `services/`. Double-booking protection, each
   validation rule, and the status transitions each live in exactly **one**
   place.
2. **The database is the double-booking guarantee.** Postgres `EXCLUDE USING
   gist` constraints on `tstzrange(start_at, end_at, '[)')` for
   `status IN ('pending','confirmed')` — per provider and per customer. The
   service layer pre-checks only to produce a friendly message. SQLSTATE
   `23P01` is caught and mapped to **409 `SLOT_TAKEN`** / **`CUSTOMER_OVERLAP`**
   by constraint name. Never replace this with a Python-only check.
3. **PostgreSQL everywhere**, including tests. Never SQLite.
4. **Time.** Every timestamp is `timestamptz`, stored and compared in UTC.
   Availability is local wall-clock time in the business's IANA timezone;
   local↔UTC conversion happens in exactly one module using `zoneinfo`. The
   API rejects timezone-naive datetimes.
5. **Injected clock.** Never call `datetime.now()` / `utcnow()` in business
   logic; take `now` from `app/core/clock.py` (a dependency tests override).
6. **Money is an integer** amount in UZS (no floats, no Decimal). The currency
   code lives on business settings.
7. **Ranges are half-open `[start, end)`.** Back-to-back bookings are allowed.
8. **Status transitions** go through the single state-machine module and are
   applied with a guarded `UPDATE … WHERE id = :id AND status = :expected`,
   checking the row count; each transition writes a `booking_events` row in
   the same transaction.
9. **Slots are computed, never stored.**
10. **Soft-deactivate, never hard-delete** services, providers and users that
    bookings reference. Bookings snapshot price and duration.
11. **One error envelope:** `{"error": {"code", "message", "details"}}`. A
    customer asking for someone else's booking gets **404**, not 403.
12. **UI saffron semantics.** Saffron (`--saffron`) means *committed or
    selected* — the chosen slot, a Confirmed status, the current step, the
    active nav item, the one button that books. Never decoration. Status chips
    always spell the status out in text. (Was lime until the 2026-09-30
    redesign; the rule is unchanged, only the colour.)
13. **Progressive enhancement.** Every form works without JavaScript.
14. **`../theoria` is read-only reference.** Never edit, move or commit
    anything there, and never reference it by path from this repo's code or
    config. Copy what's needed so this repo stays self-contained.
15. **No secrets in the repo.** `.env.example` lists every variable.

## 6. Definition of Done (every task)

A task in `tasks.md` is done only when **all** of these hold:

- [ ] Code implements the task's acceptance criteria
- [ ] Tests for it are written and `pytest` passes (whole suite, not just the
      new tests); `ruff check .` and `ruff format --check .` pass
- [ ] Relevant docs are updated **in the same commit** (README checklist,
      `docs/*.md`, ADRs, edge-case table rows with test names, OpenAPI
      examples)
- [ ] Module and service-function docstrings state the business rule and the
      errors raised
- [ ] The task's checkbox in `tasks.md` is ticked
- [ ] One focused Conventional Commit (`feat(bookings): …`, `test(slots): …`,
      `docs(edge-cases): …`, `fix: …`), with a *why* in the body when it
      isn't obvious. Never squash, never rewrite pushed history.

At the end of each **phase** additionally:

- [ ] An `AI_USAGE.md` entry for the phase (asked · produced · verified how ·
      changed/rejected · bugs caught)
- [ ] Push to `origin`
- [ ] A plain-language phase summary for the owner (§9)

## 7. How to work through `tasks.md`

- One task at a time, **top to bottom**. Don't skip ahead or batch tasks into
  one commit.
- Before starting a task, re-read its acceptance criteria and the rules above.
- If a task has to deviate from the plan (a better design, a cut, a split),
  record it in `tasks.md` → "Deviations log" with the reason, and update the
  affected docs/ADR.
- Watch the time checkpoints at the top of `tasks.md`. When behind: cut from
  the **bottom of the bonus list** first, then UI polish. Never cut tests,
  docs, or a minimum requirement.
- Stop and ask the owner before: changing a decision in §5, adding a
  dependency not listed in §3, anything touching deployment credentials, or
  anything outward-facing (pushing to a new remote, deploying, publishing).

## 8. Out of scope

Deliberately not built (Theoria features that serve no requirement here):

- AI assistant / chat widget
- i18n and the language switcher (the UI is English only)
- Poster galleries, image uploads
- Charts (the admin dashboard uses a plain `.stats` row)
- Email-code (passwordless) login
- The Θ brand mark — Navbat gets its own mark
- Provider login accounts (providers are records managed by the admin)
- Payments, multiple businesses/locations, recurring bookings

## 9. Reporting to the owner

After each phase, write a short summary in plain language:

- what was built and which requirement(s) it serves,
- **what to review and why it works** — the 3–5 files/functions that matter,
  the invariant each one protects, and the test that proves it,
- anything cut, deferred, or decided differently (and the log entry),
- where AI output was wrong or needed correction.
