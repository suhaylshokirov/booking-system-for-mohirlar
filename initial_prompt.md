# Agent Prompt — Booking System (Mohirlar Internship, Task 3)

You are my engineering partner on a timed internship assignment. Read this whole prompt before doing anything. Your first job is **not** to write application code: it is to set up the project skeleton, `CLAUDE.md`, and `tasks.md`, then stop so I can review them.

---

## 0. Context and priorities

I am building an appointment booking system for a small service business (think a barbershop or clinic). A customer picks a service, sees free time slots, and books one; the business manages services, staff (providers), availability, and bookings.

**Hard deadline: 2026-10-02 04:16 UTC (09:16 Tashkent, UTC+5).** The submission form accepts one submission only and cannot be edited. I submit it myself; you never do.

**Order of authority when anything conflicts:**

1. **The assignment requirements** (Section 1). These are what I am graded on. Never trade one away for polish.
2. **Our architecture decisions** (Sections 2–5).
3. **UI inspiration from my previous project, Theoria** (Section 6). Nice to have; drop anything from it that costs time without serving a requirement.

**I must be able to explain every line.** Reviewers will ask about AI-generated code and architecture decisions. So: prefer plain, readable code over clever code; comment the *why*, not the *what*; and after each phase, give me a short "what to review and why it works" summary.

---

## 1. Assignment requirements (source of truth)

### Minimum requirements (all mandatory)
- Create a **service** with name, description, duration, price
- Create **providers / employees**
- Set **availability**
- User can **see available time slots**
- User can **book**
- Booking **statuses**: Pending, Confirmed, Cancelled, Completed
- **No double booking**
- **Backend API**
- **Authentication**
- **Basic validation**
- **Booking history**

### What the candidate is expected to show
- Edge cases I discover myself (their example: *two users book the same slot at the same moment*)
- AI tools are allowed, but I must explain where I used them, understand generated code, and justify architecture decisions

### Bonus (optional, in the priority order I want them)
1. Tests (treat as mandatory, not bonus)
2. API documentation (Swagger comes free; add examples and a guide)
3. Docker
4. Admin dashboard
5. Timezone support
6. Cancellation policy
7. Calendar integration (a downloadable `.ics` file is enough)
8. Email notification (a pluggable notifier that logs to console / writes to an outbox table is enough; real SMTP only if time allows)

### Deliverables
- Working application
- Source code in a **public GitHub repository** (mandatory)
- **README with setup instructions**
- **Architecture explanation**
- **Edge cases explanation**
- Deployed / demo URL (if possible — aim for yes)

### What reviewers focus on
Database design · business logic and validation · race conditions and edge cases · API architecture · product thinking · **git history showing step-by-step work** · **documentation and explanation quality** · how AI was used and how its output was verified.

Note that three of the eight focus areas are about explanation (docs, git history, AI usage). Documentation is a first-class deliverable here, not an afterthought (see Section 8).

---

## 2. Stack (decided)

- **Python 3.12**, **FastAPI**, **Pydantic v2**
- **PostgreSQL 16** — chosen on purpose for `tstzrange` + `EXCLUDE` constraints (the core of double-booking prevention). Never swap to SQLite, including in tests.
- **SQLAlchemy 2.0 (sync, typed `Mapped[]` style)** + **psycopg 3** + **Alembic**. Sync is deliberate: simpler to reason about and test at this scale.
- **Jinja2 templates + vanilla JS** (no React/Vue, no build step, no HTMX), porting Theoria's patterns
- **Auth**: password hashing with Argon2 (`pwdlib[argon2]`), JWT (`PyJWT`)
- **pytest** + FastAPI `TestClient`, against a real Postgres test database
- **Docker Compose** (app + db) from day one; **GitHub Actions** running the test suite
- Tooling: `ruff` (lint + format). Keep dependencies minimal and pinned.

Working product name: **Navbat** (Uzbek for "turn / queue"). Easy to change later.

---

## 3. Project structure

```
navbat/
├── app/
│   ├── main.py              # app factory, router registration, exception handlers
│   ├── core/                # config (pydantic-settings), db session, security, errors, clock
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic request/response models
│   ├── services/            # ALL business logic lives here
│   │   ├── slots.py         # pure slot-computation functions (no DB access)
│   │   ├── booking.py       # create / transition bookings
│   │   └── ...
│   ├── api/v1/              # JSON routers — thin: validate, call service, map errors
│   ├── web/                 # HTML routers — thin: call the SAME services, render templates
│   ├── templates/           # Jinja2 (base.html, pages, _partials)
│   └── static/              # css/, js/
├── migrations/              # Alembic
├── tests/
│   ├── unit/                # pure logic: slot algorithm, state machine, validators
│   ├── integration/         # API + DB
│   └── concurrency/         # race-condition tests
├── scripts/                 # seed data, create-admin CLI
├── docs/
│   ├── architecture.md
│   ├── database.md
│   ├── edge-cases.md
│   ├── api.md
│   └── decisions/           # ADRs: 0001-postgres-exclusion-constraint.md, ...
├── CLAUDE.md
├── tasks.md
├── AI_USAGE.md
├── README.md
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── pyproject.toml
```

**Layering rule (non-negotiable):** routers never touch the database or contain business rules. Both `api/` and `web/` call `services/`. Double-booking protection, validation rules, and status transitions each live in exactly one place.

**Clock rule:** never call `datetime.now()` directly in business logic. Inject a clock (`app/core/clock.py`) so tests can freeze time.

---

## 4. Domain model and business rules

### Decisions already made
- **Roles:** `customer` and `admin` (the business owner). Providers are records managed by the admin, not login accounts. Registration always creates a customer; the first admin is created by a CLI script / env vars.
- **Providers ↔ services is many-to-many.** A provider offers a subset of services.
- **Money:** integer amounts in UZS (no floats, no decimals). Store the currency code on the business settings.
- **Time:** every timestamp is `timestamptz`, stored and compared in UTC. The business has one IANA timezone setting (default `Asia/Tashkent`). Availability is defined in the business's local wall-clock time; conversion happens in one place using `zoneinfo`. The API rejects timezone-naive datetimes.
- **Slots are computed on the fly** from availability minus active bookings; slots are never stored as rows.
- **Ranges are half-open `[start, end)`,** so back-to-back bookings (10:00–10:30 and 10:30–11:00) are allowed.

### Suggested tables (refine, then document in `docs/database.md` with an ER diagram)
- `users` — id, email (unique, case-insensitive), password_hash, full_name, role, is_active, timestamps
- `business_settings` — single row: name, timezone, currency, slot_granularity_minutes (e.g. 15), min_lead_time_minutes, max_booking_horizon_days, cancellation_cutoff_hours
- `services` — name, description, duration_minutes (>0, multiple of granularity), price (>=0), is_active
- `providers` — name, bio, is_active
- `provider_services` — (provider_id, service_id) composite PK
- `availability_rules` — provider_id, weekday, start_time, end_time (local), with `CHECK (end_time > start_time)`; overlapping rules for the same provider/weekday are rejected
- `availability_exceptions` — provider_id, date, optional start/end (full day off, or custom hours for that date)
- `bookings` — customer_id, provider_id, service_id, start_at, end_at, status, **price and duration snapshotted at booking time**, notes, cancelled_by, cancel_reason, timestamps
- `booking_events` — booking_id, from_status, to_status, actor_id, reason, created_at. This is the audit trail behind **booking history**.

### Double-booking prevention (the heart of the grade)
Enforce it **in the database**, not just in Python:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bookings ADD CONSTRAINT no_provider_overlap
  EXCLUDE USING gist (provider_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
  WHERE (status IN ('pending', 'confirmed'));

-- A customer can't be in two places at once either:
ALTER TABLE bookings ADD CONSTRAINT no_customer_overlap
  EXCLUDE USING gist (customer_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
  WHERE (status IN ('pending', 'confirmed'));
```

- Write these in the Alembic migration explicitly (autogenerate won't detect them) and add a comment explaining them.
- The service layer still pre-checks availability for a friendly message, but the **constraint is the guarantee**. Catch the exclusion violation (SQLSTATE `23P01`) and return **409 `SLOT_TAKEN`** (or `CUSTOMER_OVERLAP`).
- Cancelled/completed bookings free the slot because of the partial `WHERE`.
- Document *why* "check-then-insert" alone is a race condition in `docs/edge-cases.md` and in ADR 0001.

### Status lifecycle (state machine in one module, fully unit-tested)
| From | To | Who | Condition |
|---|---|---|---|
| (new) | Pending | customer | valid slot |
| Pending | Confirmed | admin | slot still in future |
| Pending | Cancelled | customer (own) / admin | — |
| Confirmed | Cancelled | customer (own) | before the cancellation cutoff |
| Confirmed | Cancelled | admin | any time before start, with reason |
| Confirmed | Completed | admin | only after `end_at` has passed |
| Cancelled / Completed | — | — | terminal |

Apply transitions with a guarded update (`UPDATE ... WHERE id = :id AND status = :expected`) and check the affected row count, so a concurrent confirm and cancel can't both succeed. Every transition writes a `booking_events` row in the same transaction.

### Booking validation (reject with clear error codes)
Start in the past or inside the minimum lead time · beyond the booking horizon · not aligned to slot granularity · provider doesn't offer the service · inactive service or provider · the slot doesn't fit fully inside an availability window (including exceptions) · overlap (via constraint).

### Slot algorithm
Implement as **pure functions** in `services/slots.py`: input = availability windows for a local date, exceptions, existing active bookings, service duration, granularity, `now`, lead time; output = list of UTC start times. No DB access inside, so it's trivially unit-testable. Return slots grouped by provider when no provider is chosen ("any available provider").

---

## 5. API design

- Prefix `/api/v1`. Resource-oriented, plural nouns, OpenAPI tags per resource, request/response examples on every endpoint.
- Core endpoints: `auth` (register, login, logout, me) · `services` (public list/detail; admin CRUD) · `providers` (public list/detail; admin CRUD; manage offered services) · `providers/{id}/availability` (rules + exceptions, admin) · `slots?service_id=&date=&provider_id=` (public) · `bookings` (customer: create, list own, detail, cancel; admin: list all with filters, confirm, complete, cancel) · `bookings/{id}/history` · `bookings/{id}/ics`.
- **One error envelope everywhere:** `{"error": {"code": "SLOT_TAKEN", "message": "...", "details": {...}}}`. Use 201/400/401/403/404/409/422/429 correctly. Keep a table of all error codes in `docs/api.md`.
- A customer requesting someone else's booking gets **404, not 403** (don't leak existence).
- Paginate list endpoints (`limit` capped, `offset` or cursor).
- **Auth:** JWT in an HttpOnly, `SameSite=Lax`, `Secure`-in-production cookie for the web UI; the API also accepts `Authorization: Bearer` for Swagger/curl. Cookie-authenticated unsafe requests require a CSRF token (double-submit cookie); Bearer requests don't. Rate-limit login attempts (simple, documented, e.g. per IP + email window).

---

## 6. UI — inspired by Theoria

Theoria is already on disk as a sibling of this project: both live in my `Projects` folder, so from this project's root it is at `../theoria`. Do not clone it. Study `../theoria/django_app/static/css/theoria.css`, `../theoria/django_app/templates/base.html`, `../theoria/django_app/static/js/theoria.js`, and the list/partial templates under `../theoria/django_app/movies/templates/movies/`. **Port patterns, don't copy features.**

Treat `../theoria` as **read-only reference**: never edit, move, or commit anything there, and never reference it by path from this project's code or config (copy what you need into this repo so it stays self-contained and deployable).

### Carry over
- **The CSS architecture:** one `app.css` owns all tokens and shared components; page stylesheets may add components but never restyle shared ones. No framework, no build step.
- **Tokens:** paper `#ffffff`, sheet `#f7f7f5`, sheet-2 `#efeeea`, rule `#e3e2dd`, rule-strong `#c9c7c0`, ink `#0b0b0b`, ink-muted `#57534e`, ink-faint `#78716c`, lime `#a3e635`, lime-wash, lime-text, lime-mark, `--danger` for form errors only; the spacing, type scale, radius (2px sheets, pill chips/buttons), and single reserved card shadow.
- **Dark mode as a pure token swap** (`--dark-*` values, applied via `[data-theme="dark"]` and `prefers-color-scheme`), with the inline pre-paint theme script and the header toggle.
- **Typography:** Archivo (expanded uppercase for `.sheet-title`, condensed tracked for labels/chips/buttons), Instrument Sans body, Spline Sans Mono for times, prices, and IDs.
- **Page skeleton:** `.sheet-head` → `.sheet-section` → `.section-head`; vertical rhythm owned in one place.
- **Components:** `.btn`, `.chip`, `.segmented`, `.field`, `.stats`/`.stat`, `.table-wrap`, `.notice`, `.empty`, `.menu`, `.pagination`, the confirm `<dialog>` (reuse for "Cancel this booking?", with "No" focused first).
- **JS:** a single IIFE of `initX()` functions, progressive enhancement throughout (every form works without JS). Port `initLiveFilter()`'s pattern — fetch with `X-Requested-With`, server returns a partial, swap target `innerHTML`, debounce, `AbortController`, full-submit fallback — and use it for the slot picker. Port only what's needed: theme toggle, nav toggle, live filter, confirm dialog, inline validation, submit-button disable (prevents double submit).

### Adapt to booking semantics
- **Lime = committed or selected**, never decoration: the chosen slot, Confirmed status, the current step. Available slots are neutral tiles (hairline border, mono time); taken slots are simply absent.
- **Status chips** always spell out the status in text: Pending = outlined, Confirmed = lime fill, Completed = ink, Cancelled = faint with strikethrough.
- **Empty states tell the user what to do** ("No free times on this day — try the next one").

### Pages
Customer: home/services list → service detail → pick provider (or "any") + date → slot grid (live-refreshing) → confirm booking → my bookings (upcoming / past, with history and cancel). Auth: login, register.
Admin: dashboard (`.stats`: today's bookings, pending count, this week's utilization; list of pending bookings with confirm/cancel), services CRUD, providers CRUD + offered services, availability editor, all bookings with filters.

### Leave out
AI assistant, i18n / language switcher, poster galleries, charts, email-code login. New brand mark instead of Θ.

---

## 7. Testing strategy

- Tests are written **with** each task, not at the end. A task is not done until its tests pass.
- Real Postgres (a separate test database from Docker Compose). Per-test transaction rollback for speed, except concurrency tests, which need real commits (clean up by truncation).
- **Unit:** slot algorithm (window edges, lead time, horizon, exceptions, back-to-back, duration not fitting at window end, timezone conversion including a DST zone such as `Europe/Berlin`), state machine (every allowed and forbidden transition), validators.
- **Integration:** every endpoint's happy path + main failures; authorization (customer vs admin vs anonymous; IDOR returns 404); error envelope shape.
- **Concurrency (headline tests):**
  - N threads (use `threading.Barrier` so they fire simultaneously) book the same slot → exactly one 201, the rest 409.
  - Concurrent confirm + cancel on one booking → exactly one wins; history is consistent.
  - The same customer books two overlapping slots with different providers → one rejected.
- Name tests descriptively; `docs/edge-cases.md` links each edge case to its test.
- GitHub Actions runs `ruff` + `pytest` with a Postgres service on every push. Put the badge in the README.

---

## 8. Documentation (heavily graded — treat as a feature)

**Rule: documentation is updated in the same commit as the code it describes.** A task that changes behavior without updating docs is not done.

### README.md
Written for a reviewer with five minutes. Sections, in order:
1. One-paragraph pitch + live demo URL + demo credentials (admin and customer) + CI badge
2. Screenshots (customer booking flow, admin dashboard) — add in the final phase
3. Feature checklist mapped **one-to-one to the assignment's minimum requirements and bonuses**, each linking to where it's implemented
4. Quick start: `docker compose up` → seeded data → URLs for app and `/docs`
5. Local development without Docker, running tests, environment variables table
6. Architecture in brief (diagram + 5 lines) → link to `docs/architecture.md`
7. Key decisions (bullet list linking to ADRs)
8. Edge cases highlights (top 5) → link to `docs/edge-cases.md`
9. How AI was used → link to `AI_USAGE.md`
10. Known limitations and what I'd do next

### docs/architecture.md
Layers and why; request lifecycle for "create booking" (Mermaid sequence diagram, including the constraint path); component diagram; the time model (UTC storage, business timezone, half-open ranges); auth design; why the web UI and API share services; trade-offs I accepted.

### docs/database.md
Mermaid ER diagram; every table with purpose; every constraint and index and **why** it exists; the exclusion constraints explained in plain language; snapshot fields rationale.

### docs/edge-cases.md
A table: **Edge case · Why it's a risk · How it's handled · Where enforced (DB / service / API / UI) · Test name.** Seed it with at least these and keep adding as you discover more:
- Two users book the same slot simultaneously
- Double-click / double submit
- Same customer, overlapping bookings with different providers
- Back-to-back bookings (must be allowed)
- Booking in the past, inside lead time, beyond horizon, misaligned to granularity
- Service duration doesn't fit before the availability window ends
- Provider doesn't offer the service; inactive service/provider
- Service price or duration changes after booking (snapshot)
- Availability edited or removed while future bookings exist (bookings are kept; admin sees conflicts)
- Provider/service deactivated with future bookings (soft-deactivate, never hard-delete)
- Overlapping availability rules for the same provider
- Timezone: naive datetimes rejected; DST gaps/overlaps in non-Tashkent zones; a date boundary in local time vs UTC
- Invalid status transitions; concurrent confirm + cancel; completing before end time; cancelling after the cutoff
- Customer accessing another customer's booking (IDOR → 404)
- Expired or tampered JWT; deactivated user with a valid token
- Email case sensitivity on registration; login brute force (rate limit)
- Oversized inputs, negative price, zero duration

### docs/api.md
Auth how-to (cookie vs Bearer), a curl walkthrough of the full booking flow, the error code table, pagination conventions. Swagger at `/docs` is the reference; this is the guide.

### docs/decisions/ (ADRs, short: context · decision · alternatives · consequences)
At minimum: PostgreSQL exclusion constraints for double booking · computed slots vs stored slots · sync SQLAlchemy · server-rendered UI with vanilla JS · JWT in HttpOnly cookie + Bearer · half-open ranges and UTC storage · price/duration snapshots.

### AI_USAGE.md (required by the submission form)
A running log, one entry per phase: what I asked the AI to do · what it produced · what I verified and how (tests, reading, manual checks) · what I changed or rejected and why · bugs the AI introduced that I caught. Be honest and specific. At the end, a summary section I can adapt for the form fields.

### Code-level docs
Module docstrings explaining each module's responsibility; comments on non-obvious decisions in Theoria's style (explain *why*); docstrings on every service function stating its business rule and the errors it raises.

### docs/submission.md (final phase)
Draft answers for each submission form field, ready for me to edit:
- Product description: what it is and how it works (≥100 characters)
- Architecture: parts and why (optional field — fill it anyway)
- AI tools used
- Where AI helped and what I verified or changed myself (≥120 characters)

---

## 9. Git workflow

- The history is graded. Commit **per task**, small and meaningful, using Conventional Commits (`feat(bookings): ...`, `test(slots): ...`, `docs(edge-cases): ...`, `fix: ...`). Never squash; never rewrite pushed history.
- Each commit should build and pass tests. Commit messages explain the *why* in the body when it's non-obvious.
- No secrets in the repo; `.env.example` lists every variable.
- Push after each phase so progress is visible with real timestamps.

---

## 10. What to produce first: CLAUDE.md and tasks.md

### CLAUDE.md must contain
1. Project summary and the deadline
2. The order of authority (requirements > decisions > Theoria)
3. Stack and the commands (run, test, lint, migrate, seed, create admin)
4. The project structure with one-line purpose per directory
5. The non-negotiable rules: layering; DB constraint as the double-booking guarantee; UTC + injected clock; money as integers; half-open ranges; no business logic in routers or templates; lime semantics in the UI
6. **Definition of Done** for every task: code + tests passing + relevant docs updated + `AI_USAGE.md` entry (per phase) + `tasks.md` checkbox ticked + one focused commit
7. How to work through `tasks.md` (one task at a time, top to bottom, don't skip ahead, note deviations)
8. Explicit out-of-scope list (from Section 6 "Leave out")
9. A reminder to summarize each phase for me in plain language

### tasks.md format
Phases → tasks with IDs. Each task:

```
### P3.2 — Slot computation (pure functions)
- [ ] Status
- Goal: ...
- Requirement(s) served: "User can see available time slots"
- Acceptance criteria: ...
- Tests: ...
- Docs to update: ...
- Edge cases covered: ...
```

Top of the file: a requirement-coverage matrix (each assignment requirement → task IDs), and time checkpoints.

### Suggested phases (refine them, keep the order)
- **P0 Bootstrap:** repo, `pyproject.toml`, Docker Compose, config, health endpoint, CI, `CLAUDE.md`, `tasks.md`, README skeleton, `AI_USAGE.md`, docs skeletons
- **P1 Database:** models, first migrations, exclusion constraints, check constraints, seed script, `docs/database.md`
- **P2 Auth:** register, login, logout, me, roles, JWT cookie + Bearer, CSRF, rate limiting, create-admin CLI
- **P3 Catalog:** services and providers CRUD, provider ↔ services, soft deactivation, business settings
- **P4 Availability:** rules and exceptions with validation
- **P5 Slots:** pure algorithm + endpoint + heavy unit tests
- **P6 Booking creation:** validation, snapshots, constraint handling → 409, concurrency tests, ADR 0001
- **P7 Lifecycle and history:** state machine, guarded transitions, events table, cancellation policy, history endpoint
- **P8 Customer UI:** base template + CSS port, auth pages, booking flow with live slot picker, my bookings
- **P9 Admin UI:** dashboard, CRUD pages, availability editor, bookings management
- **P10 Bonuses:** `.ics` download, notifier (console/outbox), timezone display polish
- **P11 Ship:** deploy (Render or Railway, managed Postgres; check free-tier expiry), seed demo data, screenshots, final docs pass, `docs/submission.md`, README feature checklist verified against Section 1

### Time checkpoints (UTC; Tashkent = UTC+5)
- P0–P2 done: **Sep 29, 20:00**
- P3–P6 done: **Sep 30, 18:00** (the graded core is safe at this point)
- P7–P9 done: **Oct 1, 12:00**
- P10 done: **Oct 1, 18:00**
- P11 done, deployed, docs final: **Oct 1, 23:00**
- Buffer; I submit by **Oct 2, 02:00** at the latest

If we fall behind, cut from the bottom of the bonus list first, then UI polish. Never cut tests, docs, or a minimum requirement.

---

## 11. Your first action

1. Confirm you're working in the new project's folder inside `Projects` (e.g. `Projects/navbat`) and that `../theoria` exists. If the new folder doesn't exist yet, create it there; if `../theoria` isn't found, stop and ask me for its path.
2. Read the Theoria files listed in Section 6.
3. Run `git init` in the new project (it's a separate repository from Theoria), then create the repository skeleton (Section 3), `CLAUDE.md`, `tasks.md` (with the coverage matrix and checkpoints), and skeletons of the README and docs.
4. Make the first commit(s).
5. **Stop.** Show me `CLAUDE.md` and `tasks.md`, list any assumptions you made or questions you have, and wait for my go-ahead before starting P1.
